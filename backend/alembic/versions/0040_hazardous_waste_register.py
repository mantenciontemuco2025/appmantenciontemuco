"""Add hazardous waste register and Drive sync state."""

from alembic import op
import sqlalchemy as sa


revision = "0040_hazardous_waste_register"
down_revision = "0039_kpi_query_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hazardous_waste_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("spreadsheet_id", sa.String(120), nullable=False),
        sa.Column("spreadsheet_url", sa.String(500), nullable=False),
        sa.Column("drive_folder_id", sa.String(120), nullable=True),
        sa.Column("configured_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("configured_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "hazardous_waste_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("respel_code", sa.String(120)),
        sa.Column("normalized_code", sa.String(120), nullable=False),
        sa.Column("waste_name", sa.String(300), nullable=False),
        sa.Column("normalized_name", sa.String(300), nullable=False),
        sa.Column("hazard", sa.String(200)),
        sa.Column("origin", sa.String(300)),
        sa.Column("quantity", sa.Numeric(16, 3), nullable=False),
        sa.Column("unit", sa.String(80), nullable=False, server_default=""),
        sa.Column("accumulated_quantity", sa.Numeric(16, 3), nullable=False),
        sa.Column("delivered_by", sa.String(300)),
        sa.Column("disposal_date", sa.Date()),
        sa.Column("manager", sa.String(300)),
        sa.Column("source_sheet", sa.String(120)),
        sa.Column("sheet_row", sa.Integer()),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("sync_status", sa.String(20), nullable=False, server_default="SYNCED"),
        sa.Column("sync_error", sa.Text()),
        sa.Column("sync_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sync_next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("sync_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("synced_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("sheet_synced_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_hazardous_waste_year_date", "hazardous_waste_records", ["entry_date", "id"])
    op.create_index("ix_hazardous_waste_sync_due", "hazardous_waste_records", ["sync_status", "sync_next_attempt_at"])
    op.create_index("ix_hazardous_waste_identity", "hazardous_waste_records", ["normalized_code", "normalized_name", "unit"])


def downgrade() -> None:
    op.drop_index("ix_hazardous_waste_identity", table_name="hazardous_waste_records")
    op.drop_index("ix_hazardous_waste_sync_due", table_name="hazardous_waste_records")
    op.drop_index("ix_hazardous_waste_year_date", table_name="hazardous_waste_records")
    op.drop_table("hazardous_waste_records")
    op.drop_table("hazardous_waste_settings")
