from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

MOEX_URL_TEMPLATE = (
    "https://iss.moex.com/iss/engines/stock/markets/shares/securities/{ticker}.json"
)
CACHE_TTL_SECONDS = 30
MAX_RETRIES = 3
RETRY_DELAYS_SECONDS = (0.3, 0.8, 1.5)
PREFERRED_BOARDS = ("TQBR", "TQTF", "TQIF", "TQPI", "TQTD", "SPEQ")
LIVE_PRICE_COLUMNS = ("LAST", "LCURRENTPRICE")

_price_cache: dict[str, tuple[float | None, str | None, float]] = {}


def _ordered_rows(rows: list[list[Any]], columns: list[str]) -> list[list[Any]]:
    if "BOARDID" not in columns:
        return rows
    board_index = columns.index("BOARDID")
    board_rank = {board: index for index, board in enumerate(PREFERRED_BOARDS)}
    return sorted(rows, key=lambda row: board_rank.get(str(row[board_index]), len(board_rank)))


def _first_price(payload: dict[str, Any], section_name: str, price_columns: tuple[str, ...]) -> float | None:
    section = payload.get(section_name, {})
    columns = section.get("columns", [])
    rows = section.get("data", [])
    if not isinstance(columns, list) or not isinstance(rows, list):
        return None

    for row in _ordered_rows(rows, columns):
        for price_column in price_columns:
            if price_column not in columns:
                continue
            candidate = row[columns.index(price_column)]
            if candidate is not None:
                return float(candidate)
    return None


def _extract_live_price(payload: dict[str, Any]) -> float | None:
    return _first_price(payload, "marketdata", LIVE_PRICE_COLUMNS)


def _extract_close_price(payload: dict[str, Any]) -> float | None:
    market_close = _first_price(payload, "marketdata", ("LEGALCLOSEPRICE", "MARKETPRICE"))
    if market_close is not None:
        return market_close
    return _first_price(payload, "securities", ("PREVPRICE",))


def _has_security_data(payload: dict[str, Any]) -> bool:
    return bool(payload.get("marketdata", {}).get("data") or payload.get("securities", {}).get("data"))


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
        "marketdata.columns": "SECID,BOARDID,LAST,LCURRENTPRICE,MARKETPRICE,LEGALCLOSEPRICE",
        "securities.columns": "SECID,BOARDID,SHORTNAME,PREVPRICE",
    }

    url = MOEX_URL_TEMPLATE.format(ticker=normalized)
    last_payload: dict[str, Any] | None = None
    async with httpx.AsyncClient(timeout=10.0) as client:
        for attempt in range(MAX_RETRIES):
            try:
                response = await client.get(url, params=params)
                response.raise_for_status()
                payload = response.json()
            except (httpx.TimeoutException, httpx.HTTPError, ValueError):
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAYS_SECONDS[attempt])
                continue

            if not _has_security_data(payload):
                message = f"Тикер {normalized} не найден на MOEX"
                _price_cache[normalized] = (None, message, time.time())
                return None, message

            last_payload = payload
            live_price = _extract_live_price(payload)
            if live_price is not None:
                result = (live_price, None)
                _price_cache[normalized] = (result[0], result[1], time.time())
                return result

            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAYS_SECONDS[attempt])

    if last_payload is not None:
        close_price = _extract_close_price(last_payload)
        if close_price is not None:
            message = "Использована цена закрытия прошлой торговой сессии после 3 неудачных попыток обновления"
            result = (close_price, message)
            _price_cache[normalized] = (result[0], result[1], time.time())
            return result

    message = f"Нет доступной текущей цены для {normalized}"
    _price_cache[normalized] = (None, message, time.time())
    return None, message
