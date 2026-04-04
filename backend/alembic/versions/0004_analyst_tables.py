"""add analyst tables and table_id for stock rows

Revision ID: 0004_analyst_tables
Revises: 0003_net_profit_source
Create Date: 2026-04-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_analyst_tables"
down_revision: Union[str, None] = "0003_net_profit_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "analyst_tables",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("analyst_name", sa.String(length=100), nullable=False),
        sa.Column("year_offset", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.execute("INSERT INTO analyst_tables (id, analyst_name, year_offset) VALUES (1, 'Аналитик 1', 0)")

    op.add_column("stock_rows", sa.Column("table_id", sa.Integer(), nullable=True))
    op.execute("UPDATE stock_rows SET table_id = 1 WHERE table_id IS NULL")
    op.alter_column("stock_rows", "table_id", nullable=False)
    op.create_index(op.f("ix_stock_rows_table_id"), "stock_rows", ["table_id"], unique=False)
    op.create_foreign_key(
        "fk_stock_rows_table_id_analyst_tables",
        "stock_rows",
        "analyst_tables",
        ["table_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_stock_rows_table_id_analyst_tables", "stock_rows", type_="foreignkey")
    op.drop_index(op.f("ix_stock_rows_table_id"), table_name="stock_rows")
    op.drop_column("stock_rows", "table_id")
    op.drop_table("analyst_tables")
