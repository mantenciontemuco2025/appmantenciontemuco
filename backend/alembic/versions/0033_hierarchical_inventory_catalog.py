"""Add plant areas and inventory-aware equipment catalog."""

from alembic import op
import sqlalchemy as sa


revision = "0033_inventory_hierarchy"
down_revision = "0032_material_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plant_areas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("name", name="uq_plant_areas_name"),
    )
    op.create_table(
        "plant_area_sections",
        sa.Column("plant_area_id", sa.Integer(), sa.ForeignKey("plant_areas.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("section_id", sa.Integer(), sa.ForeignKey("areas.id", ondelete="CASCADE"), primary_key=True),
    )
    op.add_column("equipment", sa.Column("inventory_code", sa.String(length=50), nullable=True))
    op.add_column("equipment", sa.Column("category", sa.String(length=180), nullable=True))
    op.add_column("equipment", sa.Column("location", sa.String(length=250), nullable=True))
    op.add_column("equipment", sa.Column("operational_status", sa.String(length=80), nullable=True))
    op.create_index("ix_equipment_inventory_code", "equipment", ["inventory_code"])
    op.create_index(
        "uq_equipment_inventory_code",
        "equipment",
        ["inventory_code"],
        unique=True,
        postgresql_where=sa.text("inventory_code IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_equipment_inventory_code", table_name="equipment")
    op.drop_index("ix_equipment_inventory_code", table_name="equipment")
    op.drop_column("equipment", "operational_status")
    op.drop_column("equipment", "location")
    op.drop_column("equipment", "category")
    op.drop_column("equipment", "inventory_code")
    op.drop_table("plant_area_sections")
    op.drop_table("plant_areas")
