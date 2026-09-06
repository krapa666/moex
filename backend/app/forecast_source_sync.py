from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .database import SessionLocal
from .forecast_source_runs import (
    complete_forecast_source_run,
    fail_forecast_source_run,
    start_forecast_source_run,
)
from .main import (
    apply_net_profit_projection,
    copy_shared_row_fields,
    get_primary_table,
    reset_net_profit_fields,
)
from .models import AnalystTable, StockRow

logger = logging.getLogger(__name__)


class ForecastRecord(Protocol):
    ticker: str
    net_profit_billion_rub: dict[str, float]
    dividends_per_share_rub: dict[str, float]


class ForecastSourceClient(Protocol):
    async def fetch_catalog_mapping(
        self, tickers: Iterable[str]
    ) -> tuple[dict[str, str], dict[str, str]]: ...

    async def fetch_forecast(self, ticker: str, source_ref: str) -> ForecastRecord: ...


@dataclass(frozen=True)
class ForecastSyncResult:
    tables: int
    tickers_total: int
    tickers_mapped: int
    tickers_updated: int
    tickers_unchanged: int
    tickers_skipped: int
    errors: dict[str, str]
    table_created: bool = False


def merge_future_values(
    existing: dict | None, incoming: dict[str, float]
) -> tuple[dict[str, float | None], bool]:
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
    client: ForecastSourceClient,
    mapping: dict[str, str],
    concurrency: int,
) -> tuple[dict[str, ForecastRecord], dict[str, str]]:
    semaphore = asyncio.Semaphore(max(1, concurrency))
    forecasts: dict[str, ForecastRecord] = {}
    errors: dict[str, str] = {}

    async def fetch_one(ticker: str, source_ref: str) -> None:
        async with semaphore:
            try:
                forecasts[ticker] = await client.fetch_forecast(ticker, source_ref)
            except Exception as exc:  # source failures are isolated per ticker
                errors[ticker] = str(exc) or exc.__class__.__name__

    await asyncio.gather(
        *(fetch_one(ticker, source_ref) for ticker, source_ref in mapping.items())
    )
    return forecasts, errors


def _create_target_table_from_primary(db: Session, analyst_name: str) -> AnalystTable | None:
    primary = get_primary_table(db)
    if primary is None:
        return None

    max_sort_order = db.scalar(select(func.max(AnalystTable.sort_order))) or 0
    target = AnalystTable(
        analyst_name=analyst_name,
        year_offset=0,
        forecast_start_year=primary.forecast_start_year,
        sort_order=int(max_sort_order) + 1,
    )
    db.add(target)
    db.flush()

    primary_rows = db.scalars(
        select(StockRow).where(StockRow.table_id == primary.id).order_by(StockRow.id.asc())
    ).all()
    for source_row in primary_rows:
        target_row = StockRow(table_id=target.id, ticker=source_row.ticker)
        copy_shared_row_fields(source_row, target_row)
        reset_net_profit_fields(target_row)
        db.add(target_row)
    db.flush()
    return target


def _get_or_create_target_tables(
    db: Session,
    analyst_name: str,
    *,
    create_table_if_missing: bool,
) -> tuple[list[AnalystTable], bool]:
    tables = db.scalars(
        select(AnalystTable).where(func.lower(AnalystTable.analyst_name) == analyst_name.lower())
    ).all()
    if tables or not create_table_if_missing:
        return list(tables), False

    created = _create_target_table_from_primary(db, analyst_name)
    return ([created] if created is not None else []), created is not None


def _run_status(result: ForecastSyncResult) -> str:
    if not result.errors:
        return "success"
    if result.tickers_mapped == 0:
        return "failed"
    return "partial"


def _start_run(source_key: str | None, analyst_name: str) -> int | None:
    if not source_key:
        return None
    try:
        return start_forecast_source_run(source_key=source_key, analyst_name=analyst_name)
    except Exception:
        logger.exception("Could not start forecast source run history for %r", analyst_name)
        return None


def _finish_run(run_id: int | None, result: ForecastSyncResult) -> None:
    if run_id is None:
        return
    try:
        complete_forecast_source_run(
            run_id,
            status=_run_status(result),
            tables=result.tables,
            tickers_total=result.tickers_total,
            tickers_mapped=result.tickers_mapped,
            tickers_updated=result.tickers_updated,
            tickers_unchanged=result.tickers_unchanged,
            tickers_skipped=result.tickers_skipped,
            table_created=result.table_created,
            error_details=result.errors,
        )
    except Exception:
        logger.exception("Could not complete forecast source run history id=%s", run_id)


