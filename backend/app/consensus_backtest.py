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

    samples = build_accuracy_samples(db, snapshot=snapshot)
    if not samples:
        return []

    actual_rows = list(db.scalars(select(ActualNetProfit)).all())
    reported_at_by_key = {
        (row.ticker.strip().upper(), row.fiscal_year): row.reported_at for row in actual_rows
    }

    grouped: dict[tuple[str, int], list[AccuracySample]] = {}
    for sample in samples:
        grouped.setdefault((sample.ticker, sample.fiscal_year), []).append(sample)

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
        available_training = _available_training_samples(
            samples,
            target_fiscal_year=fiscal_year,
            target_cutoff=cutoff,
            reported_at_by_key=reported_at_by_key,
        )
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
