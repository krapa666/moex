from datetime import datetime, timezone

from app import shadow_consensus
from app.models import AnalystTable, Base, StockRow
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_batch_shadow_consensus_builds_training_context_once(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    calls = 0
    original = shadow_consensus.build_accuracy_samples

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(shadow_consensus, "build_accuracy_samples", counted)

    with Session(engine) as db:
        primary = AnalystTable(analyst_name="A", forecast_start_year=2027, sort_order=1)
        secondary = AnalystTable(analyst_name="B", forecast_start_year=2027, sort_order=2)
        db.add_all([primary, secondary])
        db.flush()
        for ticker, first, second in (
            ("AAA", 100.0, 120.0),
            ("BBB", 80.0, 140.0),
        ):
            db.add_all(
                [
                    StockRow(
                        table_id=primary.id,
                        ticker=ticker,
                        shares_billion=10.0,
                        pe_avg_5y=10.0,
                        net_profit_year_map={"2027": first},
                    ),
                    StockRow(
                        table_id=secondary.id,
                        ticker=ticker,
                        shares_billion=10.0,
                        pe_avg_5y=10.0,
                        net_profit_year_map={"2027": second},
                    ),
                ]
            )
        db.commit()

        results = shadow_consensus.build_shadow_consensus_batch(
            db,
            as_of=datetime(2026, 9, 6, tzinfo=timezone.utc),
        )

    assert calls == 1
    assert [result.ticker for result in results] == ["AAA", "BBB"]
    assert all(result.shadow_available for result in results)
    assert all(result.training_samples == 0 for result in results)
    assert results[0].weighted_target_price == results[0].mean_target_price
    assert results[1].weighted_target_price == results[1].mean_target_price
