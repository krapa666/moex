from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean, median

from sqlalchemy import select
from sqlalchemy.orm import Session

from .forecast_accuracy import (
    AccuracySample,
    AccuracySnapshot,
    ActualNetProfit,
    build_accuracy_samples,
    snapshot_cutoff,
    symmetric_absolute_percentage_error,
)

DEFAULT_MIN_SOURCES = 2
DEFAULT_SHRINKAGE_SAMPLES = 5
DEFAULT_ERROR_FLOOR_PERCENT = 5.0
DEFAULT_RELATIVE_SCORE_CAP = 2.0
DEFAULT_PRIOR_ERROR_PERCENT = 50.0
ROBUSTNESS_SHRINKAGE_GRID = (2, 5, 10)
ROBUSTNESS_ERROR_FLOOR_GRID = (2.5, 5.0, 10.0)
ROBUSTNESS_RELATIVE_SCORE_CAP_GRID = (1.5, 2.0, 3.0)


@dataclass(frozen=True)
class ConsensusBacktestObservation:
    ticker: str
    fiscal_year: int
    snapshot: AccuracySnapshot
    cutoff: datetime
    actual_billion_rub: float
    sources: int
    sources_with_training_history: int
    training_samples: int
    source_forecasts: dict[str, float]
    source_weights: dict[str, float]
    source_training_samples: dict[str, int]
    median_forecast_billion_rub: float
    mean_forecast_billion_rub: float
    weighted_forecast_billion_rub: float


@dataclass(frozen=True)
class ConsensusBacktestMethod:
    method: str
    label: str
    samples: int
    tickers: int
    years: int
    median_smape_percent: float
    mean_smape_percent: float
    median_absolute_error_billion_rub: float
    mean_absolute_error_billion_rub: float
    mean_bias_billion_rub: float
    sign_accuracy_percent: float
    median_smape_delta_vs_median_pp: float
    mean_smape_delta_vs_median_pp: float


@dataclass(frozen=True)
class ConsensusBacktestResult:
    snapshot: AccuracySnapshot
    min_sources: int
    shrinkage_samples: int
    error_floor_percent: float
    relative_score_cap: float
    observations: int
    tickers: int
    years: int
    methods: list[ConsensusBacktestMethod]


@dataclass(frozen=True)
class ConsensusBacktestSlice:
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


@dataclass(frozen=True)
class ConsensusBacktestJackknife:
    dimension: str
    excluded_key: str
    observations: int
    weighted_median_delta_pp: float
    weighted_mean_delta_pp: float
    preserves_median_improvement: bool
    preserves_mean_improvement: bool


@dataclass(frozen=True)
class ConsensusBacktestParameterCase:
    shrinkage_samples: int
    error_floor_percent: float
    relative_score_cap: float
    observations: int
    weighted_median_smape_percent: float
    weighted_mean_smape_percent: float
    weighted_median_delta_pp: float
    weighted_mean_delta_pp: float


@dataclass(frozen=True)
class ConsensusBacktestRobustnessResult:
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
    by_year: list[ConsensusBacktestSlice]
    by_ticker: list[ConsensusBacktestSlice]
    jackknife_year: list[ConsensusBacktestJackknife]
    jackknife_ticker: list[ConsensusBacktestJackknife]
    parameter_sweep: list[ConsensusBacktestParameterCase]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _available_training_samples(
    samples: list[AccuracySample],
    *,
    target_fiscal_year: int,
    target_cutoff: datetime,
    reported_at_by_key: dict[tuple[str, int], datetime | None],
) -> list[AccuracySample]:
    available: list[AccuracySample] = []
    for sample in samples:
        if sample.fiscal_year >= target_fiscal_year:
            continue
        reported_at = reported_at_by_key.get((sample.ticker, sample.fiscal_year))
        if reported_at is None or _as_utc(reported_at) >= target_cutoff:
            continue
        available.append(sample)
    return available


