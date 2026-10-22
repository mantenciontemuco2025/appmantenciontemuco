"""Allow hazardous-waste entries with unknown quantities."""

from alembic import op


revision = "0041_hazwaste_optional_qty"
down_revision = "0040_hazardous_waste_register"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("hazardous_waste_records", "quantity", nullable=True)
    op.alter_column("hazardous_waste_records", "accumulated_quantity", nullable=True)


def downgrade() -> None:
    # Fail rather than silently replacing unknown quantities with zero.
    op.alter_column("hazardous_waste_records", "accumulated_quantity", nullable=False)
    op.alter_column("hazardous_waste_records", "quantity", nullable=False)
