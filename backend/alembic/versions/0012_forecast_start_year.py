"""store an absolute forecast start year

Revision ID: 0012_forecast_start_year
Revises: 0011_dividend_year_maps
Create Date: 2026-08-08
"""

import sqlalchemy as sa
from alembic import op

revision = "0012_forecast_start_year"
down_revision = "0011_dividend_year_maps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("analyst_tables", sa.Column("forecast_start_year", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE analyst_tables
        SET forecast_start_year = EXTRACT(YEAR FROM CURRENT_DATE)::INTEGER + COALESCE(year_offset, 0)
        """
    )
    op.alter_column("analyst_tables", "forecast_start_year", nullable=False)


def downgrade() -> None:
    op.drop_column("analyst_tables", "forecast_start_year")
