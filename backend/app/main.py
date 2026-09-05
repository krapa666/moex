import asyncio
import contextlib
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session, load_only

from .calculations import recalculate_fields
from .database import SessionLocal, get_db
from .models import AnalystTable, ForecastRevision, StockRow
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
from .volume_api import router as volume_router

logger = logging.getLogger(__name__)
price_refresh_task: asyncio.Task | None = None
BACKGROUND_REFRESH_SECONDS = 10 * 60
MAX_IMPORT_BYTES = 20 * 1024 * 1024


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global price_refresh_task
    price_refresh_task = asyncio.create_task(periodic_price_refresh())
    try:
        yield
    finally:
        tasks = [task for task in (price_refresh_task,) if task is not None]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task


app = FastAPI(title="MOEX Fair Price", version="1.2.0", lifespan=lifespan)
app.include_router(volume_router)


@dataclass
class AccessPrincipal:
    username: str
    is_admin: bool


def current_calendar_year() -> int:
    return datetime.now(timezone.utc).year


sort_order_schema_ready = False
sort_order_supported = True


async def periodic_price_refresh() -> None:
    while True:
        db = SessionLocal()
        try:
            rows = await refresh_all_prices(db, force=True)
            tables = {table.id: table for table in get_tables_ordered(db)}
            for row in rows:
                table = tables.get(row.table_id)
                if table is not None:
                    apply_net_profit_projection(row, table.forecast_start_year)
            db.commit()
        except asyncio.CancelledError:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            logger.exception("Background MOEX price refresh failed; retrying on the next cycle")
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
                    AnalystTable.forecast_start_year,
                    AnalystTable.created_at,
                )
            )
            .order_by(AnalystTable.id.asc())
            .limit(1)
        ).first()
    if first_table is None:
        db.add(
            AnalystTable(
                analyst_name="Аналитик 1",
                year_offset=0,
                forecast_start_year=current_calendar_year(),
                sort_order=1,
            )
        )
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
                    AnalystTable.forecast_start_year,
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
                AnalystTable.forecast_start_year,
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


def resolve_network_principal(request: Request) -> AccessPrincipal | None:
    access_scope = (request.headers.get("x-moex-access-scope") or "").strip().lower()
    if access_scope == "local":
        return AccessPrincipal(username="local-network", is_admin=True)
    # Missing, malformed and explicit internet scopes are all read-only. This is
    # intentional: backend usually sees the private IP of the frontend proxy, so
    # request.client cannot safely distinguish an internet user from a LAN user.
    return None


def get_current_user(request: Request) -> AccessPrincipal:
    principal = resolve_network_principal(request)
    if principal is None:
        raise HTTPException(status_code=403, detail="Доступ только из локальной сети")
    return principal


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


def ensure_ticker_unique(
    db: Session,
    table_id: int,
    ticker: str,
    *,
    exclude_row_id: int | None = None,
) -> None:
    normalized_ticker = ticker.strip().upper()
    if not normalized_ticker:
        return
    query = select(StockRow.id).where(
        StockRow.table_id == table_id,
        StockRow.ticker == normalized_ticker,
    )
    if exclude_row_id is not None:
        query = query.where(StockRow.id != exclude_row_id)
    if db.scalar(query.limit(1)) is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Тикер {normalized_ticker} уже есть в этой таблице",
        )


