from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, delete, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .consensus_canary import build_active_consensus, get_canary_settings
from .database import Base, SessionLocal
from .shadow_history import get_shadow_history_settings


class CanaryEvidenceSnapshot(Base):
    __tablename__ = "canary_evidence_snapshots"
    __table_args__ = (
        Index("ix_canary_evidence_ticker_captured_at", "ticker", "captured_at"),
        Index("ix_canary_evidence_target_year_captured_at", "target_year", "captured_at"),
        Index("ix_canary_evidence_effective_mode_captured_at", "effective_mode", "captured_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    target_year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    canary_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    in_allowlist: Mapped[bool] = mapped_column(Boolean, nullable=False)
    configured_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    effective_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    active_available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    safety_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    fallback_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sources: Mapped[int] = mapped_column(Integer, nullable=False)
    current_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    median_target_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    weighted_target_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    active_target_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    median_expected_return_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    weighted_expected_return_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    active_expected_return_percent: Mapped[float | None] = mapped_column(Float, nullable=True)


@dataclass(frozen=True)
class CanaryEvidenceCaptureResult:
    captured_at: datetime
    configured_tickers: int
    snapshots_created: int
    deleted_expired: int


@dataclass(frozen=True)
class CanaryTickerEvidenceResult:
    ticker: str
    history_days: int
    snapshots: int
    target_years: list[int]
    latest_target_year: int | None
    first_captured_at: datetime | None
    last_captured_at: datetime | None
    history_span_hours: float
    configured_weighted_hours: float
    weighted_hours: float
    fallback_hours: float
    weighted_uptime_percent: float | None
    fallback_incidents: int
    recoveries: int
    longest_weighted_run_hours: float
    longest_fallback_run_hours: float
    fallback_reason_counts: dict[str, int]
    current_canary_enabled: bool | None
    current_in_allowlist: bool | None
    current_configured_mode: str | None
    current_effective_mode: str | None
    current_safety_status: str | None
    current_fallback_reason: str | None
    current_median_target_price: float | None
    current_weighted_target_price: float | None
    current_active_target_price: float | None
    current_median_expected_return_percent: float | None
    current_weighted_expected_return_percent: float | None
    current_active_expected_return_percent: float | None


@dataclass(frozen=True)
class CanaryEvidenceOverviewResult:
    generated_at: datetime
    history_days: int
    configured_tickers: int
    tickers_with_evidence: int
    snapshots: int
    configured_weighted_hours: float
    weighted_hours: float
    fallback_hours: float
    weighted_uptime_percent: float | None
    fallback_incidents: int
    recoveries: int
    current_weighted_tickers: int
    current_fallback_tickers: int
    current_median_tickers: int
    median_history_span_hours: float
    items: list[CanaryTickerEvidenceResult]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _configured_weighted(row: CanaryEvidenceSnapshot) -> bool:
    return bool(
        row.canary_enabled
        and row.in_allowlist
        and row.configured_mode == "weighted_canary"
    )


def _fallback(row: CanaryEvidenceSnapshot) -> bool:
    return _configured_weighted(row) and row.effective_mode != "weighted"


def _weighted(row: CanaryEvidenceSnapshot) -> bool:
    return _configured_weighted(row) and row.effective_mode == "weighted"


def capture_canary_evidence(
    db: Session,
    *,
    captured_at: datetime | None = None,
    retention_days: int | None = None,
) -> CanaryEvidenceCaptureResult:
    current = _as_utc(captured_at or datetime.now(timezone.utc))
    settings = get_canary_settings(db)
    tickers = list(settings.tickers)
    created = 0

    for ticker in tickers:
        result = build_active_consensus(db, ticker=ticker)
        db.add(
            CanaryEvidenceSnapshot(
                ticker=result.ticker,
                target_year=result.target_year,
                captured_at=current,
                canary_enabled=result.canary_enabled,
                in_allowlist=result.in_allowlist,
                configured_mode=result.configured_mode,
                effective_mode=result.effective_mode,
                active_available=result.active_available,
                safety_status=result.safety_status,
                fallback_reason=result.fallback_reason,
                sources=result.sources,
                current_price=result.current_price,
                median_target_price=result.median_target_price,
                weighted_target_price=result.weighted_target_price,
                active_target_price=result.active_target_price,
                median_expected_return_percent=result.median_expected_return_percent,
                weighted_expected_return_percent=result.weighted_expected_return_percent,
                active_expected_return_percent=result.active_expected_return_percent,
            )
        )
        created += 1

    effective_retention = retention_days or get_shadow_history_settings().retention_days
    cutoff = current - timedelta(days=effective_retention)
    deleted_expired = int(
        db.execute(
            delete(CanaryEvidenceSnapshot).where(CanaryEvidenceSnapshot.captured_at < cutoff)
        ).rowcount
        or 0
    )
    db.commit()
    return CanaryEvidenceCaptureResult(
        captured_at=current,
        configured_tickers=len(tickers),
        snapshots_created=created,
        deleted_expired=deleted_expired,
    )


def capture_canary_evidence_once() -> CanaryEvidenceCaptureResult:
    with SessionLocal() as db:
        return capture_canary_evidence(db)


def list_canary_evidence_history(
    db: Session,
    *,
    ticker: str,
    days: int = 30,
    limit: int = 500,
) -> list[CanaryEvidenceSnapshot]:
    normalized = ticker.strip().upper()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return list(
        db.scalars(
            select(CanaryEvidenceSnapshot)
            .where(
                CanaryEvidenceSnapshot.ticker == normalized,
                CanaryEvidenceSnapshot.captured_at >= cutoff,
            )
            .order_by(
                CanaryEvidenceSnapshot.captured_at.asc(),
                CanaryEvidenceSnapshot.id.asc(),
            )
            .limit(limit)
        ).all()
    )


def _empty_ticker_result(ticker: str, days: int) -> CanaryTickerEvidenceResult:
    return CanaryTickerEvidenceResult(
        ticker=ticker,
        history_days=days,
        snapshots=0,
        target_years=[],
        latest_target_year=None,
        first_captured_at=None,
        last_captured_at=None,
        history_span_hours=0.0,
        configured_weighted_hours=0.0,
        weighted_hours=0.0,
        fallback_hours=0.0,
        weighted_uptime_percent=None,
        fallback_incidents=0,
        recoveries=0,
        longest_weighted_run_hours=0.0,
        longest_fallback_run_hours=0.0,
        fallback_reason_counts={},
        current_canary_enabled=None,
        current_in_allowlist=None,
        current_configured_mode=None,
        current_effective_mode=None,
        current_safety_status=None,
        current_fallback_reason=None,
        current_median_target_price=None,
        current_weighted_target_price=None,
        current_active_target_price=None,
        current_median_expected_return_percent=None,
        current_weighted_expected_return_percent=None,
        current_active_expected_return_percent=None,
    )


def _build_ticker_evidence_from_rows(
    *,
    ticker: str,
    days: int,
    rows: list[CanaryEvidenceSnapshot],
) -> CanaryTickerEvidenceResult:
    if not rows:
        return _empty_ticker_result(ticker, days)

    ordered = sorted(rows, key=lambda row: (_as_utc(row.captured_at), row.id or 0))
    first = ordered[0]
    last = ordered[-1]
    first_at = _as_utc(first.captured_at)
    last_at = _as_utc(last.captured_at)

    configured_hours = 0.0
    weighted_hours = 0.0
    fallback_hours = 0.0
    longest_weighted_run = 0.0
    longest_fallback_run = 0.0
    weighted_run = 0.0
    fallback_run = 0.0

    for previous, current in zip(ordered, ordered[1:]):
        if previous.target_year != current.target_year:
            weighted_run = 0.0
            fallback_run = 0.0
            continue
        duration = max(
            (_as_utc(current.captured_at) - _as_utc(previous.captured_at)).total_seconds()
            / 3600.0,
            0.0,
        )
        if _configured_weighted(previous):
            configured_hours += duration
            if _weighted(previous):
                weighted_hours += duration
                weighted_run += duration
                fallback_run = 0.0
                longest_weighted_run = max(longest_weighted_run, weighted_run)
            else:
                fallback_hours += duration
                fallback_run += duration
                weighted_run = 0.0
                longest_fallback_run = max(longest_fallback_run, fallback_run)
        else:
            weighted_run = 0.0
            fallback_run = 0.0

    fallback_incidents = 0
    recoveries = 0
    fallback_reasons: dict[str, int] = {}
    previous: CanaryEvidenceSnapshot | None = None
    for row in ordered:
        same_regime = (
            previous is not None
            and previous.target_year == row.target_year
            and _configured_weighted(previous)
            and _configured_weighted(row)
        )
        if _fallback(row) and (not same_regime or not _fallback(previous)):  # type: ignore[arg-type]
            fallback_incidents += 1
            reason = row.fallback_reason or "unknown"
            fallback_reasons[reason] = fallback_reasons.get(reason, 0) + 1
        if _weighted(row) and same_regime and _fallback(previous):  # type: ignore[arg-type]
            recoveries += 1
        previous = row

    uptime = (
        100.0 * weighted_hours / configured_hours
        if configured_hours > 0
        else None
    )
    target_years = sorted({int(row.target_year) for row in ordered if row.target_year is not None})
    return CanaryTickerEvidenceResult(
        ticker=ticker,
        history_days=days,
        snapshots=len(ordered),
        target_years=target_years,
        latest_target_year=last.target_year,
        first_captured_at=first_at,
        last_captured_at=last_at,
        history_span_hours=max((last_at - first_at).total_seconds() / 3600.0, 0.0),
        configured_weighted_hours=configured_hours,
        weighted_hours=weighted_hours,
        fallback_hours=fallback_hours,
        weighted_uptime_percent=uptime,
        fallback_incidents=fallback_incidents,
        recoveries=recoveries,
        longest_weighted_run_hours=longest_weighted_run,
        longest_fallback_run_hours=longest_fallback_run,
        fallback_reason_counts=dict(sorted(fallback_reasons.items())),
        current_canary_enabled=last.canary_enabled,
        current_in_allowlist=last.in_allowlist,
        current_configured_mode=last.configured_mode,
        current_effective_mode=last.effective_mode,
        current_safety_status=last.safety_status,
        current_fallback_reason=last.fallback_reason,
        current_median_target_price=last.median_target_price,
        current_weighted_target_price=last.weighted_target_price,
        current_active_target_price=last.active_target_price,
        current_median_expected_return_percent=last.median_expected_return_percent,
        current_weighted_expected_return_percent=last.weighted_expected_return_percent,
        current_active_expected_return_percent=last.active_expected_return_percent,
    )


def build_canary_ticker_evidence(
    db: Session,
    *,
    ticker: str,
    days: int = 30,
) -> CanaryTickerEvidenceResult:
    normalized = ticker.strip().upper()
    rows = list_canary_evidence_history(db, ticker=normalized, days=days)
    return _build_ticker_evidence_from_rows(ticker=normalized, days=days, rows=rows)


def build_canary_evidence_overview(
    db: Session,
    *,
    days: int = 30,
) -> CanaryEvidenceOverviewResult:
    settings = get_canary_settings(db)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    all_rows = list(
        db.scalars(
            select(CanaryEvidenceSnapshot)
            .where(CanaryEvidenceSnapshot.captured_at >= cutoff)
            .order_by(
                CanaryEvidenceSnapshot.ticker.asc(),
                CanaryEvidenceSnapshot.captured_at.asc(),
                CanaryEvidenceSnapshot.id.asc(),
            )
        ).all()
    )
    grouped: dict[str, list[CanaryEvidenceSnapshot]] = {}
    for row in all_rows:
        grouped.setdefault(row.ticker, []).append(row)

    tickers = sorted(set(settings.tickers) | set(grouped))
    items = [
        _build_ticker_evidence_from_rows(ticker=ticker, days=days, rows=grouped.get(ticker, []))
        for ticker in tickers
    ]
    items.sort(
        key=lambda item: (
            0 if item.current_effective_mode == "median" and item.current_configured_mode == "weighted_canary" else 1,
            -(item.fallback_incidents),
            item.ticker,
        )
    )

    configured_hours = sum(item.configured_weighted_hours for item in items)
    weighted_hours = sum(item.weighted_hours for item in items)
    fallback_hours = sum(item.fallback_hours for item in items)
    uptime = 100.0 * weighted_hours / configured_hours if configured_hours > 0 else None
    spans = [item.history_span_hours for item in items if item.snapshots > 0]
    return CanaryEvidenceOverviewResult(
        generated_at=datetime.now(timezone.utc),
        history_days=days,
        configured_tickers=len(settings.tickers),
        tickers_with_evidence=sum(item.snapshots > 0 for item in items),
        snapshots=sum(item.snapshots for item in items),
        configured_weighted_hours=configured_hours,
        weighted_hours=weighted_hours,
        fallback_hours=fallback_hours,
        weighted_uptime_percent=uptime,
        fallback_incidents=sum(item.fallback_incidents for item in items),
        recoveries=sum(item.recoveries for item in items),
        current_weighted_tickers=sum(item.current_effective_mode == "weighted" for item in items),
        current_fallback_tickers=sum(
            item.current_configured_mode == "weighted_canary"
            and item.current_effective_mode == "median"
            for item in items
        ),
        current_median_tickers=sum(
            item.current_configured_mode != "weighted_canary" for item in items
        ),
        median_history_span_hours=float(median(spans)) if spans else 0.0,
        items=items,
    )
