from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from .database import get_db
from .forecast_history import ForecastRevision

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


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
