from datetime import datetime, timezone

from app.consensus_backtest import (
    ConsensusBacktestObservation,
    _jackknife_backtest,
    _slice_backtest,
    build_consensus_backtest_robustness,
)
from app.forecast_accuracy import ActualNetProfit
from app.models import Base, ForecastRevision
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def _observation(
    *,
    ticker: str,
    year: int,
    actual: float,
    median_forecast: float,
    weighted_forecast: float,
) -> ConsensusBacktestObservation:
    return ConsensusBacktestObservation(
        ticker=ticker,
        fiscal_year=year,
        snapshot="pre_year",
        cutoff=datetime(year, 1, 1, tzinfo=timezone.utc),
        actual_billion_rub=actual,
        sources=2,
        sources_with_training_history=2,
        training_samples=10,
        source_forecasts={"A": median_forecast, "B": median_forecast},
        source_weights={"A": 0.6, "B": 0.4},
        source_training_samples={"A": 5, "B": 5},
        median_forecast_billion_rub=median_forecast,
        mean_forecast_billion_rub=median_forecast,
        weighted_forecast_billion_rub=weighted_forecast,
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


def test_slices_and_jackknife_reveal_ticker_and_year_concentration() -> None:
    observations = [
        _observation(
            ticker="AAA",
            year=2024,
            actual=100.0,
            median_forecast=110.0,
            weighted_forecast=100.0,
        ),
        _observation(
            ticker="BBB",
            year=2024,
            actual=100.0,
            median_forecast=100.0,
            weighted_forecast=120.0,
        ),
        _observation(
            ticker="AAA",
            year=2025,
            actual=200.0,
            median_forecast=220.0,
            weighted_forecast=200.0,
        ),
    ]

    by_ticker = {row.key: row for row in _slice_backtest(observations, dimension="ticker")}
    by_year = {row.key: row for row in _slice_backtest(observations, dimension="year")}
    jackknife = {
        row.excluded_key: row for row in _jackknife_backtest(observations, dimension="ticker")
    }

    assert by_ticker["AAA"].weighted_median_delta_pp > 0
    assert by_ticker["BBB"].weighted_median_delta_pp < 0
    assert by_year["2024"].weighted_median_delta_pp < 0
    assert by_year["2025"].weighted_median_delta_pp > 0
    assert jackknife["AAA"].preserves_median_improvement is False
    assert jackknife["BBB"].preserves_median_improvement is True


def test_robustness_parameter_sweep_has_27_cases_on_same_observation_set() -> None:
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

        result = build_consensus_backtest_robustness(db, snapshot="pre_year")

    assert result.observations == 2
    assert result.tickers == 1
    assert result.years == 2
    assert result.parameter_cases == 27
    assert len(result.parameter_sweep) == 27
    assert {row.observations for row in result.parameter_sweep} == {2}
    assert result.parameter_min_median_delta_pp is not None
    assert result.parameter_max_median_delta_pp is not None
    assert result.parameter_min_median_delta_pp <= result.parameter_max_median_delta_pp
    assert result.year_slices == 2
    assert result.ticker_slices == 1


def test_empty_robustness_result_is_well_formed() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        result = build_consensus_backtest_robustness(db)

    assert result.observations == 0
    assert result.parameter_cases == 0
    assert result.by_year == []
    assert result.by_ticker == []
    assert result.jackknife_year == []
    assert result.jackknife_ticker == []
    assert result.parameter_sweep == []
