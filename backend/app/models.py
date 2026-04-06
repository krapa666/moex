from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class StockRow(Base):
    __tablename__ = "stock_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    table_id: Mapped[int] = mapped_column(ForeignKey("analyst_tables.id", ondelete="CASCADE"), nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False, default="")

    current_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    shares_billion: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_cap_billion_rub: Mapped[float | None] = mapped_column(Float, nullable=True)

    pe_avg_5y: Mapped[float | None] = mapped_column(Float, nullable=True)
    forecast_profit_year1_billion_rub: Mapped[float | None] = mapped_column(Float, nullable=True)
    forecast_profit_year2_billion_rub: Mapped[float | None] = mapped_column(Float, nullable=True)
    forecast_profit_year3_billion_rub: Mapped[float | None] = mapped_column(Float, nullable=True)
    forecast_profit_year4_billion_rub: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_profit_year_map: Mapped[dict[str, float | None] | None] = mapped_column(JSON, nullable=True)
    net_profit_source_comment: Mapped[str | None] = mapped_column(String(512), nullable=True)

    forecast_price_year1: Mapped[float | None] = mapped_column(Float, nullable=True)
    forecast_price_year2: Mapped[float | None] = mapped_column(Float, nullable=True)
    forecast_price_year3: Mapped[float | None] = mapped_column(Float, nullable=True)
    forecast_price_year4: Mapped[float | None] = mapped_column(Float, nullable=True)

    upside_percent_year1: Mapped[float | None] = mapped_column(Float, nullable=True)
    upside_percent_year2: Mapped[float | None] = mapped_column(Float, nullable=True)
    upside_percent_year3: Mapped[float | None] = mapped_column(Float, nullable=True)
    upside_percent_year4: Mapped[float | None] = mapped_column(Float, nullable=True)

    status_message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    price_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AnalystTable(Base):
    __tablename__ = "analyst_tables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    analyst_name: Mapped[str] = mapped_column(String(100), nullable=False, default="Аналитик 1")
    year_offset: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
