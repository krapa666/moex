from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .forecast_accuracy import AccuracySnapshot, ActualNetProfit, snapshot_cutoff
from .forecast_history import ForecastRevision


@dataclass(frozen=True)
class ForecastCoverageCandidate:
    table_id: int
    analyst_name: str
    ticker: str
    fiscal_year: int


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _coverage_percent(covered: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return 100.0 * covered / total


def build_actual_result_coverage(
    db: Session,
    *,
    snapshot: AccuracySnapshot = "pre_year",
    start_year: int,
    end_year: int,
    missing_limit: int = 50,
) -> dict[str, object]:
    """Measure how much historical forecast evidence has a canonical actual result.

    The denominator contains one candidate per source/ticker/fiscal-year when that
    source had a finite forecast available before the selected snapshot cutoff.
    Actual results are then matched by ticker and fiscal year. Future/incomplete
    years are intentionally kept out by the API layer.
    """

    if start_year > end_year:
        raise ValueError("start_year must not be greater than end_year")
    if missing_limit < 0:
        raise ValueError("missing_limit must be non-negative")

    actuals = list(
        db.scalars(
            select(ActualNetProfit)
            .where(
                ActualNetProfit.fiscal_year >= start_year,
                ActualNetProfit.fiscal_year <= end_year,
            )
            .order_by(ActualNetProfit.fiscal_year.asc(), ActualNetProfit.ticker.asc())
        ).all()
    )
    actual_keys = {
        (actual.ticker.strip().upper(), int(actual.fiscal_year))
        for actual in actuals
        if (actual.ticker or "").strip()
    }

    revisions = list(
        db.scalars(
            select(ForecastRevision).order_by(
                ForecastRevision.created_at.asc(), ForecastRevision.id.asc()
            )
        ).all()
    )

    candidates: dict[tuple[int, str, str, int], ForecastCoverageCandidate] = {}
    for revision in revisions:
        ticker = (revision.ticker or "").strip().upper()
        analyst_name = (revision.analyst_name or "").strip()
        if not ticker or not analyst_name:
            continue

        created_at = _as_utc(revision.created_at)
        for raw_year, raw_value in (revision.net_profit_year_map or {}).items():
            if raw_value is None:
                continue
            try:
                fiscal_year = int(raw_year)
                forecast_value = float(raw_value)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(forecast_value):
                continue
            if fiscal_year < start_year or fiscal_year > end_year:
                continue
            if created_at >= snapshot_cutoff(fiscal_year, snapshot):
                continue

            key = (int(revision.table_id), analyst_name, ticker, fiscal_year)
            candidates[key] = ForecastCoverageCandidate(
                table_id=int(revision.table_id),
                analyst_name=analyst_name,
                ticker=ticker,
                fiscal_year=fiscal_year,
            )

    candidate_rows = list(candidates.values())
    covered_rows = [
        row for row in candidate_rows if (row.ticker, row.fiscal_year) in actual_keys
    ]
    missing_rows = [
        row for row in candidate_rows if (row.ticker, row.fiscal_year) not in actual_keys
    ]

    actuals_by_year: dict[int, int] = {}
    for actual in actuals:
        actuals_by_year[int(actual.fiscal_year)] = actuals_by_year.get(int(actual.fiscal_year), 0) + 1

    by_year: list[dict[str, object]] = []
    for fiscal_year in range(end_year, start_year - 1, -1):
        year_rows = [row for row in candidate_rows if row.fiscal_year == fiscal_year]
        covered = sum(
            1 for row in year_rows if (row.ticker, row.fiscal_year) in actual_keys
        )
        actual_records = actuals_by_year.get(fiscal_year, 0)
        if not year_rows and not actual_records:
            continue
        total = len(year_rows)
        by_year.append(
            {
                "fiscal_year": fiscal_year,
                "forecast_pairs": total,
                "covered_pairs": covered,
                "missing_forecast_pairs": total - covered,
                "coverage_percent": _coverage_percent(covered, total),
                "actual_records": actual_records,
            }
        )

    source_groups: dict[tuple[int, str], list[ForecastCoverageCandidate]] = {}
    for row in candidate_rows:
        source_groups.setdefault((row.table_id, row.analyst_name), []).append(row)

    by_source: list[dict[str, object]] = []
    for (table_id, analyst_name), source_rows in source_groups.items():
        covered = sum(
            1 for row in source_rows if (row.ticker, row.fiscal_year) in actual_keys
        )
        total = len(source_rows)
        by_source.append(
            {
                "table_id": table_id,
                "analyst_name": analyst_name,
                "forecast_pairs": total,
                "covered_pairs": covered,
                "missing_forecast_pairs": total - covered,
                "coverage_percent": _coverage_percent(covered, total),
                "tickers": len({row.ticker for row in source_rows}),
                "years": len({row.fiscal_year for row in source_rows}),
            }
        )
    by_source.sort(
        key=lambda row: (
            -int(row["missing_forecast_pairs"]),
            float(row["coverage_percent"]),
            str(row["analyst_name"]).casefold(),
        )
    )

    missing_groups: dict[tuple[str, int], set[tuple[int, str]]] = {}
    for row in missing_rows:
        missing_groups.setdefault((row.ticker, row.fiscal_year), set()).add(
            (row.table_id, row.analyst_name)
        )
    missing_actuals = [
        {
            "ticker": ticker,
            "fiscal_year": fiscal_year,
            "sources": len(sources),
        }
        for (ticker, fiscal_year), sources in missing_groups.items()
    ]
    missing_actuals.sort(
        key=lambda row: (-int(row["sources"]), -int(row["fiscal_year"]), str(row["ticker"]))
    )
    if missing_limit:
        missing_actuals = missing_actuals[:missing_limit]
    else:
        missing_actuals = []

    total = len(candidate_rows)
    covered = len(covered_rows)
    return {
        "snapshot": snapshot,
        "start_year": start_year,
        "end_year": end_year,
        "forecast_pairs": total,
        "covered_pairs": covered,
        "missing_forecast_pairs": total - covered,
        "missing_actual_records": len(missing_groups),
        "coverage_percent": _coverage_percent(covered, total),
        "forecast_tickers": len({row.ticker for row in candidate_rows}),
        "covered_tickers": len({row.ticker for row in covered_rows}),
        "actual_records": len(actuals),
        "actual_tickers": len({ticker for ticker, _year in actual_keys}),
        "by_year": by_year,
        "by_source": by_source,
        "missing_actuals": missing_actuals,
    }
