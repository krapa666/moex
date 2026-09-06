from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, SessionLocal


class ForecastSourceRun(Base):
    __tablename__ = "forecast_source_runs"
    __table_args__ = (
        Index("ix_forecast_source_runs_source_started", "source_key", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    analyst_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running", index=True)
    tables: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tickers_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tickers_mapped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tickers_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tickers_unchanged: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tickers_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    table_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_details: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


def start_forecast_source_run(*, source_key: str, analyst_name: str) -> int:
    now = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        run = ForecastSourceRun(
            source_key=source_key,
            analyst_name=analyst_name,
            started_at=now,
            status="running",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run.id
    finally:
        db.close()


def complete_forecast_source_run(
    run_id: int,
    *,
    status: str,
    tables: int,
    tickers_total: int,
    tickers_mapped: int,
    tickers_updated: int,
    tickers_unchanged: int,
    tickers_skipped: int,
    table_created: bool,
    error_details: dict[str, str] | None,
) -> None:
    db = SessionLocal()
    try:
        run = db.get(ForecastSourceRun, run_id)
        if run is None:
            return
        run.finished_at = datetime.now(timezone.utc)
        run.status = status
        run.tables = tables
        run.tickers_total = tickers_total
        run.tickers_mapped = tickers_mapped
        run.tickers_updated = tickers_updated
        run.tickers_unchanged = tickers_unchanged
        run.tickers_skipped = tickers_skipped
        run.table_created = table_created
        run.error_details = dict(error_details or {}) or None
        run.error_message = None
        db.commit()
    finally:
        db.close()


def fail_forecast_source_run(run_id: int, error: Exception) -> None:
    db = SessionLocal()
    try:
        run = db.get(ForecastSourceRun, run_id)
        if run is None:
            return
        run.finished_at = datetime.now(timezone.utc)
        run.status = "failed"
        run.error_message = (str(error) or error.__class__.__name__)[:4000]
        db.commit()
    finally:
        db.close()
