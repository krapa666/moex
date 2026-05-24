"""add sort_order for analyst tables

Revision ID: 0007_table_sort_order
Revises: 0006_add_fourth_forecast_year
Create Date: 2026-04-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_table_sort_order"
down_revision: Union[str, None] = "0006_add_fourth_forecast_year"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("analyst_tables", sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"))
    op.execute("UPDATE analyst_tables SET sort_order = id")
    op.create_index("ix_analyst_tables_sort_order", "analyst_tables", ["sort_order"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_analyst_tables_sort_order", table_name="analyst_tables")
    op.drop_column("analyst_tables", "sort_order")
