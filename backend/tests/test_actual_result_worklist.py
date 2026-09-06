from app.actual_result_backfill_api import ActualWorklistRead
from app.actual_result_worklist import (
    build_actual_result_worklist,
    render_actual_result_worklist_csv,
)
from app.application import app
from app.database import Base
from app.forecast_accuracy import ActualNetProfit
from app.models import AnalystTable, StockRow
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def _seed_primary_universe(db: Session) -> None:
    primary = AnalystTable(
        analyst_name="Primary",
        forecast_start_year=2026,
        sort_order=1,
    )
    secondary = AnalystTable(
        analyst_name="Secondary",
        forecast_start_year=2026,
        sort_order=2,
    )
    db.add_all([primary, secondary])
    db.flush()
    db.add_all(
        [
            StockRow(table_id=primary.id, ticker="sber"),
            StockRow(table_id=primary.id, ticker="GAZP"),
            StockRow(table_id=primary.id, ticker=" SBER "),
            StockRow(table_id=secondary.id, ticker="LKOH"),
        ]
    )
    db.commit()


def test_worklist_routes_are_registered() -> None:
    paths = {route.path for route in app.routes}
    assert "/api/analytics/actual-net-profits/backfill/worklist" in paths
    assert "/api/analytics/actual-net-profits/backfill/worklist.csv" in paths


def test_worklist_uses_current_primary_universe_and_existing_actuals() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        _seed_primary_universe(db)
        db.add_all(
            [
                ActualNetProfit(
                    ticker="SBER",
                    fiscal_year=2025,
                    source_key="manual",
                    net_profit_billion_rub=1.0,
                    source_name="Issuer",
                ),
                ActualNetProfit(
                    ticker="gazp",
                    fiscal_year=2024,
                    source_key="manual",
                    net_profit_billion_rub=2.0,
                    source_name="Issuer",
                ),
                ActualNetProfit(
                    ticker="LKOH",
                    fiscal_year=2025,
                    source_key="manual",
                    net_profit_billion_rub=3.0,
                    source_name="Issuer",
                ),
            ]
        )
        db.commit()

        result = build_actual_result_worklist(db, years=2, end_year=2025)

    assert result["start_year"] == 2024
    assert result["end_year"] == 2025
    assert result["primary_tickers"] == 2
    assert result["expected_pairs"] == 4
    assert result["existing_pairs"] == 2
    assert result["missing_pairs"] == 2
    assert result["coverage_percent"] == 50.0
    assert result["by_year"] == [
        {
            "fiscal_year": 2024,
            "expected_pairs": 2,
            "existing_pairs": 1,
            "missing_pairs": 1,
            "coverage_percent": 50.0,
        },
        {
            "fiscal_year": 2025,
            "expected_pairs": 2,
            "existing_pairs": 1,
            "missing_pairs": 1,
            "coverage_percent": 50.0,
        },
    ]
    assert result["missing"] == [
        {"ticker": "SBER", "fiscal_year": 2024},
        {"ticker": "GAZP", "fiscal_year": 2025},
    ]
    ActualWorklistRead.model_validate(result)


def test_worklist_csv_matches_backfill_contract_and_contains_only_missing_pairs() -> None:
    worklist = {
        "missing": [
            {"ticker": "SBER", "fiscal_year": 2024},
            {"ticker": "GAZP", "fiscal_year": 2025},
        ]
    }

    csv_text = render_actual_result_worklist_csv(worklist)

    assert csv_text.startswith("\ufeffticker;fiscal_year;net_profit_billion_rub;")
    assert "SBER;2024;;;;;" in csv_text
    assert "GAZP;2025;;;;;" in csv_text
    assert "source_name;source_url;reported_at;source_comment" in csv_text


def test_worklist_without_primary_table_is_empty_but_well_formed() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        result = build_actual_result_worklist(db, years=5, end_year=2025)

    assert result["primary_table_id"] is None
    assert result["primary_tickers"] == 0
    assert result["expected_pairs"] == 0
    assert result["existing_pairs"] == 0
    assert result["missing_pairs"] == 0
    assert result["coverage_percent"] == 0.0
    assert len(result["by_year"]) == 5
    assert result["missing"] == []
