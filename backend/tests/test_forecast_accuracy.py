from datetime import datetime, timezone

from app.application import app
from app.forecast_accuracy import (
    AccuracySample,
    ActualNetProfit,
    aggregate_source_accuracy,
    build_accuracy_samples,
    snapshot_cutoff,
    symmetric_absolute_percentage_error,
)
from app.models import Base, ForecastRevision
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def _revision(
    *,
    analyst_name: str,
    table_id: int,
    ticker: str,
    created_at: datetime,
    year: int,
    value: float,
) -> ForecastRevision:
    return ForecastRevision(
        table_id=table_id,
        ticker=ticker,
        analyst_name=analyst_name,
        forecast_start_year=year,
        event_type="updated",
        net_profit_year_map={str(year): value},
        created_at=created_at,
    )


def test_accuracy_routes_are_registered() -> None:
    paths = {route.path for route in app.routes}
    assert "/api/analytics/actual-net-profits" in paths
    assert "/api/analytics/actual-net-profits/{ticker}/{fiscal_year}" in paths
    assert "/api/analytics/source-accuracy" in paths
    assert "/api/analytics/source-accuracy/samples" in paths


def test_snapshot_cutoffs_are_fixed_and_no_hindsight() -> None:
    assert snapshot_cutoff(2026, "pre_year") == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert snapshot_cutoff(2026, "mid_year") == datetime(2026, 7, 1, tzinfo=timezone.utc)
    assert snapshot_cutoff(2026, "year_end") == datetime(2027, 1, 1, tzinfo=timezone.utc)


def test_smape_handles_losses_and_zero_without_division_error() -> None:
    assert symmetric_absolute_percentage_error(0.0, 0.0) == 0.0
    assert symmetric_absolute_percentage_error(10.0, 0.0) == 200.0
    assert round(symmetric_absolute_percentage_error(-90.0, -100.0), 4) == 10.5263


def test_accuracy_uses_last_forecast_before_each_snapshot_cutoff() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(
            ActualNetProfit(
                ticker="SBER",
                fiscal_year=2026,
                net_profit_billion_rub=125.0,
                source_name="issuer report",
            )
        )
        db.add_all(
            [
                _revision(
                    analyst_name="Source A",
                    table_id=1,
                    ticker="SBER",
                    created_at=datetime(2025, 12, 15, tzinfo=timezone.utc),
                    year=2026,
                    value=100.0,
                ),
                _revision(
                    analyst_name="Source A",
                    table_id=1,
                    ticker="SBER",
                    created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
                    year=2026,
                    value=110.0,
                ),
                _revision(
                    analyst_name="Source A",
                    table_id=1,
                    ticker="SBER",
                    created_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                    year=2026,
                    value=120.0,
                ),
                _revision(
                    analyst_name="Source A",
                    table_id=1,
                    ticker="SBER",
                    created_at=datetime(2027, 1, 15, tzinfo=timezone.utc),
                    year=2026,
                    value=125.0,
                ),
            ]
        )
        db.commit()

        pre_year = build_accuracy_samples(db, snapshot="pre_year")
        mid_year = build_accuracy_samples(db, snapshot="mid_year")
        year_end = build_accuracy_samples(db, snapshot="year_end")

    assert [sample.forecast_billion_rub for sample in pre_year] == [100.0]
    assert [sample.forecast_billion_rub for sample in mid_year] == [110.0]
    assert [sample.forecast_billion_rub for sample in year_end] == [120.0]


def test_source_ranking_requires_minimum_sample_count() -> None:
    samples = [
        AccuracySample(
            table_id=1,
            analyst_name="Accurate",
            ticker="AAA",
            fiscal_year=2025,
            snapshot="pre_year",
            forecast_billion_rub=100.0,
            actual_billion_rub=100.0,
            forecast_created_at=datetime(2024, 12, 1, tzinfo=timezone.utc),
            absolute_error_billion_rub=0.0,
            smape_percent=0.0,
            sign_correct=True,
        ),
        AccuracySample(
            table_id=1,
            analyst_name="Accurate",
            ticker="BBB",
            fiscal_year=2025,
            snapshot="pre_year",
            forecast_billion_rub=90.0,
            actual_billion_rub=100.0,
            forecast_created_at=datetime(2024, 12, 1, tzinfo=timezone.utc),
            absolute_error_billion_rub=10.0,
            smape_percent=10.526315789,
            sign_correct=True,
        ),
        AccuracySample(
            table_id=2,
            analyst_name="One shot",
            ticker="AAA",
            fiscal_year=2025,
            snapshot="pre_year",
            forecast_billion_rub=100.0,
            actual_billion_rub=100.0,
            forecast_created_at=datetime(2024, 12, 1, tzinfo=timezone.utc),
            absolute_error_billion_rub=0.0,
            smape_percent=0.0,
            sign_correct=True,
        ),
    ]

    ranking = aggregate_source_accuracy(samples, min_samples=2)
    by_name = {row["analyst_name"]: row for row in ranking}

    assert by_name["Accurate"]["eligible"] is True
    assert by_name["Accurate"]["rank"] == 1
    assert by_name["Accurate"]["samples"] == 2
    assert by_name["One shot"]["eligible"] is False
    assert by_name["One shot"]["rank"] is None
