import asyncio
import contextlib

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import SessionLocal, get_db
from .models import StockRow
from .schemas import StockRowCreate, StockRowRead, StockRowUpdate
from .services import refresh_all_prices, refresh_row_price

app = FastAPI(title="MOEX Fair Price", version="1.0.0")
price_refresh_task: asyncio.Task | None = None

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
        await asyncio.sleep(60)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/rows", response_model=list[StockRowRead])
def get_rows(db: Session = Depends(get_db)):
    rows = db.scalars(select(StockRow).order_by(StockRow.id.asc())).all()
    return rows


@app.post("/api/rows", response_model=StockRowRead)
async def create_row(payload: StockRowCreate, db: Session = Depends(get_db)):
    row = StockRow(
        ticker=payload.ticker.strip().upper(),
        shares_billion=payload.shares_billion,
        pe_avg_5y=payload.pe_avg_5y,
        forecast_profit_year1_billion_rub=payload.forecast_profit_year1_billion_rub,
        forecast_profit_year2_billion_rub=payload.forecast_profit_year2_billion_rub,
        forecast_profit_year3_billion_rub=payload.forecast_profit_year3_billion_rub,
        net_profit_source_comment=payload.net_profit_source_comment.strip() if payload.net_profit_source_comment else None,
    )

    await refresh_row_price(row, force=True)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@app.put("/api/rows/{row_id}", response_model=StockRowRead)
async def update_row(row_id: int, payload: StockRowUpdate, db: Session = Depends(get_db)):
    row = db.get(StockRow, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Строка не найдена")

    row.ticker = payload.ticker.strip().upper()
    row.shares_billion = payload.shares_billion
    row.pe_avg_5y = payload.pe_avg_5y
    row.forecast_profit_year1_billion_rub = payload.forecast_profit_year1_billion_rub
    row.forecast_profit_year2_billion_rub = payload.forecast_profit_year2_billion_rub
    row.forecast_profit_year3_billion_rub = payload.forecast_profit_year3_billion_rub
    row.net_profit_source_comment = (
        payload.net_profit_source_comment.strip() if payload.net_profit_source_comment else None
    )

    await refresh_row_price(row, force=bool(row.ticker))
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
async def refresh_prices(db: Session = Depends(get_db)):
    return await refresh_all_prices(db, force=True)
