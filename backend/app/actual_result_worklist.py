from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .forecast_accuracy import ActualNetProfit
from .main import get_primary_table
from .models import StockRow

WORKLIST_COLUMNS = (
    "ticker",
    "fiscal_year",
    "net_profit_billion_rub",
    "source_name",
    "source_url",
    "reported_at",
    "source_comment",
)


@dataclass(frozen=True)
class ActualResultWorklistItem:
    ticker: str
    fiscal_year: int


def _primary_tickers(db: Session) -> tuple[int | None, list[str]]:
    primary = get_primary_table(db)
    if primary is None:
        return None, []
    tickers = sorted(
        {
            str(ticker or "").strip().upper()
            for ticker in db.scalars(
                select(StockRow.ticker).where(StockRow.table_id == primary.id)
            ).all()
            if str(ticker or "").strip()
        }
    )
    return primary.id, tickers


def build_actual_result_worklist(
    db: Session,
    *,
    years: int = 5,
    end_year: int,
) -> dict[str, object]:
    years = max(1, min(int(years), 20))
    end_year = int(end_year)
    start_year = end_year - years + 1

    primary_table_id, tickers = _primary_tickers(db)
    ticker_set = set(tickers)
    existing_rows = list(
        db.scalars(
            select(ActualNetProfit).where(
                ActualNetProfit.fiscal_year >= start_year,
                ActualNetProfit.fiscal_year <= end_year,
            )
        ).all()
    )
    existing = {
        (row.ticker.strip().upper(), int(row.fiscal_year))
        for row in existing_rows
        if row.ticker and row.ticker.strip().upper() in ticker_set
    }

    missing: list[ActualResultWorklistItem] = []
    by_year: list[dict[str, object]] = []
    for fiscal_year in range(start_year, end_year + 1):
        year_expected = len(tickers)
        year_existing = sum(1 for ticker in tickers if (ticker, fiscal_year) in existing)
        year_missing = year_expected - year_existing
        by_year.append(
            {
                "fiscal_year": fiscal_year,
                "expected_pairs": year_expected,
                "existing_pairs": year_existing,
                "missing_pairs": year_missing,
                "coverage_percent": round(100.0 * year_existing / year_expected, 2)
                if year_expected
                else 0.0,
            }
        )
        missing.extend(
            ActualResultWorklistItem(ticker=ticker, fiscal_year=fiscal_year)
            for ticker in tickers
            if (ticker, fiscal_year) not in existing
        )

    expected_pairs = len(tickers) * years
    existing_pairs = expected_pairs - len(missing)
    return {
        "primary_table_id": primary_table_id,
        "start_year": start_year,
        "end_year": end_year,
        "years": years,
        "primary_tickers": len(tickers),
        "expected_pairs": expected_pairs,
        "existing_pairs": existing_pairs,
        "missing_pairs": len(missing),
        "coverage_percent": round(100.0 * existing_pairs / expected_pairs, 2)
        if expected_pairs
        else 0.0,
        "by_year": by_year,
        "missing": [
            {"ticker": item.ticker, "fiscal_year": item.fiscal_year}
            for item in missing
        ],
    }


def render_actual_result_worklist_csv(worklist: dict[str, object]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=WORKLIST_COLUMNS, delimiter=";")
    writer.writeheader()
    for item in worklist.get("missing", []):
        if not isinstance(item, dict):
            continue
        writer.writerow(
            {
                "ticker": item.get("ticker", ""),
                "fiscal_year": item.get("fiscal_year", ""),
                "net_profit_billion_rub": "",
                "source_name": "",
                "source_url": "",
                "reported_at": "",
                "source_comment": "",
            }
        )
    return "\ufeff" + buffer.getvalue()
