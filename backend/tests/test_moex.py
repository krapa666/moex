import asyncio

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
    assert message is None
