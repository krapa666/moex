from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean, median

from sqlalchemy import select
from sqlalchemy.orm import Session

from .consensus_backtest import (
    DEFAULT_ERROR_FLOOR_PERCENT,
    DEFAULT_RELATIVE_SCORE_CAP,
    DEFAULT_SHRINKAGE_SAMPLES,
    _available_training_samples,
    _source_weights,
)
from .forecast_accuracy import AccuracySnapshot, ActualNetProfit, build_accuracy_samples
from .models import AnalystTable, StockRow


@dataclass(frozen=True)
class ShadowConsensusResult:
    ticker: str
    target_year: int | None
    training_snapshot: AccuracySnapshot | None
    as_of: datetime
    shadow_available: bool
    reason: str | None
    sources: int
    sources_with_training_history: int
    training_samples: int
    weighting_uses_history: bool
    max_source_weight_percent: float | None
    min_source_weight_percent: float | None
    median_net_profit_billion_rub: float | None
    mean_net_profit_billion_rub: float | None
    weighted_net_profit_billion_rub: float | None
    median_target_price: float | None
    mean_target_price: float | None
    weighted_target_price: float | None
    weighted_vs_median_target_delta_rub: float | None
    weighted_vs_median_target_delta_percent: float | None
    current_price: float | None
    median_market_gap_percent: float | None
    weighted_market_gap_percent: float | None


@dataclass(frozen=True)
class _ShadowComponent:
    analyst_name: str
    net_profit_billion_rub: float
    target_price: float
    current_price: float | None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def training_snapshot_for_target(target_year: int, as_of: datetime) -> AccuracySnapshot:
    current = _as_utc(as_of)
    if target_year > current.year:
        return "pre_year"
    if target_year < current.year:
        return "year_end"
    if current >= datetime(current.year, 7, 1, tzinfo=timezone.utc):
        return "mid_year"
    return "pre_year"


