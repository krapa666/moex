from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean, median
from typing import Literal

from sqlalchemy import DateTime, Float, Index, Integer, String, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .database import Base
from .forecast_history import ForecastRevision

AccuracySnapshot = Literal["pre_year", "mid_year", "year_end"]


class ActualNetProfit(Base):
    __tablename__ = "actual_net_profits"
    __table_args__ = (
        UniqueConstraint("ticker", "fiscal_year", name="uq_actual_net_profit_ticker_year"),
        Index("ix_actual_net_profits_year_ticker", "fiscal_year", "ticker"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    net_profit_billion_rub: Mapped[float] = mapped_column(Float, nullable=False)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_comment: Mapped[str | None] = mapped_column(String(512), nullable=True)
    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


@dataclass(frozen=True)
class AccuracySample:
    table_id: int
    analyst_name: str
    ticker: str
    fiscal_year: int
    snapshot: AccuracySnapshot
    forecast_billion_rub: float
    actual_billion_rub: float
    forecast_created_at: datetime
    absolute_error_billion_rub: float
    smape_percent: float
    sign_correct: bool


def snapshot_cutoff(fiscal_year: int, snapshot: AccuracySnapshot) -> datetime:
    if snapshot == "pre_year":
        return datetime(fiscal_year, 1, 1, tzinfo=timezone.utc)
    if snapshot == "mid_year":
        return datetime(fiscal_year, 7, 1, tzinfo=timezone.utc)
    if snapshot == "year_end":
        return datetime(fiscal_year + 1, 1, 1, tzinfo=timezone.utc)
    raise ValueError(f"unsupported accuracy snapshot: {snapshot}")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def symmetric_absolute_percentage_error(forecast: float, actual: float) -> float:
    denominator = abs(forecast) + abs(actual)
    if denominator <= 1e-12:
        return 0.0
    return 200.0 * abs(forecast - actual) / denominator


def build_accuracy_samples(
    db: Session,
    *,
    snapshot: AccuracySnapshot = "pre_year",
) -> list[AccuracySample]:
    actuals = list(
        db.scalars(
            select(ActualNetProfit).order_by(
                ActualNetProfit.fiscal_year.asc(), ActualNetProfit.ticker.asc()
            )
        ).all()
    )
    if not actuals:
        return []

    revisions = list(
        db.scalars(
            select(ForecastRevision).order_by(
                ForecastRevision.created_at.asc(), ForecastRevision.id.asc()
            )
        ).all()
    )
    by_ticker_source: dict[tuple[str, str], list[ForecastRevision]] = {}
    for revision in revisions:
        ticker = (revision.ticker or "").strip().upper()
        analyst_name = (revision.analyst_name or "").strip()
        if not ticker or not analyst_name:
            continue
        by_ticker_source.setdefault((ticker, analyst_name), []).append(revision)

    samples: list[AccuracySample] = []
    for actual in actuals:
        ticker = actual.ticker.strip().upper()
        year_key = str(actual.fiscal_year)
        cutoff = snapshot_cutoff(actual.fiscal_year, snapshot)
        actual_value = float(actual.net_profit_billion_rub)

        for (source_ticker, analyst_name), source_revisions in by_ticker_source.items():
            if source_ticker != ticker:
                continue
            selected: ForecastRevision | None = None
            selected_value: float | None = None
            for revision in source_revisions:
                if _as_utc(revision.created_at) >= cutoff:
                    break
                value = (revision.net_profit_year_map or {}).get(year_key)
                if value is None:
                    continue
                selected = revision
                selected_value = float(value)

            if selected is None or selected_value is None:
                continue

            samples.append(
                AccuracySample(
                    table_id=selected.table_id,
                    analyst_name=analyst_name,
                    ticker=ticker,
                    fiscal_year=actual.fiscal_year,
                    snapshot=snapshot,
                    forecast_billion_rub=selected_value,
                    actual_billion_rub=actual_value,
                    forecast_created_at=_as_utc(selected.created_at),
                    absolute_error_billion_rub=abs(selected_value - actual_value),
                    smape_percent=symmetric_absolute_percentage_error(selected_value, actual_value),
                    sign_correct=_sign(selected_value) == _sign(actual_value),
                )
            )
    return samples


def aggregate_source_accuracy(
    samples: list[AccuracySample],
    *,
    min_samples: int = 5,
) -> list[dict[str, object]]:
    grouped: dict[str, list[AccuracySample]] = {}
    for sample in samples:
        grouped.setdefault(sample.analyst_name, []).append(sample)

    rows: list[dict[str, object]] = []
    for analyst_name, source_samples in grouped.items():
        smapes = [sample.smape_percent for sample in source_samples]
        absolute_errors = [sample.absolute_error_billion_rub for sample in source_samples]
        biases = [sample.forecast_billion_rub - sample.actual_billion_rub for sample in source_samples]
        latest_sample = max(source_samples, key=lambda item: item.forecast_created_at)
        eligible = len(source_samples) >= min_samples
        rows.append(
            {
                "table_id": latest_sample.table_id,
                "analyst_name": analyst_name,
                "samples": len(source_samples),
                "tickers": len({sample.ticker for sample in source_samples}),
                "years": len({sample.fiscal_year for sample in source_samples}),
                "median_smape_percent": median(smapes),
                "mean_smape_percent": mean(smapes),
                "median_absolute_error_billion_rub": median(absolute_errors),
                "mean_absolute_error_billion_rub": mean(absolute_errors),
                "mean_bias_billion_rub": mean(biases),
                "sign_accuracy_percent": 100.0
                * sum(1 for sample in source_samples if sample.sign_correct)
                / len(source_samples),
                "eligible": eligible,
                "rank": None,
            }
        )

    eligible_rows = sorted(
        (row for row in rows if bool(row["eligible"])),
        key=lambda row: (
            float(row["median_smape_percent"]),
            float(row["mean_smape_percent"]),
            -int(row["samples"]),
            str(row["analyst_name"]).casefold(),
        ),
    )
    for rank, row in enumerate(eligible_rows, start=1):
        row["rank"] = rank

    return sorted(
        rows,
        key=lambda row: (
            row["rank"] is None,
            int(row["rank"] or 10**9),
            -int(row["samples"]),
            str(row["analyst_name"]).casefold(),
        ),
    )
