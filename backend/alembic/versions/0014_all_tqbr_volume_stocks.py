"""monitor all TQBR common and preferred shares

Revision ID: 0014_all_tqbr_volume_stocks
Revises: 0013_integrate_volume_monitor
Create Date: 2026-08-09
"""

import sqlalchemy as sa
from alembic import op

revision = "0014_all_tqbr_volume_stocks"
down_revision = "0013_integrate_volume_monitor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "volume_securities",
        sa.Column("security_type", sa.String(length=16), nullable=False, server_default="common"),
    )
    op.create_check_constraint(
        "ck_volume_securities_security_type",
        "volume_securities",
        "security_type IN ('common', 'preferred')",
    )
    op.add_column(
        "volume_securities",
        sa.Column("is_imoex", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        op.f("ix_volume_securities_is_imoex"),
        "volume_securities",
        ["is_imoex"],
        unique=False,
    )
    # The existing rows came from IMOEX; preserve that membership until the
    # first TQBR refresh replaces the complete active universe.
    op.execute("UPDATE volume_securities SET is_imoex = true WHERE active = true")
    op.add_column(
        "volume_monitor_settings",
        sa.Column(
            "notification_scope",
            sa.String(length=16),
            nullable=False,
            server_default="imoex",
        ),
    )
    op.create_check_constraint(
        "ck_volume_monitor_settings_notification_scope",
        "volume_monitor_settings",
        "notification_scope IN ('imoex', 'all')",
    )
    op.drop_column("volume_monitor_settings", "notification_email")
    op.add_column(
        "volume_monitor_settings",
        sa.Column(
            "baseline_sessions",
            sa.Integer(),
            nullable=False,
            server_default="60",
        ),
    )
    op.create_check_constraint(
        "ck_volume_monitor_settings_baseline_sessions",
        "volume_monitor_settings",
        "baseline_sessions BETWEEN 10 AND 250",
    )


def downgrade() -> None:
    op.add_column(
        "volume_monitor_settings",
        sa.Column("notification_email", sa.String(length=320), nullable=True),
    )
    op.drop_constraint(
        "ck_volume_monitor_settings_baseline_sessions",
        "volume_monitor_settings",
        type_="check",
    )
    op.drop_column("volume_monitor_settings", "baseline_sessions")
    op.drop_constraint(
        "ck_volume_monitor_settings_notification_scope",
        "volume_monitor_settings",
        type_="check",
    )
    op.drop_column("volume_monitor_settings", "notification_scope")
    op.drop_index(op.f("ix_volume_securities_is_imoex"), table_name="volume_securities")
    op.drop_column("volume_securities", "is_imoex")
    op.drop_constraint(
        "ck_volume_securities_security_type",
        "volume_securities",
        type_="check",
    )
    op.drop_column("volume_securities", "security_type")
