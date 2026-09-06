from app.application import app
from app.forecast_api import list_consensus_backtest_observations
from fastapi import HTTPException
from starlette.requests import Request


def _request(scope: str | None) -> Request:
    headers = []
    if scope is not None:
        headers.append((b"x-moex-access-scope", scope.encode("ascii")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/analytics/consensus-backtest/observations",
            "headers": headers,
            "client": ("127.0.0.1", 12345),
            "server": ("backend", 8000),
            "scheme": "http",
            "query_string": b"",
        }
    )


def test_consensus_backtest_routes_are_registered() -> None:
    paths = {route.path for route in app.routes}
    assert "/api/analytics/consensus-backtest" in paths
    assert "/api/analytics/consensus-backtest/observations" in paths


def test_detailed_backtest_observations_require_local_scope() -> None:
    for scope in (None, "internet"):
        try:
            list_consensus_backtest_observations(
                request=_request(scope),
                snapshot="pre_year",
                min_sources=2,
                shrinkage_samples=5,
                error_floor_percent=5.0,
                relative_score_cap=2.0,
                ticker=None,
                fiscal_year=None,
                limit=200,
                db=None,  # access check runs before DB use
            )
        except HTTPException as exc:
            assert exc.status_code == 403
        else:
            raise AssertionError("detailed backtest leaked outside local scope")
