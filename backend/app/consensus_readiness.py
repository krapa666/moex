from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from .consensus_backtest import (
    ConsensusBacktestRobustnessResult,
    build_consensus_backtest_robustness,
)
from .forecast_accuracy import AccuracySnapshot

READINESS_MIN_OBSERVATIONS = 30
READINESS_MIN_TICKERS = 10
READINESS_MIN_YEARS = 3
READINESS_MIN_MEDIAN_IMPROVEMENT_PP = 1.0
READINESS_MIN_TICKER_SLICE_RATIO = 0.60
READINESS_MIN_YEAR_SLICE_RATIO = 2.0 / 3.0
READINESS_MIN_TICKER_JACKKNIFE_RATIO = 0.80
READINESS_MIN_YEAR_JACKKNIFE_RATIO = 0.80
READINESS_MIN_PARAMETER_RATIO = 0.80


@dataclass(frozen=True)
class ConsensusReadinessGate:
    key: str
    label: str
    passed: bool
    actual: str
    requirement: str


@dataclass(frozen=True)
class ConsensusReadinessResult:
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
    gates: list[ConsensusReadinessGate]


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _format_ratio(value: float) -> str:
    return f"{100.0 * value:.1f}%"


def _format_delta(value: float | None) -> str:
    return "—" if value is None else f"{value:+.2f} pp"


def evaluate_consensus_readiness(
    robustness: ConsensusBacktestRobustnessResult,
) -> ConsensusReadinessResult:
    ticker_slice_ratio = _ratio(robustness.positive_ticker_slices, robustness.ticker_slices)
    year_slice_ratio = _ratio(robustness.positive_year_slices, robustness.year_slices)
    ticker_jackknife_ratio = _ratio(
        robustness.ticker_jackknife_preserved,
        robustness.ticker_jackknife_cases,
    )
    year_jackknife_ratio = _ratio(
        robustness.year_jackknife_preserved,
        robustness.year_jackknife_cases,
    )
    parameter_ratio = _ratio(robustness.positive_parameter_cases, robustness.parameter_cases)
    median_delta = robustness.weighted_median_delta_pp
    mean_delta = robustness.weighted_mean_delta_pp
    worst_parameter_delta = robustness.parameter_min_median_delta_pp

    gates = [
        ConsensusReadinessGate(
            key="observations",
            label="Исторические наблюдения",
            passed=robustness.observations >= READINESS_MIN_OBSERVATIONS,
            actual=str(robustness.observations),
            requirement=f">= {READINESS_MIN_OBSERVATIONS}",
        ),
        ConsensusReadinessGate(
            key="tickers",
            label="Покрытие бумаг",
            passed=robustness.tickers >= READINESS_MIN_TICKERS,
            actual=str(robustness.tickers),
            requirement=f">= {READINESS_MIN_TICKERS}",
        ),
        ConsensusReadinessGate(
            key="years",
            label="Покрытие лет",
            passed=robustness.years >= READINESS_MIN_YEARS,
            actual=str(robustness.years),
            requirement=f">= {READINESS_MIN_YEARS}",
        ),
        ConsensusReadinessGate(
            key="median_improvement",
            label="Улучшение median sMAPE",
            passed=(
                median_delta is not None
                and median_delta >= READINESS_MIN_MEDIAN_IMPROVEMENT_PP
            ),
            actual=_format_delta(median_delta),
            requirement=f">= +{READINESS_MIN_MEDIAN_IMPROVEMENT_PP:.1f} pp",
        ),
        ConsensusReadinessGate(
            key="mean_improvement",
            label="Улучшение mean sMAPE",
            passed=mean_delta is not None and mean_delta > 0,
            actual=_format_delta(mean_delta),
            requirement="> 0 pp",
        ),
        ConsensusReadinessGate(
            key="ticker_slices",
            label="Положительные ticker-срезы",
            passed=(
                robustness.ticker_slices > 0
                and ticker_slice_ratio >= READINESS_MIN_TICKER_SLICE_RATIO
            ),
            actual=_format_ratio(ticker_slice_ratio),
            requirement=f">= {_format_ratio(READINESS_MIN_TICKER_SLICE_RATIO)}",
        ),
        ConsensusReadinessGate(
            key="year_slices",
            label="Положительные year-срезы",
            passed=(
                robustness.year_slices > 0
                and year_slice_ratio >= READINESS_MIN_YEAR_SLICE_RATIO
            ),
            actual=_format_ratio(year_slice_ratio),
            requirement=f">= {_format_ratio(READINESS_MIN_YEAR_SLICE_RATIO)}",
        ),
        ConsensusReadinessGate(
            key="ticker_jackknife",
            label="Leave-one-ticker-out",
            passed=(
                robustness.ticker_jackknife_cases > 0
                and ticker_jackknife_ratio >= READINESS_MIN_TICKER_JACKKNIFE_RATIO
            ),
            actual=_format_ratio(ticker_jackknife_ratio),
            requirement=f">= {_format_ratio(READINESS_MIN_TICKER_JACKKNIFE_RATIO)}",
        ),
        ConsensusReadinessGate(
            key="year_jackknife",
            label="Leave-one-year-out",
            passed=(
                robustness.year_jackknife_cases > 0
                and year_jackknife_ratio >= READINESS_MIN_YEAR_JACKKNIFE_RATIO
            ),
            actual=_format_ratio(year_jackknife_ratio),
            requirement=f">= {_format_ratio(READINESS_MIN_YEAR_JACKKNIFE_RATIO)}",
        ),
        ConsensusReadinessGate(
            key="parameter_sweep",
            label="Положительные наборы параметров",
            passed=(
                robustness.parameter_cases > 0
                and parameter_ratio >= READINESS_MIN_PARAMETER_RATIO
            ),
            actual=_format_ratio(parameter_ratio),
            requirement=f">= {_format_ratio(READINESS_MIN_PARAMETER_RATIO)}",
        ),
        ConsensusReadinessGate(
            key="worst_parameter_case",
            label="Худший набор параметров",
            passed=worst_parameter_delta is not None and worst_parameter_delta > 0,
            actual=_format_delta(worst_parameter_delta),
            requirement="> 0 pp",
        ),
    ]
    passed = sum(1 for gate in gates if gate.passed)
    return ConsensusReadinessResult(
        snapshot=robustness.snapshot,
        ready=passed == len(gates),
        gates_passed=passed,
        gates_total=len(gates),
        observations=robustness.observations,
        tickers=robustness.tickers,
        years=robustness.years,
        weighted_median_delta_pp=median_delta,
        weighted_mean_delta_pp=mean_delta,
        ticker_slice_positive_ratio=ticker_slice_ratio,
        year_slice_positive_ratio=year_slice_ratio,
        ticker_jackknife_preserved_ratio=ticker_jackknife_ratio,
        year_jackknife_preserved_ratio=year_jackknife_ratio,
        parameter_positive_ratio=parameter_ratio,
        worst_parameter_median_delta_pp=worst_parameter_delta,
        gates=gates,
    )


def build_consensus_readiness(
    db: Session,
    *,
    snapshot: AccuracySnapshot = "pre_year",
) -> ConsensusReadinessResult:
    robustness = build_consensus_backtest_robustness(db, snapshot=snapshot)
    return evaluate_consensus_readiness(robustness)
