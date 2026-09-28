"""Scope imported physical equipment to its plant area."""

from alembic import op
import sqlalchemy as sa


revision = "0034_equipment_plant_area"
down_revision = "0033_inventory_hierarchy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "equipment",
        sa.Column("plant_area_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_equipment_plant_area_id",
        "equipment",
        "plant_areas",
        ["plant_area_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_equipment_plant_area_id", "equipment", ["plant_area_id"])


def downgrade() -> None:
    op.drop_index("ix_equipment_plant_area_id", table_name="equipment")
    op.drop_constraint("fk_equipment_plant_area_id", "equipment", type_="foreignkey")
    op.drop_column("equipment", "plant_area_id")
