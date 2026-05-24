"""add three-year forecast columns

Revision ID: 0002_three_year_forecast
Revises: 0001_create_stock_rows
Create Date: 2026-03-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_three_year_forecast"
down_revision: Union[str, None] = "0001_create_stock_rows"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("stock_rows", sa.Column("forecast_profit_year1_billion_rub", sa.Float(), nullable=True))
    op.add_column("stock_rows", sa.Column("forecast_profit_year2_billion_rub", sa.Float(), nullable=True))
    op.add_column("stock_rows", sa.Column("forecast_profit_year3_billion_rub", sa.Float(), nullable=True))

    op.add_column("stock_rows", sa.Column("forecast_price_year1", sa.Float(), nullable=True))
    op.add_column("stock_rows", sa.Column("forecast_price_year2", sa.Float(), nullable=True))
    op.add_column("stock_rows", sa.Column("forecast_price_year3", sa.Float(), nullable=True))

    op.add_column("stock_rows", sa.Column("upside_percent_year1", sa.Float(), nullable=True))
    op.add_column("stock_rows", sa.Column("upside_percent_year2", sa.Float(), nullable=True))
    op.add_column("stock_rows", sa.Column("upside_percent_year3", sa.Float(), nullable=True))

    op.execute(
        """
        UPDATE stock_rows
        SET forecast_profit_year1_billion_rub = forecast_profit_billion_rub,
            forecast_price_year1 = forecast_price,
            upside_percent_year1 = upside_percent
        """
    )


def downgrade() -> None:
    op.drop_column("stock_rows", "upside_percent_year3")
    op.drop_column("stock_rows", "upside_percent_year2")
    op.drop_column("stock_rows", "upside_percent_year1")

    op.drop_column("stock_rows", "forecast_price_year3")
    op.drop_column("stock_rows", "forecast_price_year2")
    op.drop_column("stock_rows", "forecast_price_year1")

    op.drop_column("stock_rows", "forecast_profit_year3_billion_rub")
    op.drop_column("stock_rows", "forecast_profit_year2_billion_rub")
    op.drop_column("stock_rows", "forecast_profit_year1_billion_rub")
