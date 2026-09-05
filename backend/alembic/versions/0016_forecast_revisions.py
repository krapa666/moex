"""add append-only forecast revision history

Revision ID: 0016_forecast_revisions
Revises: 0015_reliable_alerts
Create Date: 2026-09-05
"""

import sqlalchemy as sa
from alembic import op

revision = "0016_forecast_revisions"
down_revision = "0015_reliable_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "forecast_revisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stock_row_id", sa.Integer(), nullable=True),
        sa.Column("table_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("analyst_name", sa.String(length=100), nullable=False),
        sa.Column("forecast_start_year", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=16), nullable=False),
        sa.Column("changed_by", sa.String(length=64), nullable=True),
        sa.Column("shares_billion", sa.Float(), nullable=True),
        sa.Column("pe_avg_5y", sa.Float(), nullable=True),
        sa.Column("current_price", sa.Float(), nullable=True),
        sa.Column("net_profit_year_map", sa.JSON(), nullable=True),
        sa.Column("dividend_year_map", sa.JSON(), nullable=True),
        sa.Column("net_profit_source_comment", sa.String(length=512), nullable=True),
        sa.Column("forecast_price_year1", sa.Float(), nullable=True),
        sa.Column("forecast_price_year2", sa.Float(), nullable=True),
        sa.Column("upside_percent_year1", sa.Float(), nullable=True),
        sa.Column("upside_percent_year2", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_forecast_revisions_stock_row_id", "forecast_revisions", ["stock_row_id"])
    op.create_index("ix_forecast_revisions_table_id", "forecast_revisions", ["table_id"])
    op.create_index("ix_forecast_revisions_ticker", "forecast_revisions", ["ticker"])
    op.create_index("ix_forecast_revisions_created_at", "forecast_revisions", ["created_at"])
    op.create_index(
        "ix_forecast_revisions_ticker_created_at",
        "forecast_revisions",
        ["ticker", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_forecast_revisions_ticker_created_at", table_name="forecast_revisions")
    op.drop_index("ix_forecast_revisions_created_at", table_name="forecast_revisions")
    op.drop_index("ix_forecast_revisions_ticker", table_name="forecast_revisions")
    op.drop_index("ix_forecast_revisions_table_id", table_name="forecast_revisions")
    op.drop_index("ix_forecast_revisions_stock_row_id", table_name="forecast_revisions")
    op.drop_table("forecast_revisions")
