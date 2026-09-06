from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from .consensus_backtest import (
    ConsensusBacktestRobustnessResult,
    build_consensus_backtest_robustness,
)
from .database import get_db

router = APIRouter(prefix="/api/analytics", tags=["analytics"])
AccuracySnapshot = Literal["pre_year", "mid_year", "year_end"]


class ConsensusBacktestSliceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    dimension: str
    key: str
    observations: int
    tickers: int
    years: int
    baseline_median_smape_percent: float
    weighted_median_smape_percent: float
    weighted_median_delta_pp: float
    baseline_mean_smape_percent: float
    weighted_mean_smape_percent: float
    weighted_mean_delta_pp: float


class ConsensusBacktestJackknifeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    dimension: str
    excluded_key: str
    observations: int
    weighted_median_delta_pp: float
    weighted_mean_delta_pp: float
    preserves_median_improvement: bool
    preserves_mean_improvement: bool


class ConsensusBacktestParameterCaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    shrinkage_samples: int
    error_floor_percent: float
    relative_score_cap: float
    observations: int
    weighted_median_smape_percent: float
    weighted_mean_smape_percent: float
    weighted_median_delta_pp: float
    weighted_mean_delta_pp: float


class ConsensusBacktestRobustnessRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    snapshot: AccuracySnapshot
    min_sources: int
    observations: int
    tickers: int
    years: int
    weighted_median_delta_pp: float | None
    weighted_mean_delta_pp: float | None
    positive_ticker_slices: int
    ticker_slices: int
    positive_year_slices: int
    year_slices: int
    ticker_jackknife_preserved: int
    ticker_jackknife_cases: int
    year_jackknife_preserved: int
    year_jackknife_cases: int
    positive_parameter_cases: int
    parameter_cases: int
    parameter_min_median_delta_pp: float | None
    parameter_max_median_delta_pp: float | None
    by_year: list[ConsensusBacktestSliceRead]
    by_ticker: list[ConsensusBacktestSliceRead]
    jackknife_year: list[ConsensusBacktestJackknifeRead]
    jackknife_ticker: list[ConsensusBacktestJackknifeRead]
    parameter_sweep: list[ConsensusBacktestParameterCaseRead]


@router.get(
    "/consensus-backtest/robustness",
    response_model=ConsensusBacktestRobustnessRead,
)
def get_consensus_backtest_robustness(
    snapshot: AccuracySnapshot = Query(default="pre_year"),
    min_sources: int = Query(default=2, ge=2, le=10),
    db: Session = Depends(get_db),
) -> ConsensusBacktestRobustnessResult:
    return build_consensus_backtest_robustness(
        db,
        snapshot=snapshot,
        min_sources=min_sources,
    )
