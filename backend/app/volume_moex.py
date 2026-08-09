from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
from zoneinfo import ZoneInfo

from .volume_config import VolumeSettings


class VolumeMoexError(RuntimeError):
    pass


def table_rows(payload: dict[str, Any], table: str) -> list[dict[str, Any]]:
    block = payload.get(table)
    if not isinstance(block, dict):
        raise VolumeMoexError(f"MOEX response has no '{table}' table")
    columns = block.get("columns", [])
    data = block.get("data", [])
    if not isinstance(columns, list) or not isinstance(data, list):
        raise VolumeMoexError(f"Malformed MOEX '{table}' table")
    return [dict(zip(columns, row, strict=False)) for row in data]


class VolumeMoexClient:
    base_url = "https://iss.moex.com/iss"

    def __init__(self, settings: VolumeSettings):
        self.settings = settings
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=settings.moex_timeout_seconds,
            trust_env=False,
            headers={"User-Agent": "moex-integrated-volume-monitor/1.0", "Accept": "application/json"},
        )
        self._semaphore = asyncio.Semaphore(settings.moex_concurrency)

    async def __aenter__(self) -> "VolumeMoexClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                async with self._semaphore:
                    response = await self._client.get(path, params=params)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise VolumeMoexError("MOEX returned non-object JSON")
                return payload
            except (httpx.HTTPError, ValueError, VolumeMoexError) as exc:
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(0.5 * (2**attempt))
        raise VolumeMoexError(f"MOEX request failed: {path}: {last_error}") from last_error

    async def fetch_imoex_constituents(self) -> list[dict[str, Any]]:
        payload = await self._get(
            "/statistics/engines/stock/markets/index/analytics/IMOEX.json",
            {"iss.meta": "off", "iss.only": "analytics", "limit": 100},
        )
        rows = table_rows(payload, "analytics")
        normalized = [{str(key).lower(): value for key, value in row.items()} for row in rows]
        if not normalized:
            raise VolumeMoexError("IMOEX constituents table is empty")

        dates = [str(row.get("tradedate")) for row in normalized if row.get("tradedate")]
        latest_date = max(dates) if dates else None
        result: dict[str, dict[str, Any]] = {}
        for row in normalized:
            if latest_date and str(row.get("tradedate")) != latest_date:
                continue
            ticker = row.get("ticker") or row.get("secid")
            if not ticker:
                continue
            ticker = str(ticker).upper()
            result[ticker] = {
                "ticker": ticker,
                "short_name": str(row.get("shortnames") or row.get("shortname") or ticker),
                "weight": Decimal(str(row["weight"])) if row.get("weight") is not None else None,
            }
        if not result:
            raise VolumeMoexError("Could not extract tickers from IMOEX analytics")
        return sorted(result.values(), key=lambda item: item["ticker"])

    async def fetch_history(self, ticker: str, rows_needed: int) -> list[dict[str, Any]]:
        start = 0
        result: list[dict[str, Any]] = []
        today = datetime.now(ZoneInfo(self.settings.schedule_timezone)).date()
        date_from = today - timedelta(days=max(400, rows_needed * 3))
        path = f"/history/engines/stock/markets/shares/boards/TQBR/securities/{ticker}.json"
        while True:
            payload = await self._get(
                path,
                {
                    "iss.meta": "off",
                    "iss.only": "history",
                    "history.columns": "TRADEDATE,SECID,VALUE,VOLUME,CLOSE",
                    "from": date_from.isoformat(),
                    "start": start,
                    "limit": 100,
                },
            )
            page = table_rows(payload, "history")
            if not page:
                break
            result.extend(page)
            if len(page) < 100:
                break
            start += len(page)

        clean = []
        for row in result:
            if not row.get("TRADEDATE") or row.get("VALUE") is None:
                continue
            clean.append(
                {
                    "trade_date": date.fromisoformat(str(row["TRADEDATE"])),
                    "turnover_rub": Decimal(str(row["VALUE"])),
                    "volume_units": int(row["VOLUME"]) if row.get("VOLUME") is not None else None,
                    "close_price": Decimal(str(row["CLOSE"])) if row.get("CLOSE") is not None else None,
                }
            )
        clean.sort(key=lambda item: item["trade_date"])
        return clean[-rows_needed:]

    async def fetch_current(self, ticker: str) -> dict[str, Any] | None:
        path = f"/engines/stock/markets/shares/boards/TQBR/securities/{ticker}.json"
        payload = await self._get(
            path,
            {
                "iss.meta": "off",
                "iss.only": "marketdata",
                "marketdata.columns": (
                    "SECID,LAST,VALTODAY,VOLTODAY,UPDATETIME,SYSTIME,TRADINGSTATUS"
                ),
            },
        )
        rows = table_rows(payload, "marketdata")
        if not rows:
            return None
        row = rows[0]
        if row.get("TRADINGSTATUS") != "T":
            return None
        if row.get("VALTODAY") is None or Decimal(str(row["VALTODAY"])) <= 0:
            return None
        system_time = str(row.get("SYSTIME") or "")
        try:
            trade_date = date.fromisoformat(system_time[:10])
        except ValueError:
            trade_date = datetime.now(ZoneInfo(self.settings.schedule_timezone)).date()
        return {
            "trade_date": trade_date,
            "turnover_rub": Decimal(str(row["VALTODAY"])),
            "volume_units": int(row["VOLTODAY"]) if row.get("VOLTODAY") is not None else None,
            "close_price": Decimal(str(row["LAST"])) if row.get("LAST") is not None else None,
            "update_time": row.get("UPDATETIME") or row.get("SYSTIME"),
            "trading_status": row.get("TRADINGSTATUS"),
        }
