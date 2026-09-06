from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .canary_evidence import CanaryEvidenceSnapshot
from .consensus_canary import get_canary_settings
from .shadow_history import get_shadow_history_settings

CanaryEvidenceHealthStatus = Literal[
    "not_configured",
    "warming_up",
    "healthy",
    "degraded",
    "stale",
]

FRESHNESS_MULTIPLIER = 1.5
STALE_MULTIPLIER = 2.5
MISSED_GAP_MULTIPLIER = 1.75

_STATUS_PRIORITY: dict[CanaryEvidenceHealthStatus, int] = {
    "stale": 0,
    "degraded": 1,
    "warming_up": 2,
    "healthy": 3,
    "not_configured": 4,
}


@dataclass(frozen=True)
class CanaryTickerEvidenceHealthResult:
    ticker: str
    status: CanaryEvidenceHealthStatus
    reasons: list[str]
    expected_interval_hours: float
    snapshots: int
    first_captured_at: datetime | None
    last_captured_at: datetime | None
    latest_age_hours: float | None
    history_span_hours: float
    observed_intervals: int
    gap_violations: int
    missed_cycles_estimate: int
    longest_gap_hours: float
    continuity_percent: float | None


@dataclass(frozen=True)
class CanaryEvidenceHealthOverviewResult:
    generated_at: datetime
    history_days: int
    canary_enabled: bool
    configured_tickers: int
    expected_interval_hours: float
    status: CanaryEvidenceHealthStatus
    tickers_with_evidence: int
    healthy_tickers: int
    warming_up_tickers: int
    degraded_tickers: int
    stale_tickers: int
    fresh_tickers: int
    delayed_tickers: int
    missed_cycles_estimate: int
    gap_violations: int
    latest_capture_at: datetime | None
    latest_capture_age_hours: float | None
    longest_gap_hours: float
    median_continuity_percent: float | None
    items: list[CanaryTickerEvidenceHealthResult]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _age_hours(*, now: datetime, captured_at: datetime) -> float:
    return max((now - _as_utc(captured_at)).total_seconds() / 3600.0, 0.0)


def _missed_cycles_for_gap(gap_hours: float, expected_interval_hours: float) -> int:
    if gap_hours < expected_interval_hours * MISSED_GAP_MULTIPLIER:
        return 0
    return max(int(round(gap_hours / expected_interval_hours)) - 1, 1)


def _empty_ticker_health(
    *,
    ticker: str,
    expected_interval_hours: float,
) -> CanaryTickerEvidenceHealthResult:
    return CanaryTickerEvidenceHealthResult(
        ticker=ticker,
        status="warming_up",
        reasons=["no_evidence"],
        expected_interval_hours=expected_interval_hours,
        snapshots=0,
        first_captured_at=None,
        last_captured_at=None,
        latest_age_hours=None,
        history_span_hours=0.0,
        observed_intervals=0,
        gap_violations=0,
        missed_cycles_estimate=0,
        longest_gap_hours=0.0,
        continuity_percent=None,
    )


def _build_ticker_health_from_rows(
    *,
    ticker: str,
    rows: list[CanaryEvidenceSnapshot],
    expected_interval_hours: float,
    now: datetime,
) -> CanaryTickerEvidenceHealthResult:
    if not rows:
        return _empty_ticker_health(
            ticker=ticker,
            expected_interval_hours=expected_interval_hours,
        )

    ordered = sorted(rows, key=lambda row: (_as_utc(row.captured_at), row.id or 0))
    first_at = _as_utc(ordered[0].captured_at)
    last_at = _as_utc(ordered[-1].captured_at)
    latest_age = _age_hours(now=now, captured_at=last_at)

    gaps: list[float] = []
    missed_cycles = 0
    gap_violations = 0
    for previous, current in zip(ordered, ordered[1:]):
        if previous.target_year != current.target_year:
            continue
        gap = max(
            (_as_utc(current.captured_at) - _as_utc(previous.captured_at)).total_seconds()
            / 3600.0,
            0.0,
        )
        gaps.append(gap)
        missed = _missed_cycles_for_gap(gap, expected_interval_hours)
        if missed:
            gap_violations += 1
            missed_cycles += missed

    observed_intervals = len(gaps)
    continuity = None
    denominator = observed_intervals + missed_cycles
    if denominator > 0:
        continuity = 100.0 * observed_intervals / denominator

    reasons: list[str] = []
    if latest_age > expected_interval_hours * STALE_MULTIPLIER:
        status: CanaryEvidenceHealthStatus = "stale"
        reasons.append("latest_snapshot_stale")
    elif observed_intervals < 1:
        status = "warming_up"
        reasons.append("too_few_snapshots")
    elif (
        latest_age > expected_interval_hours * FRESHNESS_MULTIPLIER
        or missed_cycles > 0
    ):
        status = "degraded"
        if latest_age > expected_interval_hours * FRESHNESS_MULTIPLIER:
            reasons.append("latest_snapshot_delayed")
        if missed_cycles > 0:
            reasons.append("capture_gaps_detected")
    else:
        status = "healthy"

    return CanaryTickerEvidenceHealthResult(
        ticker=ticker,
        status=status,
        reasons=reasons,
        expected_interval_hours=expected_interval_hours,
        snapshots=len(ordered),
        first_captured_at=first_at,
        last_captured_at=last_at,
        latest_age_hours=latest_age,
        history_span_hours=max((last_at - first_at).total_seconds() / 3600.0, 0.0),
        observed_intervals=observed_intervals,
        gap_violations=gap_violations,
        missed_cycles_estimate=missed_cycles,
        longest_gap_hours=max(gaps) if gaps else 0.0,
        continuity_percent=continuity,
    )


