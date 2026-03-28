from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import QuoteRequest
from app.moex import MoexPriceNotFoundError, MoexTickerNotFoundError, get_current_price
from app.schemas import QuoteResponse

app = FastAPI(title="MOEX Fair Price App")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

quote_requests_total = Counter(
    "quote_requests_total",
    "Total number of quote requests",
    ["status"],
)
quote_request_latency = Histogram(
    "quote_request_duration_seconds",
    "Latency of quote requests",
)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/quote/{ticker}", response_model=QuoteResponse)
def get_quote(ticker: str, db: Session = Depends(get_db)):
    with quote_request_latency.time():
        try:
            quote = get_current_price(ticker)
        except MoexTickerNotFoundError as exc:
            quote_requests_total.labels(status="not_found").inc()
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except MoexPriceNotFoundError as exc:
            quote_requests_total.labels(status="no_price").inc()
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            quote_requests_total.labels(status="error").inc()
            raise HTTPException(status_code=502, detail=f"Ошибка получения данных MOEX: {exc}") from exc

        db_record = QuoteRequest(
            ticker=quote["ticker"],
            board=quote["board"],
            price=quote["price"],
            currency=quote["currency"],
        )
        db.add(db_record)
        db.commit()

        quote_requests_total.labels(status="ok").inc()
        return quote


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)
