"""Add voucher date and material codes to work orders."""

from alembic import op
import sqlalchemy as sa


revision = "0031_work_order_voucher_details"
down_revision = "0030_hallazgo_work_orders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("work_orders", sa.Column("voucher_date", sa.Date(), nullable=True))
    op.add_column("work_orders", sa.Column("material_codes", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("work_orders", "material_codes")
    op.drop_column("work_orders", "voucher_date")
