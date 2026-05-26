from datetime import datetime, timedelta, timezone

import pytest

from app.models import StockRow
from app.services import refresh_row_price


@pytest.mark.asyncio
async def test_refresh_row_price_keeps_recent_last_price_when_moex_unavailable(monkeypatch):
    row = StockRow(ticker="SBER", current_price=250.0)
    row.price_updated_at = datetime.now(timezone.utc) - timedelta(minutes=20)

    async def fake_fetch(_ticker: str):
        return None, "Не удалось получить цену от MOEX ISS"

    monkeypatch.setattr("app.services.fetch_current_price", fake_fetch)

    await refresh_row_price(row, force=True)

    assert row.current_price == 250.0
    assert row.status_message == "MOEX временно недоступна, используем последнюю сохранённую цену"


@pytest.mark.asyncio
async def test_refresh_row_price_clears_too_old_price_when_moex_unavailable(monkeypatch):
    row = StockRow(ticker="SBER", current_price=250.0)
    row.price_updated_at = datetime.now(timezone.utc) - timedelta(days=2)

    async def fake_fetch(_ticker: str):
        return None, "Не удалось получить цену от MOEX ISS"

    monkeypatch.setattr("app.services.fetch_current_price", fake_fetch)

    await refresh_row_price(row, force=True)

    assert row.current_price is None
    assert row.status_message == "Не удалось получить цену от MOEX ISS"
