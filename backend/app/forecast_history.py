from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String, event, insert, inspect, select
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base

_HISTORY_SUPPRESSION_KEY = "moex_suppress_forecast_history"


class ForecastRevision(Base):
    __tablename__ = "forecast_revisions"
    __table_args__ = (
        Index("ix_forecast_revisions_ticker_created_at", "ticker", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_row_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    table_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    analyst_name: Mapped[str] = mapped_column(String(100), nullable=False)
    forecast_start_year: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    changed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)

    shares_billion: Mapped[float | None] = mapped_column(Float, nullable=True)
    pe_avg_5y: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_profit_year_map: Mapped[dict[str, float | None] | None] = mapped_column(JSON, nullable=True)
    dividend_year_map: Mapped[dict[str, float | None] | None] = mapped_column(JSON, nullable=True)
    net_profit_source_comment: Mapped[str | None] = mapped_column(String(512), nullable=True)
    forecast_price_year1: Mapped[float | None] = mapped_column(Float, nullable=True)
    forecast_price_year2: Mapped[float | None] = mapped_column(Float, nullable=True)
    upside_percent_year1: Mapped[float | None] = mapped_column(Float, nullable=True)
    upside_percent_year2: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    @staticmethod
    @contextmanager
    def suppress_capture(connection):
        """Temporarily disable revision capture for bulk state replacement."""
        marker = object()
        previous = connection.info.get(_HISTORY_SUPPRESSION_KEY, marker)
        connection.info[_HISTORY_SUPPRESSION_KEY] = True
        try:
            yield
        finally:
            if previous is marker:
                connection.info.pop(_HISTORY_SUPPRESSION_KEY, None)
            else:
                connection.info[_HISTORY_SUPPRESSION_KEY] = previous


# Import the stock models only after ForecastRevision exists. models.py imports this
# class at module teardown so Alembic can discover the history table; importing the
# models earlier creates a cycle when production starts via app.application.
from .models import AnalystTable, StockRow  # noqa: E402,I001


_DIRECT_FORECAST_FIELDS = (
    "ticker",
    "shares_billion",
    "pe_avg_5y",
    "net_profit_year_map",
    "dividend_year_map",
    "net_profit_source_comment",
)
_MAP_OR_COMMENT_FIELDS = (
    "net_profit_year_map",
    "dividend_year_map",
    "net_profit_source_comment",
)


def _history_suppressed(connection) -> bool:
    return bool(connection.info.get(_HISTORY_SUPPRESSION_KEY))


def _has_forecast_content(row: StockRow) -> bool:
    profit_map = row.net_profit_year_map or {}
    dividend_map = row.dividend_year_map or {}
    return (
        any(value is not None for value in profit_map.values())
        or any(value is not None for value in dividend_map.values())
        or bool((row.net_profit_source_comment or "").strip())
    )


def _material_change(row: StockRow) -> bool:
    state = inspect(row)
    changed = {name for name in _DIRECT_FORECAST_FIELDS if state.attrs[name].history.has_changes()}
    if not changed:
        return False
    if changed.intersection(_MAP_OR_COMMENT_FIELDS):
        return True
    return _has_forecast_content(row)


def _table_snapshot(connection, table_id: int) -> tuple[str, int] | None:
    statement = select(AnalystTable.analyst_name, AnalystTable.forecast_start_year).where(
        AnalystTable.id == table_id
    )
    result = connection.execute(statement).first()
    if result is None:
        return None
    return str(result.analyst_name), int(result.forecast_start_year)


def _remaining_dividends(row: StockRow, target_year: int) -> float:
    current_year = datetime.now(timezone.utc).year
    if target_year < current_year:
        return 0.0
    dividend_map = row.dividend_year_map or {}
    total = sum(
        float(dividend_map.get(str(year)) or 0.0)
        for year in range(current_year, target_year + 1)
    )
    if row.paid_dividend_year_map is None:
        return max(total - float(dividend_map.get(str(current_year)) or 0.0), 0.0)
    paid_current = float(row.paid_dividend_year_map.get(str(current_year)) or 0.0)
    full_current = float(dividend_map.get(str(current_year)) or 0.0)
    return max(total - min(full_current, paid_current), 0.0)


def _derived_values(
    row: StockRow,
    forecast_start_year: int,
) -> tuple[float | None, float | None, float | None, float | None]:
    profit_map = row.net_profit_year_map or {}
    prices: list[float | None] = []
    upsides: list[float | None] = []

    for year_index in range(2):
        target_year = forecast_start_year + year_index
        profit = profit_map.get(str(target_year))
        if (
            profit is not None
            and row.pe_avg_5y is not None
            and row.shares_billion is not None
            and row.shares_billion > 0
        ):
            forecast_price = float(profit) * row.pe_avg_5y / row.shares_billion
        else:
            forecast_price = None
        prices.append(forecast_price)

        if forecast_price is not None and row.current_price is not None and row.current_price > 0:
            dividends = _remaining_dividends(row, target_year)
            upside = ((forecast_price - row.current_price + dividends) / row.current_price) * 100
        else:
            upside = None
        upsides.append(upside)

    return prices[0], prices[1], upsides[0], upsides[1]


def _insert_revision(connection, row: StockRow, event_type: str) -> None:
    ticker = (row.ticker or "").strip().upper()
    if not ticker:
        return

    table = _table_snapshot(connection, row.table_id)
    if table is None:
        return
    analyst_name, forecast_start_year = table
    forecast_price_year1, forecast_price_year2, upside_year1, upside_year2 = _derived_values(
        row,
        forecast_start_year,
    )

    connection.execute(
        insert(ForecastRevision).values(
            stock_row_id=row.id,
            table_id=row.table_id,
            ticker=ticker,
            analyst_name=analyst_name,
            forecast_start_year=forecast_start_year,
            event_type=event_type,
            changed_by=getattr(row, "_forecast_changed_by", None) or "local-network",
            shares_billion=row.shares_billion,
            pe_avg_5y=row.pe_avg_5y,
            current_price=row.current_price,
            net_profit_year_map=dict(row.net_profit_year_map or {}),
            dividend_year_map=dict(row.dividend_year_map or {}),
            net_profit_source_comment=row.net_profit_source_comment,
            forecast_price_year1=forecast_price_year1,
            forecast_price_year2=forecast_price_year2,
            upside_percent_year1=upside_year1,
            upside_percent_year2=upside_year2,
            created_at=datetime.now(timezone.utc),
        )
    )


@event.listens_for(StockRow, "after_insert")
def _record_created_forecast(_mapper, connection, row: StockRow) -> None:
    if _history_suppressed(connection):
        return
    if _has_forecast_content(row):
        _insert_revision(connection, row, "created")


@event.listens_for(StockRow, "after_update")
def _record_updated_forecast(_mapper, connection, row: StockRow) -> None:
    if _history_suppressed(connection):
        return
    if _material_change(row):
        _insert_revision(connection, row, "updated")
