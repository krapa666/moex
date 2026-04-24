"""add remaining previous-year dividends columns

Revision ID: 0010_remaining_dividends
Revises: 0009_add_dividend_columns
Create Date: 2026-04-24
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_remaining_dividends"
down_revision = "0009_add_dividend_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stock_rows", sa.Column("remaining_dividends_prev_year1", sa.Float(), nullable=True))
    op.add_column("stock_rows", sa.Column("remaining_dividends_prev_year2", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("stock_rows", "remaining_dividends_prev_year2")
    op.drop_column("stock_rows", "remaining_dividends_prev_year1")
