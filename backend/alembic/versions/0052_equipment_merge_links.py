"""Track catalog equipment merged into a canonical equipment record."""

from alembic import op
import sqlalchemy as sa


revision = "0052_equipment_merge_links"
down_revision = "0051_preventive_selected_months"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "equipment",
        sa.Column("merged_into_equipment_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_equipment_merged_into_equipment_id_equipment",
        "equipment",
        "equipment",
        ["merged_into_equipment_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_equipment_merged_into_equipment_id",
        "equipment",
        ["merged_into_equipment_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_equipment_merged_into_equipment_id", table_name="equipment")
    op.drop_constraint("fk_equipment_merged_into_equipment_id_equipment", "equipment", type_="foreignkey")
    op.drop_column("equipment", "merged_into_equipment_id")
