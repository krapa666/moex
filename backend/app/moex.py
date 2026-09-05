from __future__ import annotations

import asyncio
import time
from datetime import date
from typing import Any

import httpx

MOEX_URL_TEMPLATE = (
    "https://iss.moex.com/iss/engines/stock/markets/shares/securities/{ticker}.json"
)
MOEX_DIVIDENDS_URL_TEMPLATE = "https://iss.moex.com/iss/securities/{ticker}/dividends.json"
CACHE_TTL_SECONDS = 30
MAX_RETRIES = 3
RETRY_DELAYS_SECONDS = (0.3, 0.8, 1.5)

_price_cache: dict[str, tuple[float | None, str | None, float]] = {}
_dividend_cache: dict[str, tuple[dict[str, float], float]] = {}


async def fetch_current_price(ticker: str) -> tuple[float | None, str | None]:
    normalized = ticker.strip().upper()
    if not normalized:
        return None, "Введите тикер"

    now = time.time()
    cached = _price_cache.get(normalized)
    if cached and now - cached[2] <= CACHE_TTL_SECONDS:
        return cached[0], cached[1]

    params = {
        "iss.meta": "off",
        "iss.only": "marketdata,securities",
        "marketdata.columns": "SECID,LAST,LCURRENTPRICE,MARKETPRICE,LEGALCLOSEPRICE",
        "securities.columns": "SECID,SHORTNAME,PREVPRICE",
    }

    url = MOEX_URL_TEMPLATE.format(ticker=normalized)
    payload: dict[str, Any] | None = None
    async with httpx.AsyncClient(timeout=10.0) as client:
        for attempt in range(MAX_RETRIES):
            try:
                response = await client.get(url, params=params)
                response.raise_for_status()
                payload = response.json()
                break
            except (httpx.TimeoutException, httpx.HTTPError, ValueError):
                if attempt >= MAX_RETRIES - 1:
                    _price_cache[normalized] = (None, "Не удалось получить цену от MOEX ISS", time.time())
                    return None, "Не удалось получить цену от MOEX ISS"
                await asyncio.sleep(RETRY_DELAYS_SECONDS[attempt])

    if payload is None:
        _price_cache[normalized] = (None, "Не удалось получить цену от MOEX ISS", time.time())
        return None, "Не удалось получить цену от MOEX ISS"

    marketdata = payload.get("marketdata", {})
    data = marketdata.get("data", [])
    securities = payload.get("securities", {})
    securities_data = securities.get("data", [])
    if not data and not securities_data:
        message = f"Тикер {normalized} не найден на MOEX"
        _price_cache[normalized] = (None, message, time.time())
        return None, message

    price = None
    used_fallback_price = False
    columns = marketdata.get("columns", [])
    if data:
        row = data[0]
        for price_column in ("LAST", "LCURRENTPRICE", "MARKETPRICE", "LEGALCLOSEPRICE"):
            if price_column in columns:
                candidate = row[columns.index(price_column)]
                if candidate is not None:
                    price = candidate
                    break

    if price is None and securities_data:
        sec_columns = securities.get("columns", [])
        sec_row = securities_data[0]
        for price_column in ("PREVPRICE",):
            if price_column in sec_columns:
                candidate = sec_row[sec_columns.index(price_column)]
                if candidate is not None:
                    price = candidate
                    used_fallback_price = True
                    break

    if price is None:
        message = f"Нет доступной текущей цены для {normalized}"
        _price_cache[normalized] = (None, message, time.time())
        return None, message

    status_message = "Использована последняя доступная цена (PREVPRICE)" if used_fallback_price else None
    result = (float(price), status_message)
    _price_cache[normalized] = (result[0], result[1], time.time())
    return result


async def fetch_paid_dividends_by_year(ticker: str, *, as_of: date | None = None) -> dict[str, float]:
    """Return dividends whose registry close date has already passed, grouped by year."""

    normalized = ticker.strip().upper()
    if not normalized:
        return {}

    cutoff = as_of or date.today()
    now = time.time()
    cached = _dividend_cache.get(normalized)
    if as_of is None and cached and now - cached[1] <= CACHE_TTL_SECONDS:
        return dict(cached[0])

    params = {
        "iss.meta": "off",
        "dividends.columns": "registryclosedate,value,currencyid",
        "limit": 100,
    }
    url = MOEX_DIVIDENDS_URL_TEMPLATE.format(ticker=normalized)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
    except (httpx.TimeoutException, httpx.HTTPError, ValueError):
        return {}

    block = payload.get("dividends", {})
    columns = block.get("columns", [])
    rows = block.get("data", [])
    if not rows or "registryclosedate" not in columns or "value" not in columns:
        return {}

    date_index = columns.index("registryclosedate")
    value_index = columns.index("value")
    currency_index = columns.index("currencyid") if "currencyid" in columns else None
    totals: dict[str, float] = {}

    for row in rows:
        raw_date = row[date_index]
        raw_value = row[value_index]
        if not raw_date or raw_value is None:
            continue
        if currency_index is not None and row[currency_index] not in (None, "RUB", "SUR"):
            continue
        try:
            registry_close = date.fromisoformat(str(raw_date))
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        if registry_close > cutoff:
            continue
        key = str(registry_close.year)
        totals[key] = totals.get(key, 0.0) + value

    if as_of is None:
        _dividend_cache[normalized] = (dict(totals), time.time())
    return totals
