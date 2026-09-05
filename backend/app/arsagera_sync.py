from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select

from .arsagera_source import ArsageraClient, ArsageraForecast, ArsageraParseError
from .database import SessionLocal
from .main import apply_net_profit_projection
from .models import AnalystTable, StockRow

logger = logging.getLogger(__name__)
DEFAULT_ANALYST_NAME = "Арсагера"
DEFAULT_CONCURRENCY = 4
SOURCE_COMMENT = "Арсагера — автоматическая синхронизация"


@dataclass(frozen=True)
class ArsageraSyncResult:
    tables: int
    tickers_total: int
    tickers_mapped: int
    tickers_updated: int
    tickers_unchanged: int
    tickers_skipped: int
    errors: dict[str, str]


def _merge_future_values(existing: dict | None, incoming: dict[str, float]) -> tuple[dict[str, float | None], bool]:
    current_year = datetime.now(timezone.utc).year
    merged: dict[str, float | None] = dict(existing or {})
    changed = False
    for year, value in incoming.items():
        if not year.isdigit() or int(year) < current_year:
            continue
        old = merged.get(year)
        if old is None or abs(float(old) - float(value)) > 1e-9:
            merged[year] = float(value)
            changed = True
    return merged, changed


async def _fetch_forecasts(
    client: ArsageraClient,
    mapping: dict[str, str],
    concurrency: int,
) -> tuple[dict[str, ArsageraForecast], dict[str, str]]:
    semaphore = asyncio.Semaphore(max(1, concurrency))
    forecasts: dict[str, ArsageraForecast] = {}
    errors: dict[str, str] = {}

    async def fetch_one(ticker: str, gid: str) -> None:
        async with semaphore:
            try:
                forecasts[ticker] = await client.fetch_forecast(ticker, gid)
            except (ArsageraParseError, Exception) as exc:  # source errors are isolated per ticker
                errors[ticker] = str(exc) or exc.__class__.__name__

    await asyncio.gather(*(fetch_one(ticker, gid) for ticker, gid in mapping.items()))
    return forecasts, errors


async def sync_arsagera_once(
    *,
    analyst_name: str | None = None,
    concurrency: int | None = None,
    client: ArsageraClient | None = None,
) -> ArsageraSyncResult:
    target_name = (analyst_name or os.getenv("ARSAGERA_ANALYST_NAME") or DEFAULT_ANALYST_NAME).strip()
    concurrency = concurrency or int(os.getenv("ARSAGERA_SYNC_CONCURRENCY", str(DEFAULT_CONCURRENCY)))
    source = client or ArsageraClient()

    db = SessionLocal()
    try:
        tables = db.scalars(
            select(AnalystTable).where(func.lower(AnalystTable.analyst_name) == target_name.lower())
        ).all()
        if not tables:
            logger.warning("Arsagera sync skipped: analyst table %r not found", target_name)
            return ArsageraSyncResult(0, 0, 0, 0, 0, 0, {"__table__": "таблица аналитика не найдена"})

        table_ids = [table.id for table in tables]
        rows = db.scalars(
            select(StockRow).where(StockRow.table_id.in_(table_ids)).order_by(StockRow.id.asc())
        ).all()
        tickers = sorted({row.ticker.strip().upper() for row in rows if row.ticker.strip()})
        if not tickers:
            return ArsageraSyncResult(len(tables), 0, 0, 0, 0, 0, {})

        mapping, mapping_errors = await source.fetch_catalog_mapping(tickers)
        forecasts, fetch_errors = await _fetch_forecasts(source, mapping, concurrency)
        errors = {**mapping_errors, **fetch_errors}
        table_by_id = {table.id: table for table in tables}
        updated_tickers: set[str] = set()
        unchanged_tickers: set[str] = set()

        for row in rows:
            ticker = row.ticker.strip().upper()
            forecast = forecasts.get(ticker)
            if not ticker or forecast is None:
                continue
            profit_map, profit_changed = _merge_future_values(
                row.net_profit_year_map,
                forecast.net_profit_billion_rub,
            )
            dividend_map, dividend_changed = _merge_future_values(
                row.dividend_year_map,
                forecast.dividends_per_share_rub,
            )
            if not profit_changed and not dividend_changed:
                unchanged_tickers.add(ticker)
                continue

            row.net_profit_year_map = profit_map
            row.dividend_year_map = dividend_map
            row.net_profit_source_comment = SOURCE_COMMENT
            row._forecast_changed_by = "arsagera-sync"
            table = table_by_id[row.table_id]
            apply_net_profit_projection(row, table.forecast_start_year)
            updated_tickers.add(ticker)

        db.commit()
        result = ArsageraSyncResult(
            tables=len(tables),
            tickers_total=len(tickers),
            tickers_mapped=len(mapping),
            tickers_updated=len(updated_tickers),
            tickers_unchanged=len(unchanged_tickers - updated_tickers),
            tickers_skipped=len(errors),
            errors=errors,
        )
        logger.info(
            "Arsagera sync: tables=%s total=%s mapped=%s updated=%s unchanged=%s skipped=%s",
            result.tables,
            result.tickers_total,
            result.tickers_mapped,
            result.tickers_updated,
            result.tickers_unchanged,
            result.tickers_skipped,
        )
        for ticker, error in sorted(errors.items()):
            logger.warning("Arsagera sync skipped %s: %s", ticker, error)
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
