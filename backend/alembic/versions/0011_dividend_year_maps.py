"""add dividend year maps

Revision ID: 0011_dividend_year_maps
Revises: 0010_remaining_dividends
Create Date: 2026-04-28
"""

from alembic import op
import sqlalchemy as sa


revision = "0011_dividend_year_maps"
down_revision = "0010_remaining_dividends"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stock_rows", sa.Column("dividend_year_map", sa.JSON(), nullable=True))
    op.add_column("stock_rows", sa.Column("remaining_dividend_year_map", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("stock_rows", "remaining_dividend_year_map")
    op.drop_column("stock_rows", "dividend_year_map")
