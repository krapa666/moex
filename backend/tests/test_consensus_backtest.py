from datetime import datetime, timezone

from app.consensus_backtest import (
    ConsensusBacktestObservation,
    _available_training_samples,
    _source_weights,
    aggregate_consensus_backtest,
    build_consensus_backtest_observations,
)
from app.forecast_accuracy import AccuracySample, ActualNetProfit
from app.models import Base, ForecastRevision
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def _sample(
    *,
    source: str,
    ticker: str,
    year: int,
    forecast: float,
    actual: float,
    smape: float,
) -> AccuracySample:
    return AccuracySample(
        table_id=1,
        analyst_name=source,
        ticker=ticker,
        fiscal_year=year,
        snapshot="pre_year",
        forecast_billion_rub=forecast,
        actual_billion_rub=actual,
        forecast_created_at=datetime(year - 1, 12, 1, tzinfo=timezone.utc),
        absolute_error_billion_rub=abs(forecast - actual),
        smape_percent=smape,
        sign_correct=(forecast >= 0) == (actual >= 0),
    )


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


def test_training_excludes_facts_not_published_before_target_cutoff() -> None:
    older = _sample(
        source="A",
        ticker="AAA",
        year=2023,
        forecast=95.0,
        actual=100.0,
        smape=5.1,
    )
    too_late = _sample(
        source="A",
        ticker="BBB",
        year=2024,
        forecast=100.0,
        actual=120.0,
        smape=18.2,
    )
    target_cutoff = datetime(2025, 1, 1, tzinfo=timezone.utc)

    available = _available_training_samples(
        [older, too_late],
        target_fiscal_year=2025,
        target_cutoff=target_cutoff,
        reported_at_by_key={
            ("AAA", 2023): datetime(2024, 3, 1, tzinfo=timezone.utc),
            ("BBB", 2024): datetime(2025, 3, 1, tzinfo=timezone.utc),
        },
    )

    assert available == [older]


def test_training_excludes_actual_with_unknown_publication_date() -> None:
    sample = _sample(
        source="A",
        ticker="AAA",
        year=2023,
        forecast=95.0,
        actual=100.0,
        smape=5.1,
    )

    available = _available_training_samples(
        [sample],
        target_fiscal_year=2025,
        target_cutoff=datetime(2025, 1, 1, tzinfo=timezone.utc),
        reported_at_by_key={("AAA", 2023): None},
    )

    assert available == []


def test_accuracy_weighting_prefers_better_source_but_respects_cap() -> None:
    history = [
        *[
            _sample(
                source="Accurate",
                ticker=f"A{index}",
                year=2023,
                forecast=100.0,
                actual=100.0,
                smape=5.0,
            )
            for index in range(6)
        ],
        *[
            _sample(
                source="Weak",
                ticker=f"W{index}",
                year=2023,
                forecast=50.0,
                actual=100.0,
                smape=66.7,
            )
            for index in range(6)
        ],
    ]

    weights, counts = _source_weights(
        ["Accurate", "Weak", "New"],
        history,
        shrinkage_samples=0,
        error_floor_percent=5.0,
        relative_score_cap=2.0,
    )

    assert counts == {"Accurate": 6, "Weak": 6, "New": 0}
    assert weights["Accurate"] > weights["New"] > weights["Weak"]
    assert max(weights.values()) / min(weights.values()) <= 4.0 + 1e-9
    assert abs(sum(weights.values()) - 1.0) < 1e-12


def test_no_training_history_makes_weighted_forecast_equal_mean() -> None:
    weights, counts = _source_weights(
        ["A", "B"],
        [],
        shrinkage_samples=5,
        error_floor_percent=5.0,
        relative_score_cap=2.0,
    )

    assert counts == {"A": 0, "B": 0}
    assert weights == {"A": 0.5, "B": 0.5}
    weighted = 80.0 * weights["A"] + 120.0 * weights["B"]
    assert weighted == 100.0


def test_backtest_methods_use_same_observation_set_and_report_delta_vs_median() -> None:
    observations = [
        ConsensusBacktestObservation(
            ticker="AAA",
            fiscal_year=2024,
            snapshot="pre_year",
            cutoff=datetime(2024, 1, 1, tzinfo=timezone.utc),
            actual_billion_rub=100.0,
            sources=2,
            sources_with_training_history=2,
            training_samples=10,
            source_forecasts={"A": 80.0, "B": 140.0},
            source_weights={"A": 0.75, "B": 0.25},
            source_training_samples={"A": 5, "B": 5},
            median_forecast_billion_rub=110.0,
            mean_forecast_billion_rub=110.0,
            weighted_forecast_billion_rub=95.0,
        ),
        ConsensusBacktestObservation(
            ticker="BBB",
            fiscal_year=2024,
            snapshot="pre_year",
            cutoff=datetime(2024, 1, 1, tzinfo=timezone.utc),
            actual_billion_rub=200.0,
            sources=2,
            sources_with_training_history=2,
            training_samples=10,
            source_forecasts={"A": 180.0, "B": 260.0},
            source_weights={"A": 0.75, "B": 0.25},
            source_training_samples={"A": 5, "B": 5},
            median_forecast_billion_rub=220.0,
            mean_forecast_billion_rub=220.0,
            weighted_forecast_billion_rub=200.0,
        ),
    ]

    methods = aggregate_consensus_backtest(observations)
    by_method = {method.method: method for method in methods}

    assert set(by_method) == {"median", "mean", "weighted"}
    assert {method.samples for method in methods} == {2}
    assert by_method["median"].median_smape_delta_vs_median_pp == 0.0
    assert by_method["weighted"].median_smape_delta_vs_median_pp > 0
    assert by_method["weighted"].mean_smape_delta_vs_median_pp > 0


def test_integrated_backtest_trains_2025_weights_only_on_published_2023_fact() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                ActualNetProfit(
                    ticker="AAA",
                    fiscal_year=2023,
                    net_profit_billion_rub=100.0,
                    source_name="Issuer",
                    reported_at=datetime(2024, 3, 1, tzinfo=timezone.utc),
                ),
                ActualNetProfit(
                    ticker="AAA",
                    fiscal_year=2025,
                    net_profit_billion_rub=200.0,
                    source_name="Issuer",
                    reported_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
                ),
                _revision(
                    source="Accurate",
                    table_id=1,
                    ticker="AAA",
                    year=2023,
                    forecast=100.0,
                ),
                _revision(
                    source="Weak",
                    table_id=2,
                    ticker="AAA",
                    year=2023,
                    forecast=50.0,
                ),
                _revision(
                    source="Accurate",
                    table_id=1,
                    ticker="AAA",
                    year=2025,
                    forecast=190.0,
                ),
                _revision(
                    source="Weak",
                    table_id=2,
                    ticker="AAA",
                    year=2025,
                    forecast=280.0,
                ),
            ]
        )
        db.commit()

        observations = build_consensus_backtest_observations(
            db,
            snapshot="pre_year",
            shrinkage_samples=0,
        )

    target = next(item for item in observations if item.fiscal_year == 2025)
    assert target.training_samples == 2
    assert target.sources_with_training_history == 2
    assert target.source_training_samples == {"Accurate": 1, "Weak": 1}
    assert target.source_weights["Accurate"] > target.source_weights["Weak"]
    assert target.weighted_forecast_billion_rub < target.mean_forecast_billion_rub
