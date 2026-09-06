from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Literal

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, and_, delete, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .database import Base, SessionLocal
from .forecast_accuracy import AccuracySnapshot
from .models import AnalystTable, StockRow
from .shadow_consensus import build_shadow_consensus_batch

ShadowDriftStatus = Literal["insufficient", "stable", "watch", "alert"]

DRIFT_MIN_SNAPSHOTS = 3
DRIFT_MIN_SPAN_HOURS = 24.0
DRIFT_WATCH_ABS_DIVERGENCE_PERCENT = 10.0
DRIFT_ALERT_ABS_DIVERGENCE_PERCENT = 20.0
DRIFT_WATCH_STEP_PERCENTAGE_POINTS = 5.0
DRIFT_ALERT_STEP_PERCENTAGE_POINTS = 10.0
DRIFT_WATCH_CONCENTRATION_RATIO = 1.5
DRIFT_ALERT_CONCENTRATION_RATIO = 1.75
DRIFT_WATCH_MOVEMENT_GAP_PERCENTAGE_POINTS = 5.0
DRIFT_ALERT_MOVEMENT_GAP_PERCENTAGE_POINTS = 10.0

_STATUS_PRIORITY: dict[ShadowDriftStatus, int] = {
    "alert": 0,
    "watch": 1,
    "stable": 2,
    "insufficient": 3,
}


