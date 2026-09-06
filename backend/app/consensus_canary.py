from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median
from typing import Literal

from sqlalchemy import Boolean, DateTime, Integer, JSON, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .database import Base
from .models import AnalystTable, StockRow
from .production_impact import build_production_impact
from .shadow_consensus import ShadowConsensusResult, build_shadow_consensus, build_shadow_consensus_batch
from .shadow_history import (
    DRIFT_WATCH_ABS_DIVERGENCE_PERCENT,
    DRIFT_WATCH_CONCENTRATION_RATIO,
    build_shadow_drift,
    build_shadow_drift_overview,
)

MAX_CANARY_TICKERS = 5
CANARY_HISTORY_DAYS = 30
MIN_CANARY_TRAINED_SOURCES = 2
CanaryMode = Literal["median", "weighted_canary"]
EffectiveConsensusMode = Literal["median", "weighted"]


class ConsensusCanarySettings(Base):
    __tablename__ = "consensus_canary_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tickers: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class ConsensusCanaryEvent(Base):
    __tablename__ = "consensus_canary_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    previous_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    new_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    previous_tickers: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    new_tickers: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    promotion_status: Mapped[str | None] = mapped_column(String(32), nullable=True)


@dataclass(frozen=True)
class CanarySettingsResult:
    enabled: bool
    tickers: list[str]
    max_tickers: int
    safety_policy: str
    updated_by: str | None
    updated_at: datetime | None


@dataclass(frozen=True)
class ActiveConsensusResult:
    ticker: str
    target_year: int | None
    active_available: bool
    reason: str | None
    canary_enabled: bool
    in_allowlist: bool
    configured_mode: CanaryMode
    effective_mode: EffectiveConsensusMode
    safety_status: str | None
    fallback_reason: str | None
    sources: int
    current_price: float | None
    median_target_price: float | None
    weighted_target_price: float | None
    active_target_price: float | None
    median_expected_return_percent: float | None
    weighted_expected_return_percent: float | None
    active_expected_return_percent: float | None


