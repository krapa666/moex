from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.volume_collector import _fetch_security_snapshot


@pytest.mark.asyncio
async def test_full_snapshot_fetches_history_and_current_market_data() -> None:
    moex = SimpleNamespace(
        fetch_history=AsyncMock(return_value=[{"trade_date": "history"}]),
        fetch_current=AsyncMock(return_value={"trade_date": "current"}),
    )

    history, current = await _fetch_security_snapshot(
        moex,
        "SBER",
        140,
        refresh_history=True,
    )

    assert history == [{"trade_date": "history"}]
    assert current == {"trade_date": "current"}
    moex.fetch_history.assert_awaited_once_with("SBER", 140)
    moex.fetch_current.assert_awaited_once_with("SBER")


@pytest.mark.asyncio
async def test_current_only_snapshot_skips_history_request() -> None:
    moex = SimpleNamespace(
        fetch_history=AsyncMock(),
        fetch_current=AsyncMock(return_value={"trade_date": "current"}),
    )

    history, current = await _fetch_security_snapshot(
        moex,
        "SBER",
        140,
        refresh_history=False,
    )

    assert history == []
    assert current == {"trade_date": "current"}
    moex.fetch_history.assert_not_awaited()
    moex.fetch_current.assert_awaited_once_with("SBER")
