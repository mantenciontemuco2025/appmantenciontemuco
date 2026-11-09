"""Allow hiding plant areas from new work orders."""

from alembic import op
import sqlalchemy as sa


revision = "0045_plant_area_active"
down_revision = "0044_single_inventory_editor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "plant_areas",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("plant_areas", "is_active")
