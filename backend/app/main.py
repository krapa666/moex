import asyncio
import contextlib
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import SessionLocal, get_db
from .models import AnalystTable, StockRow
from .calculations import recalculate_fields
from .schemas import (
    AnalystTableCreate,
    AnalystTableRead,
    AnalystTableUpdate,
    StockRowCreate,
    StockRowRead,
    StockRowUpdate,
    TickerComparisonItem,
    TickerComparisonYear,
)
from .services import refresh_all_prices, refresh_row_price

app = FastAPI(title="MOEX Fair Price", version="1.0.0")
price_refresh_task: asyncio.Task | None = None
BACKGROUND_REFRESH_SECONDS = 10 * 60
BASE_FORECAST_YEAR = datetime.now(timezone.utc).year

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


@app.on_event("startup")
def on_startup() -> None:
    global price_refresh_task
    price_refresh_task = asyncio.create_task(periodic_price_refresh())


@app.on_event("shutdown")
async def on_shutdown() -> None:
    global price_refresh_task
    if price_refresh_task:
        price_refresh_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await price_refresh_task


async def periodic_price_refresh() -> None:
    while True:
        db = SessionLocal()
        try:
            await refresh_all_prices(db, force=True)
        finally:
            db.close()
        await asyncio.sleep(BACKGROUND_REFRESH_SECONDS)


def ensure_default_table(db: Session) -> None:
    first_table = db.scalars(select(AnalystTable).order_by(AnalystTable.id.asc()).limit(1)).first()
    if first_table is None:
        db.add(AnalystTable(analyst_name="Аналитик 1", year_offset=0))
        db.commit()


def get_table_or_404(db: Session, table_id: int) -> AnalystTable:
    table = db.get(AnalystTable, table_id)
    if table is None:
        raise HTTPException(status_code=404, detail="Таблица аналитика не найдена")
    return table


def get_tables_ordered(db: Session) -> list[AnalystTable]:
    return db.scalars(select(AnalystTable).order_by(AnalystTable.id.asc())).all()


def serialize_table(table: AnalystTable, table_number: int) -> dict:
    return {
        "id": table.id,
        "table_number": table_number,
        "analyst_name": table.analyst_name,
        "year_offset": table.year_offset,
        "created_at": table.created_at,
    }


def serialize_tables(tables: list[AnalystTable]) -> list[dict]:
    return [serialize_table(table, index + 1) for index, table in enumerate(tables)]


def apply_net_profit_projection(row: StockRow, year_offset: int) -> None:
    years = [BASE_FORECAST_YEAR + year_offset + i for i in range(4)]
    profit_map = row.net_profit_year_map or {}
    row.forecast_profit_year1_billion_rub = profit_map.get(str(years[0]))
    row.forecast_profit_year2_billion_rub = profit_map.get(str(years[1]))
    row.forecast_profit_year3_billion_rub = profit_map.get(str(years[2]))
    row.forecast_profit_year4_billion_rub = profit_map.get(str(years[3]))
    recalculate_fields(row)


def merge_payload_profit_map(payload: StockRowCreate | StockRowUpdate, year_offset: int) -> dict[str, float | None]:
    years = [BASE_FORECAST_YEAR + year_offset + i for i in range(4)]
    merged = dict(payload.net_profit_year_map or {})
    merged[str(years[0])] = payload.forecast_profit_year1_billion_rub
    merged[str(years[1])] = payload.forecast_profit_year2_billion_rub
    merged[str(years[2])] = payload.forecast_profit_year3_billion_rub
    merged[str(years[3])] = payload.forecast_profit_year4_billion_rub
    return merged


def reset_net_profit_fields(row: StockRow) -> None:
    row.forecast_profit_year1_billion_rub = None
    row.forecast_profit_year2_billion_rub = None
    row.forecast_profit_year3_billion_rub = None
    row.forecast_profit_year4_billion_rub = None
    row.net_profit_year_map = {}
    row.forecast_price_year1 = None
    row.forecast_price_year2 = None
    row.forecast_price_year3 = None
    row.forecast_price_year4 = None
    row.upside_percent_year1 = None
    row.upside_percent_year2 = None
    row.upside_percent_year3 = None
    row.upside_percent_year4 = None


def copy_shared_row_fields(src: StockRow, dest: StockRow) -> None:
    dest.ticker = src.ticker
    dest.current_price = src.current_price
    dest.shares_billion = src.shares_billion
    dest.market_cap_billion_rub = src.market_cap_billion_rub
    dest.pe_avg_5y = src.pe_avg_5y
    dest.status_message = src.status_message
    dest.price_updated_at = src.price_updated_at