def serialize_table(table: AnalystTable, table_number: int) -> dict:
    return {
        "id": table.id,
        "table_number": table_number,
        "analyst_name": table.analyst_name,
        "year_offset": table.year_offset,
        "forecast_start_year": table.forecast_start_year,
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
                "forecast_start_year": table.forecast_start_year,
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
                "dividends_year1": row.dividends_year1,
                "dividends_year2": row.dividends_year2,
                "dividend_year_map": row.dividend_year_map,
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

    imported_rows = 0
    try:
        with ForecastRevision.suppress_capture(db.connection()):
            db.query(ForecastRevision).delete(synchronize_session=False)

            existing_rows = db.scalars(select(StockRow)).all()
            for row in existing_rows:
                db.delete(row)
            existing_tables = db.scalars(select(AnalystTable)).all()
            for table in existing_tables:
                db.delete(table)
            db.flush()

            table_id_map: dict[int, int] = {}
            for table_data in tables_data:
                legacy_offset = int(table_data.get("year_offset") or 0)
                forecast_start_year = int(
                    table_data.get("forecast_start_year") or current_calendar_year() + legacy_offset
                )
                new_table = AnalystTable(
                    analyst_name=str(table_data.get("analyst_name") or "Аналитик"),
                    year_offset=legacy_offset,
                    forecast_start_year=forecast_start_year,
                    sort_order=int(table_data.get("sort_order") or 0),
                )
                db.add(new_table)
                db.flush()
                source_id = int(table_data.get("id") or 0)
                if source_id:
                    table_id_map[source_id] = new_table.id

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
                    dividends_year1=row_data.get("dividends_year1"),
                    dividends_year2=row_data.get("dividends_year2"),
                    dividend_year_map=row_data.get("dividend_year_map"),
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

            db.flush()
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {"tables_count": len(tables_data), "rows_count": imported_rows}


def apply_net_profit_projection(row: StockRow, forecast_start_year: int) -> None:
    years = [forecast_start_year + i for i in range(4)]
    profit_map = row.net_profit_year_map or {}
    dividend_map = dict(row.dividend_year_map or {})
    if row.dividend_year_map is None:
        if row.dividends_year1 is not None:
            dividend_map[str(years[0])] = row.dividends_year1
        if row.dividends_year2 is not None:
            dividend_map[str(years[1])] = row.dividends_year2
        row.dividend_year_map = dividend_map
    row.forecast_profit_year1_billion_rub = profit_map.get(str(years[0]))
    row.forecast_profit_year2_billion_rub = profit_map.get(str(years[1]))
    row.forecast_profit_year3_billion_rub = profit_map.get(str(years[2]))
    row.forecast_profit_year4_billion_rub = profit_map.get(str(years[3]))
    row.dividends_year1 = dividend_map.get(str(years[0]))
    row.dividends_year2 = dividend_map.get(str(years[1]))
    dividend_totals_by_year_index: dict[int, float] = {}
    today_year = current_calendar_year()
    for index, target_year in enumerate(years, start=1):
        if target_year < today_year:
            dividend_totals_by_year_index[index] = 0.0
        else:
            dividend_totals_by_year_index[index] = sum(
                float(dividend_map.get(str(dividend_year)) or 0.0)
                for dividend_year in range(today_year, target_year + 1)
            )
    recalculate_fields(row, dividend_totals_by_year_index)


def merge_payload_profit_map(
    payload: StockRowCreate | StockRowUpdate, forecast_start_year: int
) -> dict[str, float | None]:
    years = [forecast_start_year + i for i in range(2)]
    merged = dict(payload.net_profit_year_map or {})
    merged[str(years[0])] = payload.forecast_profit_year1_billion_rub
    merged[str(years[1])] = payload.forecast_profit_year2_billion_rub
    return merged


def merge_payload_dividend_map(
    payload: StockRowCreate | StockRowUpdate, forecast_start_year: int
) -> dict[str, float | None]:
    years = [forecast_start_year + i for i in range(2)]
    merged = dict(payload.dividend_year_map or {})
    merged[str(years[0])] = payload.dividends_year1
    merged[str(years[1])] = payload.dividends_year2
    return merged


def reset_net_profit_fields(row: StockRow) -> None:
    row.forecast_profit_year1_billion_rub = None
    row.forecast_profit_year2_billion_rub = None
    row.forecast_profit_year3_billion_rub = None
    row.forecast_profit_year4_billion_rub = None
    row.net_profit_year_map = {}
    row.dividends_year1 = None
    row.dividends_year2 = None
    row.dividend_year_map = {}
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
            apply_net_profit_projection(target, table.forecast_start_year)


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
        apply_net_profit_projection(target, table.forecast_start_year)


def build_ticker_comparison_item(table: AnalystTable, row: StockRow, table_number: int) -> TickerComparisonItem:
    years = [table.forecast_start_year + i for i in range(2)]
    values = [
        (
            row.forecast_profit_year1_billion_rub,
            row.forecast_price_year1,
            row.dividends_year1,
            row.upside_percent_year1,
        ),
        (
            row.forecast_profit_year2_billion_rub,
            row.forecast_price_year2,
            row.dividends_year2,
            row.upside_percent_year2,
        ),
    ]
    return TickerComparisonItem(
        table_id=table.id,
        table_number=table_number,
        analyst_name=table.analyst_name,
        year_offset=table.year_offset,
        forecast_start_year=table.forecast_start_year,
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
                dividends_per_share=dividends,
                upside_percent=upside,
            )
            for idx, (profit, price, dividends, upside) in enumerate(values)
        ],
    )


