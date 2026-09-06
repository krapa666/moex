from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Iterable

import httpx

from .arsagera_source import MAX_RETRIES, REQUEST_TIMEOUT_SECONDS, RETRY_DELAYS_SECONDS
from .forecast_source_sync import ForecastSyncResult, sync_forecast_source_once

FINVISTA_BASE_URL = "https://fin-vista.ru/stocks"
DEFAULT_ANALYST_NAME = "fin-vista (модель)"
DEFAULT_CONCURRENCY = 4
_YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
_SLUG_RE = re.compile(r"^[A-Z0-9_-]+$")
_NUMBER_RE = re.compile(r"[-+]?(?:\d{1,3}(?:[\s\u00a0]\d{3})+|\d+)(?:[.,]\d+)?")


@dataclass(frozen=True)
class FinVistaForecast:
    ticker: str
    source_ref: str
    net_profit_billion_rub: dict[str, float]
    dividends_per_share_rub: dict[str, float]


class FinVistaParseError(ValueError):
    pass


class _TablesParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self.text: list[str] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._in_cell = False
        self._cell_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._table = []
            return
        if tag == "tr" and self._table is not None:
            self._row = []
            return
        if tag in {"td", "th"} and self._row is not None:
            self._in_cell = True
            self._cell_text = []
            return
        if tag == "br" and self._in_cell:
            self._cell_text.append(" ")

    def handle_data(self, data: str) -> None:
        self.text.append(data)
        if self._in_cell:
            self._cell_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._in_cell and self._row is not None:
            text = _normalize_text("".join(self._cell_text))
            self._row.append(text)
            self._in_cell = False
            self._cell_text = []
            return
        if tag == "tr" and self._row is not None and self._table is not None:
            if any(cell for cell in self._row):
                self._table.append(self._row)
            self._row = None
            self._in_cell = False
            self._cell_text = []
            return
        if tag == "table" and self._table is not None:
            if self._table:
                self.tables.append(self._table)
            self._table = None
            self._row = None
            self._in_cell = False
            self._cell_text = []


def _normalize_text(value: str) -> str:
    return " ".join(value.replace("\u00a0", " ").split())


def _parse_first_number(value: str) -> float | None:
    text = _normalize_text(value)
    if not text or text in {"-", "—", "–", "н/д", "N/A", "NA"}:
        return None
    match = _NUMBER_RE.search(text)
    if not match:
        return None
    number = match.group(0).replace(" ", "").replace("\u00a0", "").replace(",", ".")
    try:
        return float(number)
    except ValueError:
        return None


def _forecast_columns(row: list[str]) -> dict[int, str]:
    columns: dict[int, str] = {}
    for index, cell in enumerate(row):
        normalized = cell.casefold()
        match = _YEAR_RE.search(normalized)
        if not match:
            continue
        if "прогноз" not in normalized and not re.search(r"(?:^|\s)20\d{2}\s*[пp](?:\s|$)", normalized):
            continue
        columns[index] = match.group(1)
    return columns


def _row_label(row: list[str]) -> str:
    return row[0].casefold() if row else ""


def _metric_values(
    tables: list[list[list[str]]],
    *,
    label_prefix: str,
    required: bool,
) -> dict[str, float]:
    candidates: list[dict[str, float]] = []
    wanted = label_prefix.casefold()

    for table in tables:
        for header_index, header in enumerate(table):
            columns = _forecast_columns(header)
            if not columns:
                continue
            for row in table[header_index + 1 :]:
                if not _row_label(row).startswith(wanted):
                    continue
                values: dict[str, float] = {}
                for column_index, year in columns.items():
                    if column_index >= len(row):
                        continue
                    number = _parse_first_number(row[column_index])
                    if number is not None:
                        values[year] = number
                if values:
                    candidates.append(values)

    if not candidates:
        if required:
            raise FinVistaParseError(f"не найдена прогнозная строка: {label_prefix}")
        return {}
    if len(candidates) != 1:
        raise FinVistaParseError(f"неоднозначная прогнозная строка: {label_prefix}")
    return candidates[0]


def _dividend_multiplier(page_text: str) -> float:
    normalized = page_text.casefold().replace("ё", "е")
    if "дивиденд на акцию и eps — в копейках" in normalized or "дивиденд на акцию и eps - в копейках" in normalized:
        return 0.01
    if "дивиденд на акцию и eps — в рублях" in normalized or "дивиденд на акцию и eps - в рублях" in normalized:
        return 1.0
    raise FinVistaParseError("не определены единицы измерения дивиденда на акцию")


