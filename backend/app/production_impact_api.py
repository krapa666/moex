from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from .database import get_db
from .production_impact import (
    ProductionImpactItem,
    ProductionImpactResult,
    ProductionImpactSummary,
    PromotionDossier,
    PromotionGate,
    build_production_impact,
    build_production_impact_summary,
    build_promotion_dossier,
)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


class ProductionImpactItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticker: str
    target_year: int
    current_price: float | None
    median_target_price: float
    weighted_target_price: float
    target_delta_rub: float
    target_delta_percent: float | None
    median_expected_return_percent: float | None
    weighted_expected_return_percent: float | None
    expected_return_delta_pp: float | None
    expected_return_sign_changed: bool
    volume_signal_status: str | None
    median_watchlist_score: int | None
    weighted_watchlist_score: int | None
    watchlist_score_delta: int | None
    median_rank: int | None
    weighted_rank: int | None
    rank_delta: int | None
    in_median_top_n: bool
    in_weighted_top_n: bool


class ProductionImpactSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    generated_at: datetime
    top_n: int
    universe_tickers: int
    comparable_tickers: int
    comparable_coverage_percent: float
    median_abs_target_delta_percent: float | None
    max_abs_target_delta_percent: float | None
    median_abs_expected_return_delta_pp: float | None
    return_sign_flip_tickers: int
    return_sign_flip_percent: float
    rank_correlation_spearman: float | None
    mean_abs_rank_change: float | None
    max_abs_rank_change: int | None
    top_n_overlap_tickers: int
    top_n_overlap_percent: float
    top_n_entered: list[str]
    top_n_exited: list[str]
    mean_abs_watchlist_score_delta: float | None
    items: list[ProductionImpactItemRead]


class PromotionGateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    label: str
    passed: bool
    actual: str
    requirement: str


class PromotionDossierRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    generated_at: datetime
    status: str
    gates_passed: int
    gates_total: int
    historical_snapshot: str
    historical_readiness: bool
    forward_history_days: int
    gates: list[PromotionGateRead]


class ProductionImpactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    impact: ProductionImpactSummaryRead
    promotion: PromotionDossierRead


@router.get("/production-impact", response_model=ProductionImpactRead)
def get_production_impact(
    top_n: int = Query(default=10, ge=3, le=50),
    history_days: int = Query(default=30, ge=7, le=180),
    db: Session = Depends(get_db),
) -> ProductionImpactResult:
    return build_production_impact(db, top_n=top_n, history_days=history_days)


@router.get("/promotion-dossier", response_model=PromotionDossierRead)
def get_promotion_dossier(
    top_n: int = Query(default=10, ge=3, le=50),
    history_days: int = Query(default=30, ge=7, le=180),
    db: Session = Depends(get_db),
) -> PromotionDossier:
    impact: ProductionImpactSummary = build_production_impact_summary(db, top_n=top_n)
    return build_promotion_dossier(db, impact=impact, history_days=history_days)
