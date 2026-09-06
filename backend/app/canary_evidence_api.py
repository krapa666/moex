from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from .canary_evidence import (
    CanaryEvidenceCaptureResult,
    CanaryEvidenceOverviewResult,
    CanaryEvidenceSnapshot,
    CanaryTickerEvidenceResult,
    build_canary_evidence_overview,
    build_canary_ticker_evidence,
    capture_canary_evidence,
    list_canary_evidence_history,
)
from .consensus_canary_api import require_local_actor
from .database import get_db

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


class CanaryEvidenceSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticker: str
    target_year: int | None
    captured_at: datetime
    canary_enabled: bool
    in_allowlist: bool
    configured_mode: str
    effective_mode: str
    active_available: bool
    safety_status: str | None
    fallback_reason: str | None
    sources: int
    current_price: float | None
    median_target_price: float | None
    weighted_target_price: float | None
    active_target_price: float | None
    median_expected_return_percent: float | None
    weighted_expected_return_percent: float | None
    active_expected_return_percent: float | None


class CanaryTickerEvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticker: str
    history_days: int
    snapshots: int
    target_years: list[int]
    latest_target_year: int | None
    first_captured_at: datetime | None
    last_captured_at: datetime | None
    history_span_hours: float
    configured_weighted_hours: float
    weighted_hours: float
    fallback_hours: float
    weighted_uptime_percent: float | None
    fallback_incidents: int
    recoveries: int
    longest_weighted_run_hours: float
    longest_fallback_run_hours: float
    fallback_reason_counts: dict[str, int]
    current_canary_enabled: bool | None
    current_in_allowlist: bool | None
    current_configured_mode: str | None
    current_effective_mode: str | None
    current_safety_status: str | None
    current_fallback_reason: str | None
    current_median_target_price: float | None
    current_weighted_target_price: float | None
    current_active_target_price: float | None
    current_median_expected_return_percent: float | None
    current_weighted_expected_return_percent: float | None
    current_active_expected_return_percent: float | None


class CanaryEvidenceOverviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    generated_at: datetime
    history_days: int
    configured_tickers: int
    tickers_with_evidence: int
    snapshots: int
    configured_weighted_hours: float
    weighted_hours: float
    fallback_hours: float
    weighted_uptime_percent: float | None
    fallback_incidents: int
    recoveries: int
    current_weighted_tickers: int
    current_fallback_tickers: int
    current_median_tickers: int
    current_unknown_tickers: int
    median_history_span_hours: float
    items: list[CanaryTickerEvidenceRead]


class CanaryEvidenceCaptureRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    captured_at: datetime
    configured_tickers: int
    snapshots_created: int
    deleted_expired: int


@router.get("/consensus-canary/evidence", response_model=CanaryEvidenceOverviewRead)
def get_canary_evidence_overview(
    days: int = Query(default=30, ge=1, le=730),
    db: Session = Depends(get_db),
) -> CanaryEvidenceOverviewResult:
    return build_canary_evidence_overview(db, days=days)


@router.get("/consensus-canary/evidence/ticker", response_model=CanaryTickerEvidenceRead)
def get_canary_ticker_evidence(
    ticker: str = Query(max_length=32, pattern=r"^[A-Za-z0-9._-]+$"),
    days: int = Query(default=30, ge=1, le=730),
    db: Session = Depends(get_db),
) -> CanaryTickerEvidenceResult:
    return build_canary_ticker_evidence(db, ticker=ticker, days=days)


@router.get(
    "/consensus-canary/evidence/history",
    response_model=list[CanaryEvidenceSnapshotRead],
)
def get_canary_evidence_history(
    ticker: str = Query(max_length=32, pattern=r"^[A-Za-z0-9._-]+$"),
    days: int = Query(default=30, ge=1, le=730),
    limit: int = Query(default=500, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> list[CanaryEvidenceSnapshot]:
    return list_canary_evidence_history(db, ticker=ticker, days=days, limit=limit)


@router.post("/consensus-canary/evidence/capture", response_model=CanaryEvidenceCaptureRead)
def post_canary_evidence_capture(
    _actor: str = Depends(require_local_actor),
    db: Session = Depends(get_db),
) -> CanaryEvidenceCaptureResult:
    return capture_canary_evidence(db)
