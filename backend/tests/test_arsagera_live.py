import pytest

from app.arsagera_source import ArsageraClient


@pytest.mark.asyncio
async def test_live_arsagera_sber_smoke() -> None:
    client = ArsageraClient(timeout_seconds=30.0)
    mapping, errors = await client.fetch_catalog_mapping(["SBER"])
    assert not errors, errors
    assert "SBER" in mapping, mapping

    forecast = await client.fetch_forecast("SBER", mapping["SBER"])
    assert forecast.net_profit_billion_rub, forecast
    assert forecast.dividends_per_share_rub, forecast
    print("ARSAGERA_LIVE", mapping["SBER"], forecast)
