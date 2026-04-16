import asyncio
import contextlib
import ipaddress
import json
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session, load_only

from .calculations import recalculate_fields
from .database import SessionLocal, get_db
from .models import AnalystTable, StockRow
from .schemas import (
    AnalystTableCreate,
    AnalystTableRead,
    AnalystTableUpdate,
    DataTransferResult,
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
sort_order_schema_ready = False
sort_order_supported = True

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
    ensure_sort_order_schema(db)
    if sort_order_supported:
        first_table = db.scalars(select(AnalystTable).order_by(AnalystTable.sort_order.asc(), AnalystTable.id.asc()).limit(1)).first()
    else:
        first_table = db.scalars(
            select(AnalystTable)
            .options(
                load_only(
                    AnalystTable.id,
                    AnalystTable.analyst_name,
                    AnalystTable.year_offset,
                    AnalystTable.created_at,
                )
            )
            .order_by(AnalystTable.id.asc())
            .limit(1)
        ).first()
    if first_table is None:
        db.add(AnalystTable(analyst_name="Аналитик 1", year_offset=0, sort_order=1))
        db.commit()


def ensure_sort_order_schema(db: Session) -> None:
    global sort_order_schema_ready, sort_order_supported
    if sort_order_schema_ready:
        return

    engine = db.get_bind()
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("analyst_tables")}
    if "sort_order" not in columns:
        try:
            db.execute(text("ALTER TABLE analyst_tables ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0"))
            db.execute(text("UPDATE analyst_tables SET sort_order = id WHERE sort_order = 0"))
            db.commit()
        except Exception:
            db.rollback()
            sort_order_supported = False
    sort_order_schema_ready = True


def get_table_or_404(db: Session, table_id: int) -> AnalystTable:
    ensure_sort_order_schema(db)
    if sort_order_supported:
        table = db.get(AnalystTable, table_id)
    else:
        table = db.scalars(
            select(AnalystTable)
            .options(
                load_only(
                    AnalystTable.id,
                    AnalystTable.analyst_name,
                    AnalystTable.year_offset,
                    AnalystTable.created_at,
                )
            )
            .where(AnalystTable.id == table_id)
            .limit(1)
        ).first()
    if table is None:
        raise HTTPException(status_code=404, detail="Таблица аналитика не найдена")
    return table


def get_tables_ordered(db: Session) -> list[AnalystTable]:
    ensure_sort_order_schema(db)
    if sort_order_supported:
        return db.scalars(select(AnalystTable).order_by(AnalystTable.sort_order.asc(), AnalystTable.id.asc())).all()
    return db.scalars(
        select(AnalystTable)
        .options(
            load_only(
                AnalystTable.id,
                AnalystTable.analyst_name,
                AnalystTable.year_offset,
                AnalystTable.created_at,
            )
        )
        .order_by(AnalystTable.id.asc())
    ).all()


def get_primary_table(db: Session) -> AnalystTable | None:
    tables = get_tables_ordered(db)
    return tables[0] if tables else None


def is_primary_table_id(db: Session, table_id: int) -> bool:
    primary = get_primary_table(db)
    return primary is not None and primary.id == table_id


def ensure_primary_table_for_row_mutation(db: Session, table_id: int) -> None:
    if not is_primary_table_id(db, table_id):
        raise HTTPException(
            status_code=403,
            detail="Добавлять и удалять строки можно только в таблице №1",
        )


def resolve_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        candidate = forwarded_for.split(",", 1)[0].strip()
        if candidate:
            return candidate
    return request.client.host if request.client else ""


def is_local_network_request(request: Request) -> bool:
    ip_text = resolve_client_ip(request)
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback


def require_local_admin(request: Request) -> None:
    if not is_local_network_request(request):
        raise HTTPException(status_code=403, detail="Доступ только для локальной сети (гостевой режим)")


def get_primary_row_by_ticker(db: Session, ticker: str) -> StockRow | None:
    primary = get_primary_table(db)
    normalized_ticker = ticker.strip().upper()
    if primary is None or not normalized_ticker:
        return None
    return db.scalars(
        select(StockRow).where(StockRow.table_id == primary.id, StockRow.ticker == normalized_ticker).limit(1)
    ).first()


