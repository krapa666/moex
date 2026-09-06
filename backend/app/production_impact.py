from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean, median

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from .consensus_readiness import ConsensusReadinessResult, build_consensus_readiness
from .models import AnalystTable, StockRow, VolumeObservation, VolumeSecurity
from .shadow_consensus import (
    ShadowConsensusResult,
    build_shadow_consensus_batch,
    training_snapshot_for_target,
)
from .shadow_history import ShadowDriftOverviewResult, build_shadow_drift_overview

DEFAULT_IMPACT_HISTORY_DAYS = 30
DEFAULT_TOP_N = 10
MIN_COMPARABLE_COVERAGE_PERCENT = 70.0
MIN_RANK_CORRELATION = 0.90
MIN_TOP_N_OVERLAP_PERCENT = 80.0
MAX_RETURN_SIGN_FLIP_PERCENT = 10.0
MAX_MEAN_ABS_WATCHLIST_SCORE_DELTA = 10.0
MIN_FORWARD_CLASSIFIED_COVERAGE_PERCENT = 80.0
MAX_FORWARD_ACTIONABLE_PERCENT = 20.0
MIN_FORWARD_SPAN_HOURS = 7 * 24


@dataclass(frozen=True)
class ProductionImpactItem:
    ticker: str
    target_year: int
    current_price: float | None
    median_target_price: float
    weighted_target_price: float
    target_delta_rub: float
    target_delta_percent: float | None
    median_expected_return_percent: float | None
    weighted_expected_return_percent: float | None
    expected_return_delta_pp: float | None
    expected_return_sign_changed: bool
    volume_signal_status: str | None
    median_watchlist_score: int | None
    weighted_watchlist_score: int | None
    watchlist_score_delta: int | None
    median_rank: int | None
    weighted_rank: int | None
    rank_delta: int | None
    in_median_top_n: bool
    in_weighted_top_n: bool


@dataclass(frozen=True)
class ProductionImpactSummary:
    generated_at: datetime
    top_n: int
    universe_tickers: int
    comparable_tickers: int
    comparable_coverage_percent: float
    median_abs_target_delta_percent: float | None
    max_abs_target_delta_percent: float | None
    median_abs_expected_return_delta_pp: float | None
    return_sign_flip_tickers: int
    return_sign_flip_percent: float
    rank_correlation_spearman: float | None
    mean_abs_rank_change: float | None
    max_abs_rank_change: int | None
    top_n_overlap_tickers: int
    top_n_overlap_percent: float
    top_n_entered: list[str]
    top_n_exited: list[str]
    mean_abs_watchlist_score_delta: float | None
    items: list[ProductionImpactItem]


@dataclass(frozen=True)
class PromotionGate:
    key: str
    label: str
    passed: bool
    actual: str
    requirement: str


@dataclass(frozen=True)
class PromotionDossier:
    generated_at: datetime
    status: str
    gates_passed: int
    gates_total: int
    historical_snapshot: str
    historical_readiness: bool
    forward_history_days: int
    gates: list[PromotionGate]


@dataclass(frozen=True)
class ProductionImpactResult:
    impact: ProductionImpactSummary
    promotion: PromotionDossier


