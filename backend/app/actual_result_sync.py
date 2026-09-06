from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Protocol

from sqlalchemy import select

from .database import SessionLocal
from .forecast_accuracy import ActualNetProfit
from .main import get_primary_table
from .models import StockRow


class ActualProfitRecord(Protocol):
    ticker: str
    fiscal_year: int
    net_profit_billion_rub: float
    source_name: str
    source_url: str | None
    source_comment: str | None
    reported_at: datetime | None


class ActualProfitSourceClient(Protocol):
    async def fetch_actuals(
        self,
        tickers: Iterable[str],
        *,
        min_fiscal_year: int,
    ) -> tuple[list[ActualProfitRecord], dict[str, str]]: ...


@dataclass(frozen=True)
class ActualSyncResult:
    tickers_total: int
    tickers_mapped: int
    records_found: int
    records_created: int
    records_updated: int
    records_unchanged: int
    records_protected: int
    tickers_skipped: int
    errors: dict[str, str]


def _same_optional_text(left: str | None, right: str | None) -> bool:
    return (left or "").strip() == (right or "").strip()


def _same_optional_datetime(left: datetime | None, right: datetime | None) -> bool:
    if left is None or right is None:
        return left is right
    if left.tzinfo is None:
        left = left.replace(tzinfo=timezone.utc)
    if right.tzinfo is None:
        right = right.replace(tzinfo=timezone.utc)
    return left.astimezone(timezone.utc) == right.astimezone(timezone.utc)


async def sync_actual_profit_source_once(
    *,
    source_key: str,
    client: ActualProfitSourceClient,
    years_back: int = 5,
) -> ActualSyncResult:
    normalized_source_key = source_key.strip().lower()
    if not normalized_source_key:
        raise ValueError("source_key must not be empty")
    years_back = max(1, min(int(years_back), 20))
    current_year = datetime.now(timezone.utc).year
    min_fiscal_year = current_year - years_back

    db = SessionLocal()
    try:
        primary = get_primary_table(db)
        if primary is None:
            return ActualSyncResult(0, 0, 0, 0, 0, 0, 0, 0, {"__table__": "основная таблица не найдена"})

        tickers = sorted(
            {
                ticker.strip().upper()
                for ticker in db.scalars(
                    select(StockRow.ticker).where(StockRow.table_id == primary.id)
                ).all()
                if ticker and ticker.strip()
            }
        )
        if not tickers:
            return ActualSyncResult(0, 0, 0, 0, 0, 0, 0, 0, {})

        records, fetch_errors = await client.fetch_actuals(
            tickers,
            min_fiscal_year=min_fiscal_year,
        )
        ticker_set = set(tickers)
        created = updated = unchanged = protected = 0
        mapped_tickers: set[str] = set()
        errors = dict(fetch_errors)

        for record in records:
            ticker = (record.ticker or "").strip().upper()
            year = int(record.fiscal_year)
            value = float(record.net_profit_billion_rub)
            if ticker not in ticker_set:
                errors[f"{ticker}:{year}"] = "источник вернул тикер вне основной таблицы"
                continue
            if year < min_fiscal_year or year > current_year:
                errors[f"{ticker}:{year}"] = "факт вне разрешённого диапазона лет"
                continue
            if not math.isfinite(value):
                errors[f"{ticker}:{year}"] = "источник вернул нечисловое значение факта"
                continue
            source_name = (record.source_name or "").strip()
            if not source_name:
                errors[f"{ticker}:{year}"] = "источник не указал provenance"
                continue

            mapped_tickers.add(ticker)
            row = db.scalars(
                select(ActualNetProfit).where(
                    ActualNetProfit.ticker == ticker,
                    ActualNetProfit.fiscal_year == year,
                )
            ).first()
            if row is None:
                row = ActualNetProfit(
                    ticker=ticker,
                    fiscal_year=year,
                    source_key=normalized_source_key,
                    net_profit_billion_rub=value,
                    source_name=source_name,
                    source_url=(record.source_url or "").strip() or None,
                    source_comment=(record.source_comment or "").strip() or None,
                    reported_at=record.reported_at,
                )
                db.add(row)
                created += 1
                continue

            existing_source_key = (row.source_key or "manual").strip().lower()
            if existing_source_key != normalized_source_key:
                protected += 1
                errors[f"{ticker}:{year}"] = (
                    f"сохранён факт из источника {row.source_key or 'manual'}; "
                    f"автосинхронизация {normalized_source_key} его не перезаписывает"
                )
                continue

            source_url = (record.source_url or "").strip() or None
            source_comment = (record.source_comment or "").strip() or None
            changed = (
                abs(float(row.net_profit_billion_rub) - value) > 1e-9
                or row.source_name != source_name
                or not _same_optional_text(row.source_url, source_url)
                or not _same_optional_text(row.source_comment, source_comment)
                or not _same_optional_datetime(row.reported_at, record.reported_at)
            )
            if not changed:
                unchanged += 1
                continue

            row.net_profit_billion_rub = value
            row.source_name = source_name
            row.source_url = source_url
            row.source_comment = source_comment
            row.reported_at = record.reported_at
            updated += 1

        db.commit()
        return ActualSyncResult(
            tickers_total=len(tickers),
            tickers_mapped=len(mapped_tickers),
            records_found=len(records),
            records_created=created,
            records_updated=updated,
            records_unchanged=unchanged,
            records_protected=protected,
            tickers_skipped=len({key.split(":", 1)[0] for key in errors if not key.startswith("__")}),
            errors=errors,
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