def sync_row_to_other_tables(
    db: Session,
    row: StockRow,
    *,
    old_ticker: str | None = None,
) -> None:
    ticker = row.ticker.strip().upper()
    if not ticker:
        return

    tables = get_tables_ordered(db)
    for table in tables:
        if table.id == row.table_id:
            continue

        target = None
        if old_ticker:
            target = db.scalars(
                select(StockRow).where(StockRow.table_id == table.id, StockRow.ticker == old_ticker).limit(1)
            ).first()
        if target is None:
            target = db.scalars(
                select(StockRow).where(StockRow.table_id == table.id, StockRow.ticker == ticker).limit(1)
            ).first()

        if target is None:
            target = StockRow(table_id=table.id, ticker=ticker)
            copy_shared_row_fields(row, target)
            reset_net_profit_fields(target)
            db.add(target)
            continue

        copy_shared_row_fields(row, target)
        if target.net_profit_year_map is None:
            reset_net_profit_fields(target)
        else:
            apply_net_profit_projection(target, table.year_offset)


def build_ticker_comparison_item(table: AnalystTable, row: StockRow, table_number: int) -> TickerComparisonItem:
    years = [BASE_FORECAST_YEAR + table.year_offset + i for i in range(4)]
    values = [
        (
            row.forecast_profit_year1_billion_rub,
            row.forecast_price_year1,
            row.upside_percent_year1,
        ),
        (
            row.forecast_profit_year2_billion_rub,
            row.forecast_price_year2,
            row.upside_percent_year2,
        ),
        (
            row.forecast_profit_year3_billion_rub,
            row.forecast_price_year3,
            row.upside_percent_year3,
        ),
        (
            row.forecast_profit_year4_billion_rub,
            row.forecast_price_year4,
            row.upside_percent_year4,
        ),
    ]
    return TickerComparisonItem(
        table_id=table.id,
        table_number=table_number,
        analyst_name=table.analyst_name,
        year_offset=table.year_offset,
        ticker=row.ticker,
        current_price=row.current_price,
        shares_billion=row.shares_billion,
        market_cap_billion_rub=row.market_cap_billion_rub,
        pe_avg_5y=row.pe_avg_5y,
        status_message=row.status_message,
        price_updated_at=row.price_updated_at,
        years=[
            TickerComparisonYear(
                year=years[idx],
                forecast_profit_billion_rub=profit,
                forecast_price=price,
                upside_percent=upside,
            )
            for idx, (profit, price, upside) in enumerate(values)
        ],
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/tables", response_model=list[AnalystTableRead])
def get_tables(db: Session = Depends(get_db)):
    ensure_default_table(db)
    return serialize_tables(get_tables_ordered(db))


@app.post("/api/tables", response_model=AnalystTableRead)
def create_table(payload: AnalystTableCreate, db: Session = Depends(get_db)):
    ensure_default_table(db)
    total = db.query(AnalystTable).count()
    if total >= 10:
        raise HTTPException(status_code=400, detail="Можно создать не более 10 таблиц")
    source_table = db.get(AnalystTable, 1) or db.scalars(select(AnalystTable).order_by(AnalystTable.id.asc()).limit(1)).first()
    table = AnalystTable(analyst_name=payload.analyst_name.strip(), year_offset=0)
    db.add(table)
    db.commit()
    db.refresh(table)

    if source_table is not None:
        source_rows = db.scalars(select(StockRow).where(StockRow.table_id == source_table.id).order_by(StockRow.id.asc())).all()
        for src in source_rows:
            db.add(
                StockRow(
                    table_id=table.id,
                    ticker=src.ticker,
                    current_price=src.current_price,
                    shares_billion=src.shares_billion,
                    market_cap_billion_rub=src.market_cap_billion_rub,
                    pe_avg_5y=src.pe_avg_5y,
                    forecast_profit_year1_billion_rub=None,
                    forecast_profit_year2_billion_rub=None,
                    forecast_profit_year3_billion_rub=None,
                    forecast_profit_year4_billion_rub=None,
                    net_profit_year_map={},
                    forecast_price_year1=None,
                    forecast_price_year2=None,
                    forecast_price_year3=None,
                    forecast_price_year4=None,
                    upside_percent_year1=None,
                    upside_percent_year2=None,
                    upside_percent_year3=None,
                    upside_percent_year4=None,
                    status_message=src.status_message,
                    price_updated_at=src.price_updated_at,
                )
            )
        db.commit()
    tables = get_tables_ordered(db)
    created_index = next((index for index, item in enumerate(tables, start=1) if item.id == table.id), 1)
    return serialize_table(table, created_index)


@app.patch("/api/tables/{table_id}", response_model=AnalystTableRead)
def update_table(table_id: int, payload: AnalystTableUpdate, db: Session = Depends(get_db)):
    table = get_table_or_404(db, table_id)
    if payload.analyst_name is not None:
        table.analyst_name = payload.analyst_name.strip()
    if payload.year_offset is not None:
        table.year_offset = payload.year_offset
    db.commit()
    rows = db.scalars(select(StockRow).where(StockRow.table_id == table.id)).all()
    for row in rows:
        apply_net_profit_projection(row, table.year_offset)
    db.commit()
    db.refresh(table)
    tables = get_tables_ordered(db)
    table_index = next((index for index, item in enumerate(tables, start=1) if item.id == table.id), 1)
    return serialize_table(table, table_index)


@app.delete("/api/tables/{table_id}")
def delete_table(table_id: int, db: Session = Depends(get_db)):
    if table_id == 1:
        raise HTTPException(status_code=400, detail="Основную таблицу №1 удалять нельзя")
    table = get_table_or_404(db, table_id)
    rows = db.scalars(select(StockRow).where(StockRow.table_id == table.id)).all()
    for row in rows:
        db.delete(row)
    db.delete(table)
    db.commit()
    return {"ok": True}


@app.get("/api/rows", response_model=list[StockRowRead])
def get_rows(table_id: int, db: Session = Depends(get_db)):
    table = get_table_or_404(db, table_id)
    rows = db.scalars(select(StockRow).where(StockRow.table_id == table_id).order_by(StockRow.id.asc())).all()
    for row in rows:
        apply_net_profit_projection(row, table.year_offset)
    db.commit()
    return rows


@app.post("/api/rows", response_model=StockRowRead)
async def create_row(payload: StockRowCreate, db: Session = Depends(get_db)):
    table = get_table_or_404(db, payload.table_id)
    row = StockRow(
        table_id=payload.table_id,
        ticker=payload.ticker.strip().upper(),
        shares_billion=payload.shares_billion,
        pe_avg_5y=payload.pe_avg_5y,
        net_profit_year_map=merge_payload_profit_map(payload, table.year_offset),
        net_profit_source_comment=payload.net_profit_source_comment.strip() if payload.net_profit_source_comment else None,
    )
    apply_net_profit_projection(row, table.year_offset)

    await refresh_row_price(row, force=True)
    db.add(row)
    db.commit()
    db.refresh(row)
    sync_row_to_other_tables(db, row)
    db.commit()
    return row


@app.put("/api/rows/{row_id}", response_model=StockRowRead)
async def update_row(row_id: int, payload: StockRowUpdate, db: Session = Depends(get_db)):
    row = db.get(StockRow, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Строка не найдена")

    table = get_table_or_404(db, payload.table_id)
    old_ticker = row.ticker.strip().upper()
    row.table_id = payload.table_id
    row.ticker = payload.ticker.strip().upper()
    row.shares_billion = payload.shares_billion
    row.pe_avg_5y = payload.pe_avg_5y
    row.net_profit_year_map = merge_payload_profit_map(payload, table.year_offset)
    apply_net_profit_projection(row, table.year_offset)
    row.net_profit_source_comment = (
        payload.net_profit_source_comment.strip() if payload.net_profit_source_comment else None
    )

    await refresh_row_price(row, force=bool(row.ticker))
    sync_row_to_other_tables(db, row, old_ticker=old_ticker if old_ticker != row.ticker else None)
    db.commit()
    db.refresh(row)
    return row


@app.delete("/api/rows/{row_id}")
def delete_row(row_id: int, db: Session = Depends(get_db)):
    row = db.get(StockRow, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Строка не найдена")
    db.delete(row)
    db.commit()
    return {"ok": True}


@app.post("/api/rows/refresh", response_model=list[StockRowRead])
async def refresh_prices(table_id: int, db: Session = Depends(get_db)):
    get_table_or_404(db, table_id)
    return await refresh_all_prices(db, force=True, table_id=table_id)


@app.get("/api/ticker-comparison", response_model=list[TickerComparisonItem])
def ticker_comparison(ticker: str, db: Session = Depends(get_db)):
    normalized = ticker.strip().upper()
    if not normalized:
        raise HTTPException(status_code=400, detail="Тикер обязателен")

    tables = get_tables_ordered(db)
    table_number_map = {table.id: index + 1 for index, table in enumerate(tables)}
    result: list[TickerComparisonItem] = []
    for table in tables:
        row = db.scalars(
            select(StockRow).where(StockRow.table_id == table.id, StockRow.ticker == normalized).limit(1)
        ).first()
        if row is None:
            continue
        apply_net_profit_projection(row, table.year_offset)
        result.append(build_ticker_comparison_item(table, row, table_number_map[table.id]))

    return result
