import asyncio
from datetime import date

from app import moex


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, payload):
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, _url, params=None):
        return _FakeResponse(self.payload)


def test_fetch_current_price_uses_prevprice_fallback(monkeypatch):
    payload = {
        "marketdata": {
            "columns": ["SECID", "LAST", "LCURRENTPRICE", "MARKETPRICE", "LEGALCLOSEPRICE"],
            "data": [["RENI", None, None, None, None]],
        },
        "securities": {
            "columns": ["SECID", "SHORTNAME", "PREVPRICE"],
            "data": [["RENI", "Renaissance Insurance", 95.45]],
        },
    }

    monkeypatch.setattr(moex.httpx, "AsyncClient", lambda timeout=10.0: _FakeClient(payload))

    price, message = asyncio.run(moex.fetch_current_price("reni"))

    assert price == 95.45
    assert message == "Использована последняя доступная цена (PREVPRICE)"


def test_fetch_paid_dividends_groups_only_passed_ruble_registry_dates(monkeypatch):
    payload = {
        "dividends": {
            "columns": ["registryclosedate", "value", "currencyid"],
            "data": [
                ["2026-07-15", 25.0, "RUB"],
                ["2026-10-15", 10.0, "RUB"],
                ["2025-07-15", 20.0, "RUB"],
                ["2026-06-01", 3.0, "USD"],
            ],
        }
    }
    monkeypatch.setattr(moex.httpx, "AsyncClient", lambda timeout=10.0: _FakeClient(payload))

    result = asyncio.run(
        moex.fetch_paid_dividends_by_year("SBER", as_of=date(2026, 9, 5))
    )

    assert result == {"2025": 20.0, "2026": 25.0}
