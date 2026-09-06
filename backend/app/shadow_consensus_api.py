from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from .consensus_readiness import ConsensusReadinessResult, build_consensus_readiness
from .database import get_db
from .forecast_accuracy import AccuracySnapshot
from .shadow_consensus import ShadowConsensusResult, build_shadow_consensus
from .shadow_history import (
    ShadowCaptureResult,
    ShadowConsensusSnapshot,
    ShadowDriftResult,
    build_shadow_drift,
    capture_shadow_consensus,
    list_shadow_history,
)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


class ShadowConsensusRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticker: str
    target_year: int | None
    training_snapshot: AccuracySnapshot | None
    as_of: datetime
    shadow_available: bool
    reason: str | None
    sources: int
    sources_with_training_history: int
    training_samples: int
    weighting_uses_history: bool
    max_source_weight_percent: float | None
    min_source_weight_percent: float | None
    median_net_profit_billion_rub: float | None
    mean_net_profit_billion_rub: float | None
    weighted_net_profit_billion_rub: float | None
    median_target_price: float | None
    mean_target_price: float | None
    weighted_target_price: float | None
    weighted_vs_median_target_delta_rub: float | None
    weighted_vs_median_target_delta_percent: float | None
    current_price: float | None
    median_market_gap_percent: float | None
    weighted_market_gap_percent: float | None


class ShadowConsensusSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticker: str
    target_year: int
    training_snapshot: AccuracySnapshot
    captured_at: datetime
    sources: int
    sources_with_training_history: int
    training_samples: int
    weighting_uses_history: bool
    max_source_weight_percent: float
    min_source_weight_percent: float
    median_net_profit_billion_rub: float
    weighted_net_profit_billion_rub: float
    median_target_price: float
    weighted_target_price: float
    weighted_vs_median_target_delta_rub: float
    weighted_vs_median_target_delta_percent: float
    current_price: float | None
    median_market_gap_percent: float | None
    weighted_market_gap_percent: float | None


class ShadowCaptureRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    captured_at: datetime
    tickers_total: int
    snapshots_created: int
    skipped_unavailable: int
    deleted_expired: int


class ShadowDriftRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticker: str
    target_year: int | None
    latest_training_snapshot: AccuracySnapshot | None
    status: str
    reasons: list[str]
    snapshots: int
    history_days: int
    history_span_hours: float
    first_captured_at: datetime | None
    last_captured_at: datetime | None
    latest_delta_percent: float | None
    previous_delta_percent: float | None
    delta_step_percentage_points: float | None
    median_abs_delta_percent: float | None
    max_abs_delta_percent: float | None
    latest_weight_concentration_ratio: float | None
    max_weight_concentration_ratio: float | None
    median_target_change_percent: float | None
    weighted_target_change_percent: float | None
    relative_movement_gap_percentage_points: float | None
    training_snapshot_changed: bool


class ConsensusReadinessGateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    label: str
    passed: bool
    actual: str
    requirement: str


class ConsensusReadinessRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    snapshot: AccuracySnapshot
    ready: bool
    gates_passed: int
    gates_total: int
    observations: int
    tickers: int
    years: int
    weighted_median_delta_pp: float | None
    weighted_mean_delta_pp: float | None
    ticker_slice_positive_ratio: float
    year_slice_positive_ratio: float
    ticker_jackknife_preserved_ratio: float
    year_jackknife_preserved_ratio: float
    parameter_positive_ratio: float
    worst_parameter_median_delta_pp: float | None
    gates: list[ConsensusReadinessGateRead]


def require_local_access(request: Request) -> None:
    if (request.headers.get("x-moex-access-scope") or "").strip().lower() != "local":
        raise HTTPException(status_code=403, detail="Доступ только из локальной сети")


@router.get("/shadow-consensus", response_model=ShadowConsensusRead)
def get_shadow_consensus(
    ticker: str = Query(max_length=32, pattern=r"^[A-Za-z0-9._-]+$"),
    db: Session = Depends(get_db),
) -> ShadowConsensusResult:
    return build_shadow_consensus(db, ticker=ticker)


@router.get(
    "/shadow-consensus/history",
    response_model=list[ShadowConsensusSnapshotRead],
)
def get_shadow_consensus_history(
    ticker: str = Query(max_length=32, pattern=r"^[A-Za-z0-9._-]+$"),
    days: int = Query(default=90, ge=1, le=730),
    limit: int = Query(default=500, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> list[ShadowConsensusSnapshot]:
    return list_shadow_history(db, ticker=ticker, days=days, limit=limit)


@router.get("/shadow-consensus/drift", response_model=ShadowDriftRead)
def get_shadow_consensus_drift(
    ticker: str = Query(max_length=32, pattern=r"^[A-Za-z0-9._-]+$"),
    days: int = Query(default=30, ge=2, le=180),
    db: Session = Depends(get_db),
) -> ShadowDriftResult:
    return build_shadow_drift(db, ticker=ticker, days=days)


@router.post("/shadow-consensus/capture", response_model=ShadowCaptureRead)
def capture_shadow_consensus_history(
    request: Request,
    db: Session = Depends(get_db),
) -> ShadowCaptureResult:
    require_local_access(request)
    return capture_shadow_consensus(db)


@router.get("/consensus-readiness", response_model=ConsensusReadinessRead)
def get_consensus_readiness(
    snapshot: AccuracySnapshot = Query(default="pre_year"),
    db: Session = Depends(get_db),
) -> ConsensusReadinessResult:
    return build_consensus_readiness(db, snapshot=snapshot)
