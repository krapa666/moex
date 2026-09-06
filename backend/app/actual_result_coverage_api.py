from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .actual_result_coverage import build_actual_result_coverage
from .database import get_db

router = APIRouter(prefix="/api/analytics", tags=["analytics"])
AccuracySnapshot = Literal["pre_year", "mid_year", "year_end"]


class ActualResultCoverageByYearRead(BaseModel):
    fiscal_year: int
    forecast_pairs: int
    covered_pairs: int
    missing_forecast_pairs: int
    coverage_percent: float
    actual_records: int


class ActualResultCoverageBySourceRead(BaseModel):
    table_id: int
    analyst_name: str
    forecast_pairs: int
    covered_pairs: int
    missing_forecast_pairs: int
    coverage_percent: float
    tickers: int
    years: int


class MissingActualResultRead(BaseModel):
    ticker: str
    fiscal_year: int
    sources: int


class ActualResultCoverageRead(BaseModel):
    snapshot: AccuracySnapshot
    start_year: int
    end_year: int
    forecast_pairs: int
    covered_pairs: int
    missing_forecast_pairs: int
    missing_actual_records: int
    coverage_percent: float
    forecast_tickers: int
    covered_tickers: int
    actual_records: int
    actual_tickers: int
    by_year: list[ActualResultCoverageByYearRead]
    by_source: list[ActualResultCoverageBySourceRead]
    missing_actuals: list[MissingActualResultRead]


@router.get(
    "/actual-net-profits/coverage",
    response_model=ActualResultCoverageRead,
)
def get_actual_result_coverage(
    snapshot: AccuracySnapshot = Query(default="pre_year"),
    years: int = Query(default=5, ge=1, le=10),
    end_year: int | None = Query(default=None, ge=2000, le=2100),
    missing_limit: int = Query(default=50, ge=0, le=200),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    completed_year = datetime.now(timezone.utc).year - 1
    effective_end_year = completed_year if end_year is None else end_year
    if effective_end_year > completed_year:
        raise HTTPException(
            status_code=422,
            detail="Actual-result coverage is limited to completed fiscal years",
        )

    start_year = effective_end_year - years + 1
    return build_actual_result_coverage(
        db,
        snapshot=snapshot,
        start_year=start_year,
        end_year=effective_end_year,
        missing_limit=missing_limit,
    )
