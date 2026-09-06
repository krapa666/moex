"""persist shadow consensus monitoring snapshots

Revision ID: 0021_shadow_consensus_snapshots
Revises: 0020_actual_source_key
Create Date: 2026-09-06
"""

import sqlalchemy as sa
from alembic import op

revision = "0021_shadow_consensus_snapshots"
down_revision = "0020_actual_source_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shadow_consensus_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("target_year", sa.Integer(), nullable=False),
        sa.Column("training_snapshot", sa.String(length=16), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sources", sa.Integer(), nullable=False),
        sa.Column("sources_with_training_history", sa.Integer(), nullable=False),
        sa.Column("training_samples", sa.Integer(), nullable=False),
        sa.Column("weighting_uses_history", sa.Boolean(), nullable=False),
        sa.Column("max_source_weight_percent", sa.Float(), nullable=False),
        sa.Column("min_source_weight_percent", sa.Float(), nullable=False),
        sa.Column("median_net_profit_billion_rub", sa.Float(), nullable=False),
        sa.Column("weighted_net_profit_billion_rub", sa.Float(), nullable=False),
        sa.Column("median_target_price", sa.Float(), nullable=False),
        sa.Column("weighted_target_price", sa.Float(), nullable=False),
        sa.Column("weighted_vs_median_target_delta_rub", sa.Float(), nullable=False),
        sa.Column("weighted_vs_median_target_delta_percent", sa.Float(), nullable=False),
        sa.Column("current_price", sa.Float(), nullable=True),
        sa.Column("median_market_gap_percent", sa.Float(), nullable=True),
        sa.Column("weighted_market_gap_percent", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_shadow_consensus_snapshots_ticker",
        "shadow_consensus_snapshots",
        ["ticker"],
        unique=False,
    )
    op.create_index(
        "ix_shadow_consensus_snapshots_target_year",
        "shadow_consensus_snapshots",
        ["target_year"],
        unique=False,
    )
    op.create_index(
        "ix_shadow_consensus_snapshots_captured_at",
        "shadow_consensus_snapshots",
        ["captured_at"],
        unique=False,
    )
    op.create_index(
        "ix_shadow_consensus_snapshots_ticker_captured_at",
        "shadow_consensus_snapshots",
        ["ticker", "captured_at"],
        unique=False,
    )
    op.create_index(
        "ix_shadow_consensus_snapshots_target_year_captured_at",
        "shadow_consensus_snapshots",
        ["target_year", "captured_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_shadow_consensus_snapshots_target_year_captured_at",
        table_name="shadow_consensus_snapshots",
    )
    op.drop_index(
        "ix_shadow_consensus_snapshots_ticker_captured_at",
        table_name="shadow_consensus_snapshots",
    )
    op.drop_index(
        "ix_shadow_consensus_snapshots_captured_at",
        table_name="shadow_consensus_snapshots",
    )
    op.drop_index(
        "ix_shadow_consensus_snapshots_target_year",
        table_name="shadow_consensus_snapshots",
    )
    op.drop_index(
        "ix_shadow_consensus_snapshots_ticker",
        table_name="shadow_consensus_snapshots",
    )
    op.drop_table("shadow_consensus_snapshots")