@app.get("/api/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database is unavailable") from exc
    return {"status": "ok"}


@app.get("/api/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/auth/me")
def auth_me(request: Request):
    try:
        current_user = resolve_network_principal(request)
    except Exception:
        return {"username": "guest", "is_admin": False}

    if current_user is None:
        return {"username": "guest", "is_admin": False}
    return {"username": current_user.username, "is_admin": bool(current_user.is_admin)}


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
async def import_data(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _user: AccessPrincipal = Depends(get_current_user),
):
    try:
        raw = await file.read(MAX_IMPORT_BYTES + 1)
        if len(raw) > MAX_IMPORT_BYTES:
            raise HTTPException(status_code=413, detail="JSON-файл превышает лимит 20 МБ")
        payload = json.loads(raw.decode("utf-8"))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Не удалось прочитать JSON-файл") from exc
    result = import_database_snapshot(db, payload)
    return {**result, "ok": True, "file_path": file.filename or "uploaded.json", "detail": "Загрузка выполнена"}


@app.get("/api/tables", response_model=list[AnalystTableRead])
def get_tables(db: Session = Depends(get_db)):
    ensure_default_table(db)
    return serialize_tables(get_tables_ordered(db))


@app.post("/api/tables", response_model=AnalystTableRead)
def create_table(payload: AnalystTableCreate, db: Session = Depends(get_db), _user: AccessPrincipal = Depends(get_current_user)):
    ensure_default_table(db)
    total = db.query(AnalystTable).count()
    if total >= 10:
        raise HTTPException(status_code=400, detail="Можно создать не более 10 таблиц")
    source_table = (
        get_table_or_404(db, payload.source_table_id)
        if payload.source_table_id is not None
        else get_primary_table(db)
    )
    next_sort_order = (db.query(func.max(AnalystTable.sort_order)).scalar() or 0) + 1 if sort_order_supported else 0
    forecast_start_year = (
        source_table.forecast_start_year if source_table is not None else current_calendar_year()
    )
    table = AnalystTable(
        analyst_name=payload.analyst_name.strip(),
        year_offset=forecast_start_year - current_calendar_year(),
        forecast_start_year=forecast_start_year,
        sort_order=next_sort_order,
    )
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
                    dividends_year1=None,
                    dividends_year2=None,
                    dividend_year_map={},
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
def update_table(
    table_id: int,
    payload: AnalystTableUpdate,
    db: Session = Depends(get_db),
    _user: AccessPrincipal = Depends(get_current_user),
):
    table = get_table_or_404(db, table_id)
    if payload.analyst_name is not None:
        table.analyst_name = payload.analyst_name.strip()
    if payload.forecast_start_year is not None:
        table.forecast_start_year = payload.forecast_start_year
    elif payload.year_offset is not None:
        # Backward compatibility for old API clients. The persisted year itself
        # remains absolute and therefore cannot drift after a server restart.
        table.forecast_start_year = current_calendar_year() + payload.year_offset
    table.year_offset = table.forecast_start_year - current_calendar_year()
    db.commit()
    rows = db.scalars(select(StockRow).where(StockRow.table_id == table.id)).all()
    for row in rows:
        apply_net_profit_projection(row, table.forecast_start_year)
    db.commit()
    db.refresh(table)
    tables = get_tables_ordered(db)
    table_index = next((index for index, item in enumerate(tables, start=1) if item.id == table.id), 1)
    return serialize_table(table, table_index)


