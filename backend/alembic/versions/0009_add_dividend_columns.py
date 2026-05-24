"""add dividend columns

Revision ID: 0009_add_dividend_columns
Revises: 0008_auth_tables
Create Date: 2026-04-23
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0009_add_dividend_columns"
down_revision = "0008_auth_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stock_rows", sa.Column("dividends_year1", sa.Float(), nullable=True))
    op.add_column("stock_rows", sa.Column("dividends_year2", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("stock_rows", "dividends_year2")
    op.drop_column("stock_rows", "dividends_year1")
