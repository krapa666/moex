from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .calculations import recalculate_fields
from .models import StockRow
from .moex import fetch_current_price

PRICE_REFRESH_INTERVAL = timedelta(minutes=10)


async def refresh_row_price(row: StockRow, force: bool = False) -> None:
    if not row.ticker:
        row.current_price = None
        row.status_message = "Введите тикер"
        row.price_updated_at = None
        recalculate_fields(row)
        return

    if (
        not force
        and row.price_updated_at is not None
        and row.price_updated_at >= datetime.now(timezone.utc) - PRICE_REFRESH_INTERVAL
    ):
        recalculate_fields(row)
        return

    row.current_price, row.status_message = await fetch_current_price(row.ticker)
    row.price_updated_at = datetime.now(timezone.utc)
    recalculate_fields(row)


async def refresh_all_prices(db: Session, force: bool = False, table_id: int | None = None) -> list[StockRow]:
    query = select(StockRow)
    if table_id is not None:
        query = query.where(StockRow.table_id == table_id)
    rows = db.scalars(query.order_by(StockRow.id.asc())).all()
    for row in rows:
        await refresh_row_price(row, force=force)
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows
