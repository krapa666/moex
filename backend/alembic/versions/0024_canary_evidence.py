"""persist active consensus canary evidence snapshots

Revision ID: 0024_canary_evidence
Revises: 0023_consensus_canary
Create Date: 2026-09-06
"""

import sqlalchemy as sa
from alembic import op

revision = "0024_canary_evidence"
down_revision = "0023_consensus_canary"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "canary_evidence_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("target_year", sa.Integer(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("canary_enabled", sa.Boolean(), nullable=False),
        sa.Column("in_allowlist", sa.Boolean(), nullable=False),
        sa.Column("configured_mode", sa.String(length=32), nullable=False),
        sa.Column("effective_mode", sa.String(length=16), nullable=False),
        sa.Column("active_available", sa.Boolean(), nullable=False),
        sa.Column("safety_status", sa.String(length=16), nullable=True),
        sa.Column("fallback_reason", sa.String(length=64), nullable=True),
        sa.Column("sources", sa.Integer(), nullable=False),
        sa.Column("current_price", sa.Float(), nullable=True),
        sa.Column("median_target_price", sa.Float(), nullable=True),
        sa.Column("weighted_target_price", sa.Float(), nullable=True),
        sa.Column("active_target_price", sa.Float(), nullable=True),
        sa.Column("median_expected_return_percent", sa.Float(), nullable=True),
        sa.Column("weighted_expected_return_percent", sa.Float(), nullable=True),
        sa.Column("active_expected_return_percent", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_canary_evidence_snapshots_ticker",
        "canary_evidence_snapshots",
        ["ticker"],
        unique=False,
    )
    op.create_index(
        "ix_canary_evidence_snapshots_target_year",
        "canary_evidence_snapshots",
        ["target_year"],
        unique=False,
    )
    op.create_index(
        "ix_canary_evidence_snapshots_captured_at",
        "canary_evidence_snapshots",
        ["captured_at"],
        unique=False,
    )
    op.create_index(
        "ix_canary_evidence_ticker_captured_at",
        "canary_evidence_snapshots",
        ["ticker", "captured_at"],
        unique=False,
    )
    op.create_index(
        "ix_canary_evidence_target_year_captured_at",
        "canary_evidence_snapshots",
        ["target_year", "captured_at"],
        unique=False,
    )
    op.create_index(
        "ix_canary_evidence_effective_mode_captured_at",
        "canary_evidence_snapshots",
        ["effective_mode", "captured_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_canary_evidence_effective_mode_captured_at",
        table_name="canary_evidence_snapshots",
    )
    op.drop_index(
        "ix_canary_evidence_target_year_captured_at",
        table_name="canary_evidence_snapshots",
    )
    op.drop_index(
        "ix_canary_evidence_ticker_captured_at",
        table_name="canary_evidence_snapshots",
    )
    op.drop_index(
        "ix_canary_evidence_snapshots_captured_at",
        table_name="canary_evidence_snapshots",
    )
    op.drop_index(
        "ix_canary_evidence_snapshots_target_year",
        table_name="canary_evidence_snapshots",
    )
    op.drop_index(
        "ix_canary_evidence_snapshots_ticker",
        table_name="canary_evidence_snapshots",
    )
    op.drop_table("canary_evidence_snapshots")
