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


@pytest.mark.asyncio
async def test_tqbr_universe_keeps_only_active_common_and_preferred_shares() -> None:
    client = VolumeMoexClient(settings())
    client._get = AsyncMock(
        return_value={
            "securities": {
                "columns": ["SECID", "SHORTNAME", "STATUS", "SECTYPE"],
                "data": [
                    ["SBER", "Сбербанк", "A", "1"],
                    ["SBERP", "Сбербанк-п", "A", "2"],
                    ["AGRO", "Русагро-гдр", "A", "3"],
                    ["OLD", "Не торгуется", "N", "1"],
                ],
            }
        }
    )
    try:
        assert await client.fetch_tqbr_equities() == [
            {"ticker": "SBER", "short_name": "Сбербанк", "security_type": "common"},
            {"ticker": "SBERP", "short_name": "Сбербанк-п", "security_type": "preferred"},
        ]
    finally:
        await client._client.aclose()
