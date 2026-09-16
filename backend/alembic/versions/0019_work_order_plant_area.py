"""Store the new general area separately from section catalog entries."""

from alembic import op
import sqlalchemy as sa


revision = "0019_work_order_plant_area"
down_revision = "0018_loto_controls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "work_orders",
        sa.Column("plant_area", sa.String(length=50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("work_orders", "plant_area")
