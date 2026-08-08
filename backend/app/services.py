from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import StockRow
from .moex import fetch_current_price

PRICE_REFRESH_INTERVAL = timedelta(minutes=10)
STALE_PRICE_MAX_AGE = timedelta(hours=24)


async def refresh_row_price(row: StockRow, force: bool = False) -> None:
    if not row.ticker:
        row.current_price = None
        row.status_message = "Введите тикер"
        row.price_updated_at = None
        return

    if (
        not force
        and row.price_updated_at is not None
        and row.price_updated_at >= datetime.now(timezone.utc) - PRICE_REFRESH_INTERVAL
    ):
        return

    fetched_price, fetch_message = await fetch_current_price(row.ticker)
    now = datetime.now(timezone.utc)

    if fetched_price is not None:
        row.current_price = fetched_price
        row.status_message = fetch_message
        row.price_updated_at = now
        return

    can_keep_last_price = (
        row.current_price is not None
        and row.price_updated_at is not None
        and row.price_updated_at >= now - STALE_PRICE_MAX_AGE
    )
    if can_keep_last_price:
        row.status_message = "MOEX временно недоступна, используем последнюю сохранённую цену"
        return

    if row.current_price is not None and row.price_updated_at is not None:
        row.status_message = "MOEX недоступна, сохранённая цена устарела более чем на 24 часа"
        return

    row.current_price = None
    row.status_message = fetch_message or "Не удалось получить цену от MOEX ISS"
    row.price_updated_at = None


async def refresh_all_prices(db: Session, force: bool = False, table_id: int | None = None) -> list[StockRow]:
    query = select(StockRow)
    if table_id is not None:
        query = query.where(StockRow.table_id == table_id)
    rows = db.scalars(query.order_by(StockRow.id.asc())).all()
    rows_by_ticker: dict[str, list[StockRow]] = {}
    for row in rows:
        rows_by_ticker.setdefault(row.ticker.strip().upper(), []).append(row)

    for ticker, ticker_rows in rows_by_ticker.items():
        if not ticker:
            for row in ticker_rows:
                await refresh_row_price(row, force=force)
            continue

        representative = max(
            ticker_rows,
            key=lambda item: item.price_updated_at.timestamp() if item.price_updated_at else float("-inf"),
        )
        await refresh_row_price(representative, force=force)
        for row in ticker_rows:
            if row is representative:
                continue
            row.current_price = representative.current_price
            row.status_message = representative.status_message
            row.price_updated_at = representative.price_updated_at
    return rows
