"""persist shadow drift notification state and events

Revision ID: 0022_shadow_drift_notifications
Revises: 0021_shadow_consensus_snapshots
Create Date: 2026-09-06
"""

import sqlalchemy as sa
from alembic import op

revision = "0022_shadow_drift_notifications"
down_revision = "0021_shadow_consensus_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shadow_drift_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("target_year", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "incident_notified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_shadow_drift_states_ticker",
        "shadow_drift_states",
        ["ticker"],
        unique=True,
    )
    op.create_index(
        "ix_shadow_drift_states_observed_at",
        "shadow_drift_states",
        ["observed_at"],
        unique=False,
    )

    op.create_table(
        "shadow_drift_notification_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("target_year", sa.Integer(), nullable=True),
        sa.Column("from_status", sa.String(length=16), nullable=True),
        sa.Column("to_status", sa.String(length=16), nullable=False),
        sa.Column("transition_kind", sa.String(length=32), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latest_delta_percent", sa.Float(), nullable=True),
        sa.Column("reasons", sa.JSON(), nullable=True),
        sa.Column("delivery_status", sa.String(length=24), nullable=False),
        sa.Column("delivery_reason", sa.String(length=64), nullable=True),
        sa.Column(
            "delivery_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_shadow_drift_notification_events_ticker",
        "shadow_drift_notification_events",
        ["ticker"],
        unique=False,
    )
    op.create_index(
        "ix_shadow_drift_notification_events_target_year",
        "shadow_drift_notification_events",
        ["target_year"],
        unique=False,
    )
    op.create_index(
        "ix_shadow_drift_notification_events_observed_at",
        "shadow_drift_notification_events",
        ["observed_at"],
        unique=False,
    )
    op.create_index(
        "ix_shadow_drift_notification_events_delivery_status",
        "shadow_drift_notification_events",
        ["delivery_status"],
        unique=False,
    )
    op.create_index(
        "ix_shadow_drift_notification_events_ticker_observed_at",
        "shadow_drift_notification_events",
        ["ticker", "observed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_shadow_drift_notification_events_ticker_observed_at",
        table_name="shadow_drift_notification_events",
    )
    op.drop_index(
        "ix_shadow_drift_notification_events_delivery_status",
        table_name="shadow_drift_notification_events",
    )
    op.drop_index(
        "ix_shadow_drift_notification_events_observed_at",
        table_name="shadow_drift_notification_events",
    )
    op.drop_index(
        "ix_shadow_drift_notification_events_target_year",
        table_name="shadow_drift_notification_events",
    )
    op.drop_index(
        "ix_shadow_drift_notification_events_ticker",
        table_name="shadow_drift_notification_events",
    )
    op.drop_table("shadow_drift_notification_events")

    op.drop_index(
        "ix_shadow_drift_states_observed_at",
        table_name="shadow_drift_states",
    )
    op.drop_index("ix_shadow_drift_states_ticker", table_name="shadow_drift_states")
    op.drop_table("shadow_drift_states")