def _source_weights(
    source_names: list[str],
    training_samples: list[AccuracySample],
    *,
    shrinkage_samples: int,
    error_floor_percent: float,
    relative_score_cap: float,
) -> tuple[dict[str, float], dict[str, int]]:
    if shrinkage_samples < 0:
        raise ValueError("shrinkage_samples must be non-negative")
    if error_floor_percent <= 0:
        raise ValueError("error_floor_percent must be positive")
    if relative_score_cap < 1:
        raise ValueError("relative_score_cap must be at least 1")

    global_errors = [sample.smape_percent for sample in training_samples]
    global_error = median(global_errors) if global_errors else DEFAULT_PRIOR_ERROR_PERCENT
    reference_error = max(float(global_error), error_floor_percent)

    by_source: dict[str, list[AccuracySample]] = {}
    for sample in training_samples:
        by_source.setdefault(sample.analyst_name, []).append(sample)

    scores: dict[str, float] = {}
    counts: dict[str, int] = {}
    for source_name in source_names:
        source_history = by_source.get(source_name, [])
        count = len(source_history)
        counts[source_name] = count
        if source_history:
            source_error = float(median(sample.smape_percent for sample in source_history))
            reliability = count / (count + shrinkage_samples) if shrinkage_samples else 1.0
            effective_error = reliability * source_error + (1.0 - reliability) * global_error
        else:
            effective_error = global_error

        effective_error = max(float(effective_error), error_floor_percent)
        relative_score = reference_error / effective_error
        relative_score = max(
            1.0 / relative_score_cap,
            min(relative_score_cap, relative_score),
        )
        scores[source_name] = relative_score

    score_sum = sum(scores.values())
    if score_sum <= 0:
        equal_weight = 1.0 / len(source_names)
        return ({name: equal_weight for name in source_names}, counts)
    return ({name: score / score_sum for name, score in scores.items()}, counts)


def _load_backtest_context(
    db: Session,
    *,
    snapshot: AccuracySnapshot,
) -> tuple[list[AccuracySample], dict[tuple[str, int], datetime | None]]:
    samples = build_accuracy_samples(db, snapshot=snapshot)
    actual_rows = list(db.scalars(select(ActualNetProfit)).all())
    reported_at_by_key = {
        (row.ticker.strip().upper(), row.fiscal_year): row.reported_at for row in actual_rows
    }
    return samples, reported_at_by_key


def _build_consensus_backtest_observations_from_context(
    samples: list[AccuracySample],
    reported_at_by_key: dict[tuple[str, int], datetime | None],
    *,
    snapshot: AccuracySnapshot,
    min_sources: int,
    shrinkage_samples: int,
    error_floor_percent: float,
    relative_score_cap: float,
) -> list[ConsensusBacktestObservation]:
    grouped: dict[tuple[str, int], list[AccuracySample]] = {}
    for sample in samples:
        grouped.setdefault((sample.ticker, sample.fiscal_year), []).append(sample)

    training_by_year: dict[int, list[AccuracySample]] = {}
    observations: list[ConsensusBacktestObservation] = []
    for (ticker, fiscal_year), target_samples in sorted(grouped.items(), key=lambda item: item[0]):
        by_source: dict[str, AccuracySample] = {}
        for sample in target_samples:
            by_source[sample.analyst_name] = sample
        if len(by_source) < min_sources:
            continue

        source_names = sorted(by_source, key=str.casefold)
        forecasts = {name: float(by_source[name].forecast_billion_rub) for name in source_names}
        actual_values = [float(sample.actual_billion_rub) for sample in by_source.values()]
        actual = actual_values[0]
        if any(abs(value - actual) > 1e-9 for value in actual_values[1:]):
            continue

        cutoff = snapshot_cutoff(fiscal_year, snapshot)
        if fiscal_year not in training_by_year:
            training_by_year[fiscal_year] = _available_training_samples(
                samples,
                target_fiscal_year=fiscal_year,
                target_cutoff=cutoff,
                reported_at_by_key=reported_at_by_key,
            )
        available_training = training_by_year[fiscal_year]
        weights, training_counts = _source_weights(
            source_names,
            available_training,
            shrinkage_samples=shrinkage_samples,
            error_floor_percent=error_floor_percent,
            relative_score_cap=relative_score_cap,
        )

        forecast_values = list(forecasts.values())
        weighted_forecast = sum(forecasts[name] * weights[name] for name in source_names)
        observations.append(
            ConsensusBacktestObservation(
                ticker=ticker,
                fiscal_year=fiscal_year,
                snapshot=snapshot,
                cutoff=cutoff,
                actual_billion_rub=actual,
                sources=len(source_names),
                sources_with_training_history=sum(
                    1 for count in training_counts.values() if count > 0
                ),
                training_samples=sum(training_counts.values()),
                source_forecasts=forecasts,
                source_weights=weights,
                source_training_samples=training_counts,
                median_forecast_billion_rub=float(median(forecast_values)),
                mean_forecast_billion_rub=float(mean(forecast_values)),
                weighted_forecast_billion_rub=float(weighted_forecast),
            )
        )
    return observations


