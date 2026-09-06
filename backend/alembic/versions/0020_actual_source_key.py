"""track canonical actual result source

Revision ID: 0020_actual_source_key
Revises: 0019_actual_net_profits
Create Date: 2026-09-06
"""

import sqlalchemy as sa
from alembic import op

revision = "0020_actual_source_key"
down_revision = "0019_actual_net_profits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "actual_net_profits",
        sa.Column("source_key", sa.String(length=64), nullable=False, server_default="manual"),
    )
    op.create_index(
        "ix_actual_net_profits_source_key",
        "actual_net_profits",
        ["source_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_actual_net_profits_source_key", table_name="actual_net_profits")
    op.drop_column("actual_net_profits", "source_key")
