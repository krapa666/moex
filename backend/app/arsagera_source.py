from __future__ import annotations

import asyncio
import csv
import io
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Iterable
from urllib.parse import parse_qs, urlparse

import httpx

ARSAGERA_PUBLISHED_ID = (
    "2PACX-1vTBIiA52dEEVaEVkMt0UVTZQoW26EIzRLteUouQgsTAvtDSdbCh9iT4xrf8jJo6O-d9EbFVrfOXQ3Lz"
)
ARSAGERA_BASE_URL = f"https://docs.google.com/spreadsheets/d/e/{ARSAGERA_PUBLISHED_ID}"
ARSAGERA_CATALOG_GID = "790995554"
REQUEST_TIMEOUT_SECONDS = 20.0
MAX_RETRIES = 3
RETRY_DELAYS_SECONDS = (0.5, 1.5)
_YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
_SHEET_ITEM_RE = re.compile(r'items\.push\(\{name:\s*"([^"]+)"[^}]*?gid:\s*"(\d+)"')


@dataclass(frozen=True)
class ArsageraForecast:
    ticker: str
    gid: str
    net_profit_billion_rub: dict[str, float]
    dividends_per_share_rub: dict[str, float]


class ArsageraParseError(ValueError):
    pass


class _CatalogHTMLParser(HTMLParser):
    """Legacy fallback for catalogue pages that contain explicit sheet links."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[str, list[str]]] = []
        self._in_row = False
        self._text: list[str] = []
        self._gids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._in_row = True
            self._text = []
            self._gids = []
            return
        if not self._in_row or tag != "a":
            return
        href = dict(attrs).get("href") or ""
        gid = _extract_gid(href)
        if gid:
            self._gids.append(gid)

    def handle_data(self, data: str) -> None:
        if self._in_row:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "tr" or not self._in_row:
            return
        text = " ".join(part.strip() for part in self._text if part.strip())
        gids = list(dict.fromkeys(self._gids))
        self.rows.append((text, gids))
        self._in_row = False
        self._text = []
        self._gids = []


def _extract_gid(url: str) -> str | None:
    try:
        query = parse_qs(urlparse(url).query)
    except ValueError:
        return None
    gid = query.get("gid", [None])[0]
    return str(gid) if gid and str(gid).isdigit() else None


def _ticker_present(text: str, ticker: str) -> bool:
    normalized = text.upper()
    return re.search(rf"(?<![A-Z0-9]){re.escape(ticker.upper())}(?![A-Z0-9])", normalized) is not None


def _menu_sheet_candidates(html: str, wanted: set[str]) -> dict[str, list[str]]:
    candidates = {ticker: [] for ticker in wanted}
    for raw_name, gid in _SHEET_ITEM_RE.findall(html):
        name = raw_name.strip().upper()
        if name in candidates and gid != ARSAGERA_CATALOG_GID:
            candidates[name].append(gid)
    return candidates


def parse_catalog_gids(html: str, tickers: Iterable[str]) -> tuple[dict[str, str], dict[str, str]]:
    wanted = {ticker.strip().upper() for ticker in tickers if ticker.strip()}
    found: dict[str, str] = {}
    errors: dict[str, str] = {}

    # Google Published Sheets exposes the complete workbook tab list in the
    # page switcher's JavaScript as items.push({name: "SBER", ..., gid: "..."}).
    # This is more reliable than reading links from the visible catalogue tab.
    menu_candidates = _menu_sheet_candidates(html, wanted)

    parser = _CatalogHTMLParser()
    parser.feed(html)
    for ticker in sorted(wanted):
        candidates = list(menu_candidates.get(ticker, []))
        if not candidates:
            for text, gids in parser.rows:
                if not _ticker_present(text, ticker):
                    continue
                candidates.extend(gid for gid in gids if gid != ARSAGERA_CATALOG_GID)
        candidates = list(dict.fromkeys(candidates))
        if len(candidates) == 1:
            found[ticker] = candidates[0]
        elif not candidates:
            errors[ticker] = "тикер не найден среди листов Арсагеры"
        else:
            errors[ticker] = f"неоднозначное сопоставление листа: {', '.join(candidates)}"
    return found, errors


def _parse_number(value: str) -> float | None:
    text = value.strip().replace("\u00a0", "").replace(" ", "")
    if not text or text in {"-", "—", "–", "н/д", "N/A", "NA"}:
        return None
    if "%" in text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    text = text.replace(",", ".")
    text = re.sub(r"[^0-9.+-]", "", text)
    if not text or text in {"+", "-", "."}:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return -number if negative else number


def _year_columns(row: list[str]) -> dict[int, str]:
    result: dict[int, str] = {}
    for index, cell in enumerate(row):
        match = _YEAR_RE.search(cell)
        if match:
            result[index] = match.group(1)
    return result


def _nearest_year_columns(rows: list[list[str]], metric_row_index: int) -> dict[int, str]:
    candidates: list[tuple[int, dict[int, str]]] = []
    start = max(0, metric_row_index - 15)
    end = min(len(rows), metric_row_index + 4)
    for index in range(start, end):
        columns = _year_columns(rows[index])
        if len(columns) >= 2:
            candidates.append((abs(metric_row_index - index), columns))
    if not candidates:
        raise ArsageraParseError("не удалось определить прогнозные годы")
    candidates.sort(key=lambda item: (-len(item[1]), item[0]))
    return candidates[0][1]


def _row_label(row: list[str]) -> str:
    return " ".join(cell.strip() for cell in row if cell.strip()).lower()


def _select_metric_row(rows: list[list[str]], *, ticker: str, metric: str) -> int:
    scored: list[tuple[int, int]] = []
    for index, row in enumerate(rows):
        label = _row_label(row)
        if metric == "profit":
            if "чист" not in label or "прибыл" not in label:
                continue
            score = 10
            if "на акц" in label or "eps" in label or "%" in label:
                score -= 20
            if "млрд" in label or "млн" in label or "тыс" in label:
                score += 3
        else:
            if "дивид" not in label or "%" in label:
                continue
            score = 5
            if "акц" in label:
                score += 4
            if "руб" in label:
                score += 2
            if _ticker_present(label, ticker):
                score += 8
        if score > 0:
            scored.append((score, index))

    if not scored:
        name = "чистой прибыли" if metric == "profit" else "дивидендов"
        raise ArsageraParseError(f"не найдена строка {name}")
    scored.sort(reverse=True)
    best_score = scored[0][0]
    best = [index for score, index in scored if score == best_score]
    if len(best) != 1:
        name = "чистой прибыли" if metric == "profit" else "дивидендов"
        raise ArsageraParseError(f"неоднозначная строка {name}")
    return best[0]


def _profit_multiplier(rows: list[list[str]], metric_row_index: int) -> float:
    start = max(0, metric_row_index - 3)
    context = " ".join(_row_label(rows[index]) for index in range(start, metric_row_index + 1))
    if "млрд" in context:
        return 1.0
    if "млн" in context:
        return 0.001
    if "тыс" in context:
        return 0.000001
    raise ArsageraParseError("не определены единицы измерения чистой прибыли")


def _values_by_year(
    rows: list[list[str]],
    metric_row_index: int,
    *,
    multiplier: float = 1.0,
) -> dict[str, float]:
    columns = _nearest_year_columns(rows, metric_row_index)
    row = rows[metric_row_index]
    values: dict[str, float] = {}
    for column_index, year in columns.items():
        if column_index >= len(row):
            continue
        number = _parse_number(row[column_index])
        if number is not None:
            values[year] = number * multiplier
    if not values:
        raise ArsageraParseError("в прогнозной строке нет числовых значений по годам")
    return values


def parse_forecast_csv(ticker: str, gid: str, content: str) -> ArsageraForecast:
    rows = [list(row) for row in csv.reader(io.StringIO(content))]
    rows = [row for row in rows if any(cell.strip() for cell in row)]
    if not rows:
        raise ArsageraParseError("лист Арсагеры пуст")

    profit_row = _select_metric_row(rows, ticker=ticker, metric="profit")
    dividend_row = _select_metric_row(rows, ticker=ticker, metric="dividend")
    profit = _values_by_year(rows, profit_row, multiplier=_profit_multiplier(rows, profit_row))
    dividends = _values_by_year(rows, dividend_row)
    return ArsageraForecast(
        ticker=ticker.strip().upper(),
        gid=gid,
        net_profit_billion_rub=profit,
        dividends_per_share_rub=dividends,
    )


class ArsageraClient:
    def __init__(self, timeout_seconds: float = REQUEST_TIMEOUT_SECONDS) -> None:
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
        # Do not use single=true: the complete workbook page contains the
        # page-switcher metadata with every published sheet name and gid.
        url = f"{ARSAGERA_BASE_URL}/pubhtml?gid={ARSAGERA_CATALOG_GID}"
        html = await self._get_text(url)
        return parse_catalog_gids(html, tickers)

    async def fetch_forecast(self, ticker: str, gid: str) -> ArsageraForecast:
        url = f"{ARSAGERA_BASE_URL}/pub?gid={gid}&single=true&output=csv"
        content = await self._get_text(url)
        return parse_forecast_csv(ticker, gid, content)