def build_consensus_backtest_observations(
    db: Session,
    *,
    snapshot: AccuracySnapshot = "pre_year",
    min_sources: int = DEFAULT_MIN_SOURCES,
    shrinkage_samples: int = DEFAULT_SHRINKAGE_SAMPLES,
    error_floor_percent: float = DEFAULT_ERROR_FLOOR_PERCENT,
    relative_score_cap: float = DEFAULT_RELATIVE_SCORE_CAP,
) -> list[ConsensusBacktestObservation]:
    if min_sources < 2:
        raise ValueError("min_sources must be at least 2")

    samples, reported_at_by_key = _load_backtest_context(db, snapshot=snapshot)
    if not samples:
        return []
    return _build_consensus_backtest_observations_from_context(
        samples,
        reported_at_by_key,
        snapshot=snapshot,
        min_sources=min_sources,
        shrinkage_samples=shrinkage_samples,
        error_floor_percent=error_floor_percent,
        relative_score_cap=relative_score_cap,
    )


def _method_summary(
    observations: list[ConsensusBacktestObservation],
    *,
    method: str,
    label: str,
    forecast_field: str,
) -> ConsensusBacktestMethod:
    forecasts = [float(getattr(observation, forecast_field)) for observation in observations]
    actuals = [observation.actual_billion_rub for observation in observations]
    smapes = [
        symmetric_absolute_percentage_error(forecast, actual)
        for forecast, actual in zip(forecasts, actuals, strict=True)
    ]
    absolute_errors = [
        abs(forecast - actual) for forecast, actual in zip(forecasts, actuals, strict=True)
    ]
    biases = [forecast - actual for forecast, actual in zip(forecasts, actuals, strict=True)]
    sign_accuracy = 100.0 * sum(
        1
        for forecast, actual in zip(forecasts, actuals, strict=True)
        if _sign(forecast) == _sign(actual)
    ) / len(observations)

    return ConsensusBacktestMethod(
        method=method,
        label=label,
        samples=len(observations),
        tickers=len({observation.ticker for observation in observations}),
        years=len({observation.fiscal_year for observation in observations}),
        median_smape_percent=float(median(smapes)),
        mean_smape_percent=float(mean(smapes)),
        median_absolute_error_billion_rub=float(median(absolute_errors)),
        mean_absolute_error_billion_rub=float(mean(absolute_errors)),
        mean_bias_billion_rub=float(mean(biases)),
        sign_accuracy_percent=sign_accuracy,
        median_smape_delta_vs_median_pp=0.0,
        mean_smape_delta_vs_median_pp=0.0,
    )


def aggregate_consensus_backtest(
    observations: list[ConsensusBacktestObservation],
) -> list[ConsensusBacktestMethod]:
    if not observations:
        return []

    methods = [
        _method_summary(
            observations,
            method="median",
            label="Медиана",
            forecast_field="median_forecast_billion_rub",
        ),
        _method_summary(
            observations,
            method="mean",
            label="Среднее",
            forecast_field="mean_forecast_billion_rub",
        ),
        _method_summary(
            observations,
            method="weighted",
            label="Accuracy-weighted",
            forecast_field="weighted_forecast_billion_rub",
        ),
    ]
    baseline = methods[0]
    return [
        ConsensusBacktestMethod(
            **{
                **method.__dict__,
                "median_smape_delta_vs_median_pp": (
                    baseline.median_smape_percent - method.median_smape_percent
                ),
                "mean_smape_delta_vs_median_pp": (
                    baseline.mean_smape_percent - method.mean_smape_percent
                ),
            }
        )
        for method in methods
    ]


def _median_and_weighted(
    observations: list[ConsensusBacktestObservation],
) -> tuple[ConsensusBacktestMethod, ConsensusBacktestMethod] | None:
    methods = aggregate_consensus_backtest(observations)
    if not methods:
        return None
    by_method = {method.method: method for method in methods}
    return by_method["median"], by_method["weighted"]


def _dimension_key(observation: ConsensusBacktestObservation, dimension: str) -> str:
    if dimension == "year":
        return str(observation.fiscal_year)
    if dimension == "ticker":
        return observation.ticker
    raise ValueError("unsupported robustness dimension")


