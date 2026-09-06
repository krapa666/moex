from datetime import datetime, timezone

from app.actual_result_coverage import build_actual_result_coverage
from app.actual_result_coverage_api import ActualResultCoverageRead
from app.application import app
from app.forecast_accuracy import ActualNetProfit
from app.models import Base, ForecastRevision
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def _revision(
    *,
    analyst_name: str,
    table_id: int,
    ticker: str,
    created_at: datetime,
    year_map: dict[str, float | None],
) -> ForecastRevision:
    return ForecastRevision(
        table_id=table_id,
        ticker=ticker,
        analyst_name=analyst_name,
        forecast_start_year=min(int(year) for year in year_map),
        event_type="updated",
        net_profit_year_map=year_map,
        created_at=created_at,
    )


def test_actual_result_coverage_route_is_registered() -> None:
    paths = {route.path for route in app.routes}
    assert "/api/analytics/actual-net-profits/coverage" in paths


def test_coverage_counts_only_forecasts_available_before_snapshot_cutoff() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                ActualNetProfit(
                    ticker="SBER",
                    fiscal_year=2025,
                    net_profit_billion_rub=1580.0,
                    source_name="issuer report",
                ),
                ActualNetProfit(
                    ticker="TATN",
                    fiscal_year=2025,
                    net_profit_billion_rub=250.0,
                    source_name="issuer report",
                ),
                _revision(
                    analyst_name="Source A",
                    table_id=1,
                    ticker="SBER",
                    created_at=datetime(2024, 12, 10, tzinfo=timezone.utc),
                    year_map={"2025": 1500.0, "2026": 1600.0},
                ),
                _revision(
                    analyst_name="Source A",
                    table_id=1,
                    ticker="GAZP",
                    created_at=datetime(2024, 12, 15, tzinfo=timezone.utc),
                    year_map={"2025": 1200.0},
                ),
                _revision(
                    analyst_name="Source B",
                    table_id=2,
                    ticker="SBER",
                    created_at=datetime(2024, 12, 20, tzinfo=timezone.utc),
                    year_map={"2025": 1550.0},
                ),
                _revision(
                    analyst_name="Source A",
                    table_id=1,
                    ticker="LKOH",
                    created_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
                    year_map={"2025": 900.0},
                ),
            ]
        )
        db.commit()

        result = build_actual_result_coverage(
            db,
            snapshot="pre_year",
            start_year=2024,
            end_year=2025,
        )

    payload = ActualResultCoverageRead.model_validate(result)
    assert payload.forecast_pairs == 3
    assert payload.covered_pairs == 2
    assert payload.missing_forecast_pairs == 1
    assert payload.missing_actual_records == 1
    assert round(payload.coverage_percent, 2) == 66.67
    assert payload.forecast_tickers == 2
    assert payload.covered_tickers == 1
    assert payload.actual_records == 2
    assert payload.actual_tickers == 2

    assert payload.by_year[0].fiscal_year == 2025
    assert payload.by_year[0].forecast_pairs == 3
    assert payload.by_year[0].covered_pairs == 2
    assert payload.by_year[0].actual_records == 2

    by_source = {row.analyst_name: row for row in payload.by_source}
    assert by_source["Source A"].forecast_pairs == 2
    assert by_source["Source A"].missing_forecast_pairs == 1
    assert by_source["Source A"].coverage_percent == 50.0
    assert by_source["Source B"].coverage_percent == 100.0

    assert [(row.ticker, row.fiscal_year, row.sources) for row in payload.missing_actuals] == [
        ("GAZP", 2025, 1)
    ]


def test_mid_year_snapshot_includes_forecast_that_pre_year_excludes() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(
            _revision(
                analyst_name="Source A",
                table_id=1,
                ticker="GAZP",
                created_at=datetime(2025, 4, 1, tzinfo=timezone.utc),
                year_map={"2025": 1200.0},
            )
        )
        db.commit()

        pre_year = build_actual_result_coverage(
            db,
            snapshot="pre_year",
            start_year=2025,
            end_year=2025,
        )
        mid_year = build_actual_result_coverage(
            db,
            snapshot="mid_year",
            start_year=2025,
            end_year=2025,
        )

    assert pre_year["forecast_pairs"] == 0
    assert mid_year["forecast_pairs"] == 1
    assert mid_year["missing_forecast_pairs"] == 1


def test_missing_limit_zero_keeps_summary_but_omits_detail_rows() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(
            _revision(
                analyst_name="Source A",
                table_id=1,
                ticker="GAZP",
                created_at=datetime(2024, 12, 1, tzinfo=timezone.utc),
                year_map={"2025": 1200.0},
            )
        )
        db.commit()

        result = build_actual_result_coverage(
            db,
            snapshot="pre_year",
            start_year=2025,
            end_year=2025,
            missing_limit=0,
        )

    assert result["missing_forecast_pairs"] == 1
    assert result["missing_actual_records"] == 1
    assert result["missing_actuals"] == []
