from datetime import datetime, timedelta, timezone

import pytest
from app.database import Base
from app.forecast_source_health import (
    ForecastSourceHealthConfig,
    build_forecast_source_health,
    load_forecast_source_health_configs,
)
from app.forecast_source_runs import ForecastSourceRun
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def _config(
    *,
    source_id: str = "test",
    source_key: str = "test-source",
    analyst_name: str = "Test Source",
    interval_hours: float = 6.0,
) -> ForecastSourceHealthConfig:
    return ForecastSourceHealthConfig(
        source_id=source_id,
        source_key=source_key,
        analyst_name=analyst_name,
        public_name="Test Source",
        expected_interval_hours=interval_hours,
    )


def _run(
    *,
    row_id: int,
    started_at: datetime,
    status: str = "success",
    total: int = 100,
    mapped: int = 100,
    skipped: int = 0,
    error_message: str | None = None,
    error_details: dict[str, str] | None = None,
) -> ForecastSourceRun:
    return ForecastSourceRun(
        id=row_id,
        source_key="test-source",
        analyst_name="Test Source",
        started_at=started_at,
        finished_at=started_at + timedelta(minutes=5) if status != "running" else None,
        status=status,
        tables=1,
        tickers_total=total,
        tickers_mapped=mapped,
        tickers_updated=max(mapped - 5, 0),
        tickers_unchanged=min(mapped, 5),
        tickers_skipped=skipped,
        table_created=False,
        error_message=error_message,
        error_details=error_details,
    )


def _build(rows: list[ForecastSourceRun], *, now: datetime):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all(rows)
        db.commit()
        return build_forecast_source_health(
            db,
            days=30,
            now=now,
            configs=[_config()],
        )


def test_low_absolute_coverage_is_healthy_without_historical_drop() -> None:
    now = datetime(2026, 9, 6, 12, tzinfo=timezone.utc)
    result = _build(
        [_run(row_id=1, started_at=now - timedelta(hours=1), total=100, mapped=55)],
        now=now,
    )

    item = result.items[0]
    assert item.status == "healthy"
    assert item.coverage_percent == pytest.approx(55.0)
    assert item.coverage_baseline_runs == 0
    assert item.reasons == []


def test_partial_latest_run_is_degraded_and_keeps_ticker_error_count() -> None:
    now = datetime(2026, 9, 6, 12, tzinfo=timezone.utc)
    result = _build(
        [
            _run(
                row_id=1,
                started_at=now - timedelta(hours=1),
                status="partial",
                total=100,
                mapped=90,
                skipped=10,
                error_details={"AAA": "missing", "BBB": "parse"},
            )
        ],
        now=now,
    )

    item = result.items[0]
    assert item.status == "degraded"
    assert "latest_run_partial" in item.reasons
    assert item.latest_error_kind == "ticker_errors"
    assert item.latest_error_count == 2


def test_latest_failed_run_has_priority() -> None:
    now = datetime(2026, 9, 6, 12, tzinfo=timezone.utc)
    result = _build(
        [
            _run(row_id=1, started_at=now - timedelta(hours=7)),
            _run(
                row_id=2,
                started_at=now - timedelta(hours=1),
                status="failed",
                total=0,
                mapped=0,
                error_message="source unavailable",
            ),
        ],
        now=now,
    )

    item = result.items[0]
    assert item.status == "failed"
    assert item.reasons == ["latest_run_failed"]
    assert item.consecutive_failures == 1
    assert item.consecutive_successes == 0
    assert item.latest_error_kind == "sync_exception"
    assert item.latest_error_message == "source unavailable"


def test_old_successful_run_is_stale_relative_to_its_cadence() -> None:
    now = datetime(2026, 9, 6, 18, tzinfo=timezone.utc)
    result = _build(
        [_run(row_id=1, started_at=now - timedelta(hours=20))],
        now=now,
    )

    item = result.items[0]
    assert item.status == "stale"
    assert item.reasons == ["latest_run_stale"]
    assert item.latest_age_hours is not None
    assert item.latest_age_hours > 15.0


def test_coverage_drop_requires_three_baseline_runs() -> None:
    now = datetime(2026, 9, 6, 12, tzinfo=timezone.utc)
    rows = [
        _run(row_id=1, started_at=now - timedelta(hours=25), mapped=100),
        _run(row_id=2, started_at=now - timedelta(hours=19), mapped=100),
        _run(row_id=3, started_at=now - timedelta(hours=13), mapped=100),
        _run(row_id=4, started_at=now - timedelta(hours=1), mapped=70),
    ]
    result = _build(rows, now=now)

    item = result.items[0]
    assert item.status == "degraded"
    assert item.coverage_baseline_runs == 3
    assert item.baseline_coverage_percent == pytest.approx(100.0)
    assert item.coverage_change_pp == pytest.approx(-30.0)
    assert "coverage_drop" in item.reasons


def test_overview_orders_failed_before_healthy() -> None:
    now = datetime(2026, 9, 6, 12, tzinfo=timezone.utc)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    configs = [
        _config(source_id="healthy", source_key="healthy", analyst_name="Healthy"),
        _config(source_id="failed", source_key="failed", analyst_name="Failed"),
    ]
    with Session(engine) as db:
        db.add_all(
            [
                ForecastSourceRun(
                    source_key="healthy",
                    analyst_name="Healthy",
                    started_at=now - timedelta(hours=1),
                    finished_at=now - timedelta(minutes=55),
                    status="success",
                    tables=1,
                    tickers_total=10,
                    tickers_mapped=10,
                    tickers_updated=1,
                    tickers_unchanged=9,
                    tickers_skipped=0,
                    table_created=False,
                ),
                ForecastSourceRun(
                    source_key="failed",
                    analyst_name="Failed",
                    started_at=now - timedelta(hours=1),
                    finished_at=now - timedelta(minutes=55),
                    status="failed",
                    tables=1,
                    tickers_total=0,
                    tickers_mapped=0,
                    tickers_updated=0,
                    tickers_unchanged=0,
                    tickers_skipped=0,
                    table_created=False,
                    error_message="boom",
                ),
            ]
        )
        db.commit()
        result = build_forecast_source_health(db, days=30, now=now, configs=configs)

    assert result.status == "failed"
    assert result.failed_sources == 1
    assert result.healthy_sources == 1
    assert [item.source_id for item in result.items] == ["failed", "healthy"]


def test_published_sheet_names_are_masked_in_public_configs(monkeypatch) -> None:
    monkeypatch.setenv("DOHOD_ENABLED", "false")
    monkeypatch.setenv("FINVISTA_ENABLED", "false")
    monkeypatch.setenv(
        "FORECAST_SHEETS_SOURCES_JSON",
        '[{"analyst_name":"Private Analyst","published_id":"abc","catalog_gid":"123"}]',
    )

    configs = load_forecast_source_health_configs()
    published = next(config for config in configs if config.source_key == "published-sheets")

    assert published.analyst_name == "Private Analyst"
    assert published.public_name == "Published Sheets #1"
    assert "Private Analyst" not in published.source_id
