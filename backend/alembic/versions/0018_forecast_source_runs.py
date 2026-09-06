"""track forecast source sync runs

Revision ID: 0018_forecast_source_runs
Revises: 0017_paid_dividend_year_map
Create Date: 2026-09-06
"""

import sqlalchemy as sa
from alembic import op

revision = "0018_forecast_source_runs"
down_revision = "0017_paid_dividend_year_map"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "forecast_source_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_key", sa.String(length=64), nullable=False),
        sa.Column("analyst_name", sa.String(length=100), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("tables", sa.Integer(), nullable=False),
        sa.Column("tickers_total", sa.Integer(), nullable=False),
        sa.Column("tickers_mapped", sa.Integer(), nullable=False),
        sa.Column("tickers_updated", sa.Integer(), nullable=False),
        sa.Column("tickers_unchanged", sa.Integer(), nullable=False),
        sa.Column("tickers_skipped", sa.Integer(), nullable=False),
        sa.Column("table_created", sa.Boolean(), nullable=False),
        sa.Column("error_details", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_forecast_source_runs_source_started",
        "forecast_source_runs",
        ["source_key", "started_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_forecast_source_runs_analyst_name"),
        "forecast_source_runs",
        ["analyst_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_forecast_source_runs_source_key"),
        "forecast_source_runs",
        ["source_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_forecast_source_runs_started_at"),
        "forecast_source_runs",
        ["started_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_forecast_source_runs_status"),
        "forecast_source_runs",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_forecast_source_runs_status"), table_name="forecast_source_runs")
    op.drop_index(op.f("ix_forecast_source_runs_started_at"), table_name="forecast_source_runs")
    op.drop_index(op.f("ix_forecast_source_runs_source_key"), table_name="forecast_source_runs")
    op.drop_index(op.f("ix_forecast_source_runs_analyst_name"), table_name="forecast_source_runs")
    op.drop_index("ix_forecast_source_runs_source_started", table_name="forecast_source_runs")
    op.drop_table("forecast_source_runs")
