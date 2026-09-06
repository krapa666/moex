"""persist controlled consensus canary state and audit events

Revision ID: 0023_consensus_canary
Revises: 0022_shadow_drift_notifications
Create Date: 2026-09-06
"""

import sqlalchemy as sa
from alembic import op

revision = "0023_consensus_canary"
down_revision = "0022_shadow_drift_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "consensus_canary_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("tickers", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "consensus_canary_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("previous_enabled", sa.Boolean(), nullable=False),
        sa.Column("new_enabled", sa.Boolean(), nullable=False),
        sa.Column("previous_tickers", sa.JSON(), nullable=False),
        sa.Column("new_tickers", sa.JSON(), nullable=False),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("promotion_status", sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_consensus_canary_events_occurred_at",
        "consensus_canary_events",
        ["occurred_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_consensus_canary_events_occurred_at", table_name="consensus_canary_events")
    op.drop_table("consensus_canary_events")
    op.drop_table("consensus_canary_settings")