def _finite(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _row_return_for_year(row: StockRow, table: AnalystTable, target_year: int) -> float | None:
    offset = target_year - int(table.forecast_start_year)
    if 0 <= offset <= 3:
        return _finite(getattr(row, f"upside_percent_year{offset + 1}"))
    return None


def _average_ranks(values: dict[str, float], *, descending: bool) -> dict[str, float]:
    ordered = sorted(values.items(), key=lambda item: item[1], reverse=descending)
    ranks: dict[str, float] = {}
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and math.isclose(
            ordered[end][1], ordered[index][1], rel_tol=1e-12, abs_tol=1e-12
        ):
            end += 1
        average_rank = ((index + 1) + end) / 2.0
        for ticker, _value in ordered[index:end]:
            ranks[ticker] = average_rank
        index = end
    return ranks


def _spearman(left: dict[str, float], right: dict[str, float]) -> float | None:
    common = sorted(set(left) & set(right))
    if len(common) < 2:
        return None
    left_ranks = _average_ranks({ticker: left[ticker] for ticker in common}, descending=True)
    right_ranks = _average_ranks({ticker: right[ticker] for ticker in common}, descending=True)
    left_values = [left_ranks[ticker] for ticker in common]
    right_values = [right_ranks[ticker] for ticker in common]
    left_mean = mean(left_values)
    right_mean = mean(right_values)
    numerator = sum(
        (left_ranks[ticker] - left_mean) * (right_ranks[ticker] - right_mean)
        for ticker in common
    )
    left_ss = sum((left_ranks[ticker] - left_mean) ** 2 for ticker in common)
    right_ss = sum((right_ranks[ticker] - right_mean) ** 2 for ticker in common)
    denominator = math.sqrt(left_ss * right_ss)
    if denominator <= 1e-12:
        return 1.0 if all(
            math.isclose(left_ranks[ticker], right_ranks[ticker]) for ticker in common
        ) else None
    return numerator / denominator


def _score(current_price: float | None, fair_value: float | None, full_return: float | None, signal: str | None) -> int | None:
    if current_price is None or fair_value is None or current_price <= 0:
        return None
    price_potential = ((fair_value - current_price) / current_price) * 100.0
    price_points = min(60.0, max(0.0, price_potential))
    remaining_dividend_yield = (
        max(full_return - price_potential, 0.0) if full_return is not None else 0.0
    )
    dividend_points = min(15.0, max(0.0, remaining_dividend_yield)) * (25.0 / 15.0)
    activity_points = {"signal": 15.0, "above_range": 7.0}.get(signal or "", 0.0)
    total = min(100.0, max(0.0, price_points + dividend_points + activity_points))
    return int(math.floor(total + 0.5))


def _load_latest_volume_signals(db: Session, tickers: list[str]) -> dict[str, str]:
    if not tickers:
        return {}
    latest = (
        select(
            VolumeObservation.security_id.label("security_id"),
            func.max(VolumeObservation.trade_date).label("trade_date"),
        )
        .group_by(VolumeObservation.security_id)
        .subquery()
    )
    statement = (
        select(VolumeSecurity.ticker, VolumeObservation.signal_status)
        .join(latest, latest.c.security_id == VolumeSecurity.id)
        .join(
            VolumeObservation,
            and_(
                VolumeObservation.security_id == latest.c.security_id,
                VolumeObservation.trade_date == latest.c.trade_date,
            ),
        )
        .where(VolumeSecurity.ticker.in_(tickers))
    )
    return {
        str(ticker).strip().upper(): str(status)
        for ticker, status in db.execute(statement).all()
        if ticker
    }


def _load_median_returns(
    db: Session,
    shadows: list[ShadowConsensusResult],
) -> dict[str, float | None]:
    available = {item.ticker: item for item in shadows if item.shadow_available and item.target_year}
    if not available:
        return {}
    tables = list(
        db.scalars(
            select(AnalystTable).order_by(AnalystTable.sort_order.asc(), AnalystTable.id.asc())
        ).all()
    )
    rows = list(db.scalars(select(StockRow).where(StockRow.ticker.in_(sorted(available)))).all())
    table_by_id = {table.id: table for table in tables}
    values: dict[str, list[float]] = {ticker: [] for ticker in available}
    for row in rows:
        ticker = (row.ticker or "").strip().upper()
        shadow = available.get(ticker)
        table = table_by_id.get(row.table_id)
        if shadow is None or table is None or shadow.target_year is None:
            continue
        result = _row_return_for_year(row, table, shadow.target_year)
        if result is not None:
            values[ticker].append(result)
    return {
        ticker: float(median(items)) if items else None
        for ticker, items in values.items()
    }


def _rank_items(items: list[dict], field: str) -> dict[str, int]:
    ordered = sorted(
        [item for item in items if item[field] is not None],
        key=lambda item: (-float(item[field]), item["ticker"]),
    )
    return {item["ticker"]: index for index, item in enumerate(ordered, start=1)}


def build_production_impact_summary(
    db: Session,
    *,
    top_n: int = DEFAULT_TOP_N,
    as_of: datetime | None = None,
) -> ProductionImpactSummary:
    current = as_of or datetime.now(timezone.utc)
    shadows = build_shadow_consensus_batch(db, as_of=current)
    universe_tickers = len(shadows)
    comparable = [item for item in shadows if item.shadow_available and item.target_year is not None]
    median_returns = _load_median_returns(db, comparable)
    volume_signals = _load_latest_volume_signals(db, [item.ticker for item in comparable])

    raw_items: list[dict] = []
    for item in comparable:
        median_target = _finite(item.median_target_price)
        weighted_target = _finite(item.weighted_target_price)
        current_price = _finite(item.current_price)
        if median_target is None or weighted_target is None or item.target_year is None:
            continue
        median_return = median_returns.get(item.ticker)
        weighted_return = None
        if median_return is not None and current_price is not None and current_price > 0:
            median_price_potential = ((median_target - current_price) / current_price) * 100.0
            dividend_layer = median_return - median_price_potential
            weighted_price_potential = ((weighted_target - current_price) / current_price) * 100.0
            weighted_return = weighted_price_potential + dividend_layer
        return_delta = (
            weighted_return - median_return
            if weighted_return is not None and median_return is not None
            else None
        )
        sign_changed = bool(
            median_return is not None
            and weighted_return is not None
            and ((median_return > 0) != (weighted_return > 0))
            and not math.isclose(median_return, weighted_return, abs_tol=1e-12)
        )
        signal = volume_signals.get(item.ticker)
        median_score = _score(current_price, median_target, median_return, signal)
        weighted_score = _score(current_price, weighted_target, weighted_return, signal)
        raw_items.append(
            {
                "ticker": item.ticker,
                "target_year": item.target_year,
                "current_price": current_price,
                "median_target_price": median_target,
                "weighted_target_price": weighted_target,
                "target_delta_rub": weighted_target - median_target,
                "target_delta_percent": item.weighted_vs_median_target_delta_percent,
                "median_expected_return_percent": median_return,
                "weighted_expected_return_percent": weighted_return,
                "expected_return_delta_pp": return_delta,
                "expected_return_sign_changed": sign_changed,
                "volume_signal_status": signal,
                "median_watchlist_score": median_score,
                "weighted_watchlist_score": weighted_score,
                "watchlist_score_delta": (
                    weighted_score - median_score
                    if weighted_score is not None and median_score is not None
                    else None
                ),
            }
        )

    median_ranks = _rank_items(raw_items, "median_expected_return_percent")
    weighted_ranks = _rank_items(raw_items, "weighted_expected_return_percent")
    effective_top_n = max(1, min(top_n, len(raw_items))) if raw_items else top_n
    median_top = {ticker for ticker, rank in median_ranks.items() if rank <= effective_top_n}
    weighted_top = {ticker for ticker, rank in weighted_ranks.items() if rank <= effective_top_n}

    items: list[ProductionImpactItem] = []
    for item in raw_items:
        median_rank = median_ranks.get(item["ticker"])
        weighted_rank = weighted_ranks.get(item["ticker"])
        items.append(
            ProductionImpactItem(
                **item,
                median_rank=median_rank,
                weighted_rank=weighted_rank,
                rank_delta=(
                    weighted_rank - median_rank
                    if median_rank is not None and weighted_rank is not None
                    else None
                ),
                in_median_top_n=item["ticker"] in median_top,
                in_weighted_top_n=item["ticker"] in weighted_top,
            )
        )
    items.sort(
        key=lambda item: (
            -abs(item.rank_delta or 0),
            -abs(item.target_delta_percent or 0.0),
            item.ticker,
        )
    )

    target_deltas = [abs(item.target_delta_percent) for item in items if item.target_delta_percent is not None]
    return_deltas = [abs(item.expected_return_delta_pp) for item in items if item.expected_return_delta_pp is not None]
    rank_changes = [abs(item.rank_delta) for item in items if item.rank_delta is not None]
    score_changes = [abs(item.watchlist_score_delta) for item in items if item.watchlist_score_delta is not None]
    flips = sum(1 for item in items if item.expected_return_sign_changed)
    ranked_count = len(set(median_ranks) & set(weighted_ranks))
    overlap = len(median_top & weighted_top)
    top_denominator = max(1, min(effective_top_n, len(median_top), len(weighted_top)))
    return ProductionImpactSummary(
        generated_at=current,
        top_n=effective_top_n,
        universe_tickers=universe_tickers,
        comparable_tickers=len(items),
        comparable_coverage_percent=(100.0 * len(items) / universe_tickers if universe_tickers else 0.0),
        median_abs_target_delta_percent=float(median(target_deltas)) if target_deltas else None,
        max_abs_target_delta_percent=max(target_deltas) if target_deltas else None,
        median_abs_expected_return_delta_pp=float(median(return_deltas)) if return_deltas else None,
        return_sign_flip_tickers=flips,
        return_sign_flip_percent=(100.0 * flips / ranked_count if ranked_count else 0.0),
        rank_correlation_spearman=_spearman(
            {item["ticker"]: item["median_expected_return_percent"] for item in raw_items if item["median_expected_return_percent"] is not None},
            {item["ticker"]: item["weighted_expected_return_percent"] for item in raw_items if item["weighted_expected_return_percent"] is not None},
        ),
        mean_abs_rank_change=float(mean(rank_changes)) if rank_changes else None,
        max_abs_rank_change=max(rank_changes) if rank_changes else None,
        top_n_overlap_tickers=overlap,
        top_n_overlap_percent=100.0 * overlap / top_denominator,
        top_n_entered=sorted(weighted_top - median_top),
        top_n_exited=sorted(median_top - weighted_top),
        mean_abs_watchlist_score_delta=float(mean(score_changes)) if score_changes else None,
        items=items,
    )


def _gate(key: str, label: str, passed: bool, actual: str, requirement: str) -> PromotionGate:
    return PromotionGate(key=key, label=label, passed=passed, actual=actual, requirement=requirement)


def _ratio(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}%"


def build_promotion_dossier(
    db: Session,
    *,
    impact: ProductionImpactSummary,
    history_days: int = DEFAULT_IMPACT_HISTORY_DAYS,
    as_of: datetime | None = None,
) -> PromotionDossier:
    current = as_of or datetime.now(timezone.utc)
    primary = db.scalars(
        select(AnalystTable).order_by(AnalystTable.sort_order.asc(), AnalystTable.id.asc()).limit(1)
    ).first()
    snapshot = training_snapshot_for_target(int(primary.forecast_start_year), current) if primary else "pre_year"
    readiness: ConsensusReadinessResult = build_consensus_readiness(db, snapshot=snapshot)
    overview: ShadowDriftOverviewResult = build_shadow_drift_overview(db, days=history_days)
    classified = [item for item in overview.items if item.status != "insufficient"]
    actionable_percent = (
        100.0 * overview.actionable_tickers / overview.classified_tickers
        if overview.classified_tickers
        else 100.0
    )
    spans = [item.history_span_hours for item in classified if item.history_span_hours > 0]
    median_span = float(median(spans)) if spans else 0.0

    gates = [
        _gate(
            "historical_readiness",
            "Исторический readiness",
            readiness.ready,
            f"{readiness.gates_passed}/{readiness.gates_total}",
            "11/11 PASS",
        ),
        _gate(
            "impact_coverage",
            "Покрытие impact simulator",
            impact.comparable_coverage_percent >= MIN_COMPARABLE_COVERAGE_PERCENT,
            _ratio(impact.comparable_coverage_percent),
            f">= {MIN_COMPARABLE_COVERAGE_PERCENT:.0f}%",
        ),
        _gate(
            "rank_correlation",
            "Стабильность ранжирования",
            impact.rank_correlation_spearman is not None
            and impact.rank_correlation_spearman >= MIN_RANK_CORRELATION,
            "—" if impact.rank_correlation_spearman is None else f"{impact.rank_correlation_spearman:.3f}",
            f">= {MIN_RANK_CORRELATION:.2f}",
        ),
        _gate(
            "top_n_overlap",
            f"Пересечение Top-{impact.top_n}",
            impact.top_n_overlap_percent >= MIN_TOP_N_OVERLAP_PERCENT,
            _ratio(impact.top_n_overlap_percent),
            f">= {MIN_TOP_N_OVERLAP_PERCENT:.0f}%",
        ),
        _gate(
            "return_sign_flips",
            "Смена знака ожидаемой доходности",
            impact.return_sign_flip_percent <= MAX_RETURN_SIGN_FLIP_PERCENT,
            _ratio(impact.return_sign_flip_percent),
            f"<= {MAX_RETURN_SIGN_FLIP_PERCENT:.0f}%",
        ),
        _gate(
            "watchlist_score_stability",
            "Стабильность Watchlist score",
            impact.mean_abs_watchlist_score_delta is not None
            and impact.mean_abs_watchlist_score_delta <= MAX_MEAN_ABS_WATCHLIST_SCORE_DELTA,
            "—" if impact.mean_abs_watchlist_score_delta is None else f"{impact.mean_abs_watchlist_score_delta:.1f} pt",
            f"<= {MAX_MEAN_ABS_WATCHLIST_SCORE_DELTA:.0f} pt",
        ),
        _gate(
            "forward_classified_coverage",
            "Forward classified coverage",
            overview.classified_coverage_percent >= MIN_FORWARD_CLASSIFIED_COVERAGE_PERCENT,
            _ratio(overview.classified_coverage_percent),
            f">= {MIN_FORWARD_CLASSIFIED_COVERAGE_PERCENT:.0f}%",
        ),
        _gate(
            "forward_alerts",
            "Forward ALERT",
            overview.alert_tickers == 0,
            str(overview.alert_tickers),
            "0",
        ),
        _gate(
            "forward_actionable",
            "Forward WATCH + ALERT",
            actionable_percent <= MAX_FORWARD_ACTIONABLE_PERCENT,
            _ratio(actionable_percent),
            f"<= {MAX_FORWARD_ACTIONABLE_PERCENT:.0f}% classified",
        ),
        _gate(
            "forward_observation_span",
            "Forward observation span",
            median_span >= MIN_FORWARD_SPAN_HOURS,
            f"{median_span / 24.0:.1f} d",
            f">= {MIN_FORWARD_SPAN_HOURS / 24.0:.0f} d median",
        ),
    ]
    passed = sum(1 for gate in gates if gate.passed)
    if all(gate.passed for gate in gates):
        status = "READY_FOR_MANUAL_PROMOTION"
    elif not readiness.ready:
        status = "NOT_READY"
    else:
        status = "OBSERVE"
    return PromotionDossier(
        generated_at=current,
        status=status,
        gates_passed=passed,
        gates_total=len(gates),
        historical_snapshot=snapshot,
        historical_readiness=readiness.ready,
        forward_history_days=history_days,
        gates=gates,
    )


def build_production_impact(
    db: Session,
    *,
    top_n: int = DEFAULT_TOP_N,
    history_days: int = DEFAULT_IMPACT_HISTORY_DAYS,
    as_of: datetime | None = None,
) -> ProductionImpactResult:
    current = as_of or datetime.now(timezone.utc)
    impact = build_production_impact_summary(db, top_n=top_n, as_of=current)
    promotion = build_promotion_dossier(
        db,
        impact=impact,
        history_days=history_days,
        as_of=current,
    )
    return ProductionImpactResult(impact=impact, promotion=promotion)
