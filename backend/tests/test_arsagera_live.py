import pytest
from app.arsagera_source import ArsageraClient


@pytest.mark.asyncio
async def test_live_arsagera_sber_smoke() -> None:
    client = ArsageraClient(timeout_seconds=30.0)
    mapping, errors = await client.fetch_catalog_mapping(["SBER"])
    assert not errors, errors
    assert mapping == {"SBER": "1342158761"}

    forecast = await client.fetch_forecast("SBER", mapping["SBER"])
    assert forecast.net_profit_billion_rub["2026"] == pytest.approx(1986.44809)
    assert forecast.net_profit_billion_rub["2029"] == pytest.approx(2704.642949)
    assert forecast.dividends_per_share_rub["2026"] == pytest.approx(43.76)
    assert forecast.dividends_per_share_rub["2029"] == pytest.approx(59.58)
