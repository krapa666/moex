from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Literal

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from .arsagera_sync import DEFAULT_ANALYST_NAME as ARSAGERA_DEFAULT_ANALYST_NAME
from .dohod_source import DEFAULT_ANALYST_NAME as DOHOD_DEFAULT_ANALYST_NAME
from .finvista_source import DEFAULT_ANALYST_NAME as FINVISTA_DEFAULT_ANALYST_NAME
from .forecast_source_runs import ForecastSourceRun
from .forecast_sources import load_published_sheets_sources

ForecastSourceHealthStatus = Literal["healthy", "degraded", "stale", "failed"]

FRESHNESS_MULTIPLIER = 1.5
STALE_MULTIPLIER = 2.5
COVERAGE_DROP_THRESHOLD_PP = 10.0
COVERAGE_BASELINE_MIN_RUNS = 3
COVERAGE_BASELINE_MAX_RUNS = 10

_STATUS_PRIORITY: dict[ForecastSourceHealthStatus, int] = {
    "failed": 0,
    "stale": 1,
    "degraded": 2,
    "healthy": 3,
}


@dataclass(frozen=True)
class ForecastSourceHealthConfig:
    source_id: str
    source_key: str
    analyst_name: str
    public_name: str
    expected_interval_hours: float
    configuration_error: str | None = None


@dataclass(frozen=True)
class ForecastSourceHealthItem:
    source_id: str
    source_key: str
    display_name: str
    analyst_name: str
    expected_interval_hours: float
    status: ForecastSourceHealthStatus
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
    latest_error_message: str | None
    latest_error_details: dict[str, str] | None


@dataclass(frozen=True)
class ForecastSourceHealthOverview:
    generated_at: datetime
    history_days: int
    configured_sources: int
    sources_with_runs: int
    status: ForecastSourceHealthStatus
    healthy_sources: int
    degraded_sources: int
    stale_sources: int
    failed_sources: int
    latest_run_at: datetime | None
    items: list[ForecastSourceHealthItem]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _interval_from_env(name: str, default: float = 6.0) -> tuple[float, str | None]:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default, None
    try:
        value = float(raw)
    except ValueError:
        return default, f"{name} must be a number"
    return max(value, 1.0), None


def load_forecast_source_health_configs() -> list[ForecastSourceHealthConfig]:
    configs: list[ForecastSourceHealthConfig] = []

    arsagera_interval, arsagera_error = _interval_from_env("ARSAGERA_SYNC_INTERVAL_HOURS")
    arsagera_name = (
        os.getenv("ARSAGERA_ANALYST_NAME") or ARSAGERA_DEFAULT_ANALYST_NAME
    ).strip()
    if not arsagera_name:
        arsagera_error = arsagera_error or "ARSAGERA_ANALYST_NAME must not be blank"
    configs.append(
        ForecastSourceHealthConfig(
            source_id="arsagera",
            source_key="arsagera",
            analyst_name=arsagera_name,
            public_name="Арсагера",
            expected_interval_hours=arsagera_interval,
            configuration_error=arsagera_error,
        )
    )

    if _env_bool("DOHOD_ENABLED", True):
        dohod_interval, dohod_error = _interval_from_env("DOHOD_SYNC_INTERVAL_HOURS")
        dohod_name = (os.getenv("DOHOD_ANALYST_NAME") or DOHOD_DEFAULT_ANALYST_NAME).strip()
        if not dohod_name:
            dohod_error = dohod_error or "DOHOD_ANALYST_NAME must not be blank"
        configs.append(
            ForecastSourceHealthConfig(
                source_id="dohod",
                source_key="dohod",
                analyst_name=dohod_name,
                public_name="ДОХОДЪ",
                expected_interval_hours=dohod_interval,
                configuration_error=dohod_error,
            )
        )

    if _env_bool("FINVISTA_ENABLED", False):
        finvista_interval, finvista_error = _interval_from_env("FINVISTA_SYNC_INTERVAL_HOURS")
        finvista_name = (
            os.getenv("FINVISTA_ANALYST_NAME") or FINVISTA_DEFAULT_ANALYST_NAME
        ).strip()
        if not finvista_name:
            finvista_error = finvista_error or "FINVISTA_ANALYST_NAME must not be blank"
        configs.append(
            ForecastSourceHealthConfig(
                source_id="fin-vista",
                source_key="fin-vista",
                analyst_name=finvista_name,
                public_name="fin-vista (модель)",
                expected_interval_hours=finvista_interval,
                configuration_error=finvista_error,
            )
        )

    sheets_interval, sheets_interval_error = _interval_from_env(
        "FORECAST_SHEETS_SYNC_INTERVAL_HOURS"
    )
    try:
        sheets_sources = sorted(
            load_published_sheets_sources(),
            key=lambda source: source.analyst_name.casefold(),
        )
    except ValueError as exc:
        configs.append(
            ForecastSourceHealthConfig(
                source_id="published-sheets-config",
                source_key="published-sheets",
                analyst_name="",
                public_name="Published Sheets",
                expected_interval_hours=sheets_interval,
                configuration_error=str(exc),
            )
        )
    else:
        for index, source in enumerate(sheets_sources, start=1):
            configs.append(
                ForecastSourceHealthConfig(
                    source_id=f"published-sheets:{index}",
                    source_key="published-sheets",
                    analyst_name=source.analyst_name,
                    public_name=f"Published Sheets #{index}",
                    expected_interval_hours=sheets_interval,
                    configuration_error=sheets_interval_error,
                )
            )

    return configs


