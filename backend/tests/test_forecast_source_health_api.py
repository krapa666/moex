from datetime import datetime, timezone

from app.application import app
from app.forecast_source_health import ForecastSourceHealthItem
from app.forecast_source_health_api import ForecastSourceHealthItemRead
from fastapi.testclient import TestClient


def test_forecast_source_health_routes_are_registered() -> None:
    paths = {route.path for route in app.routes}
    assert "/api/dashboard/source-health" in paths
    assert "/api/dashboard/source-health/details" in paths


def test_source_health_details_require_explicit_local_scope() -> None:
    client = TestClient(app)
    response = client.get("/api/dashboard/source-health/details")
    assert response.status_code == 403


def test_public_source_health_schema_does_not_expose_private_identity_or_errors() -> None:
    item = ForecastSourceHealthItem(
        source_id="published-sheets:abc",
        source_key="published-sheets",
        display_name="Published Sheets #1",
        analyst_name="Private Analyst",
        expected_interval_hours=6.0,
        status="failed",
        reasons=["latest_run_failed"],
        run_in_progress=False,
        latest_run_status="failed",
        last_run_at=datetime(2026, 9, 6, tzinfo=timezone.utc),
        last_completed_at=datetime(2026, 9, 6, tzinfo=timezone.utc),
        last_success_at=None,
        latest_age_hours=1.0,
        coverage_percent=None,
        baseline_coverage_percent=None,
        coverage_change_pp=None,
        coverage_baseline_runs=0,
        tickers_total=0,
        tickers_mapped=0,
        tickers_updated=0,
        tickers_unchanged=0,
        tickers_skipped=0,
        runs_in_window=1,
        success_runs=0,
        partial_runs=0,
        failed_runs=1,
        consecutive_successes=0,
        consecutive_failures=1,
        latest_error_kind="sync_exception",
        latest_error_count=1,
        latest_error_message="secret upstream detail",
        latest_error_details={"SBER": "private detail"},
    )

    public_payload = ForecastSourceHealthItemRead.model_validate(item).model_dump()

    assert public_payload["display_name"] == "Published Sheets #1"
    assert "analyst_name" not in public_payload
    assert "latest_error_message" not in public_payload
    assert "latest_error_details" not in public_payload