def _finite_number(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _row_profit_for_year(row: StockRow, table: AnalystTable, target_year: int) -> float | None:
    mapped = _finite_number((row.net_profit_year_map or {}).get(str(target_year)))
    if mapped is not None:
        return mapped
    offset = target_year - table.forecast_start_year
    if 0 <= offset <= 3:
        return _finite_number(getattr(row, f"forecast_profit_year{offset + 1}_billion_rub"))
    return None


def _component_for_row(
    row: StockRow,
    table: AnalystTable,
    *,
    target_year: int,
) -> _ShadowComponent | None:
    profit = _row_profit_for_year(row, table, target_year)
    pe = _finite_number(row.pe_avg_5y)
    shares = _finite_number(row.shares_billion)
    if profit is None or pe is None or shares is None or shares <= 0:
        return None
    target_price = profit * pe / shares
    if not math.isfinite(target_price):
        return None
    current_price = _finite_number(row.current_price)
    if current_price is not None and current_price <= 0:
        current_price = None
    analyst_name = (table.analyst_name or "").strip()
    if not analyst_name:
        return None
    return _ShadowComponent(
        analyst_name=analyst_name,
        net_profit_billion_rub=profit,
        target_price=target_price,
        current_price=current_price,
    )


def _empty_result(
    *,
    ticker: str,
    as_of: datetime,
    target_year: int | None,
    snapshot: AccuracySnapshot | None,
    sources: int,
    reason: str,
) -> ShadowConsensusResult:
    return ShadowConsensusResult(
        ticker=ticker,
        target_year=target_year,
        training_snapshot=snapshot,
        as_of=as_of,
        shadow_available=False,
        reason=reason,
        sources=sources,
        sources_with_training_history=0,
        training_samples=0,
        weighting_uses_history=False,
        max_source_weight_percent=None,
        min_source_weight_percent=None,
        median_net_profit_billion_rub=None,
        mean_net_profit_billion_rub=None,
        weighted_net_profit_billion_rub=None,
        median_target_price=None,
        mean_target_price=None,
        weighted_target_price=None,
        weighted_vs_median_target_delta_rub=None,
        weighted_vs_median_target_delta_percent=None,
        current_price=None,
        median_market_gap_percent=None,
        weighted_market_gap_percent=None,
    )


def build_shadow_consensus(
    db: Session,
    *,
    ticker: str,
    as_of: datetime | None = None,
) -> ShadowConsensusResult:
    normalized_ticker = ticker.strip().upper()
    current = _as_utc(as_of or datetime.now(timezone.utc))
    if not normalized_ticker:
        return _empty_result(
            ticker="",
            as_of=current,
            target_year=None,
            snapshot=None,
            sources=0,
            reason="ticker is required",
        )

    tables = list(
        db.scalars(
            select(AnalystTable).order_by(AnalystTable.sort_order.asc(), AnalystTable.id.asc())
        ).all()
    )
    if not tables:
        return _empty_result(
            ticker=normalized_ticker,
            as_of=current,
            target_year=None,
            snapshot=None,
            sources=0,
            reason="no analyst tables",
        )

    target_year = int(tables[0].forecast_start_year)
    snapshot = training_snapshot_for_target(target_year, current)
    rows = list(db.scalars(select(StockRow).where(StockRow.ticker == normalized_ticker)).all())
    row_by_table_id = {row.table_id: row for row in rows}
    component_by_source: dict[str, _ShadowComponent] = {}
    for table in tables:
        row = row_by_table_id.get(table.id)
        if row is None:
            continue
        component = _component_for_row(row, table, target_year=target_year)
        if component is not None:
            component_by_source.setdefault(component.analyst_name, component)
    components = list(component_by_source.values())

    if len(components) < 2:
        return _empty_result(
            ticker=normalized_ticker,
            as_of=current,
            target_year=target_year,
            snapshot=snapshot,
            sources=len(components),
            reason="at least two comparable current forecasts are required",
        )

    samples = build_accuracy_samples(db, snapshot=snapshot)
    actual_rows = list(db.scalars(select(ActualNetProfit)).all())
    reported_at_by_key = {
        (row.ticker.strip().upper(), row.fiscal_year): row.reported_at for row in actual_rows
    }
    training_samples = _available_training_samples(
        samples,
        target_fiscal_year=target_year,
        target_cutoff=current,
        reported_at_by_key=reported_at_by_key,
    )

    source_names = [component.analyst_name for component in components]
    weights, counts = _source_weights(
        source_names,
        training_samples,
        shrinkage_samples=DEFAULT_SHRINKAGE_SAMPLES,
        error_floor_percent=DEFAULT_ERROR_FLOOR_PERCENT,
        relative_score_cap=DEFAULT_RELATIVE_SCORE_CAP,
    )

    profits = [component.net_profit_billion_rub for component in components]
    target_prices = [component.target_price for component in components]
    weighted_profit = sum(
        component.net_profit_billion_rub * weights[component.analyst_name]
        for component in components
    )
    weighted_target = sum(
        component.target_price * weights[component.analyst_name]
        for component in components
    )
    median_profit = float(median(profits))
    mean_profit = float(mean(profits))
    median_target = float(median(target_prices))
    mean_target = float(mean(target_prices))
    current_prices = [
        component.current_price for component in components if component.current_price is not None
    ]
    current_price = float(median(current_prices)) if current_prices else None
    target_delta = weighted_target - median_target
    target_delta_percent = (
        100.0 * target_delta / median_target if abs(median_target) > 1e-12 else None
    )
    median_market_gap = (
        100.0 * (median_target / current_price - 1.0)
        if current_price is not None and current_price > 0
        else None
    )
    weighted_market_gap = (
        100.0 * (weighted_target / current_price - 1.0)
        if current_price is not None and current_price > 0
        else None
    )
    weight_values = list(weights.values())
    source_training_samples = sum(counts.values())

    return ShadowConsensusResult(
        ticker=normalized_ticker,
        target_year=target_year,
        training_snapshot=snapshot,
        as_of=current,
        shadow_available=True,
        reason=None,
        sources=len(components),
        sources_with_training_history=sum(1 for count in counts.values() if count > 0),
        training_samples=source_training_samples,
        weighting_uses_history=source_training_samples > 0,
        max_source_weight_percent=100.0 * max(weight_values),
        min_source_weight_percent=100.0 * min(weight_values),
        median_net_profit_billion_rub=median_profit,
        mean_net_profit_billion_rub=mean_profit,
        weighted_net_profit_billion_rub=float(weighted_profit),
        median_target_price=median_target,
        mean_target_price=mean_target,
        weighted_target_price=float(weighted_target),
        weighted_vs_median_target_delta_rub=float(target_delta),
        weighted_vs_median_target_delta_percent=target_delta_percent,
        current_price=current_price,
        median_market_gap_percent=median_market_gap,
        weighted_market_gap_percent=weighted_market_gap,
    )
