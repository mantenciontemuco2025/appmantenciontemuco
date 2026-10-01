"""Store the Drive reference and sync state for equipment life sheets."""

from alembic import op
import sqlalchemy as sa


revision = "0038_equipment_life_sheets"
down_revision = "0037_seed_legacy_plant_areas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("equipment", sa.Column("life_sheet_file_id", sa.String(length=200), nullable=True))
    op.add_column("equipment", sa.Column("life_sheet_url", sa.String(length=500), nullable=True))
    op.add_column(
        "equipment",
        sa.Column(
            "life_sheet_sync_status",
            sa.String(length=20),
            server_default="PENDING",
            nullable=False,
        ),
    )
    op.add_column("equipment", sa.Column("life_sheet_sync_error", sa.String(length=500), nullable=True))
    op.add_column(
        "equipment",
        sa.Column("life_sheet_synced_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("equipment", "life_sheet_synced_at")
    op.drop_column("equipment", "life_sheet_sync_error")
    op.drop_column("equipment", "life_sheet_sync_status")
    op.drop_column("equipment", "life_sheet_url")
    op.drop_column("equipment", "life_sheet_file_id")
