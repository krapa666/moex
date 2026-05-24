"""add net profit source comment column

Revision ID: 0003_net_profit_source
Revises: 0002_three_year_forecast
Create Date: 2026-03-30
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0003_net_profit_source"
down_revision = "0002_three_year_forecast"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stock_rows", sa.Column("net_profit_source_comment", sa.String(length=512), nullable=True))


def downgrade() -> None:
    op.drop_column("stock_rows", "net_profit_source_comment")