def parse_finvista_prospect_html(
    ticker: str,
    source_ref: str,
    html: str,
) -> FinVistaForecast:
    parser = _TablesParser()
    parser.feed(html)
    page_text = _normalize_text(" ".join(parser.text))
    if "денежные суммы указаны в млрд рублей" not in page_text.casefold():
        raise FinVistaParseError("не подтверждены единицы измерения финансовых показателей")

    profit = _metric_values(
        parser.tables,
        label_prefix="чистая прибыль",
        required=True,
    )
    dividends = _metric_values(
        parser.tables,
        label_prefix="дивиденд на акцию",
        required=False,
    )
    if dividends:
        multiplier = _dividend_multiplier(page_text)
        dividends = {year: round(value * multiplier, 8) for year, value in dividends.items()}

    return FinVistaForecast(
        ticker=ticker.strip().upper(),
        source_ref=source_ref,
        net_profit_billion_rub=profit,
        dividends_per_share_rub=dividends,
    )


def _normalize_aliases(value: object) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("FINVISTA_TICKER_ALIASES_JSON must be a JSON object")
    aliases: dict[str, str] = {}
    for raw_ticker, raw_slug in value.items():
        ticker = str(raw_ticker).strip().upper()
        slug = str(raw_slug).strip().upper()
        if not ticker or not slug:
            raise ValueError("FINVISTA ticker aliases must not contain empty keys or values")
        if not _SLUG_RE.fullmatch(slug):
            raise ValueError(f"invalid fin-vista slug for {ticker}: {slug}")
        aliases[ticker] = slug
    return aliases


def load_finvista_aliases(raw: str | None = None) -> dict[str, str]:
    payload = raw if raw is not None else os.getenv("FINVISTA_TICKER_ALIASES_JSON", "{}")
    try:
        data = json.loads(payload or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"FINVISTA_TICKER_ALIASES_JSON is not valid JSON: {exc.msg}") from exc
    return _normalize_aliases(data)


class FinVistaClient:
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
                    if exc.response.status_code == 404:
                        raise FinVistaParseError("страница тикера не найдена у fin-vista") from exc
                    if attempt >= MAX_RETRIES - 1:
                        raise
                    await asyncio.sleep(RETRY_DELAYS_SECONDS[attempt])
                except (httpx.TimeoutException, httpx.HTTPError):
                    if attempt >= MAX_RETRIES - 1:
                        raise
                    await asyncio.sleep(RETRY_DELAYS_SECONDS[attempt])
        raise RuntimeError("unreachable")

    async def fetch_catalog_mapping(
        self,
        tickers: Iterable[str],
    ) -> tuple[dict[str, str], dict[str, str]]:
        mapping: dict[str, str] = {}
        errors: dict[str, str] = {}
        for raw_ticker in tickers:
            ticker = raw_ticker.strip().upper()
            if not ticker:
                continue
            slug = self.aliases.get(ticker, ticker)
            if not _SLUG_RE.fullmatch(slug):
                errors[ticker] = "некорректный ticker/slug для fin-vista"
                continue
            mapping[ticker] = slug
        return mapping, errors

    async def fetch_forecast(self, ticker: str, source_ref: str) -> FinVistaForecast:
        html = await self._get_text(f"{FINVISTA_BASE_URL}/{source_ref}/prospect")
        return parse_finvista_prospect_html(ticker, source_ref, html)


async def sync_finvista_once(
    *,
    analyst_name: str | None = None,
    aliases: dict[str, str] | None = None,
    concurrency: int | None = None,
) -> ForecastSyncResult:
    target_name = (analyst_name or os.getenv("FINVISTA_ANALYST_NAME", DEFAULT_ANALYST_NAME)).strip()
    effective_aliases = aliases if aliases is not None else load_finvista_aliases()
    effective_concurrency = concurrency or int(
        os.getenv("FINVISTA_SYNC_CONCURRENCY", str(DEFAULT_CONCURRENCY))
    )
    return await sync_forecast_source_once(
        analyst_name=target_name,
        source_comment="fin-vista — автоматическая модель календарных прогнозов",
        changed_by="finvista-sync",
        client=FinVistaClient(aliases=effective_aliases),
        concurrency=effective_concurrency,
        create_table_if_missing=True,
        source_key="fin-vista",
    )
