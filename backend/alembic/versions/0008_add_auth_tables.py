"""compat revision placeholder for removed auth migration

Revision ID: 0008_auth_tables
Revises: 0007_table_sort_order
Create Date: 2026-04-16
"""

from typing import Sequence, Union

revision: str = "0008_auth_tables"
down_revision: Union[str, None] = "0007_table_sort_order"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op revision kept for compatibility with deployed DB history."""


def downgrade() -> None:
    """No-op downgrade."""
