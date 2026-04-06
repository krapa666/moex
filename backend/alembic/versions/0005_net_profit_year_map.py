"""add net profit year map

Revision ID: 0005_net_profit_year_map
Revises: 0004_analyst_tables
Create Date: 2026-04-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_net_profit_year_map"
down_revision: Union[str, None] = "0004_analyst_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("stock_rows", sa.Column("net_profit_year_map", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("stock_rows", "net_profit_year_map")
