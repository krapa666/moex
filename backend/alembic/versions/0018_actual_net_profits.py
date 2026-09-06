"""add actual annual net profit ledger

Revision ID: 0018_actual_net_profits
Revises: 0017_paid_dividend_year_map
Create Date: 2026-09-06
"""

import sqlalchemy as sa
from alembic import op

revision = "0018_actual_net_profits"
down_revision = "0017_paid_dividend_year_map"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "actual_net_profits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("net_profit_billion_rub", sa.Float(), nullable=False),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("source_url", sa.String(length=1024), nullable=True),
        sa.Column("source_comment", sa.String(length=512), nullable=True),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker", "fiscal_year", name="uq_actual_net_profit_ticker_year"),
    )
    op.create_index(
        "ix_actual_net_profits_ticker",
        "actual_net_profits",
        ["ticker"],
        unique=False,
    )
    op.create_index(
        "ix_actual_net_profits_fiscal_year",
        "actual_net_profits",
        ["fiscal_year"],
        unique=False,
    )
    op.create_index(
        "ix_actual_net_profits_year_ticker",
        "actual_net_profits",
        ["fiscal_year", "ticker"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_actual_net_profits_year_ticker", table_name="actual_net_profits")
    op.drop_index("ix_actual_net_profits_fiscal_year", table_name="actual_net_profits")
    op.drop_index("ix_actual_net_profits_ticker", table_name="actual_net_profits")
    op.drop_table("actual_net_profits")