@app.delete("/api/tables/{table_id}")
def delete_table(table_id: int, db: Session = Depends(get_db), _user: AccessPrincipal = Depends(get_current_user)):
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
        apply_net_profit_projection(row, table.forecast_start_year)
        row.shared_fields_editable = is_shared_fields_editable_for_table(db, row.table_id, row.ticker)
    db.commit()
    return rows


@app.post("/api/rows", response_model=StockRowRead)
async def create_row(payload: StockRowCreate, db: Session = Depends(get_db), _user: AccessPrincipal = Depends(get_current_user)):
    table = get_table_or_404(db, payload.table_id)
    ensure_primary_table_for_row_mutation(db, table.id)
    ensure_ticker_unique(db, table.id, payload.ticker)
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
        net_profit_year_map=merge_payload_profit_map(payload, table.forecast_start_year),
        dividend_year_map=merge_payload_dividend_map(payload, table.forecast_start_year),
        net_profit_source_comment=payload.net_profit_source_comment.strip() if payload.net_profit_source_comment else None,
    )
    apply_net_profit_projection(row, table.forecast_start_year)

    await refresh_row_price(row, force=True)
    apply_net_profit_projection(row, table.forecast_start_year)
    db.add(row)
    db.commit()
    db.refresh(row)
    if shared_fields_editable:
        sync_row_to_other_tables(db, row)
    db.commit()
    row.shared_fields_editable = shared_fields_editable
    return row


@app.put("/api/rows/{row_id}", response_model=StockRowRead)
async def update_row(
    row_id: int, payload: StockRowUpdate, db: Session = Depends(get_db), _user: AccessPrincipal = Depends(get_current_user)
):
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
    if is_primary_row:
        ensure_ticker_unique(db, row.table_id, new_ticker, exclude_row_id=row.id)
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
    row.net_profit_year_map = merge_payload_profit_map(payload, table.forecast_start_year)
    row.dividend_year_map = merge_payload_dividend_map(payload, table.forecast_start_year)
    apply_net_profit_projection(row, table.forecast_start_year)
    row.net_profit_source_comment = (
        payload.net_profit_source_comment.strip() if payload.net_profit_source_comment else None
    )

    if new_ticker != old_ticker or row.current_price is None:
        await refresh_row_price(row, force=new_ticker != old_ticker)
    apply_net_profit_projection(row, table.forecast_start_year)
    if shared_fields_editable:
        sync_row_to_other_tables(db, row, old_ticker=old_ticker if old_ticker != row.ticker else None)
    sync_primary_table_multipliers(db, row)
    db.commit()
    db.refresh(row)
    row.shared_fields_editable = shared_fields_editable
    return row


@app.delete("/api/rows/{row_id}")
def delete_row(row_id: int, db: Session = Depends(get_db), _user: AccessPrincipal = Depends(get_current_user)):
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
async def refresh_prices(table_id: int, db: Session = Depends(get_db), _user: AccessPrincipal = Depends(get_current_user)):
    get_table_or_404(db, table_id)
    rows = await refresh_all_prices(db, force=True)
    tables = {table.id: table for table in get_tables_ordered(db)}
    for row in rows:
        table = tables.get(row.table_id)
        if table is not None:
            apply_net_profit_projection(row, table.forecast_start_year)
    db.commit()
    return [row for row in rows if row.table_id == table_id]


@app.post("/api/tables/{table_id}/make-primary", response_model=list[AnalystTableRead])
def make_table_primary(table_id: int, db: Session = Depends(get_db), _user: AccessPrincipal = Depends(get_current_user)):
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
        apply_net_profit_projection(row, table.forecast_start_year)
        result.append(build_ticker_comparison_item(table, row, table_number_map[table.id]))

    return result
