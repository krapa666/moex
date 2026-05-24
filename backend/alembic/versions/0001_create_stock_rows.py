"""create stock_rows table

Revision ID: 0001_create_stock_rows
Revises:
Create Date: 2026-03-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_create_stock_rows"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stock_rows",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("current_price", sa.Float(), nullable=True),
        sa.Column("shares_billion", sa.Float(), nullable=True),
        sa.Column("market_cap_billion_rub", sa.Float(), nullable=True),
        sa.Column("pe_avg_5y", sa.Float(), nullable=True),
        sa.Column("forecast_profit_billion_rub", sa.Float(), nullable=True),
        sa.Column("forecast_price", sa.Float(), nullable=True),
        sa.Column("upside_percent", sa.Float(), nullable=True),
        sa.Column("status_message", sa.String(length=255), nullable=True),
        sa.Column("price_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_stock_rows_id"), "stock_rows", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_stock_rows_id"), table_name="stock_rows")
    op.drop_table("stock_rows")
