"""add work_orders table

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "work_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ot_number", sa.String(20), nullable=False, unique=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),

        sa.Column("area_id", sa.Integer(), sa.ForeignKey("areas.id"), nullable=False),
        sa.Column("equipment_id", sa.Integer(), sa.ForeignKey("equipment.id"), nullable=True),

        sa.Column("maintenance_type", sa.String(20), nullable=False),
        sa.Column("loto_status", sa.String(20), nullable=False, server_default="NOT_APPLICABLE"),

        sa.Column("folio", sa.String(50), nullable=True),
        sa.Column("section_name", sa.String(200), nullable=True),
        sa.Column("estimated_time", sa.String(20), nullable=True),
        sa.Column("execution_date", sa.Date(), nullable=True),
        sa.Column("resources_required", sa.Text(), nullable=True),
        sa.Column("voucher_number", sa.String(50), nullable=True),
        sa.Column("risks", sa.Text(), nullable=True),
        sa.Column("observations", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.String(200), nullable=True),
        sa.Column("approved_by", sa.String(200), nullable=True),

        sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT"),

        # Google Drive / Sheets
        sa.Column("google_ot_file_id", sa.String(200), nullable=True),
        sa.Column("google_ot_url", sa.String(500), nullable=True),
        sa.Column("google_ot_sheet_id", sa.String(200), nullable=True),

        sa.Column("ot_sheet_sync_status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("ot_sheet_sync_error", sa.Text(), nullable=True),
        sa.Column("ot_sheet_synced_at", sa.DateTime(timezone=True), nullable=True),

        sa.Column("monthly_sheet_sync_status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("monthly_sheet_sync_error", sa.Text(), nullable=True),
        sa.Column("monthly_sheet_synced_at", sa.DateTime(timezone=True), nullable=True),

        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),

        # Signature placeholders (future)
        sa.Column("requested_signature", sa.String(500), nullable=True),
        sa.Column("approved_signature", sa.String(500), nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_index("ix_work_orders_ot_number", "work_orders", ["ot_number"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_work_orders_ot_number", table_name="work_orders")
    op.drop_table("work_orders")