def _coverage_percent(run: ForecastSourceRun) -> float | None:
    if run.tickers_total <= 0:
        return None
    return 100.0 * run.tickers_mapped / run.tickers_total


def _count_prefix(rows: list[ForecastSourceRun], status: str) -> int:
    count = 0
    for row in rows:
        if row.status != status:
            break
        count += 1
    return count


def _trim_error_details(value: dict[str, str] | None, limit: int = 50) -> dict[str, str] | None:
    if not value:
        return None
    return dict(list(value.items())[:limit])


def _build_source_item(
    *,
    config: ForecastSourceHealthConfig,
    rows: list[ForecastSourceRun],
    now: datetime,
    cutoff: datetime,
) -> ForecastSourceHealthItem:
    ordered = sorted(rows, key=lambda row: (_as_utc(row.started_at), row.id or 0), reverse=True)
    latest_run = ordered[0] if ordered else None
    completed = [
        row
        for row in ordered
        if row.status != "running" and row.finished_at is not None
    ]
    latest_completed = completed[0] if completed else None
    last_success = next((row for row in completed if row.status == "success"), None)
    recent = [row for row in completed if _as_utc(row.started_at) >= cutoff]

    run_in_progress = latest_run is not None and latest_run.status == "running"
    last_run_at = _as_utc(latest_run.started_at) if latest_run is not None else None
    last_completed_at = (
        _as_utc(latest_completed.finished_at or latest_completed.started_at)
        if latest_completed is not None
        else None
    )
    last_success_at = (
        _as_utc(last_success.finished_at or last_success.started_at)
        if last_success is not None
        else None
    )
    latest_age = (
        max((now - last_completed_at).total_seconds() / 3600.0, 0.0)
        if last_completed_at is not None
        else None
    )

    coverage = None
    baseline_coverage = None
    coverage_change = None
    baseline_runs = 0
    if latest_completed is not None and latest_completed.status in {"success", "partial"}:
        coverage = _coverage_percent(latest_completed)
        prior_coverages = [
            value
            for row in completed[1:]
            if row.status in {"success", "partial"}
            for value in [_coverage_percent(row)]
            if value is not None
        ][:COVERAGE_BASELINE_MAX_RUNS]
        baseline_runs = len(prior_coverages)
        if prior_coverages:
            baseline_coverage = float(median(prior_coverages))
        if coverage is not None and baseline_coverage is not None:
            coverage_change = coverage - baseline_coverage

    reasons: list[str] = []
    if config.configuration_error:
        status: ForecastSourceHealthStatus = "failed"
        reasons.append("configuration_error")
    elif latest_completed is None:
        if run_in_progress:
            status = "degraded"
            reasons.append("first_run_in_progress")
        else:
            status = "stale"
            reasons.append("no_completed_runs")
    elif latest_completed.status == "failed":
        status = "failed"
        reasons.append("latest_run_failed")
    elif latest_age is not None and latest_age > config.expected_interval_hours * STALE_MULTIPLIER:
        status = "stale"
        reasons.append("latest_run_stale")
    else:
        status = "healthy"
        if latest_age is not None and latest_age > config.expected_interval_hours * FRESHNESS_MULTIPLIER:
            status = "degraded"
            reasons.append("latest_run_delayed")
        if latest_completed.status == "partial":
            status = "degraded"
            reasons.append("latest_run_partial")
        if (
            coverage_change is not None
            and baseline_runs >= COVERAGE_BASELINE_MIN_RUNS
            and coverage_change <= -COVERAGE_DROP_THRESHOLD_PP
        ):
            status = "degraded"
            reasons.append("coverage_drop")

    latest_error_kind = None
    latest_error_count = 0
    latest_error_message = None
    latest_error_details = None
    if config.configuration_error:
        latest_error_kind = "configuration"
        latest_error_count = 1
        latest_error_message = config.configuration_error
    elif latest_completed is not None:
        if latest_completed.status == "failed" and latest_completed.error_message:
            latest_error_kind = "sync_exception"
            latest_error_count = 1
            latest_error_message = latest_completed.error_message
        elif latest_completed.error_details:
            latest_error_kind = "ticker_errors"
            latest_error_count = len(latest_completed.error_details)
            latest_error_details = _trim_error_details(latest_completed.error_details)
        elif latest_completed.status == "partial":
            latest_error_kind = "partial"
            latest_error_count = max(latest_completed.tickers_skipped, 0)

    return ForecastSourceHealthItem(
        source_id=config.source_id,
        source_key=config.source_key,
        display_name=config.public_name,
        analyst_name=config.analyst_name,
        expected_interval_hours=config.expected_interval_hours,
        status=status,
        reasons=reasons,
        run_in_progress=run_in_progress,
        latest_run_status=latest_run.status if latest_run is not None else None,
        last_run_at=last_run_at,
        last_completed_at=last_completed_at,
        last_success_at=last_success_at,
        latest_age_hours=latest_age,
        coverage_percent=coverage,
        baseline_coverage_percent=baseline_coverage,
        coverage_change_pp=coverage_change,
        coverage_baseline_runs=baseline_runs,
        tickers_total=latest_completed.tickers_total if latest_completed is not None else None,
        tickers_mapped=latest_completed.tickers_mapped if latest_completed is not None else None,
        tickers_updated=latest_completed.tickers_updated if latest_completed is not None else None,
        tickers_unchanged=latest_completed.tickers_unchanged if latest_completed is not None else None,
        tickers_skipped=latest_completed.tickers_skipped if latest_completed is not None else None,
        runs_in_window=len(recent),
        success_runs=sum(row.status == "success" for row in recent),
        partial_runs=sum(row.status == "partial" for row in recent),
        failed_runs=sum(row.status == "failed" for row in recent),
        consecutive_successes=_count_prefix(completed, "success"),
        consecutive_failures=_count_prefix(completed, "failed"),
        latest_error_kind=latest_error_kind,
        latest_error_count=latest_error_count,
        latest_error_message=latest_error_message,
        latest_error_details=latest_error_details,
    )