def build_canary_evidence_health(
    db: Session,
    *,
    days: int = 30,
    now: datetime | None = None,
) -> CanaryEvidenceHealthOverviewResult:
    current = _as_utc(now or datetime.now(timezone.utc))
    settings = get_canary_settings(db)
    tickers = sorted(settings.tickers)
    expected_interval = max(get_shadow_history_settings().interval_hours, 1.0)

    if not tickers:
        return CanaryEvidenceHealthOverviewResult(
            generated_at=current,
            history_days=days,
            canary_enabled=settings.enabled,
            configured_tickers=0,
            expected_interval_hours=expected_interval,
            status="not_configured",
            tickers_with_evidence=0,
            healthy_tickers=0,
            warming_up_tickers=0,
            degraded_tickers=0,
            stale_tickers=0,
            fresh_tickers=0,
            delayed_tickers=0,
            missed_cycles_estimate=0,
            gap_violations=0,
            latest_capture_at=None,
            latest_capture_age_hours=None,
            longest_gap_hours=0.0,
            median_continuity_percent=None,
            items=[],
        )

    cutoff = current - timedelta(days=days)
    rows = list(
        db.scalars(
            select(CanaryEvidenceSnapshot)
            .where(
                CanaryEvidenceSnapshot.ticker.in_(tickers),
                CanaryEvidenceSnapshot.captured_at >= cutoff,
            )
            .order_by(
                CanaryEvidenceSnapshot.ticker.asc(),
                CanaryEvidenceSnapshot.captured_at.asc(),
                CanaryEvidenceSnapshot.id.asc(),
            )
        ).all()
    )
    grouped: dict[str, list[CanaryEvidenceSnapshot]] = {ticker: [] for ticker in tickers}
    for row in rows:
        if row.ticker in grouped:
            grouped[row.ticker].append(row)

    items = [
        _build_ticker_health_from_rows(
            ticker=ticker,
            rows=grouped[ticker],
            expected_interval_hours=expected_interval,
            now=current,
        )
        for ticker in tickers
    ]
    items.sort(key=lambda item: (_STATUS_PRIORITY[item.status], item.ticker))

    overall_status = min(
        (item.status for item in items),
        key=lambda value: _STATUS_PRIORITY[value],
    )
    captures = [item.last_captured_at for item in items if item.last_captured_at is not None]
    latest_capture = max(captures) if captures else None
    continuities = [
        item.continuity_percent
        for item in items
        if item.continuity_percent is not None and math.isfinite(item.continuity_percent)
    ]
    freshness_limit = expected_interval * FRESHNESS_MULTIPLIER
    stale_limit = expected_interval * STALE_MULTIPLIER

    return CanaryEvidenceHealthOverviewResult(
        generated_at=current,
        history_days=days,
        canary_enabled=settings.enabled,
        configured_tickers=len(tickers),
        expected_interval_hours=expected_interval,
        status=overall_status,
        tickers_with_evidence=sum(item.snapshots > 0 for item in items),
        healthy_tickers=sum(item.status == "healthy" for item in items),
        warming_up_tickers=sum(item.status == "warming_up" for item in items),
        degraded_tickers=sum(item.status == "degraded" for item in items),
        stale_tickers=sum(item.status == "stale" for item in items),
        fresh_tickers=sum(
            item.latest_age_hours is not None and item.latest_age_hours <= freshness_limit
            for item in items
        ),
        delayed_tickers=sum(
            item.latest_age_hours is not None
            and freshness_limit < item.latest_age_hours <= stale_limit
            for item in items
        ),
        missed_cycles_estimate=sum(item.missed_cycles_estimate for item in items),
        gap_violations=sum(item.gap_violations for item in items),
        latest_capture_at=latest_capture,
        latest_capture_age_hours=(
            _age_hours(now=current, captured_at=latest_capture)
            if latest_capture is not None
            else None
        ),
        longest_gap_hours=max((item.longest_gap_hours for item in items), default=0.0),
        median_continuity_percent=(float(median(continuities)) if continuities else None),
        items=items,
    )
