"""Add opaque public links for equipment life sheets."""

from alembic import op
import sqlalchemy as sa


revision = "0054_public_life_tokens"
down_revision = "0053_equipment_merge_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "equipment",
        sa.Column("public_life_sheet_token", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_equipment_public_life_sheet_token",
        "equipment",
        ["public_life_sheet_token"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_equipment_public_life_sheet_token", table_name="equipment")
    op.drop_column("equipment", "public_life_sheet_token")
