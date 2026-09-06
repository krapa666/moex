from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from .database import get_db
from .forecast_accuracy import (
    AccuracySample,
    ActualNetProfit,
    aggregate_source_accuracy,
    build_accuracy_samples,
)
from .forecast_history import ForecastRevision

router = APIRouter(prefix="/api/analytics", tags=["analytics"])
AccuracySnapshot = Literal["pre_year", "mid_year", "year_end"]


class ForecastRevisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    stock_row_id: int | None
    table_id: int
    ticker: str
    analyst_name: str
    forecast_start_year: int
    event_type: str
    changed_by: str | None
    shares_billion: float | None
    pe_avg_5y: float | None
    current_price: float | None
    net_profit_year_map: dict[str, float | None] | None
    dividend_year_map: dict[str, float | None] | None
    net_profit_source_comment: str | None
    forecast_price_year1: float | None
    forecast_price_year2: float | None
    upside_percent_year1: float | None
    upside_percent_year2: float | None
    created_at: datetime


class ActualNetProfitWrite(BaseModel):
    net_profit_billion_rub: float
    source_name: str = Field(min_length=1, max_length=255)
    source_url: str | None = Field(default=None, max_length=1024)
    source_comment: str | None = Field(default=None, max_length=512)
    reported_at: datetime | None = None


class ActualNetProfitRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticker: str
    fiscal_year: int
    net_profit_billion_rub: float
    source_name: str
    source_url: str | None
    source_comment: str | None
    reported_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AccuracySampleRead(BaseModel):
    table_id: int
    analyst_name: str
    ticker: str
    fiscal_year: int
    snapshot: AccuracySnapshot
    forecast_billion_rub: float
    actual_billion_rub: float
    forecast_created_at: datetime
    absolute_error_billion_rub: float
    smape_percent: float
    sign_correct: bool


class SourceAccuracyRead(BaseModel):
    table_id: int
    analyst_name: str
    samples: int
    tickers: int
    years: int
    median_smape_percent: float
    mean_smape_percent: float
    median_absolute_error_billion_rub: float
    mean_absolute_error_billion_rub: float
    mean_bias_billion_rub: float
    sign_accuracy_percent: float
    eligible: bool
    rank: int | None


def require_local_access(request: Request) -> None:
    if (request.headers.get("x-moex-access-scope") or "").strip().lower() != "local":
        raise HTTPException(status_code=403, detail="Доступ только из локальной сети")


@router.get("/forecast-revisions", response_model=list[ForecastRevisionRead])
def list_forecast_revisions(
    ticker: str | None = Query(default=None, max_length=32, pattern=r"^[A-Za-z0-9._-]+$"),
    table_id: int | None = Query(default=None, ge=1),
    since: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[ForecastRevision]:
    statement = select(ForecastRevision)
    if ticker:
        statement = statement.where(ForecastRevision.ticker == ticker.strip().upper())
    if table_id is not None:
        statement = statement.where(ForecastRevision.table_id == table_id)
    if since is not None:
        statement = statement.where(ForecastRevision.created_at >= since)

    statement = statement.order_by(desc(ForecastRevision.created_at), desc(ForecastRevision.id)).limit(limit)
    return list(db.scalars(statement).all())


@router.get("/actual-net-profits", response_model=list[ActualNetProfitRead])
def list_actual_net_profits(
    ticker: str | None = Query(default=None, max_length=32, pattern=r"^[A-Za-z0-9._-]+$"),
    fiscal_year: int | None = Query(default=None, ge=2000, le=2100),
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> list[ActualNetProfit]:
    statement = select(ActualNetProfit)
    if ticker:
        statement = statement.where(ActualNetProfit.ticker == ticker.strip().upper())
    if fiscal_year is not None:
        statement = statement.where(ActualNetProfit.fiscal_year == fiscal_year)
    statement = statement.order_by(
        desc(ActualNetProfit.fiscal_year),
        ActualNetProfit.ticker.asc(),
    ).limit(limit)
    return list(db.scalars(statement).all())


@router.put(
    "/actual-net-profits/{ticker}/{fiscal_year}",
    response_model=ActualNetProfitRead,
)
def upsert_actual_net_profit(
    request: Request,
    payload: ActualNetProfitWrite,
    ticker: str = Path(max_length=32, pattern=r"^[A-Za-z0-9._-]+$"),
    fiscal_year: int = Path(ge=2000, le=2100),
    db: Session = Depends(get_db),
) -> ActualNetProfit:
    require_local_access(request)
    normalized_ticker = ticker.strip().upper()
    source_name = payload.source_name.strip()
    if not source_name:
        raise HTTPException(status_code=422, detail="source_name must not be blank")

    row = db.scalars(
        select(ActualNetProfit).where(
            ActualNetProfit.ticker == normalized_ticker,
            ActualNetProfit.fiscal_year == fiscal_year,
        )
    ).first()
    if row is None:
        row = ActualNetProfit(ticker=normalized_ticker, fiscal_year=fiscal_year)
        db.add(row)

    row.net_profit_billion_rub = float(payload.net_profit_billion_rub)
    row.source_name = source_name
    row.source_url = (payload.source_url or "").strip() or None
    row.source_comment = (payload.source_comment or "").strip() or None
    row.reported_at = payload.reported_at
    db.commit()
    db.refresh(row)
    return row


@router.delete("/actual-net-profits/{ticker}/{fiscal_year}")
def delete_actual_net_profit(
    request: Request,
    ticker: str = Path(max_length=32, pattern=r"^[A-Za-z0-9._-]+$"),
    fiscal_year: int = Path(ge=2000, le=2100),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    require_local_access(request)
    normalized_ticker = ticker.strip().upper()
    row = db.scalars(
        select(ActualNetProfit).where(
            ActualNetProfit.ticker == normalized_ticker,
            ActualNetProfit.fiscal_year == fiscal_year,
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Фактический результат не найден")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/source-accuracy", response_model=list[SourceAccuracyRead])
def list_source_accuracy(
    snapshot: AccuracySnapshot = Query(default="pre_year"),
    min_samples: int = Query(default=5, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    samples = build_accuracy_samples(db, snapshot=snapshot)
    return aggregate_source_accuracy(samples, min_samples=min_samples)


@router.get("/source-accuracy/samples", response_model=list[AccuracySampleRead])
def list_source_accuracy_samples(
    snapshot: AccuracySnapshot = Query(default="pre_year"),
    ticker: str | None = Query(default=None, max_length=32, pattern=r"^[A-Za-z0-9._-]+$"),
    analyst_name: str | None = Query(default=None, max_length=100),
    fiscal_year: int | None = Query(default=None, ge=2000, le=2100),
    limit: int = Query(default=500, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> list[AccuracySample]:
    samples = build_accuracy_samples(db, snapshot=snapshot)
    if ticker:
        normalized_ticker = ticker.strip().upper()
        samples = [sample for sample in samples if sample.ticker == normalized_ticker]
    if analyst_name:
        normalized_name = analyst_name.strip().casefold()
        samples = [sample for sample in samples if sample.analyst_name.casefold() == normalized_name]
    if fiscal_year is not None:
        samples = [sample for sample in samples if sample.fiscal_year == fiscal_year]
    samples.sort(key=lambda sample: (sample.fiscal_year, sample.ticker, sample.analyst_name), reverse=True)
    return samples[:limit]
