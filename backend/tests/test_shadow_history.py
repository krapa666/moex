from datetime import datetime, timedelta, timezone

from app.models import AnalystTable, Base, StockRow
from app.shadow_history import (
    ShadowConsensusSnapshot,
    build_shadow_drift,
    capture_shadow_consensus,
)
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


def _snapshot(
    *,
    ticker: str = "AAA",
    target_year: int = 2026,
    captured_at: datetime,
    delta_percent: float,
    median_target: float = 100.0,
    max_weight_percent: float = 55.0,
    training_snapshot: str = "mid_year",
) -> ShadowConsensusSnapshot:
    weighted_target = median_target * (1.0 + delta_percent / 100.0)
    return ShadowConsensusSnapshot(
        ticker=ticker,
        target_year=target_year,
        training_snapshot=training_snapshot,
        captured_at=captured_at,
        sources=2,
        sources_with_training_history=2,
        training_samples=10,
        weighting_uses_history=True,
        max_source_weight_percent=max_weight_percent,
        min_source_weight_percent=100.0 - max_weight_percent,
        median_net_profit_billion_rub=100.0,
        weighted_net_profit_billion_rub=100.0 * (1.0 + delta_percent / 100.0),
        median_target_price=median_target,
        weighted_target_price=weighted_target,
        weighted_vs_median_target_delta_rub=weighted_target - median_target,
        weighted_vs_median_target_delta_percent=delta_percent,
        current_price=90.0,
        median_market_gap_percent=median_target / 90.0 * 100.0 - 100.0,
        weighted_market_gap_percent=weighted_target / 90.0 * 100.0 - 100.0,
    )


def test_capture_persists_only_comparable_shadow_results_and_prunes_expired() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    captured_at = datetime(2026, 9, 6, 7, 0, tzinfo=timezone.utc)

    with Session(engine) as db:
        primary = AnalystTable(analyst_name="A", forecast_start_year=2026, sort_order=1)
        secondary = AnalystTable(analyst_name="B", forecast_start_year=2026, sort_order=2)
        db.add_all([primary, secondary])
        db.flush()
        db.add_all(
            [
                StockRow(
                    table_id=primary.id,
                    ticker="AAA",
                    shares_billion=10.0,
                    pe_avg_5y=10.0,
                    current_price=90.0,
                    net_profit_year_map={"2026": 100.0},
                ),
                StockRow(
                    table_id=secondary.id,
                    ticker="AAA",
                    shares_billion=10.0,
                    pe_avg_5y=10.0,
                    current_price=90.0,
                    net_profit_year_map={"2026": 120.0},
                ),
                StockRow(
                    table_id=primary.id,
                    ticker="BBB",
                    shares_billion=10.0,
                    pe_avg_5y=10.0,
                    current_price=80.0,
                    net_profit_year_map={"2026": 80.0},
                ),
                _snapshot(
                    ticker="OLD",
                    captured_at=captured_at - timedelta(days=60),
                    delta_percent=2.0,
                ),
            ]
        )
        db.commit()

        result = capture_shadow_consensus(
            db,
            captured_at=captured_at,
            retention_days=30,
        )
        stored = list(
            db.scalars(
                select(ShadowConsensusSnapshot).order_by(ShadowConsensusSnapshot.ticker)
            ).all()
        )

    assert result.tickers_total == 2
    assert result.snapshots_created == 1
    assert result.skipped_unavailable == 1
    assert result.deleted_expired == 1
    assert [row.ticker for row in stored] == ["AAA"]
    assert stored[0].sources == 2
    assert stored[0].max_source_weight_percent == 50.0
    assert stored[0].weighted_target_price == stored[0].median_target_price


def test_drift_requires_forward_history_span_before_classifying() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)

    with Session(engine) as db:
        db.add_all(
            [
                _snapshot(captured_at=now - timedelta(hours=6), delta_percent=2.0),
                _snapshot(captured_at=now, delta_percent=2.5),
            ]
        )
        db.commit()
        result = build_shadow_drift(db, ticker="AAA", days=30)

    assert result.status == "insufficient"
    assert result.snapshots == 2
    assert "too_few_snapshots" in result.reasons
    assert "history_too_short" in result.reasons


def test_drift_marks_persistent_ten_percent_baseline_gap_as_watch() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)

    with Session(engine) as db:
        db.add_all(
            [
                _snapshot(
                    captured_at=now - timedelta(days=3),
                    delta_percent=12.0,
                    median_target=100.0,
                ),
                _snapshot(
                    captured_at=now - timedelta(days=2),
                    delta_percent=12.0,
                    median_target=101.0,
                ),
                _snapshot(
                    captured_at=now - timedelta(days=1),
                    delta_percent=12.0,
                    median_target=102.0,
                ),
            ]
        )
        db.commit()
        result = build_shadow_drift(db, ticker="aaa", days=30)

    assert result.status == "watch"
    assert result.reasons == ["large_baseline_divergence"]
    assert result.snapshots == 3
    assert result.history_span_hours >= 48.0
    assert result.latest_delta_percent == 12.0
    assert result.latest_weight_concentration_ratio == 1.1
    assert abs(result.relative_movement_gap_percentage_points) < 1e-9


def test_drift_ignores_previous_target_year_and_alerts_on_large_current_gap() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)

    with Session(engine) as db:
        db.add(
            _snapshot(
                target_year=2025,
                captured_at=now - timedelta(days=5),
                delta_percent=80.0,
            )
        )
        db.add_all(
            [
                _snapshot(captured_at=now - timedelta(days=3), delta_percent=5.0),
                _snapshot(captured_at=now - timedelta(days=2), delta_percent=10.0),
                _snapshot(captured_at=now - timedelta(days=1), delta_percent=25.0),
            ]
        )
        db.commit()
        result = build_shadow_drift(db, ticker="AAA", days=30)

    assert result.target_year == 2026
    assert result.snapshots == 3
    assert result.status == "alert"
    assert "large_baseline_divergence" in result.reasons
    assert "rapid_divergence_change" in result.reasons
