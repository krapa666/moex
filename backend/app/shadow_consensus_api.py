from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from .consensus_readiness import ConsensusReadinessResult, build_consensus_readiness
from .database import get_db
from .forecast_accuracy import AccuracySnapshot
from .shadow_consensus import ShadowConsensusResult, build_shadow_consensus

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


@router.get("/shadow-consensus", response_model=ShadowConsensusRead)
def get_shadow_consensus(
    ticker: str = Query(max_length=32, pattern=r"^[A-Za-z0-9._-]+$"),
    db: Session = Depends(get_db),
) -> ShadowConsensusResult:
    return build_shadow_consensus(db, ticker=ticker)


@router.get("/consensus-readiness", response_model=ConsensusReadinessRead)
def get_consensus_readiness(
    snapshot: AccuracySnapshot = Query(default="pre_year"),
    db: Session = Depends(get_db),
) -> ConsensusReadinessResult:
    return build_consensus_readiness(db, snapshot=snapshot)
