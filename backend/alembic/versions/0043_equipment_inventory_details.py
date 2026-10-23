"""Add detailed inventory attributes to physical equipment."""

from alembic import op
import sqlalchemy as sa


revision = "0043_equipment_inventory_details"
down_revision = "0042_hazwaste_unit_reconcile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = [
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("dimensions", sa.String(length=200), nullable=True),
        sa.Column("weight", sa.Numeric(14, 3), nullable=True),
        sa.Column("unit", sa.String(length=40), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("purchase_receipt_date", sa.Date(), nullable=True),
        sa.Column("purchased_from", sa.String(length=250), nullable=True),
        sa.Column("warranty_end", sa.Date(), nullable=True),
        sa.Column("web1", sa.String(length=500), nullable=True),
        sa.Column("initial_value", sa.Numeric(14, 2), nullable=True),
        sa.Column("impeller_diameter", sa.String(length=100), nullable=True),
        sa.Column("flow_rate", sa.String(length=100), nullable=True),
        sa.Column("total_manometric_head", sa.String(length=100), nullable=True),
        sa.Column("rotation_speed", sa.String(length=100), nullable=True),
        sa.Column("npsh", sa.String(length=100), nullable=True),
        sa.Column("last_maintenance_date", sa.Date(), nullable=True),
        sa.Column("general_spare_parts", sa.Text(), nullable=True),
        sa.Column("observations", sa.Text(), nullable=True),
        sa.Column("power_hp", sa.String(length=80), nullable=True),
        sa.Column("power_kw", sa.String(length=80), nullable=True),
        sa.Column("voltage", sa.String(length=80), nullable=True),
        sa.Column("current", sa.String(length=80), nullable=True),
        sa.Column("revolutions", sa.String(length=80), nullable=True),
        sa.Column("efficiency", sa.String(length=80), nullable=True),
        sa.Column("capacity", sa.String(length=120), nullable=True),
        sa.Column("custom_attributes", sa.JSON(), nullable=False, server_default="[]"),
    ]
    for column in columns:
        op.add_column("equipment", column)


def downgrade() -> None:
    for name in (
        "custom_attributes", "capacity", "efficiency", "revolutions", "current",
        "voltage", "power_kw", "power_hp", "observations", "general_spare_parts",
        "last_maintenance_date", "npsh", "rotation_speed", "total_manometric_head",
        "flow_rate", "impeller_diameter", "initial_value", "web1", "warranty_end",
        "purchased_from", "purchase_receipt_date", "description", "unit", "weight",
        "dimensions", "model",
    ):
        op.drop_column("equipment", name)
