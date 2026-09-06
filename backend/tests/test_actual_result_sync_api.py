import pytest
from app import forecast_api
from app.actual_result_sync import ActualSyncResult
from app.application import app
from fastapi import HTTPException
from starlette.requests import Request


def _request(scope: str | None) -> Request:
    headers = []
    if scope is not None:
        headers.append((b"x-moex-access-scope", scope.encode("ascii")))
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/analytics/actual-net-profits/sync",
            "headers": headers,
            "client": ("127.0.0.1", 12345),
            "server": ("backend", 8000),
            "scheme": "http",
            "query_string": b"",
        }
    )


def test_application_registers_actual_sync_routes() -> None:
    paths = {route.path for route in app.routes}
    assert "/api/analytics/actual-net-profits/sync-status" in paths
    assert "/api/analytics/actual-net-profits/sync" in paths


@pytest.mark.asyncio
async def test_actual_sync_requires_local_scope(monkeypatch) -> None:
    monkeypatch.setattr(
        forecast_api,
        "get_moex_cci_public_status",
        lambda: {"enabled": True, "configured": True},
    )

    with pytest.raises(HTTPException) as exc_info:
        await forecast_api.sync_actual_net_profits(_request("internet"))

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_actual_sync_rejects_disabled_source(monkeypatch) -> None:
    monkeypatch.setattr(
        forecast_api,
        "get_moex_cci_public_status",
        lambda: {"enabled": False, "configured": False},
    )

    with pytest.raises(HTTPException) as exc_info:
        await forecast_api.sync_actual_net_profits(_request("local"))

    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_actual_sync_returns_result_when_configured(monkeypatch) -> None:
    monkeypatch.setattr(
        forecast_api,
        "get_moex_cci_public_status",
        lambda: {"enabled": True, "configured": True},
    )

    async def fake_sync() -> ActualSyncResult:
        return ActualSyncResult(
            tickers_total=2,
            tickers_mapped=2,
            records_found=3,
            records_created=2,
            records_updated=1,
            records_unchanged=0,
            records_protected=0,
            tickers_skipped=0,
            errors={},
        )

    monkeypatch.setattr(forecast_api, "sync_moex_cci_actuals_once", fake_sync)

    result = await forecast_api.sync_actual_net_profits(_request("local"))

    assert result.records_created == 2
    assert result.records_updated == 1