def _fail_run(run_id: int | None, error: Exception) -> None:
    if run_id is None:
        return
    try:
        fail_forecast_source_run(run_id, error)
    except Exception:
        logger.exception("Could not fail forecast source run history id=%s", run_id)


async def sync_forecast_source_once(
    *,
    analyst_name: str,
    source_comment: str,
    changed_by: str,
    client: ForecastSourceClient,
    concurrency: int = 4,
    create_table_if_missing: bool = False,
    source_key: str | None = None,
) -> ForecastSyncResult:
    target_name = analyst_name.strip()
    if not target_name:
        raise ValueError("analyst_name must not be empty")

    run_id = _start_run(source_key, target_name)
    db = SessionLocal()
    try:
        tables, table_created = _get_or_create_target_tables(
            db,
            target_name,
            create_table_if_missing=create_table_if_missing,
        )
        if not tables:
            error = (
                "нет основной таблицы для создания таблицы аналитика"
                if create_table_if_missing
                else "таблица аналитика не найдена"
            )
            logger.warning("Forecast sync %r skipped: %s", target_name, error)
            result = ForecastSyncResult(0, 0, 0, 0, 0, 0, {"__table__": error}, False)
            _finish_run(run_id, result)
            return result

        table_ids = [table.id for table in tables]
        rows = db.scalars(
            select(StockRow).where(StockRow.table_id.in_(table_ids)).order_by(StockRow.id.asc())
        ).all()
        tickers = sorted({row.ticker.strip().upper() for row in rows if row.ticker.strip()})
        if not tickers:
            if table_created:
                db.commit()
            result = ForecastSyncResult(len(tables), 0, 0, 0, 0, 0, {}, table_created)
            _finish_run(run_id, result)
            return result

        mapping, mapping_errors = await client.fetch_catalog_mapping(tickers)
        forecasts, fetch_errors = await _fetch_forecasts(client, mapping, concurrency)
        errors = {**mapping_errors, **fetch_errors}
        table_by_id = {table.id: table for table in tables}
        updated_tickers: set[str] = set()
        unchanged_tickers: set[str] = set()

        for row in rows:
            ticker = row.ticker.strip().upper()
            forecast = forecasts.get(ticker)
            if not ticker or forecast is None:
                continue
            profit_map, profit_changed = merge_future_values(
                row.net_profit_year_map,
                forecast.net_profit_billion_rub,
            )
            dividend_map, dividend_changed = merge_future_values(
                row.dividend_year_map,
                forecast.dividends_per_share_rub,
            )
            if not profit_changed and not dividend_changed:
                unchanged_tickers.add(ticker)
                continue

            row.net_profit_year_map = profit_map
            row.dividend_year_map = dividend_map
            if profit_changed:
                row.net_profit_source_comment = source_comment
            row._forecast_changed_by = changed_by
            table = table_by_id[row.table_id]
            apply_net_profit_projection(row, table.forecast_start_year)
            updated_tickers.add(ticker)

        db.commit()
        result = ForecastSyncResult(
            tables=len(tables),
            tickers_total=len(tickers),
            tickers_mapped=len(mapping),
            tickers_updated=len(updated_tickers),
            tickers_unchanged=len(unchanged_tickers - updated_tickers),
            tickers_skipped=len(errors),
            errors=errors,
            table_created=table_created,
        )
        _finish_run(run_id, result)
        logger.info(
            "Forecast sync %r: tables=%s created=%s total=%s mapped=%s updated=%s unchanged=%s skipped=%s",
            target_name,
            result.tables,
            result.table_created,
            result.tickers_total,
            result.tickers_mapped,
            result.tickers_updated,
            result.tickers_unchanged,
            result.tickers_skipped,
        )
        for ticker, error in sorted(errors.items()):
            logger.warning("Forecast sync %r skipped %s: %s", target_name, ticker, error)
        return result
    except Exception as exc:
        db.rollback()
        _fail_run(run_id, exc)
        raise
    finally:
        db.close()
