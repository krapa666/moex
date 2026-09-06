from datetime import datetime, timezone

from app.forecast_accuracy import ActualNetProfit
from app.models import AnalystTable, Base, ForecastRevision, StockRow
from app.shadow_consensus import build_shadow_consensus, training_snapshot_for_target
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def _revision(
    *,
    source: str,
    table_id: int,
    ticker: str,
    year: int,
    forecast: float,
) -> ForecastRevision:
    return ForecastRevision(
        table_id=table_id,
        ticker=ticker,
        analyst_name=source,
        forecast_start_year=year,
        event_type="updated",
        net_profit_year_map={str(year): forecast},
        created_at=datetime(year - 1, 12, 1, tzinfo=timezone.utc),
    )


def test_training_snapshot_matches_current_target_horizon() -> None:
    as_of = datetime(2026, 9, 6, tzinfo=timezone.utc)
    assert training_snapshot_for_target(2027, as_of) == "pre_year"
    assert training_snapshot_for_target(2026, as_of) == "mid_year"
    assert training_snapshot_for_target(2025, as_of) == "year_end"
    assert training_snapshot_for_target(
        2026,
        datetime(2026, 3, 1, tzinfo=timezone.utc),
    ) == "pre_year"


def test_shadow_consensus_prefers_source_with_better_published_history() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        accurate = AnalystTable(
            analyst_name="Accurate",
            forecast_start_year=2026,
            sort_order=1,
        )
        weak = AnalystTable(
            analyst_name="Weak",
            forecast_start_year=2026,
            sort_order=2,
        )
        db.add_all([accurate, weak])
        db.flush()
        db.add_all(
            [
                ActualNetProfit(
                    ticker="AAA",
                    fiscal_year=2024,
                    net_profit_billion_rub=100.0,
                    source_name="Issuer",
                    reported_at=datetime(2025, 3, 1, tzinfo=timezone.utc),
                ),
                _revision(
                    source="Accurate",
                    table_id=accurate.id,
                    ticker="AAA",
                    year=2024,
                    forecast=100.0,
                ),
                _revision(
                    source="Weak",
                    table_id=weak.id,
                    ticker="AAA",
                    year=2024,
                    forecast=50.0,
                ),
                StockRow(
                    table_id=accurate.id,
                    ticker="AAA",
                    shares_billion=10.0,
                    pe_avg_5y=10.0,
                    current_price=180.0,
                    net_profit_year_map={"2026": 190.0},
                ),
                StockRow(
                    table_id=weak.id,
                    ticker="AAA",
                    shares_billion=10.0,
                    pe_avg_5y=10.0,
                    current_price=180.0,
                    net_profit_year_map={"2026": 280.0},
                ),
            ]
        )
        db.commit()

        result = build_shadow_consensus(
            db,
            ticker="aaa",
            as_of=datetime(2026, 9, 6, tzinfo=timezone.utc),
        )

    assert result.shadow_available is True
    assert result.ticker == "AAA"
    assert result.target_year == 2026
    assert result.training_snapshot == "mid_year"
    assert result.sources == 2
    assert result.sources_with_training_history == 2
    assert result.training_samples == 2
    assert result.weighting_uses_history is True
    assert result.weighted_target_price < result.mean_target_price
    assert result.weighted_target_price < result.median_target_price
    assert result.max_source_weight_percent > result.min_source_weight_percent
    assert result.weighted_market_gap_percent < result.median_market_gap_percent


def test_shadow_consensus_without_history_falls_back_to_equal_weight_mean() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        tables = [
            AnalystTable(analyst_name="A", forecast_start_year=2027, sort_order=1),
            AnalystTable(analyst_name="B", forecast_start_year=2027, sort_order=2),
            AnalystTable(analyst_name="C", forecast_start_year=2027, sort_order=3),
        ]
        db.add_all(tables)
        db.flush()
        for table, forecast in zip(tables, [80.0, 100.0, 150.0], strict=True):
            db.add(
                StockRow(
                    table_id=table.id,
                    ticker="BBB",
                    shares_billion=10.0,
                    pe_avg_5y=10.0,
                    current_price=90.0,
                    net_profit_year_map={"2027": forecast},
                )
            )
        db.commit()

        result = build_shadow_consensus(
            db,
            ticker="BBB",
            as_of=datetime(2026, 9, 6, tzinfo=timezone.utc),
        )

    assert result.shadow_available is True
    assert result.training_snapshot == "pre_year"
    assert result.training_samples == 0
    assert result.sources_with_training_history == 0
    assert result.weighting_uses_history is False
    assert abs(result.weighted_target_price - result.mean_target_price) < 1e-12
    assert round(result.max_source_weight_percent, 6) == round(100.0 / 3.0, 6)
    assert round(result.min_source_weight_percent, 6) == round(100.0 / 3.0, 6)


def test_shadow_consensus_requires_two_comparable_sources() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        table = AnalystTable(
            analyst_name="Only",
            forecast_start_year=2026,
            sort_order=1,
        )
        db.add(table)
        db.flush()
        db.add(
            StockRow(
                table_id=table.id,
                ticker="ONE",
                shares_billion=10.0,
                pe_avg_5y=10.0,
                net_profit_year_map={"2026": 100.0},
            )
        )
        db.commit()

        result = build_shadow_consensus(
            db,
            ticker="ONE",
            as_of=datetime(2026, 9, 6, tzinfo=timezone.utc),
        )

    assert result.shadow_available is False
    assert result.sources == 1
    assert "two comparable" in result.reason