def is_shared_fields_editable_for_table(db: Session, table_id: int, ticker: str) -> bool:
    primary = get_primary_table(db)
    normalized_ticker = ticker.strip().upper()
    if primary is None or table_id == primary.id or not normalized_ticker:
        return True
    return get_primary_row_by_ticker(db, normalized_ticker) is None


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


def build_database_snapshot(db: Session) -> dict:
    tables = get_tables_ordered(db)
    rows = db.scalars(select(StockRow).order_by(StockRow.table_id.asc(), StockRow.id.asc())).all()
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "tables": [
            {
                "id": table.id,
                "analyst_name": table.analyst_name,
                "year_offset": table.year_offset,
                "sort_order": table.sort_order,
            }
            for table in tables
        ],
        "rows": [
            {
                "table_id": row.table_id,
                "ticker": row.ticker,
                "current_price": row.current_price,
                "shares_billion": row.shares_billion,
                "market_cap_billion_rub": row.market_cap_billion_rub,
                "pe_avg_5y": row.pe_avg_5y,
                "forecast_profit_year1_billion_rub": row.forecast_profit_year1_billion_rub,
                "forecast_profit_year2_billion_rub": row.forecast_profit_year2_billion_rub,
                "forecast_profit_year3_billion_rub": row.forecast_profit_year3_billion_rub,
                "forecast_profit_year4_billion_rub": row.forecast_profit_year4_billion_rub,
                "net_profit_year_map": row.net_profit_year_map,
                "net_profit_source_comment": row.net_profit_source_comment,
                "forecast_price_year1": row.forecast_price_year1,
                "forecast_price_year2": row.forecast_price_year2,
                "forecast_price_year3": row.forecast_price_year3,
                "forecast_price_year4": row.forecast_price_year4,
                "upside_percent_year1": row.upside_percent_year1,
                "upside_percent_year2": row.upside_percent_year2,
                "upside_percent_year3": row.upside_percent_year3,
                "upside_percent_year4": row.upside_percent_year4,
                "status_message": row.status_message,
                "price_updated_at": row.price_updated_at.isoformat() if row.price_updated_at else None,
            }
            for row in rows
        ],
    }


def import_database_snapshot(db: Session, payload: dict) -> dict:
    tables_data = payload.get("tables") if isinstance(payload, dict) else None
    rows_data = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(tables_data, list) or not isinstance(rows_data, list):
        raise HTTPException(status_code=400, detail="Некорректный формат JSON-файла")

    existing_rows = db.scalars(select(StockRow)).all()
    for row in existing_rows:
        db.delete(row)
    existing_tables = db.scalars(select(AnalystTable)).all()
    for table in existing_tables:
        db.delete(table)
    db.flush()

    table_id_map: dict[int, int] = {}
    for table_data in tables_data:
        new_table = AnalystTable(
            analyst_name=str(table_data.get("analyst_name") or "Аналитик"),
            year_offset=int(table_data.get("year_offset") or 0),
            sort_order=int(table_data.get("sort_order") or 0),
        )
        db.add(new_table)
        db.flush()
        source_id = int(table_data.get("id") or 0)
        if source_id:
            table_id_map[source_id] = new_table.id

    imported_rows = 0
    for row_data in rows_data:
        source_table_id = int(row_data.get("table_id") or 0)
        mapped_table_id = table_id_map.get(source_table_id)
        if mapped_table_id is None:
            continue
        price_updated_raw = row_data.get("price_updated_at")
        price_updated = None
        if isinstance(price_updated_raw, str) and price_updated_raw:
            try:
                price_updated = datetime.fromisoformat(price_updated_raw)
            except ValueError:
                price_updated = None

        row = StockRow(
            table_id=mapped_table_id,
            ticker=str(row_data.get("ticker") or "").strip().upper(),
            current_price=row_data.get("current_price"),
            shares_billion=row_data.get("shares_billion"),
            market_cap_billion_rub=row_data.get("market_cap_billion_rub"),
            pe_avg_5y=row_data.get("pe_avg_5y"),
            forecast_profit_year1_billion_rub=row_data.get("forecast_profit_year1_billion_rub"),
            forecast_profit_year2_billion_rub=row_data.get("forecast_profit_year2_billion_rub"),
            forecast_profit_year3_billion_rub=row_data.get("forecast_profit_year3_billion_rub"),
            forecast_profit_year4_billion_rub=row_data.get("forecast_profit_year4_billion_rub"),
            net_profit_year_map=row_data.get("net_profit_year_map"),
            net_profit_source_comment=row_data.get("net_profit_source_comment"),
            forecast_price_year1=row_data.get("forecast_price_year1"),
            forecast_price_year2=row_data.get("forecast_price_year2"),
            forecast_price_year3=row_data.get("forecast_price_year3"),
            forecast_price_year4=row_data.get("forecast_price_year4"),
            upside_percent_year1=row_data.get("upside_percent_year1"),
            upside_percent_year2=row_data.get("upside_percent_year2"),
            upside_percent_year3=row_data.get("upside_percent_year3"),
            upside_percent_year4=row_data.get("upside_percent_year4"),
            status_message=row_data.get("status_message"),
            price_updated_at=price_updated,
        )
        db.add(row)
        imported_rows += 1

    db.commit()
    return {"tables_count": len(tables_data), "rows_count": imported_rows}


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