def build_forecast_source_health(
    db: Session,
    *,
    days: int = 30,
    now: datetime | None = None,
    configs: list[ForecastSourceHealthConfig] | None = None,
) -> ForecastSourceHealthOverview:
    current = _as_utc(now or datetime.now(timezone.utc))
    cutoff = current - timedelta(days=days)
    source_configs = configs if configs is not None else load_forecast_source_health_configs()

    queryable_configs = [
        config
        for config in source_configs
        if config.analyst_name and config.configuration_error is None
    ]
    grouped: dict[tuple[str, str], list[ForecastSourceRun]] = {
        (config.source_key, config.analyst_name): [] for config in queryable_configs
    }
    if grouped:
        clauses = [
            and_(
                ForecastSourceRun.source_key == source_key,
                ForecastSourceRun.analyst_name == analyst_name,
            )
            for source_key, analyst_name in grouped
        ]
        rows = list(
            db.scalars(
                select(ForecastSourceRun)
                .where(or_(*clauses))
                .order_by(ForecastSourceRun.started_at.desc(), ForecastSourceRun.id.desc())
            ).all()
        )
        for row in rows:
            key = (row.source_key, row.analyst_name)
            if key in grouped:
                grouped[key].append(row)

    items = [
        _build_source_item(
            config=config,
            rows=grouped.get((config.source_key, config.analyst_name), []),
            now=current,
            cutoff=cutoff,
        )
        for config in source_configs
    ]
    items.sort(key=lambda item: (_STATUS_PRIORITY[item.status], item.display_name.casefold()))

    if items:
        overall_status = min(items, key=lambda item: _STATUS_PRIORITY[item.status]).status
    else:
        overall_status = "stale"

    latest_runs = [item.last_run_at for item in items if item.last_run_at is not None]
    return ForecastSourceHealthOverview(
        generated_at=current,
        history_days=days,
        configured_sources=len(items),
        sources_with_runs=sum(item.last_run_at is not None for item in items),
        status=overall_status,
        healthy_sources=sum(item.status == "healthy" for item in items),
        degraded_sources=sum(item.status == "degraded" for item in items),
        stale_sources=sum(item.status == "stale" for item in items),
        failed_sources=sum(item.status == "failed" for item in items),
        latest_run_at=max(latest_runs) if latest_runs else None,
        items=items,
    )
