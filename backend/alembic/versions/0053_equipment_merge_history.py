"""Keep a snapshot so equipment merges can be reverted."""

from alembic import op
import sqlalchemy as sa


revision = "0053_equipment_merge_history"
down_revision = "0052_equipment_merge_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "equipment_merge_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("canonical_equipment_id", sa.Integer(), nullable=False),
        sa.Column("canonical_equipment_name", sa.String(length=200), nullable=False),
        sa.Column("source_equipment_ids", sa.JSON(), nullable=False),
        sa.Column("source_equipment_names", sa.JSON(), nullable=False),
        sa.Column("work_orders_moved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("maintenance_records_moved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("preventive_plans_moved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ACTIVE"),
        sa.Column("life_sheet_sync_status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reverted_by_user_id", sa.Integer(), nullable=True),
        sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["canonical_equipment_id"], ["equipment.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["reverted_by_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_equipment_merge_history_canonical_equipment_id",
        "equipment_merge_history",
        ["canonical_equipment_id"],
    )
    op.create_index(
        "ix_equipment_merge_history_status_created",
        "equipment_merge_history",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_equipment_merge_history_status_created", table_name="equipment_merge_history")
    op.drop_index("ix_equipment_merge_history_canonical_equipment_id", table_name="equipment_merge_history")
    op.drop_table("equipment_merge_history")