def sync_primary_table_multipliers(db: Session, row: StockRow) -> None:
    primary = get_primary_table(db)
    if primary is None or row.table_id != primary.id:
        return
    ticker = row.ticker.strip().upper()
    if not ticker:
        return

    tables = get_tables_ordered(db)
    for table in tables:
        if table.id == row.table_id:
            continue
        target = db.scalars(
            select(StockRow).where(StockRow.table_id == table.id, StockRow.ticker == ticker).limit(1)
        ).first()
        if target is None:
            continue
        target.shares_billion = row.shares_billion
        target.pe_avg_5y = row.pe_avg_5y
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


@app.get("/api/access-mode")
def access_mode(request: Request) -> dict[str, str]:
    mode = "admin" if is_local_network_request(request) else "guest"
    return {"mode": mode, "client_ip": resolve_client_ip(request)}


@app.get("/api/data/export")
def export_data(db: Session = Depends(get_db)):
    payload = build_database_snapshot(db)
    filename = f"moex-data-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json"
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/data/import", response_model=DataTransferResult)
async def import_data(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    require_local_admin(request)
    try:
        raw = await file.read()
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Не удалось прочитать JSON-файл") from exc
    result = import_database_snapshot(db, payload)
    return {**result, "ok": True, "file_path": file.filename or "uploaded.json", "detail": "Загрузка выполнена"}


@app.get("/api/tables", response_model=list[AnalystTableRead])
def get_tables(db: Session = Depends(get_db)):
    ensure_default_table(db)
    return serialize_tables(get_tables_ordered(db))


@app.post("/api/tables", response_model=AnalystTableRead)
def create_table(payload: AnalystTableCreate, request: Request, db: Session = Depends(get_db)):
    require_local_admin(request)
    ensure_default_table(db)
    total = db.query(AnalystTable).count()
    if total >= 10:
        raise HTTPException(status_code=400, detail="Можно создать не более 10 таблиц")
    source_table = get_primary_table(db)
    next_sort_order = (db.query(func.max(AnalystTable.sort_order)).scalar() or 0) + 1 if sort_order_supported else 0
    table = AnalystTable(analyst_name=payload.analyst_name.strip(), year_offset=0, sort_order=next_sort_order)
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
def update_table(table_id: int, payload: AnalystTableUpdate, request: Request, db: Session = Depends(get_db)):
    require_local_admin(request)
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
def delete_table(table_id: int, request: Request, db: Session = Depends(get_db)):
    require_local_admin(request)
    table = get_table_or_404(db, table_id)
    primary = get_primary_table(db)
    if primary is not None and primary.id == table.id:
        raise HTTPException(status_code=400, detail="Текущую основную таблицу удалять нельзя")
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
        row.shared_fields_editable = is_shared_fields_editable_for_table(db, row.table_id, row.ticker)
    db.commit()
    return rows


@app.post("/api/rows", response_model=StockRowRead)
async def create_row(payload: StockRowCreate, request: Request, db: Session = Depends(get_db)):
    require_local_admin(request)
    table = get_table_or_404(db, payload.table_id)
    ensure_primary_table_for_row_mutation(db, table.id)
    shared_fields_editable = is_shared_fields_editable_for_table(db, payload.table_id, payload.ticker)
    if not shared_fields_editable:
        primary_row = get_primary_row_by_ticker(db, payload.ticker)
        if primary_row is not None:
            payload.shares_billion = primary_row.shares_billion
            payload.pe_avg_5y = primary_row.pe_avg_5y

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
    if shared_fields_editable:
        sync_row_to_other_tables(db, row)
    db.commit()
    row.shared_fields_editable = shared_fields_editable
    return row


@app.put("/api/rows/{row_id}", response_model=StockRowRead)
async def update_row(row_id: int, payload: StockRowUpdate, request: Request, db: Session = Depends(get_db)):
    require_local_admin(request)
    row = db.get(StockRow, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Строка не найдена")

    table = get_table_or_404(db, payload.table_id)
    if row.table_id != payload.table_id:
        raise HTTPException(status_code=400, detail="Нельзя переносить строку между таблицами")

    primary_table = get_primary_table(db)
    is_primary_row = primary_table is not None and row.table_id == primary_table.id
    shared_fields_editable = is_primary_row
    old_ticker = row.ticker.strip().upper()
    new_ticker = payload.ticker.strip().upper()
    row.table_id = payload.table_id
    row.ticker = new_ticker if is_primary_row else old_ticker
    if shared_fields_editable:
        row.shares_billion = payload.shares_billion
        row.pe_avg_5y = payload.pe_avg_5y
    else:
        primary_row = get_primary_row_by_ticker(db, old_ticker)
        if primary_row is None:
            raise HTTPException(
                status_code=409,
                detail="Вторичная таблица не может редактировать общие поля без строки в таблице №1",
            )
        row.shares_billion = primary_row.shares_billion
        row.pe_avg_5y = primary_row.pe_avg_5y
    row.net_profit_year_map = merge_payload_profit_map(payload, table.year_offset)
    apply_net_profit_projection(row, table.year_offset)
    row.net_profit_source_comment = (
        payload.net_profit_source_comment.strip() if payload.net_profit_source_comment else None
    )

    await refresh_row_price(row, force=bool(row.ticker))
    if shared_fields_editable:
        sync_row_to_other_tables(db, row, old_ticker=old_ticker if old_ticker != row.ticker else None)
    sync_primary_table_multipliers(db, row)
    db.commit()
    db.refresh(row)
    row.shared_fields_editable = shared_fields_editable
    return row


@app.delete("/api/rows/{row_id}")
def delete_row(row_id: int, request: Request, db: Session = Depends(get_db)):
    require_local_admin(request)
    row = db.get(StockRow, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Строка не найдена")
    ensure_primary_table_for_row_mutation(db, row.table_id)

    normalized_ticker = row.ticker.strip().upper()
    if normalized_ticker:
        linked_rows = db.scalars(select(StockRow).where(StockRow.ticker == normalized_ticker)).all()
        for linked_row in linked_rows:
            db.delete(linked_row)
    else:
        db.delete(row)
    db.commit()
    return {"ok": True}


@app.post("/api/rows/refresh", response_model=list[StockRowRead])
async def refresh_prices(table_id: int, request: Request, db: Session = Depends(get_db)):
    require_local_admin(request)
    get_table_or_404(db, table_id)
    return await refresh_all_prices(db, force=True, table_id=table_id)


@app.post("/api/tables/{table_id}/make-primary", response_model=list[AnalystTableRead])
def make_table_primary(table_id: int, request: Request, db: Session = Depends(get_db)):
    require_local_admin(request)
    ensure_sort_order_schema(db)
    if not sort_order_supported:
        raise HTTPException(status_code=400, detail="Переупорядочивание таблиц недоступно: примените миграции БД")
    table = get_table_or_404(db, table_id)
    ordered = get_tables_ordered(db)
    if not ordered:
        raise HTTPException(status_code=400, detail="Нет таблиц для переупорядочивания")
    if ordered[0].id == table.id:
        return serialize_tables(ordered)

    table.sort_order = 1
    order_value = 2
    for item in ordered:
        if item.id == table.id:
            continue
        item.sort_order = order_value
        order_value += 1

    db.commit()
    return serialize_tables(get_tables_ordered(db))


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
