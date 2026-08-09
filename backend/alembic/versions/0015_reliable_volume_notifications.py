"""track reliable volume notification decisions

Revision ID: 0015_reliable_volume_notifications
Revises: 0014_all_tqbr_volume_stocks
Create Date: 2026-08-09
"""

import sqlalchemy as sa
from alembic import op

revision = "0015_reliable_volume_notifications"
down_revision = "0014_all_tqbr_volume_stocks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "volume_collection_runs",
        sa.Column("imoex_anomalies_found", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "volume_collection_runs",
        sa.Column("notifications_suppressed", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "volume_collection_runs",
        sa.Column("notifications_sent", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "volume_collection_runs",
        sa.Column(
            "history_securities_refreshed",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("volume_collection_runs", "history_securities_refreshed")
    op.drop_column("volume_collection_runs", "notifications_sent")
    op.drop_column("volume_collection_runs", "notifications_suppressed")
    op.drop_column("volume_collection_runs", "imoex_anomalies_found")