class CanaryPolicyError(ValueError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _finite(value: object) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _normalize_tickers(tickers: list[str] | tuple[str, ...]) -> list[str]:
    normalized = sorted({str(ticker).strip().upper() for ticker in tickers if str(ticker).strip()})
    if len(normalized) > MAX_CANARY_TICKERS:
        raise CanaryPolicyError(f"Canary allowlist ограничен {MAX_CANARY_TICKERS} тикерами")
    return normalized


def _stored_settings(db: Session) -> ConsensusCanarySettings | None:
    return db.get(ConsensusCanarySettings, 1)


def get_canary_settings(db: Session) -> CanarySettingsResult:
    stored = _stored_settings(db)
    return CanarySettingsResult(
        enabled=bool(stored.enabled) if stored else False,
        tickers=_normalize_tickers(stored.tickers or []) if stored else [],
        max_tickers=MAX_CANARY_TICKERS,
        safety_policy=(
            "weighted requires >=2 trained sources, live divergence/concentration below WATCH "
            "and forward drift STABLE; otherwise median fallback"
        ),
        updated_by=stored.updated_by if stored else None,
        updated_at=stored.updated_at if stored else None,
    )


def list_canary_events(db: Session, *, limit: int = 50) -> list[ConsensusCanaryEvent]:
    return list(
        db.scalars(
            select(ConsensusCanaryEvent)
            .order_by(ConsensusCanaryEvent.occurred_at.desc(), ConsensusCanaryEvent.id.desc())
            .limit(limit)
        ).all()
    )


def _primary_universe(db: Session) -> set[str]:
    primary = db.scalars(
        select(AnalystTable).order_by(AnalystTable.sort_order.asc(), AnalystTable.id.asc()).limit(1)
    ).first()
    if primary is None:
        return set()
    return {
        str(ticker).strip().upper()
        for ticker in db.scalars(select(StockRow.ticker).where(StockRow.table_id == primary.id)).all()
        if ticker and str(ticker).strip()
    }


def _validate_tickers_in_universe(db: Session, tickers: list[str]) -> None:
    universe = _primary_universe(db)
    missing = sorted(set(tickers) - universe)
    if missing:
        raise CanaryPolicyError(f"Тикеры вне основной таблицы: {', '.join(missing)}")


def _live_shadow_guard_reason(shadow: ShadowConsensusResult) -> str | None:
    if not shadow.shadow_available or _finite(shadow.weighted_target_price) is None:
        return "shadow_unavailable"
    if (
        not shadow.weighting_uses_history
        or shadow.sources_with_training_history < MIN_CANARY_TRAINED_SOURCES
    ):
        return "insufficient_weight_history"

    divergence = _finite(shadow.weighted_vs_median_target_delta_percent)
    if divergence is None:
        return "live_divergence_unknown"
    if abs(divergence) >= DRIFT_WATCH_ABS_DIVERGENCE_PERCENT:
        return "live_divergence_watch"

    max_weight = _finite(shadow.max_source_weight_percent)
    if max_weight is None or shadow.sources <= 0:
        return "live_weight_concentration_unknown"
    equal_weight = 100.0 / shadow.sources
    concentration = max_weight / equal_weight
    if concentration >= DRIFT_WATCH_CONCENTRATION_RATIO:
        return "live_weight_concentration_watch"
    return None


def _validate_enable_policy(db: Session, tickers: list[str]) -> str:
    if not tickers:
        raise CanaryPolicyError("Для включения canary нужен непустой allowlist")

    result = build_production_impact(db, top_n=10, history_days=CANARY_HISTORY_DAYS)
    promotion_status = result.promotion.status
    if promotion_status != "READY_FOR_MANUAL_PROMOTION":
        raise CanaryPolicyError(
            f"Canary нельзя включить: promotion dossier = {promotion_status}"
        )

    shadow_by_ticker = {
        item.ticker: item
        for item in build_shadow_consensus_batch(db, tickers=tickers)
    }
    missing = sorted(ticker for ticker in tickers if ticker not in shadow_by_ticker)
    blocked = [f"{ticker}=shadow_unavailable" for ticker in missing]
    for ticker in tickers:
        shadow = shadow_by_ticker.get(ticker)
        if shadow is None:
            continue
        reason = _live_shadow_guard_reason(shadow)
        if reason is not None:
            blocked.append(f"{ticker}={reason}")
    if blocked:
        raise CanaryPolicyError("Canary live guard не пройден: " + ", ".join(sorted(blocked)))

    overview = build_shadow_drift_overview(db, days=CANARY_HISTORY_DAYS)
    status_by_ticker = {item.ticker: item.status for item in overview.items}
    unstable = sorted(
        f"{ticker}={status_by_ticker.get(ticker, 'insufficient').upper()}"
        for ticker in tickers
        if status_by_ticker.get(ticker) != "stable"
    )
    if unstable:
        raise CanaryPolicyError(
            "Canary разрешён только для STABLE тикеров: " + ", ".join(unstable)
        )
    return promotion_status


def configure_canary(
    db: Session,
    *,
    enabled: bool,
    tickers: list[str],
    actor: str,
    note: str | None = None,
) -> CanarySettingsResult:
    normalized = _normalize_tickers(tickers)
    _validate_tickers_in_universe(db, normalized)

    stored = _stored_settings(db)
    previous_enabled = bool(stored.enabled) if stored else False
    previous_tickers = _normalize_tickers(stored.tickers or []) if stored else []
    promotion_status = _validate_enable_policy(db, normalized) if enabled else None

    if stored is None:
        stored = ConsensusCanarySettings(id=1)
        db.add(stored)

    stored.enabled = bool(enabled)
    stored.tickers = normalized
    stored.updated_by = actor[:64]
    stored.updated_at = _utcnow()

    if previous_enabled and not enabled:
        action = "disable"
    elif not previous_enabled and enabled:
        action = "enable"
    elif previous_tickers != normalized:
        action = "reconfigure"
    else:
        action = "configure"

    db.add(
        ConsensusCanaryEvent(
            occurred_at=stored.updated_at,
            action=action,
            previous_enabled=previous_enabled,
            new_enabled=bool(enabled),
            previous_tickers=previous_tickers,
            new_tickers=normalized,
            actor=actor[:64],
            note=(note.strip()[:255] if note and note.strip() else None),
            promotion_status=promotion_status,
        )
    )
    db.commit()
    db.refresh(stored)
    return get_canary_settings(db)


def rollback_canary(
    db: Session,
    *,
    actor: str,
    note: str | None = None,
) -> CanarySettingsResult:
    stored = _stored_settings(db)
    if stored is None or not stored.enabled:
        return get_canary_settings(db)

    previous_tickers = _normalize_tickers(stored.tickers or [])
    current = _utcnow()
    stored.enabled = False
    stored.updated_by = actor[:64]
    stored.updated_at = current
    db.add(
        ConsensusCanaryEvent(
            occurred_at=current,
            action="rollback",
            previous_enabled=True,
            new_enabled=False,
            previous_tickers=previous_tickers,
            new_tickers=previous_tickers,
            actor=actor[:64],
            note=(note.strip()[:255] if note and note.strip() else None),
            promotion_status=None,
        )
    )
    db.commit()
    db.refresh(stored)
    return get_canary_settings(db)


def _row_profit_for_year(row: StockRow, table: AnalystTable, target_year: int) -> float | None:
    mapped = _finite((row.net_profit_year_map or {}).get(str(target_year)))
    if mapped is not None:
        return mapped
    offset = target_year - int(table.forecast_start_year)
    if 0 <= offset <= 3:
        return _finite(getattr(row, f"forecast_profit_year{offset + 1}_billion_rub"))
    return None


def _row_return_for_year(row: StockRow, table: AnalystTable, target_year: int) -> float | None:
    offset = target_year - int(table.forecast_start_year)
    if 0 <= offset <= 3:
        return _finite(getattr(row, f"upside_percent_year{offset + 1}"))
    return None


def _baseline_consensus(
    db: Session,
    *,
    ticker: str,
) -> tuple[int | None, int, float | None, float | None, float | None]:
    tables = list(
        db.scalars(
            select(AnalystTable).order_by(AnalystTable.sort_order.asc(), AnalystTable.id.asc())
        ).all()
    )
    if not tables:
        return None, 0, None, None, None
    target_year = int(tables[0].forecast_start_year)
    table_by_id = {table.id: table for table in tables}
    rows = list(db.scalars(select(StockRow).where(StockRow.ticker == ticker)).all())
    targets: list[float] = []
    returns: list[float] = []
    current_prices: list[float] = []
    sources: set[int] = set()
    for row in rows:
        table = table_by_id.get(row.table_id)
        if table is None:
            continue
        profit = _row_profit_for_year(row, table, target_year)
        pe = _finite(row.pe_avg_5y)
        shares = _finite(row.shares_billion)
        valid_target = False
        if profit is not None and pe is not None and shares is not None and shares > 0:
            target = profit * pe / shares
            if math.isfinite(target):
                targets.append(float(target))
                sources.add(table.id)
                valid_target = True
        if valid_target:
            expected_return = _row_return_for_year(row, table, target_year)
            if expected_return is not None:
                returns.append(expected_return)
        current_price = _finite(row.current_price)
        if current_price is not None and current_price > 0:
            current_prices.append(current_price)
    return (
        target_year,
        len(sources),
        float(median(current_prices)) if current_prices else None,
        float(median(targets)) if targets else None,
        float(median(returns)) if returns else None,
    )


def build_active_consensus(
    db: Session,
    *,
    ticker: str,
) -> ActiveConsensusResult:
    normalized = ticker.strip().upper()
    settings = get_canary_settings(db)
    in_allowlist = normalized in settings.tickers
    configured_weighted = settings.enabled and in_allowlist
    configured_mode: CanaryMode = "weighted_canary" if configured_weighted else "median"

    target_year, sources, current_price, median_target, median_return = _baseline_consensus(
        db, ticker=normalized
    )
    if target_year is None or median_target is None:
        return ActiveConsensusResult(
            ticker=normalized,
            target_year=target_year,
            active_available=False,
            reason="no comparable current target",
            canary_enabled=settings.enabled,
            in_allowlist=in_allowlist,
            configured_mode=configured_mode,
            effective_mode="median",
            safety_status=None,
            fallback_reason=None,
            sources=sources,
            current_price=current_price,
            median_target_price=median_target,
            weighted_target_price=None,
            active_target_price=median_target,
            median_expected_return_percent=median_return,
            weighted_expected_return_percent=None,
            active_expected_return_percent=median_return,
        )

    shadow = build_shadow_consensus(db, ticker=normalized)
    weighted_target = _finite(shadow.weighted_target_price) if shadow.shadow_available else None
    weighted_return = None
    if (
        weighted_target is not None
        and median_return is not None
        and current_price is not None
        and current_price > 0
    ):
        median_price_potential = ((median_target - current_price) / current_price) * 100.0
        dividend_layer = median_return - median_price_potential
        weighted_price_potential = ((weighted_target - current_price) / current_price) * 100.0
        weighted_return = weighted_price_potential + dividend_layer

    effective_mode: EffectiveConsensusMode = "median"
    safety_status = None
    fallback_reason = None
    if configured_weighted:
        fallback_reason = _live_shadow_guard_reason(shadow)
        if fallback_reason is None:
            drift = build_shadow_drift(db, ticker=normalized, days=CANARY_HISTORY_DAYS)
            safety_status = drift.status
            if drift.status == "stable":
                effective_mode = "weighted"
            else:
                fallback_reason = f"drift_{drift.status}"

    active_target = weighted_target if effective_mode == "weighted" else median_target
    active_return = weighted_return if effective_mode == "weighted" else median_return
    return ActiveConsensusResult(
        ticker=normalized,
        target_year=target_year,
        active_available=True,
        reason=None,
        canary_enabled=settings.enabled,
        in_allowlist=in_allowlist,
        configured_mode=configured_mode,
        effective_mode=effective_mode,
        safety_status=safety_status,
        fallback_reason=fallback_reason,
        sources=sources,
        current_price=current_price,
        median_target_price=median_target,
        weighted_target_price=weighted_target,
        active_target_price=active_target,
        median_expected_return_percent=median_return,
        weighted_expected_return_percent=weighted_return,
        active_expected_return_percent=active_return,
    )
