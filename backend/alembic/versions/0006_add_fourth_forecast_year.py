"""add fourth forecast year columns

Revision ID: 0006_add_fourth_forecast_year
Revises: 0005_net_profit_year_map
Create Date: 2026-04-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_add_fourth_forecast_year"
down_revision: Union[str, None] = "0005_net_profit_year_map"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("stock_rows", sa.Column("forecast_profit_year4_billion_rub", sa.Float(), nullable=True))
    op.add_column("stock_rows", sa.Column("forecast_price_year4", sa.Float(), nullable=True))
    op.add_column("stock_rows", sa.Column("upside_percent_year4", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("stock_rows", "upside_percent_year4")
    op.drop_column("stock_rows", "forecast_price_year4")
    op.drop_column("stock_rows", "forecast_profit_year4_billion_rub")
