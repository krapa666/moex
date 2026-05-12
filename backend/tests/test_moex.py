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
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, _url, params=None):
        self.calls += 1
        return _FakeResponse(self.payload)


def _reset_cache():
    moex._price_cache.clear()


def test_fetch_current_price_prefers_live_tqbr_price(monkeypatch):
    _reset_cache()
    payload = {
        "marketdata": {
            "columns": ["SECID", "BOARDID", "LAST", "LCURRENTPRICE", "MARKETPRICE", "LEGALCLOSEPRICE"],
            "data": [
                ["HEAD", "SPEQ", None, None, 2907, None],
                ["HEAD", "TQBR", 2722, 2720, 2907, None],
            ],
        },
        "securities": {
            "columns": ["SECID", "BOARDID", "SHORTNAME", "PREVPRICE"],
            "data": [["HEAD", "TQBR", "Хэдхантер", 2905]],
        },
    }

    monkeypatch.setattr(moex.httpx, "AsyncClient", lambda timeout=10.0: _FakeClient(payload))

    price, message = asyncio.run(moex.fetch_current_price("head"))

    assert price == 2722
    assert message is None


def test_fetch_current_price_uses_prevprice_fallback_after_three_failed_live_attempts(monkeypatch):
    _reset_cache()
    payload = {
        "marketdata": {
            "columns": ["SECID", "BOARDID", "LAST", "LCURRENTPRICE", "MARKETPRICE", "LEGALCLOSEPRICE"],
            "data": [["RENI", "TQBR", None, None, None, None]],
        },
        "securities": {
            "columns": ["SECID", "BOARDID", "SHORTNAME", "PREVPRICE"],
            "data": [["RENI", "TQBR", "Renaissance Insurance", 95.45]],
        },
    }
    fake_client = _FakeClient(payload)

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(moex.httpx, "AsyncClient", lambda timeout=10.0: fake_client)
    monkeypatch.setattr(moex.asyncio, "sleep", no_sleep)

    price, message = asyncio.run(moex.fetch_current_price("reni"))

    assert fake_client.calls == 3
    assert price == 95.45
    assert message == "Использована цена закрытия прошлой торговой сессии после 3 неудачных попыток обновления"
