"""Add legacy/historical work-order fields."""

from alembic import op
import sqlalchemy as sa


revision = "0035_historical_work_orders"
down_revision = "0034_equipment_plant_area"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "work_orders",
        sa.Column("is_historical", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "work_orders",
        sa.Column("original_ot_number", sa.String(length=50), nullable=True),
    )
    op.create_index("ix_work_orders_is_historical", "work_orders", ["is_historical"])
    op.create_index("ix_work_orders_original_ot_number", "work_orders", ["original_ot_number"])


def downgrade() -> None:
    op.drop_index("ix_work_orders_original_ot_number", table_name="work_orders")
    op.drop_index("ix_work_orders_is_historical", table_name="work_orders")
    op.drop_column("work_orders", "original_ot_number")
    op.drop_column("work_orders", "is_historical")
