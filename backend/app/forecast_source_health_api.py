from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from .database import get_db
from .forecast_source_health import ForecastSourceHealthOverview, build_forecast_source_health

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


class ForecastSourceHealthItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_id: str
    source_key: str
    display_name: str
    expected_interval_hours: float
    status: str
    reasons: list[str]
    run_in_progress: bool
    latest_run_status: str | None
    last_run_at: datetime | None
    last_completed_at: datetime | None
    last_success_at: datetime | None
    latest_age_hours: float | None
    coverage_percent: float | None
    baseline_coverage_percent: float | None
    coverage_change_pp: float | None
    coverage_baseline_runs: int
    tickers_total: int | None
    tickers_mapped: int | None
    tickers_updated: int | None
    tickers_unchanged: int | None
    tickers_skipped: int | None
    runs_in_window: int
    success_runs: int
    partial_runs: int
    failed_runs: int
    consecutive_successes: int
    consecutive_failures: int
    latest_error_kind: str | None
    latest_error_count: int


class ForecastSourceHealthPrivateItemRead(ForecastSourceHealthItemRead):
    analyst_name: str
    latest_error_message: str | None
    latest_error_details: dict[str, str] | None


class ForecastSourceHealthOverviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    generated_at: datetime
    history_days: int
    configured_sources: int
    sources_with_runs: int
    status: str
    healthy_sources: int
    degraded_sources: int
    stale_sources: int
    failed_sources: int
    latest_run_at: datetime | None
    items: list[ForecastSourceHealthItemRead]


class ForecastSourceHealthPrivateOverviewRead(ForecastSourceHealthOverviewRead):
    items: list[ForecastSourceHealthPrivateItemRead]


def _require_local(request: Request) -> None:
    if (request.headers.get("x-moex-access-scope") or "").strip().lower() != "local":
        raise HTTPException(status_code=403, detail="Доступ только из локальной сети")


@router.get("/source-health", response_model=ForecastSourceHealthOverviewRead)
def get_forecast_source_health(
    days: int = Query(default=30, ge=1, le=180),
    db: Session = Depends(get_db),
) -> ForecastSourceHealthOverview:
    return build_forecast_source_health(db, days=days)


@router.get("/source-health/details", response_model=ForecastSourceHealthPrivateOverviewRead)
def get_forecast_source_health_details(
    request: Request,
    days: int = Query(default=30, ge=1, le=180),
    db: Session = Depends(get_db),
) -> ForecastSourceHealthOverview:
    _require_local(request)
    return build_forecast_source_health(db, days=days)
