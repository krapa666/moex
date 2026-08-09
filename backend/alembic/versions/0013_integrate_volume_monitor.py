"""integrate the IMOEX volume monitor

Revision ID: 0013_integrate_volume_monitor
Revises: 0012_forecast_start_year
Create Date: 2026-08-09
"""

import sqlalchemy as sa
from alembic import op

revision = "0013_integrate_volume_monitor"
down_revision = "0012_forecast_start_year"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "volume_securities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("short_name", sa.String(length=255), nullable=False),
        sa.Column("weight", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker"),
    )
    op.create_index(
        op.f("ix_volume_securities_active"),
        "volume_securities",
        ["active"],
        unique=False,
    )
    op.create_index(
        op.f("ix_volume_securities_ticker"),
        "volume_securities",
        ["ticker"],
        unique=True,
    )

    op.create_table(
        "volume_collection_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("securities_total", sa.Integer(), nullable=False),
        sa.Column("securities_updated", sa.Integer(), nullable=False),
        sa.Column("signals_found", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_volume_collection_runs_started_at"),
        "volume_collection_runs",
        ["started_at"],
        unique=False,
    )

    op.create_table(
        "volume_monitor_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("notification_email", sa.String(length=320), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "volume_notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("security_id", sa.Integer(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recipient", sa.String(length=320), nullable=False),
        sa.Column("ratio", sa.Numeric(precision=14, scale=6), nullable=False),
        sa.ForeignKeyConstraint(["security_id"], ["volume_securities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "security_id",
            "trade_date",
            name="uq_volume_notification_security_date",
        ),
    )

    op.create_table(
        "volume_observations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("security_id", sa.Integer(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("turnover_rub", sa.Numeric(precision=22, scale=2), nullable=False),
        sa.Column("volume_units", sa.BigInteger(), nullable=True),
        sa.Column("close_price", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("baseline_average_rub", sa.Numeric(precision=22, scale=2), nullable=True),
        sa.Column("baseline_count", sa.Integer(), nullable=False),
        sa.Column("ratio", sa.Numeric(precision=14, scale=6), nullable=True),
        sa.Column("signal_status", sa.String(length=24), nullable=False),
        sa.Column("is_final", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["security_id"], ["volume_securities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "security_id",
            "trade_date",
            name="uq_volume_observation_security_date",
        ),
    )
    op.create_index(
        "ix_volume_observation_security_date",
        "volume_observations",
        ["security_id", "trade_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_volume_observation_security_date", table_name="volume_observations")
    op.drop_table("volume_observations")
    op.drop_table("volume_notifications")
    op.drop_table("volume_monitor_settings")
    op.drop_index(
        op.f("ix_volume_collection_runs_started_at"),
        table_name="volume_collection_runs",
    )
    op.drop_table("volume_collection_runs")
    op.drop_index(op.f("ix_volume_securities_ticker"), table_name="volume_securities")
    op.drop_index(op.f("ix_volume_securities_active"), table_name="volume_securities")
    op.drop_table("volume_securities")
