from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Iterable

import httpx

from .arsagera_source import MAX_RETRIES, REQUEST_TIMEOUT_SECONDS, RETRY_DELAYS_SECONDS
from .forecast_source_sync import ForecastSyncResult, sync_forecast_source_once

DOHOD_BASE_URL = "https://www.dohod.ru/ik/analytics/dividend"
DEFAULT_ANALYST_NAME = "ДОХОДЪ"
DEFAULT_CONCURRENCY = 4
_DATE_RE = re.compile(r"(?<!\d)(\d{2})\.(\d{2})\.(20\d{2})(?!\d)")
_SLUG_RE = re.compile(r"/ik/analytics/dividend/([a-z0-9_-]+)(?:[/?#]|$)", re.IGNORECASE)


@dataclass(frozen=True)
class DohodForecast:
    ticker: str
    source_ref: str
    net_profit_billion_rub: dict[str, float]
    dividends_per_share_rub: dict[str, float]


class DohodParseError(ValueError):
    pass


class _CatalogParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.slugs: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href") or ""
        match = _SLUG_RE.search(href)
        if match:
            self.slugs.add(match.group(1).lower())


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._in_row = False
        self._in_cell = False
        self._cells: list[str] = []
        self._cell_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._in_row = True
            self._cells = []
            return
        if self._in_row and tag in {"td", "th"}:
            self._in_cell = True
            self._cell_text = []
            return
        if self._in_cell and tag == "br":
            self._cell_text.append(" ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._in_cell and tag == "img":
            alt = dict(attrs).get("alt") or ""
            if alt:
                self._cell_text.append(f" {alt} ")

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._in_cell:
            text = " ".join("".join(self._cell_text).replace("\u00a0", " ").split())
            self._cells.append(text)
            self._in_cell = False
            self._cell_text = []
            return
        if tag == "tr" and self._in_row:
            if self._cells:
                self.rows.append(self._cells)
            self._in_row = False
            self._cells = []
            self._in_cell = False
            self._cell_text = []


def _normalize_aliases(value: object) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("DOHOD_TICKER_ALIASES_JSON must be a JSON object")
    aliases: dict[str, str] = {}
    for raw_ticker, raw_slug in value.items():
        ticker = str(raw_ticker).strip().upper()
        slug = str(raw_slug).strip().lower()
        if not ticker or not slug:
            raise ValueError("DOHOD ticker aliases must not contain empty keys or values")
        if not re.fullmatch(r"[a-z0-9_-]+", slug):
            raise ValueError(f"invalid DOHOD slug for {ticker}: {slug}")
        aliases[ticker] = slug
    return aliases


def load_dohod_aliases(raw: str | None = None) -> dict[str, str]:
    payload = raw if raw is not None else os.getenv("DOHOD_TICKER_ALIASES_JSON", "{}")
    try:
        data = json.loads(payload or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"DOHOD_TICKER_ALIASES_JSON is not valid JSON: {exc.msg}") from exc
    return _normalize_aliases(data)


def parse_dohod_catalog_slugs(
    html: str,
    tickers: Iterable[str],
    *,
    aliases: dict[str, str] | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    parser = _CatalogParser()
    parser.feed(html)
    normalized_aliases = {
        str(ticker).strip().upper(): str(slug).strip().lower()
        for ticker, slug in (aliases or {}).items()
    }
    wanted = {ticker.strip().upper() for ticker in tickers if ticker.strip()}
    found: dict[str, str] = {}
    errors: dict[str, str] = {}
    for ticker in sorted(wanted):
        slug = normalized_aliases.get(ticker, ticker.lower())
        if slug in parser.slugs:
            found[ticker] = slug
        else:
            errors[ticker] = "тикер не найден в каталоге дивидендов ДОХОДЪ"
    return found, errors


def _parse_number(value: str) -> float | None:
    text = value.replace("\u00a0", " ").strip().replace(" ", "").replace(",", ".")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _registry_year(value: str) -> int | None:
    match = _DATE_RE.search(value)
    if not match:
        return None
    try:
        datetime(int(match.group(3)), int(match.group(2)), int(match.group(1)))
    except ValueError:
        return None
    return int(match.group(3))


def _is_payment_header(row: list[str]) -> bool:
    normalized = " ".join(row).casefold()
    return (
        "дата объявления дивиденда" in normalized
        and "дата закрытия реестра" in normalized
        and "дивиденд" in normalized
    )


def parse_dohod_dividend_html(
    ticker: str,
    source_ref: str,
    html: str,
    *,
    current_year: int | None = None,
) -> DohodForecast:
    parser = _TableParser()
    parser.feed(html)
    if not any(_is_payment_header(row) for row in parser.rows):
        raise DohodParseError("не найдена таблица выплат дивидендов")

    effective_year = current_year or datetime.now(timezone.utc).year
    dividends: dict[str, float] = {}
    seen: set[tuple[str, str, str, float]] = set()

    for row in parser.rows:
        if len(row) < 4 or _is_payment_header(row):
            continue
        year = _registry_year(row[1])
        amount = _parse_number(row[3])
        if year is None or year < effective_year or amount is None or amount < 0:
            continue
        identity = (row[0], row[1], row[2], amount)
        if identity in seen:
            continue
        seen.add(identity)
        key = str(year)
        dividends[key] = dividends.get(key, 0.0) + amount

    return DohodForecast(
        ticker=ticker.strip().upper(),
        source_ref=source_ref,
        net_profit_billion_rub={},
        dividends_per_share_rub={year: round(value, 6) for year, value in dividends.items()},
    )


class DohodClient:
    def __init__(
        self,
        *,
        aliases: dict[str, str] | None = None,
        timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self.aliases = aliases or {}
        self.timeout_seconds = timeout_seconds

    async def _get_text(self, url: str) -> str:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; MOEX-Fair-Price/1.0; forecast sync)",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
        }
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            follow_redirects=True,
            headers=headers,
        ) as client:
            for attempt in range(MAX_RETRIES):
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    return response.text
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 404 or attempt >= MAX_RETRIES - 1:
                        raise
                    await asyncio.sleep(RETRY_DELAYS_SECONDS[attempt])
                except (httpx.TimeoutException, httpx.HTTPError):
                    if attempt >= MAX_RETRIES - 1:
                        raise
                    await asyncio.sleep(RETRY_DELAYS_SECONDS[attempt])
        raise RuntimeError("unreachable")

    async def fetch_catalog_mapping(
        self, tickers: Iterable[str]
    ) -> tuple[dict[str, str], dict[str, str]]:
        html = await self._get_text(DOHOD_BASE_URL)
        return parse_dohod_catalog_slugs(html, tickers, aliases=self.aliases)

    async def fetch_forecast(self, ticker: str, source_ref: str) -> DohodForecast:
        html = await self._get_text(f"{DOHOD_BASE_URL}/{source_ref}")
        return parse_dohod_dividend_html(ticker, source_ref, html)


async def sync_dohod_once(
    *,
    analyst_name: str | None = None,
    aliases: dict[str, str] | None = None,
    concurrency: int | None = None,
) -> ForecastSyncResult:
    target_name = (analyst_name or os.getenv("DOHOD_ANALYST_NAME", DEFAULT_ANALYST_NAME)).strip()
    effective_aliases = aliases if aliases is not None else load_dohod_aliases()
    effective_concurrency = concurrency or int(
        os.getenv("DOHOD_SYNC_CONCURRENCY", str(DEFAULT_CONCURRENCY))
    )
    return await sync_forecast_source_once(
        analyst_name=target_name,
        source_comment="ДОХОДЪ — автоматический прогноз дивидендов",
        changed_by="dohod-sync",
        client=DohodClient(aliases=effective_aliases),
        concurrency=effective_concurrency,
        create_table_if_missing=True,
        source_key="dohod",
    )
