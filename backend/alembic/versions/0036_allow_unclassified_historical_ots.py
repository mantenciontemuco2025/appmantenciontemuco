"""Allow imported historical OTs to wait for catalog classification."""

from alembic import op


revision = "0036_unclassified_historical_ots"
down_revision = "0035_historical_work_orders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("work_orders", "area_id", nullable=True)


def downgrade() -> None:
    op.alter_column("work_orders", "area_id", nullable=False)
