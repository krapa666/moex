from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
    dividends_year1: Mapped[float | None] = mapped_column(Float, nullable=True)
    dividends_year2: Mapped[float | None] = mapped_column(Float, nullable=True)
    dividend_year_map: Mapped[dict[str, float | None] | None] = mapped_column(JSON, nullable=True)

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
    forecast_start_year: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=lambda: datetime.now(timezone.utc).year,
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VolumeSecurity(Base):
    __tablename__ = "volume_securities"
    __table_args__ = (
        CheckConstraint(
            "security_type IN ('common', 'preferred')",
            name="ck_volume_securities_security_type",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    short_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    security_type: Mapped[str] = mapped_column(String(16), nullable=False, default="common")
    is_imoex: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    weight: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    observations: Mapped[list["VolumeObservation"]] = relationship(
        back_populates="security",
        cascade="all, delete-orphan",
    )


class VolumeObservation(Base):
    __tablename__ = "volume_observations"
    __table_args__ = (
        UniqueConstraint(
            "security_id",
            "trade_date",
            name="uq_volume_observation_security_date",
        ),
        Index("ix_volume_observation_security_date", "security_id", "trade_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("volume_securities.id", ondelete="CASCADE"),
        nullable=False,
    )
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    turnover_rub: Mapped[Decimal] = mapped_column(Numeric(22, 2), nullable=False)
    volume_units: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    close_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    baseline_average_rub: Mapped[Decimal | None] = mapped_column(Numeric(22, 2), nullable=True)
    baseline_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ratio: Mapped[Decimal | None] = mapped_column(Numeric(14, 6), nullable=True)
    signal_status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="insufficient",
    )
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source: Mapped[str] = mapped_column(String(24), nullable=False, default="history")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    security: Mapped[VolumeSecurity] = relationship(back_populates="observations")


class VolumeNotification(Base):
    __tablename__ = "volume_notifications"
    __table_args__ = (
        UniqueConstraint(
            "security_id",
            "trade_date",
            name="uq_volume_notification_security_date",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("volume_securities.id", ondelete="CASCADE"),
        nullable=False,
    )
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recipient: Mapped[str] = mapped_column(String(320), nullable=False)
    ratio: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)


class VolumeCollectionRun(Base):
    __tablename__ = "volume_collection_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="running")
    securities_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    securities_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    signals_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    imoex_anomalies_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notifications_suppressed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notifications_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    history_securities_refreshed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class VolumeMonitorSettings(Base):
    __tablename__ = "volume_monitor_settings"
    __table_args__ = (
        CheckConstraint(
            "notification_scope IN ('imoex', 'all')",
            name="ck_volume_monitor_settings_notification_scope",
        ),
        CheckConstraint(
            "baseline_sessions BETWEEN 10 AND 250",
            name="ck_volume_monitor_settings_baseline_sessions",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    notification_scope: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="imoex",
        server_default="imoex",
    )
    baseline_sessions: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=60,
        server_default="60",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
