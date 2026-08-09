from unittest.mock import AsyncMock

import pytest
from app.volume_config import VolumeSettings
from app.volume_moex import VolumeMoexClient, VolumeMoexError, table_rows


def settings() -> VolumeSettings:
    return VolumeSettings.from_env()


def test_columns_are_mapped_to_values() -> None:
    payload = {"history": {"columns": ["SECID", "VALUE"], "data": [["SBER", 123.4]]}}

    assert table_rows(payload, "history") == [{"SECID": "SBER", "VALUE": 123.4}]


def test_missing_table_is_rejected() -> None:
    with pytest.raises(VolumeMoexError):
        table_rows({}, "history")


@pytest.mark.asyncio
async def test_closed_market_does_not_reuse_stale_turnover() -> None:
    client = VolumeMoexClient(settings())
    client._get = AsyncMock(
        return_value={
            "marketdata": {
                "columns": ["SECID", "VALTODAY", "TRADINGSTATUS", "SYSTIME"],
                "data": [["SBER", 999_000_000, "N", "2026-08-09 09:00:00"]],
            }
        }
    )
    try:
        assert await client.fetch_current("SBER") is None
    finally:
        await client._client.aclose()


@pytest.mark.asyncio
async def test_open_market_uses_moex_system_date() -> None:
    client = VolumeMoexClient(settings())
    client._get = AsyncMock(
        return_value={
            "marketdata": {
                "columns": [
                    "SECID",
                    "LAST",
                    "VALTODAY",
                    "VOLTODAY",
                    "TRADINGSTATUS",
                    "SYSTIME",
                ],
                "data": [["SBER", 300.5, 400_000_000, 1_500_000, "T", "2026-08-10 18:40:00"]],
            }
        }
    )
    try:
        result = await client.fetch_current("SBER")
        assert result is not None
        assert result["trade_date"].isoformat() == "2026-08-10"
    finally:
        await client._client.aclose()
