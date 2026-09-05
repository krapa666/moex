"""store passed dividend payments separately

Revision ID: 0017_paid_dividend_year_map
Revises: 0016_forecast_revisions
Create Date: 2026-09-05
"""

import sqlalchemy as sa
from alembic import op

revision = "0017_paid_dividend_year_map"
down_revision = "0016_forecast_revisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stock_rows", sa.Column("paid_dividend_year_map", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("stock_rows", "paid_dividend_year_map")