def _slice_backtest(
    observations: list[ConsensusBacktestObservation],
    *,
    dimension: str,
) -> list[ConsensusBacktestSlice]:
    grouped: dict[str, list[ConsensusBacktestObservation]] = {}
    for observation in observations:
        grouped.setdefault(_dimension_key(observation, dimension), []).append(observation)

    rows: list[ConsensusBacktestSlice] = []
    for key, group in grouped.items():
        pair = _median_and_weighted(group)
        if pair is None:
            continue
        baseline, weighted = pair
        rows.append(
            ConsensusBacktestSlice(
                dimension=dimension,
                key=key,
                observations=len(group),
                tickers=len({item.ticker for item in group}),
                years=len({item.fiscal_year for item in group}),
                baseline_median_smape_percent=baseline.median_smape_percent,
                weighted_median_smape_percent=weighted.median_smape_percent,
                weighted_median_delta_pp=weighted.median_smape_delta_vs_median_pp,
                baseline_mean_smape_percent=baseline.mean_smape_percent,
                weighted_mean_smape_percent=weighted.mean_smape_percent,
                weighted_mean_delta_pp=weighted.mean_smape_delta_vs_median_pp,
            )
        )
    if dimension == "year":
        return sorted(rows, key=lambda row: int(row.key))
    if dimension == "ticker":
        return sorted(rows, key=lambda row: row.key)
    raise ValueError("unsupported robustness dimension")


def _jackknife_backtest(
    observations: list[ConsensusBacktestObservation],
    *,
    dimension: str,
) -> list[ConsensusBacktestJackknife]:
    keys = {_dimension_key(item, dimension) for item in observations}
    ordered_keys = sorted(keys, key=int) if dimension == "year" else sorted(keys)

    rows: list[ConsensusBacktestJackknife] = []
    for key in ordered_keys:
        remaining = [
            item for item in observations if _dimension_key(item, dimension) != key
        ]
        pair = _median_and_weighted(remaining)
        if pair is None:
            continue
        _, weighted = pair
        rows.append(
            ConsensusBacktestJackknife(
                dimension=dimension,
                excluded_key=key,
                observations=len(remaining),
                weighted_median_delta_pp=weighted.median_smape_delta_vs_median_pp,
                weighted_mean_delta_pp=weighted.mean_smape_delta_vs_median_pp,
                preserves_median_improvement=weighted.median_smape_delta_vs_median_pp > 0,
                preserves_mean_improvement=weighted.mean_smape_delta_vs_median_pp > 0,
            )
        )
    return rows


def _parameter_sweep(
    samples: list[AccuracySample],
    reported_at_by_key: dict[tuple[str, int], datetime | None],
    *,
    snapshot: AccuracySnapshot,
    min_sources: int,
) -> list[ConsensusBacktestParameterCase]:
    rows: list[ConsensusBacktestParameterCase] = []
    for shrinkage_samples in ROBUSTNESS_SHRINKAGE_GRID:
        for error_floor_percent in ROBUSTNESS_ERROR_FLOOR_GRID:
            for relative_score_cap in ROBUSTNESS_RELATIVE_SCORE_CAP_GRID:
                observations = _build_consensus_backtest_observations_from_context(
                    samples,
                    reported_at_by_key,
                    snapshot=snapshot,
                    min_sources=min_sources,
                    shrinkage_samples=shrinkage_samples,
                    error_floor_percent=error_floor_percent,
                    relative_score_cap=relative_score_cap,
                )
                pair = _median_and_weighted(observations)
                if pair is None:
                    continue
                _, weighted = pair
                rows.append(
                    ConsensusBacktestParameterCase(
                        shrinkage_samples=shrinkage_samples,
                        error_floor_percent=error_floor_percent,
                        relative_score_cap=relative_score_cap,
                        observations=len(observations),
                        weighted_median_smape_percent=weighted.median_smape_percent,
                        weighted_mean_smape_percent=weighted.mean_smape_percent,
                        weighted_median_delta_pp=weighted.median_smape_delta_vs_median_pp,
                        weighted_mean_delta_pp=weighted.mean_smape_delta_vs_median_pp,
                    )
                )
    return rows


