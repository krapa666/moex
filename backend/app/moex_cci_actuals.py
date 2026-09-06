from __future__ import annotations

import asyncio
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from zoneinfo import ZoneInfo

from .actual_result_sync import ActualSyncResult, sync_actual_profit_source_once

SOURCE_KEY = "moex-cci"
SOURCE_NAME = "MOEX CCI · МСФО"
ISS_BASE_URL = "https://iss.moex.com"
PASSPORT_URL = "https://passport.moex.com/authenticate"
_PERIOD_RE = re.compile(r"^(?P<year>\d{4})Y4Q$", re.IGNORECASE)
_MOSCOW = ZoneInfo("Europe/Moscow")


@dataclass(frozen=True)
class MoexCciSettings:
    enabled: bool
    username: str
    password: str
    interval_hours: float
    run_on_startup: bool
    years_back: int
    timeout_seconds: float
    concurrency: int

    @property
    def configured(self) -> bool:
        return bool(self.username and self.password)


@dataclass(frozen=True)
class MoexCciActualRecord:
    ticker: str
    fiscal_year: int
    net_profit_billion_rub: float
    source_name: str
    source_url: str | None
    source_comment: str | None
    reported_at: datetime | None


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_moex_cci_settings() -> MoexCciSettings:
    return MoexCciSettings(
        enabled=_env_bool("MOEX_CCI_ACTUALS_ENABLED", False),
        username=os.getenv("MOEX_CCI_USERNAME", "").strip(),
        password=os.getenv("MOEX_CCI_PASSWORD", "").strip(),
        interval_hours=max(float(os.getenv("MOEX_CCI_ACTUALS_SYNC_INTERVAL_HOURS", "24")), 1.0),
        run_on_startup=_env_bool("MOEX_CCI_ACTUALS_RUN_ON_STARTUP", False),
        years_back=max(1, min(int(os.getenv("MOEX_CCI_ACTUALS_YEARS_BACK", "5")), 20)),
        timeout_seconds=max(float(os.getenv("MOEX_CCI_TIMEOUT_SECONDS", "30")), 5.0),
        concurrency=max(1, min(int(os.getenv("MOEX_CCI_CONCURRENCY", "4")), 16)),
    )


def get_moex_cci_public_status() -> dict[str, object]:
    settings = get_moex_cci_settings()
    return {
        "source_key": SOURCE_KEY,
        "source_name": SOURCE_NAME,
        "enabled": settings.enabled,
        "configured": settings.configured,
        "interval_hours": settings.interval_hours,
        "run_on_startup": settings.run_on_startup,
        "years_back": settings.years_back,
    }


def _block_rows(payload: dict, required_columns: set[str]) -> list[dict[str, object]]:
    matches: list[list[dict[str, object]]] = []
    for block in payload.values():
        if not isinstance(block, dict):
            continue
        columns = block.get("columns")
        data = block.get("data")
        if not isinstance(columns, list) or not isinstance(data, list):
            continue
        names = [str(column) for column in columns]
        if not required_columns.issubset(set(names)):
            continue
        rows: list[dict[str, object]] = []
        for values in data:
            if isinstance(values, list):
                rows.append(dict(zip(names, values)))
        matches.append(rows)
    if not matches:
        raise ValueError(f"MOEX ISS response has no block with columns {sorted(required_columns)}")
    if len(matches) > 1:
        non_empty = [rows for rows in matches if rows]
        if len(non_empty) == 1:
            return non_empty[0]
        raise ValueError(f"MOEX ISS response has ambiguous blocks for {sorted(required_columns)}")
    return matches[0]


