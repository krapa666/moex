from datetime import datetime, timedelta, timezone

from app.models import AnalystTable, Base, StockRow
from app.shadow_history import ShadowConsensusSnapshot, build_shadow_drift_overview
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def _snapshot(
    *,
    ticker: str,
    captured_at: datetime,
    delta_percent: float,
    target_year: int = 2027,
) -> ShadowConsensusSnapshot:
    median_target = 100.0
    weighted_target = median_target * (1.0 + delta_percent / 100.0)
    return ShadowConsensusSnapshot(
        ticker=ticker,
        target_year=target_year,
        training_snapshot="pre_year",
        captured_at=captured_at,
        sources=2,
        sources_with_training_history=2,
        training_samples=8,
        weighting_uses_history=True,
        max_source_weight_percent=50.0,
        min_source_weight_percent=50.0,
        median_net_profit_billion_rub=100.0,
        weighted_net_profit_billion_rub=100.0 * (1.0 + delta_percent / 100.0),
        median_target_price=median_target,
        weighted_target_price=weighted_target,
        weighted_vs_median_target_delta_rub=weighted_target - median_target,
        weighted_vs_median_target_delta_percent=delta_percent,
        current_price=90.0,
        median_market_gap_percent=11.111111,
        weighted_market_gap_percent=100.0 * (weighted_target / 90.0 - 1.0),
    )


def test_shadow_drift_overview_covers_primary_universe_and_sorts_by_severity() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)

    with Session(engine) as db:
        primary = AnalystTable(analyst_name="Primary", forecast_start_year=2027, sort_order=1)
        secondary = AnalystTable(analyst_name="Secondary", forecast_start_year=2027, sort_order=2)
        db.add_all([primary, secondary])
        db.flush()
        for ticker in ["AAA", "BBB", "CCC", "DDD"]:
            db.add(StockRow(table_id=primary.id, ticker=ticker))
        db.add(StockRow(table_id=secondary.id, ticker="OUTSIDE"))

        for ticker, delta in [("AAA", 2.0), ("BBB", 11.0), ("DDD", 25.0)]:
            db.add_all(
                [
                    _snapshot(ticker=ticker, captured_at=now - timedelta(hours=30), delta_percent=delta),
                    _snapshot(ticker=ticker, captured_at=now - timedelta(hours=15), delta_percent=delta),
                    _snapshot(ticker=ticker, captured_at=now, delta_percent=delta),
                ]
            )
        db.commit()

        result = build_shadow_drift_overview(db, days=30)

    assert result.universe_tickers == 4
    assert result.tickers_with_history == 3
    assert result.classified_tickers == 3
    assert result.alert_tickers == 1
    assert result.watch_tickers == 1
    assert result.stable_tickers == 1
    assert result.insufficient_tickers == 1
    assert result.actionable_tickers == 2
    assert result.history_coverage_percent == 75.0
    assert result.classified_coverage_percent == 75.0
    assert [item.ticker for item in result.items] == ["DDD", "BBB", "AAA", "CCC"]
    assert [item.status for item in result.items] == ["alert", "watch", "stable", "insufficient"]
    assert result.items[-1].reasons == ["no_history"]


def test_shadow_drift_overview_is_empty_without_primary_table() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        result = build_shadow_drift_overview(db, days=30)

    assert result.universe_tickers == 0
    assert result.items == []
    assert result.history_coverage_percent == 0.0
    assert result.classified_coverage_percent == 0.0
