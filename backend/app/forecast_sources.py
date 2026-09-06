from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from typing import Iterable

import httpx

from .arsagera_source import (
    MAX_RETRIES,
    REQUEST_TIMEOUT_SECONDS,
    RETRY_DELAYS_SECONDS,
    ArsageraForecast,
    parse_forecast_csv,
)
from .forecast_source_sync import ForecastSyncResult, sync_forecast_source_once

DEFAULT_CONCURRENCY = 4
_SHEET_ITEM_RE = re.compile(r'items\.push\(\{name:\s*"([^"]+)"[^}]*?gid:\s*"(\d+)"')


@dataclass(frozen=True)
class PublishedSheetsSourceConfig:
    analyst_name: str
    published_id: str
    catalog_gid: str
    sheet_aliases: dict[str, str] = field(default_factory=dict)

    @property
    def source_comment(self) -> str:
        return f"{self.analyst_name} — автоматическая синхронизация"

    def build_client(self) -> PublishedSheetsClient:
        return PublishedSheetsClient(
            published_id=self.published_id,
            catalog_gid=self.catalog_gid,
            sheet_aliases=self.sheet_aliases,
        )


def parse_published_catalog_gids(
    html: str,
    tickers: Iterable[str],
    *,
    catalog_gid: str,
    sheet_aliases: dict[str, str] | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Map MOEX tickers to tab gids from Google Published Sheets page metadata."""
    aliases = {
        str(ticker).strip().upper(): str(sheet).strip().upper()
        for ticker, sheet in (sheet_aliases or {}).items()
    }
    wanted = {ticker.strip().upper() for ticker in tickers if ticker.strip()}
    candidates: dict[str, list[str]] = {ticker: [] for ticker in wanted}

    for raw_name, gid in _SHEET_ITEM_RE.findall(html):
        if gid == catalog_gid:
            continue
        sheet_name = raw_name.strip().upper()
        for ticker in wanted:
            if sheet_name == aliases.get(ticker, ticker):
                candidates[ticker].append(gid)

    found: dict[str, str] = {}
    errors: dict[str, str] = {}
    for ticker in sorted(wanted):
        gids = list(dict.fromkeys(candidates[ticker]))
        if len(gids) == 1:
            found[ticker] = gids[0]
        elif not gids:
            errors[ticker] = "тикер не найден среди листов опубликованной таблицы"
        else:
            errors[ticker] = f"неоднозначное сопоставление листа: {', '.join(gids)}"
    return found, errors


class PublishedSheetsClient:
    """Read a published Google workbook whose forecast tabs are named by ticker."""

    def __init__(
        self,
        *,
        published_id: str,
        catalog_gid: str,
        sheet_aliases: dict[str, str] | None = None,
        timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url = f"https://docs.google.com/spreadsheets/d/e/{published_id}"
        self.catalog_gid = catalog_gid
        self.sheet_aliases = {
            str(ticker).strip().upper(): str(sheet).strip().upper()
            for ticker, sheet in (sheet_aliases or {}).items()
        }
        self.timeout_seconds = timeout_seconds

    async def _get_text(self, url: str) -> str:
        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True) as client:
            for attempt in range(MAX_RETRIES):
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    return response.text
                except (httpx.TimeoutException, httpx.HTTPError):
                    if attempt >= MAX_RETRIES - 1:
                        raise
                    await asyncio.sleep(RETRY_DELAYS_SECONDS[attempt])
        raise RuntimeError("unreachable")

    async def fetch_catalog_mapping(
        self, tickers: Iterable[str]
    ) -> tuple[dict[str, str], dict[str, str]]:
        url = f"{self.base_url}/pubhtml?gid={self.catalog_gid}"
        html = await self._get_text(url)
        return parse_published_catalog_gids(
            html,
            tickers,
            catalog_gid=self.catalog_gid,
            sheet_aliases=self.sheet_aliases,
        )

    async def fetch_forecast(self, ticker: str, gid: str) -> ArsageraForecast:
        url = f"{self.base_url}/pub?gid={gid}&single=true&output=csv"
        content = await self._get_text(url)
        return parse_forecast_csv(ticker, gid, content)


def _normalize_aliases(value: object) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("sheet_aliases must be an object")
    aliases: dict[str, str] = {}
    for raw_ticker, raw_sheet in value.items():
        ticker = str(raw_ticker).strip().upper()
        sheet = str(raw_sheet).strip().upper()
        if not ticker or not sheet:
            raise ValueError("sheet_aliases keys and values must not be empty")
        aliases[ticker] = sheet
    return aliases


def load_published_sheets_sources(raw: str | None = None) -> list[PublishedSheetsSourceConfig]:
    payload = raw if raw is not None else os.getenv("FORECAST_SHEETS_SOURCES_JSON", "[]")
    try:
        data = json.loads(payload or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError(f"FORECAST_SHEETS_SOURCES_JSON is not valid JSON: {exc.msg}") from exc
    if not isinstance(data, list):
        raise ValueError("FORECAST_SHEETS_SOURCES_JSON must be a JSON array")

    sources: list[PublishedSheetsSourceConfig] = []
    seen_names: set[str] = set()
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"source #{index + 1} must be an object")
        analyst_name = str(item.get("analyst_name") or "").strip()
        published_id = str(item.get("published_id") or "").strip()
        catalog_gid = str(item.get("catalog_gid") or "").strip()
        if not analyst_name or not published_id or not catalog_gid:
            raise ValueError(
                f"source #{index + 1} requires analyst_name, published_id and catalog_gid"
            )
        if not catalog_gid.isdigit():
            raise ValueError(f"source #{index + 1} catalog_gid must contain digits only")
        name_key = analyst_name.casefold()
        if name_key in seen_names:
            raise ValueError(f"duplicate analyst_name: {analyst_name}")
        seen_names.add(name_key)
        sources.append(
            PublishedSheetsSourceConfig(
                analyst_name=analyst_name,
                published_id=published_id,
                catalog_gid=catalog_gid,
                sheet_aliases=_normalize_aliases(item.get("sheet_aliases")),
            )
        )
    return sources


async def sync_published_sheets_sources_once(
    *,
    sources: list[PublishedSheetsSourceConfig] | None = None,
    concurrency: int | None = None,
) -> dict[str, ForecastSyncResult]:
    source_configs = sources if sources is not None else load_published_sheets_sources()
    effective_concurrency = concurrency or int(
        os.getenv("FORECAST_SHEETS_SYNC_CONCURRENCY", str(DEFAULT_CONCURRENCY))
    )
    results: dict[str, ForecastSyncResult] = {}
    for config in source_configs:
        results[config.analyst_name] = await sync_forecast_source_once(
            analyst_name=config.analyst_name,
            source_comment=config.source_comment,
            changed_by="published-sheets-sync",
            client=config.build_client(),
            concurrency=effective_concurrency,
            create_table_if_missing=True,
            source_key="published-sheets",
        )
    return results