def build_consensus_backtest_robustness(
    db: Session,
    *,
    snapshot: AccuracySnapshot = "pre_year",
    min_sources: int = DEFAULT_MIN_SOURCES,
) -> ConsensusBacktestRobustnessResult:
    if min_sources < 2:
        raise ValueError("min_sources must be at least 2")

    samples, reported_at_by_key = _load_backtest_context(db, snapshot=snapshot)
    if not samples:
        return ConsensusBacktestRobustnessResult(
            snapshot=snapshot,
            min_sources=min_sources,
            observations=0,
            tickers=0,
            years=0,
            weighted_median_delta_pp=None,
            weighted_mean_delta_pp=None,
            positive_ticker_slices=0,
            ticker_slices=0,
            positive_year_slices=0,
            year_slices=0,
            ticker_jackknife_preserved=0,
            ticker_jackknife_cases=0,
            year_jackknife_preserved=0,
            year_jackknife_cases=0,
            positive_parameter_cases=0,
            parameter_cases=0,
            parameter_min_median_delta_pp=None,
            parameter_max_median_delta_pp=None,
            by_year=[],
            by_ticker=[],
            jackknife_year=[],
            jackknife_ticker=[],
            parameter_sweep=[],
        )

    observations = _build_consensus_backtest_observations_from_context(
        samples,
        reported_at_by_key,
        snapshot=snapshot,
        min_sources=min_sources,
        shrinkage_samples=DEFAULT_SHRINKAGE_SAMPLES,
        error_floor_percent=DEFAULT_ERROR_FLOOR_PERCENT,
        relative_score_cap=DEFAULT_RELATIVE_SCORE_CAP,
    )
    pair = _median_and_weighted(observations)
    weighted = pair[1] if pair is not None else None
    by_year = _slice_backtest(observations, dimension="year")
    by_ticker = _slice_backtest(observations, dimension="ticker")
    jackknife_year = _jackknife_backtest(observations, dimension="year")
    jackknife_ticker = _jackknife_backtest(observations, dimension="ticker")
    parameter_sweep = _parameter_sweep(
        samples,
        reported_at_by_key,
        snapshot=snapshot,
        min_sources=min_sources,
    )
    parameter_deltas = [row.weighted_median_delta_pp for row in parameter_sweep]

    return ConsensusBacktestRobustnessResult(
        snapshot=snapshot,
        min_sources=min_sources,
        observations=len(observations),
        tickers=len({observation.ticker for observation in observations}),
        years=len({observation.fiscal_year for observation in observations}),
        weighted_median_delta_pp=(
            weighted.median_smape_delta_vs_median_pp if weighted is not None else None
        ),
        weighted_mean_delta_pp=(
            weighted.mean_smape_delta_vs_median_pp if weighted is not None else None
        ),
        positive_ticker_slices=sum(1 for row in by_ticker if row.weighted_median_delta_pp > 0),
        ticker_slices=len(by_ticker),
        positive_year_slices=sum(1 for row in by_year if row.weighted_median_delta_pp > 0),
        year_slices=len(by_year),
        ticker_jackknife_preserved=sum(
            1 for row in jackknife_ticker if row.preserves_median_improvement
        ),
        ticker_jackknife_cases=len(jackknife_ticker),
        year_jackknife_preserved=sum(
            1 for row in jackknife_year if row.preserves_median_improvement
        ),
        year_jackknife_cases=len(jackknife_year),
        positive_parameter_cases=sum(1 for row in parameter_sweep if row.weighted_median_delta_pp > 0),
        parameter_cases=len(parameter_sweep),
        parameter_min_median_delta_pp=min(parameter_deltas) if parameter_deltas else None,
        parameter_max_median_delta_pp=max(parameter_deltas) if parameter_deltas else None,
        by_year=by_year,
        by_ticker=by_ticker,
        jackknife_year=jackknife_year,
        jackknife_ticker=jackknife_ticker,
        parameter_sweep=parameter_sweep,
    )


def build_consensus_backtest(
    db: Session,
    *,
    snapshot: AccuracySnapshot = "pre_year",
    min_sources: int = DEFAULT_MIN_SOURCES,
    shrinkage_samples: int = DEFAULT_SHRINKAGE_SAMPLES,
    error_floor_percent: float = DEFAULT_ERROR_FLOOR_PERCENT,
    relative_score_cap: float = DEFAULT_RELATIVE_SCORE_CAP,
) -> ConsensusBacktestResult:
    observations = build_consensus_backtest_observations(
        db,
        snapshot=snapshot,
        min_sources=min_sources,
        shrinkage_samples=shrinkage_samples,
        error_floor_percent=error_floor_percent,
        relative_score_cap=relative_score_cap,
    )
    methods = aggregate_consensus_backtest(observations)
    return ConsensusBacktestResult(
        snapshot=snapshot,
        min_sources=min_sources,
        shrinkage_samples=shrinkage_samples,
        error_floor_percent=error_floor_percent,
        relative_score_cap=relative_score_cap,
        observations=len(observations),
        tickers=len({observation.ticker for observation in observations}),
        years=len({observation.fiscal_year for observation in observations}),
        methods=methods,
    )