def _parse_moex_datetime(value: object) -> datetime | None:
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip()
    parsed: datetime | None = None
    for candidate in (text, text.replace(" ", "T")):
        try:
            parsed = datetime.fromisoformat(candidate)
            break
        except ValueError:
            continue
    if parsed is None:
        raise ValueError(f"unsupported MOEX datetime: {text}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_MOSCOW)
    return parsed.astimezone(timezone.utc)


def _annual_fiscal_year(period_code: object) -> int | None:
    match = _PERIOD_RE.fullmatch(str(period_code or "").strip())
    return int(match.group("year")) if match else None


def _scale_to_billion(scale_name: object) -> float:
    normalized = " ".join(str(scale_name or "").strip().lower().replace("ё", "е").split())
    if not normalized:
        raise ValueError("CCI report has no scale")
    if "миллиард" in normalized:
        return 1.0
    if "миллион" in normalized:
        return 1.0 / 1_000.0
    if "тысяч" in normalized:
        return 1.0 / 1_000_000.0
    if normalized in {"единицы", "единиц", "единица", "units", "unit"}:
        return 1.0 / 1_000_000_000.0
    raise ValueError(f"unsupported CCI scale: {scale_name}")


def _require_rub(currency_name: object) -> None:
    normalized = str(currency_name or "").strip().lower().replace(" ", "")
    if normalized in {"руб.", "руб", "rub", "rur", "₽"}:
        return
    raise ValueError(f"CCI report currency is not RUB: {currency_name}")


def _normalize_parameter_name(value: object) -> str:
    return " ".join(str(value or "").strip().lower().replace("ё", "е").split())


def _owner_profit_value(payload: dict) -> tuple[float, str]:
    rows = _block_rows(payload, {"parameter_name_short_ru", "value"})
    candidates: list[tuple[float, str]] = []
    for row in rows:
        name = str(row.get("parameter_name_short_ru") or "").strip()
        normalized = _normalize_parameter_name(name)
        if "чист" not in normalized or "прибыл" not in normalized:
            continue
        if "неконтрол" in normalized:
            continue
        if "собствен" not in normalized and "акционер" not in normalized:
            continue
        value = row.get("value")
        if value is None:
            continue
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError(f"CCI owner profit is not finite: {name}")
        candidates.append((numeric, name))
    if len(candidates) != 1:
        raise ValueError(f"expected one owner-attributable net-profit field, got {len(candidates)}")
    return candidates[0]


def _report_id(row: dict[str, object]) -> int:
    for key in ("report_id", "basis_type_report_id"):
        value = row.get(key)
        if value is not None:
            return int(value)
    raise ValueError("CCI report row has no report id")


def _select_annual_reports(
    rows: list[dict[str, object]],
    *,
    min_fiscal_year: int,
    current_year: int,
) -> dict[int, dict[str, object]]:
    selected: dict[int, dict[str, object]] = {}
    for row in rows:
        year = _annual_fiscal_year(row.get("period_code"))
        if year is None or year < min_fiscal_year or year > current_year:
            continue
        _require_rub(row.get("currency_name_short_ru"))
        _scale_to_billion(row.get("scale_name_short_ru"))
        publication = _parse_moex_datetime(row.get("report_publicate_date")) or datetime.min.replace(
            tzinfo=timezone.utc
        )
        previous = selected.get(year)
        if previous is None:
            selected[year] = row
            continue
        previous_publication = _parse_moex_datetime(previous.get("report_publicate_date")) or datetime.min.replace(
            tzinfo=timezone.utc
        )
        if publication >= previous_publication:
            selected[year] = row
    return selected


class MoexCciClient:
    def __init__(self, settings: MoexCciSettings | None = None) -> None:
        self.settings = settings or get_moex_cci_settings()
        self._client: httpx.AsyncClient | None = None
        self._authenticated = False

    async def __aenter__(self) -> "MoexCciClient":
        self._client = httpx.AsyncClient(
            timeout=self.settings.timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "moex-fair-price/actuals"},
        )
        return self

    async def __aexit__(self, *_args: object) -> None:
        if self._client is not None:
            await self._client.aclose()
        self._client = None
        self._authenticated = False

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("MoexCciClient must be used as an async context manager")
        return self._client

    async def _authenticate(self) -> None:
        if self._authenticated:
            return
        if not self.settings.configured:
            raise RuntimeError("MOEX CCI credentials are not configured")
        response = await self.client.get(
            PASSPORT_URL,
            auth=httpx.BasicAuth(self.settings.username, self.settings.password),
        )
        response.raise_for_status()
        if "MicexPassportCert" not in self.client.cookies:
            raise RuntimeError("MOEX Passport did not issue MicexPassportCert")
        self._authenticated = True

    async def _get_json(
        self,
        path: str,
        *,
        params: dict[str, object] | None = None,
        cci: bool = False,
    ) -> dict:
        if cci:
            await self._authenticate()
        response = await self.client.get(f"{ISS_BASE_URL}{path}", params=params)
        response.raise_for_status()
        if cci:
            marker = (response.headers.get("X-MicexPassport-Marker") or "").strip().lower()
            if marker == "denied":
                raise PermissionError("MOEX CCI access denied for this account/subscription")
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("MOEX ISS returned a non-object JSON payload")
        return payload

    async def _ticker_inn(self, ticker: str) -> str:
        payload = await self._get_json(
            f"/iss/securities/{ticker}.json",
            params={"iss.meta": "off"},
        )
        try:
            rows = _block_rows(payload, {"name", "value"})
            for row in rows:
                if str(row.get("name") or "").strip().lower() == "emitent_inn":
                    inn = str(row.get("value") or "").strip()
                    if inn:
                        return inn
        except ValueError:
            pass

        payload = await self._get_json(
            "/iss/securities.json",
            params={"iss.meta": "off", "q": ticker},
        )
        rows = _block_rows(payload, {"secid", "emitent_inn"})
        matches = [
            str(row.get("emitent_inn") or "").strip()
            for row in rows
            if str(row.get("secid") or "").strip().upper() == ticker.upper()
            and str(row.get("emitent_inn") or "").strip()
        ]
        if len(set(matches)) != 1:
            raise ValueError(f"MOEX ISS could not uniquely map {ticker} to issuer INN")
        return matches[0]

    async def _company_id(self, inn: str) -> int:
        payload = await self._get_json(
            "/iss/cci/info/companies.json",
            params={"iss.meta": "off", "q": inn},
            cci=True,
        )
        rows = _block_rows(payload, {"basis_company_id", "inn"})
        matches = [row for row in rows if str(row.get("inn") or "").strip() == inn]
        if len(matches) != 1:
            raise ValueError(f"CCI company lookup for INN {inn} returned {len(matches)} exact matches")
        return int(matches[0]["basis_company_id"])

    async def _ticker_actuals(
        self,
        ticker: str,
        *,
        min_fiscal_year: int,
    ) -> list[MoexCciActualRecord]:
        inn = await self._ticker_inn(ticker)
        company_id = await self._company_id(inn)
        payload = await self._get_json(
            f"/iss/cci/accounting/msfo-short/companies/{company_id}/reports.json",
            params={"iss.meta": "off"},
            cci=True,
        )
        report_rows = _block_rows(
            payload,
            {"period_code", "scale_name_short_ru", "currency_name_short_ru"},
        )
        selected = _select_annual_reports(
            report_rows,
            min_fiscal_year=min_fiscal_year,
            current_year=datetime.now(timezone.utc).year,
        )
        records: list[MoexCciActualRecord] = []
        for year, report in sorted(selected.items()):
            report_id = _report_id(report)
            detail_path = f"/iss/cci/accounting/msfo-short/reports/{report_id}.json"
            detail = await self._get_json(detail_path, params={"iss.meta": "off"}, cci=True)
            value, parameter_name = _owner_profit_value(detail)
            factor = _scale_to_billion(report.get("scale_name_short_ru"))
            _require_rub(report.get("currency_name_short_ru"))
            audited = bool(report.get("audited"))
            records.append(
                MoexCciActualRecord(
                    ticker=ticker,
                    fiscal_year=year,
                    net_profit_billion_rub=value * factor,
                    source_name=SOURCE_NAME,
                    source_url=f"{ISS_BASE_URL}{detail_path}",
                    source_comment=(
                        f"Краткое МСФО; {parameter_name}; "
                        f"масштаб: {report.get('scale_name_short_ru')}; "
                        f"аудировано: {'да' if audited else 'нет'}"
                    ),
                    reported_at=_parse_moex_datetime(report.get("report_publicate_date")),
                )
            )
        if not records:
            raise ValueError(f"CCI has no eligible annual RUB IFRS reports for {ticker}")
        return records

    async def fetch_actuals(
        self,
        tickers: list[str],
        *,
        min_fiscal_year: int,
    ) -> tuple[list[MoexCciActualRecord], dict[str, str]]:
        semaphore = asyncio.Semaphore(self.settings.concurrency)
        records: list[MoexCciActualRecord] = []
        errors: dict[str, str] = {}

        async def fetch_one(ticker: str) -> None:
            normalized = ticker.strip().upper()
            if not normalized:
                return
            async with semaphore:
                try:
                    records.extend(
                        await self._ticker_actuals(normalized, min_fiscal_year=min_fiscal_year)
                    )
                except Exception as exc:
                    errors[normalized] = str(exc) or exc.__class__.__name__

        await asyncio.gather(*(fetch_one(ticker) for ticker in tickers))
        return records, errors


async def sync_moex_cci_actuals_once() -> ActualSyncResult:
    settings = get_moex_cci_settings()
    if not settings.enabled:
        raise RuntimeError("MOEX CCI actual-result sync is disabled")
    if not settings.configured:
        raise RuntimeError("MOEX CCI credentials are not configured")
    async with MoexCciClient(settings) as client:
        return await sync_actual_profit_source_once(
            source_key=SOURCE_KEY,
            client=client,
            years_back=settings.years_back,
        )