class ShadowConsensusSnapshot(Base):
    __tablename__ = "shadow_consensus_snapshots"
    __table_args__ = (
        Index(
            "ix_shadow_consensus_snapshots_ticker_captured_at",
            "ticker",
            "captured_at",
        ),
        Index(
            "ix_shadow_consensus_snapshots_target_year_captured_at",
            "target_year",
            "captured_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    target_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    training_snapshot: Mapped[str] = mapped_column(String(16), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    sources: Mapped[int] = mapped_column(Integer, nullable=False)
    sources_with_training_history: Mapped[int] = mapped_column(Integer, nullable=False)
    training_samples: Mapped[int] = mapped_column(Integer, nullable=False)
    weighting_uses_history: Mapped[bool] = mapped_column(Boolean, nullable=False)
    max_source_weight_percent: Mapped[float] = mapped_column(Float, nullable=False)
    min_source_weight_percent: Mapped[float] = mapped_column(Float, nullable=False)
    median_net_profit_billion_rub: Mapped[float] = mapped_column(Float, nullable=False)
    weighted_net_profit_billion_rub: Mapped[float] = mapped_column(Float, nullable=False)
    median_target_price: Mapped[float] = mapped_column(Float, nullable=False)
    weighted_target_price: Mapped[float] = mapped_column(Float, nullable=False)
    weighted_vs_median_target_delta_rub: Mapped[float] = mapped_column(Float, nullable=False)
    weighted_vs_median_target_delta_percent: Mapped[float] = mapped_column(Float, nullable=False)
    current_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    median_market_gap_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    weighted_market_gap_percent: Mapped[float | None] = mapped_column(Float, nullable=True)


@dataclass(frozen=True)
class ShadowHistorySettings:
    enabled: bool
    interval_hours: float
    run_on_startup: bool
    retention_days: int


@dataclass(frozen=True)
class ShadowCaptureResult:
    captured_at: datetime
    tickers_total: int
    snapshots_created: int
    skipped_unavailable: int
    deleted_expired: int


@dataclass(frozen=True)
class ShadowDriftResult:
    ticker: str
    target_year: int | None
    latest_training_snapshot: AccuracySnapshot | None
    status: ShadowDriftStatus
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


@dataclass(frozen=True)
class ShadowDriftOverviewResult:
    generated_at: datetime
    history_days: int
    universe_tickers: int
    tickers_with_history: int
    classified_tickers: int
    alert_tickers: int
    watch_tickers: int
    stable_tickers: int
    insufficient_tickers: int
    actionable_tickers: int
    history_coverage_percent: float
    classified_coverage_percent: float
    items: list[ShadowDriftResult]


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_shadow_history_settings() -> ShadowHistorySettings:
    return ShadowHistorySettings(
        enabled=_env_bool("SHADOW_HISTORY_ENABLED", True),
        interval_hours=max(float(os.getenv("SHADOW_HISTORY_INTERVAL_HOURS", "6")), 1.0),
        run_on_startup=_env_bool("SHADOW_HISTORY_RUN_ON_STARTUP", True),
        retention_days=max(int(os.getenv("SHADOW_HISTORY_RETENTION_DAYS", "730")), 30),
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def capture_shadow_consensus(
    db: Session,
    *,
    captured_at: datetime | None = None,
    retention_days: int | None = None,
) -> ShadowCaptureResult:
    current = _as_utc(captured_at or datetime.now(timezone.utc))
    settings = get_shadow_history_settings()
    effective_retention_days = retention_days or settings.retention_days
    results = build_shadow_consensus_batch(db, as_of=current)

    created = 0
    skipped = 0
    for result in results:
        required_values = (
            result.target_year,
            result.training_snapshot,
            result.max_source_weight_percent,
            result.min_source_weight_percent,
            result.median_net_profit_billion_rub,
            result.weighted_net_profit_billion_rub,
            result.median_target_price,
            result.weighted_target_price,
            result.weighted_vs_median_target_delta_rub,
            result.weighted_vs_median_target_delta_percent,
        )
        if not result.shadow_available or any(value is None for value in required_values):
            skipped += 1
            continue

        db.add(
            ShadowConsensusSnapshot(
                ticker=result.ticker,
                target_year=int(result.target_year),
                training_snapshot=str(result.training_snapshot),
                captured_at=current,
                sources=result.sources,
                sources_with_training_history=result.sources_with_training_history,
                training_samples=result.training_samples,
                weighting_uses_history=result.weighting_uses_history,
                max_source_weight_percent=float(result.max_source_weight_percent),
                min_source_weight_percent=float(result.min_source_weight_percent),
                median_net_profit_billion_rub=float(result.median_net_profit_billion_rub),
                weighted_net_profit_billion_rub=float(result.weighted_net_profit_billion_rub),
                median_target_price=float(result.median_target_price),
                weighted_target_price=float(result.weighted_target_price),
                weighted_vs_median_target_delta_rub=float(
                    result.weighted_vs_median_target_delta_rub
                ),
                weighted_vs_median_target_delta_percent=float(
                    result.weighted_vs_median_target_delta_percent
                ),
                current_price=result.current_price,
                median_market_gap_percent=result.median_market_gap_percent,
                weighted_market_gap_percent=result.weighted_market_gap_percent,
            )
        )
        created += 1

    cutoff = current - timedelta(days=effective_retention_days)
    deleted_expired = int(
        db.execute(
            delete(ShadowConsensusSnapshot).where(
                ShadowConsensusSnapshot.captured_at < cutoff
            )
        ).rowcount
        or 0
    )
    db.commit()
    return ShadowCaptureResult(
        captured_at=current,
        tickers_total=len(results),
        snapshots_created=created,
        skipped_unavailable=skipped,
        deleted_expired=deleted_expired,
    )


def capture_shadow_consensus_once() -> ShadowCaptureResult:
    with SessionLocal() as db:
        return capture_shadow_consensus(db)


def list_shadow_history(
    db: Session,
    *,
    ticker: str,
    days: int = 90,
    limit: int = 500,
) -> list[ShadowConsensusSnapshot]:
    normalized_ticker = ticker.strip().upper()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = list(
        db.scalars(
            select(ShadowConsensusSnapshot)
            .where(
                ShadowConsensusSnapshot.ticker == normalized_ticker,
                ShadowConsensusSnapshot.captured_at >= cutoff,
            )
            .order_by(
                ShadowConsensusSnapshot.captured_at.desc(),
                ShadowConsensusSnapshot.id.desc(),
            )
            .limit(limit)
        ).all()
    )
    rows.reverse()
    return rows


def _percent_change(first: float, last: float) -> float | None:
    if abs(first) <= 1e-12:
        return None
    return 100.0 * (last / first - 1.0)


def _concentration_ratio(snapshot: ShadowConsensusSnapshot) -> float | None:
    if snapshot.sources <= 0:
        return None
    equal_weight_percent = 100.0 / snapshot.sources
    if equal_weight_percent <= 0:
        return None
    return snapshot.max_source_weight_percent / equal_weight_percent


def _empty_shadow_drift_result(
    *,
    ticker: str,
    days: int,
    reason: str = "no_history",
) -> ShadowDriftResult:
    return ShadowDriftResult(
        ticker=ticker,
        target_year=None,
        latest_training_snapshot=None,
        status="insufficient",
        reasons=[reason],
        snapshots=0,
        history_days=days,
        history_span_hours=0.0,
        first_captured_at=None,
        last_captured_at=None,
        latest_delta_percent=None,
        previous_delta_percent=None,
        delta_step_percentage_points=None,
        median_abs_delta_percent=None,
        max_abs_delta_percent=None,
        latest_weight_concentration_ratio=None,
        max_weight_concentration_ratio=None,
        median_target_change_percent=None,
        weighted_target_change_percent=None,
        relative_movement_gap_percentage_points=None,
        training_snapshot_changed=False,
    )


def _build_shadow_drift_from_rows(
    *,
    ticker: str,
    days: int,
    latest: ShadowConsensusSnapshot | None,
    rows: list[ShadowConsensusSnapshot],
) -> ShadowDriftResult:
    if latest is None:
        return _empty_shadow_drift_result(ticker=ticker, days=days)
    effective_rows = rows or [latest]

    first = effective_rows[0]
    last = effective_rows[-1]
    previous = effective_rows[-2] if len(effective_rows) >= 2 else None
    first_at = _as_utc(first.captured_at)
    last_at = _as_utc(last.captured_at)
    history_span_hours = max((last_at - first_at).total_seconds() / 3600.0, 0.0)

    deltas = [float(row.weighted_vs_median_target_delta_percent) for row in effective_rows]
    concentrations = [
        value
        for value in (_concentration_ratio(row) for row in effective_rows)
        if value is not None
    ]
    latest_delta = float(last.weighted_vs_median_target_delta_percent)
    previous_delta = (
        float(previous.weighted_vs_median_target_delta_percent) if previous is not None else None
    )
    delta_step = latest_delta - previous_delta if previous_delta is not None else None
    latest_concentration = _concentration_ratio(last)
    max_concentration = max(concentrations) if concentrations else None
    median_target_change = _percent_change(first.median_target_price, last.median_target_price)
    weighted_target_change = _percent_change(first.weighted_target_price, last.weighted_target_price)
    movement_gap = (
        weighted_target_change - median_target_change
        if weighted_target_change is not None and median_target_change is not None
        else None
    )
    training_snapshot_changed = (
        previous is not None and previous.training_snapshot != last.training_snapshot
    )

    common = dict(
        ticker=ticker,
        target_year=latest.target_year,
        latest_training_snapshot=last.training_snapshot,
        snapshots=len(effective_rows),
        history_days=days,
        history_span_hours=history_span_hours,
        first_captured_at=first_at,
        last_captured_at=last_at,
        latest_delta_percent=latest_delta,
        previous_delta_percent=previous_delta,
        delta_step_percentage_points=delta_step,
        median_abs_delta_percent=float(median(abs(value) for value in deltas)),
        max_abs_delta_percent=max(abs(value) for value in deltas),
        latest_weight_concentration_ratio=latest_concentration,
        max_weight_concentration_ratio=max_concentration,
        median_target_change_percent=median_target_change,
        weighted_target_change_percent=weighted_target_change,
        relative_movement_gap_percentage_points=movement_gap,
        training_snapshot_changed=training_snapshot_changed,
    )

    if len(effective_rows) < DRIFT_MIN_SNAPSHOTS or history_span_hours < DRIFT_MIN_SPAN_HOURS:
        reasons = []
        if len(effective_rows) < DRIFT_MIN_SNAPSHOTS:
            reasons.append("too_few_snapshots")
        if history_span_hours < DRIFT_MIN_SPAN_HOURS:
            reasons.append("history_too_short")
        return ShadowDriftResult(status="insufficient", reasons=reasons, **common)  # type: ignore[arg-type]

    alert_reasons: list[str] = []
    watch_reasons: list[str] = []
    if abs(latest_delta) >= DRIFT_ALERT_ABS_DIVERGENCE_PERCENT:
        alert_reasons.append("large_baseline_divergence")
    elif abs(latest_delta) >= DRIFT_WATCH_ABS_DIVERGENCE_PERCENT:
        watch_reasons.append("large_baseline_divergence")

    if delta_step is not None and abs(delta_step) >= DRIFT_ALERT_STEP_PERCENTAGE_POINTS:
        alert_reasons.append("rapid_divergence_change")
    elif delta_step is not None and abs(delta_step) >= DRIFT_WATCH_STEP_PERCENTAGE_POINTS:
        watch_reasons.append("rapid_divergence_change")

    if (
        latest_concentration is not None
        and latest_concentration >= DRIFT_ALERT_CONCENTRATION_RATIO
    ):
        alert_reasons.append("weight_concentration")
    elif (
        latest_concentration is not None
        and latest_concentration >= DRIFT_WATCH_CONCENTRATION_RATIO
    ):
        watch_reasons.append("weight_concentration")

    if movement_gap is not None and abs(movement_gap) >= DRIFT_ALERT_MOVEMENT_GAP_PERCENTAGE_POINTS:
        alert_reasons.append("relative_movement_gap")
    elif movement_gap is not None and abs(movement_gap) >= DRIFT_WATCH_MOVEMENT_GAP_PERCENTAGE_POINTS:
        watch_reasons.append("relative_movement_gap")

    if training_snapshot_changed:
        watch_reasons.append("training_snapshot_changed")

    if alert_reasons:
        status: ShadowDriftStatus = "alert"
        reasons = alert_reasons + [reason for reason in watch_reasons if reason not in alert_reasons]
    elif watch_reasons:
        status = "watch"
        reasons = watch_reasons
    else:
        status = "stable"
        reasons = []

    return ShadowDriftResult(status=status, reasons=reasons, **common)  # type: ignore[arg-type]


def build_shadow_drift(
    db: Session,
    *,
    ticker: str,
    days: int = 30,
) -> ShadowDriftResult:
    normalized_ticker = ticker.strip().upper()
    latest = db.scalars(
        select(ShadowConsensusSnapshot)
        .where(ShadowConsensusSnapshot.ticker == normalized_ticker)
        .order_by(
            ShadowConsensusSnapshot.captured_at.desc(),
            ShadowConsensusSnapshot.id.desc(),
        )
        .limit(1)
    ).first()
    if latest is None:
        return _empty_shadow_drift_result(ticker=normalized_ticker, days=days)

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = list(
        db.scalars(
            select(ShadowConsensusSnapshot)
            .where(
                ShadowConsensusSnapshot.ticker == normalized_ticker,
                ShadowConsensusSnapshot.target_year == latest.target_year,
                ShadowConsensusSnapshot.captured_at >= cutoff,
            )
            .order_by(
                ShadowConsensusSnapshot.captured_at.asc(),
                ShadowConsensusSnapshot.id.asc(),
            )
        ).all()
    )
    return _build_shadow_drift_from_rows(
        ticker=normalized_ticker,
        days=days,
        latest=latest,
        rows=rows,
    )


def build_shadow_drift_overview(
    db: Session,
    *,
    days: int = 30,
) -> ShadowDriftOverviewResult:
    current = datetime.now(timezone.utc)
    primary_table = db.scalars(
        select(AnalystTable).order_by(AnalystTable.sort_order.asc(), AnalystTable.id.asc()).limit(1)
    ).first()
    if primary_table is None:
        universe: list[str] = []
    else:
        universe = sorted(
            {
                ticker.strip().upper()
                for ticker in db.scalars(
                    select(StockRow.ticker).where(StockRow.table_id == primary_table.id)
                ).all()
                if ticker and ticker.strip()
            }
        )

    if not universe:
        return ShadowDriftOverviewResult(
            generated_at=current,
            history_days=days,
            universe_tickers=0,
            tickers_with_history=0,
            classified_tickers=0,
            alert_tickers=0,
            watch_tickers=0,
            stable_tickers=0,
            insufficient_tickers=0,
            actionable_tickers=0,
            history_coverage_percent=0.0,
            classified_coverage_percent=0.0,
            items=[],
        )

    latest_time = (
        select(
            ShadowConsensusSnapshot.ticker.label("ticker"),
            func.max(ShadowConsensusSnapshot.captured_at).label("captured_at"),
        )
        .where(ShadowConsensusSnapshot.ticker.in_(universe))
        .group_by(ShadowConsensusSnapshot.ticker)
        .subquery()
    )
    latest_rows = list(
        db.scalars(
            select(ShadowConsensusSnapshot)
            .join(
                latest_time,
                and_(
                    ShadowConsensusSnapshot.ticker == latest_time.c.ticker,
                    ShadowConsensusSnapshot.captured_at == latest_time.c.captured_at,
                ),
            )
            .order_by(ShadowConsensusSnapshot.ticker.asc(), ShadowConsensusSnapshot.id.desc())
        ).all()
    )
    latest_by_ticker: dict[str, ShadowConsensusSnapshot] = {}
    for row in latest_rows:
        latest_by_ticker.setdefault(row.ticker, row)

    cutoff = current - timedelta(days=days)
    recent_rows = list(
        db.scalars(
            select(ShadowConsensusSnapshot)
            .where(
                ShadowConsensusSnapshot.ticker.in_(universe),
                ShadowConsensusSnapshot.captured_at >= cutoff,
            )
            .order_by(
                ShadowConsensusSnapshot.ticker.asc(),
                ShadowConsensusSnapshot.captured_at.asc(),
                ShadowConsensusSnapshot.id.asc(),
            )
        ).all()
    )
    recent_by_ticker: dict[str, list[ShadowConsensusSnapshot]] = {}
    for row in recent_rows:
        recent_by_ticker.setdefault(row.ticker, []).append(row)

    items: list[ShadowDriftResult] = []
    for ticker in universe:
        latest = latest_by_ticker.get(ticker)
        if latest is None:
            items.append(_empty_shadow_drift_result(ticker=ticker, days=days))
            continue
        target_rows = [
            row for row in recent_by_ticker.get(ticker, []) if row.target_year == latest.target_year
        ]
        items.append(
            _build_shadow_drift_from_rows(
                ticker=ticker,
                days=days,
                latest=latest,
                rows=target_rows,
            )
        )

    items.sort(
        key=lambda item: (
            _STATUS_PRIORITY[item.status],
            -(abs(item.latest_delta_percent) if item.latest_delta_percent is not None else -1.0),
            item.ticker,
        )
    )
    status_counts = {
        status: sum(1 for item in items if item.status == status) for status in _STATUS_PRIORITY
    }
    tickers_with_history = sum(1 for item in items if item.snapshots > 0)
    classified_tickers = len(items) - status_counts["insufficient"]
    universe_count = len(items)

    return ShadowDriftOverviewResult(
        generated_at=current,
        history_days=days,
        universe_tickers=universe_count,
        tickers_with_history=tickers_with_history,
        classified_tickers=classified_tickers,
        alert_tickers=status_counts["alert"],
        watch_tickers=status_counts["watch"],
        stable_tickers=status_counts["stable"],
        insufficient_tickers=status_counts["insufficient"],
        actionable_tickers=status_counts["alert"] + status_counts["watch"],
        history_coverage_percent=100.0 * tickers_with_history / universe_count,
        classified_coverage_percent=100.0 * classified_tickers / universe_count,
        items=items,
    )
