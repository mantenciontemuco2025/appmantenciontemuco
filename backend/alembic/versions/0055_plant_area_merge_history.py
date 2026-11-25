"""Support reversible merges of duplicate general plant areas."""

from alembic import op
import sqlalchemy as sa


revision = "0055_plant_area_merge_history"
down_revision = "0054_public_life_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("plant_areas", sa.Column("merged_into_plant_area_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_plant_areas_merged_into_plant_area_id",
        "plant_areas",
        "plant_areas",
        ["merged_into_plant_area_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_plant_areas_merged_into_plant_area_id",
        "plant_areas",
        ["merged_into_plant_area_id"],
    )
    op.create_table(
        "plant_area_merge_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("canonical_plant_area_id", sa.Integer(), nullable=False),
        sa.Column("canonical_plant_area_name", sa.String(length=200), nullable=False),
        sa.Column("source_plant_area_ids", sa.JSON(), nullable=False),
        sa.Column("source_plant_area_names", sa.JSON(), nullable=False),
        sa.Column("equipment_moved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sections_moved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("supervisor_assignments_moved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ACTIVE"),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reverted_by_user_id", sa.Integer(), nullable=True),
        sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["canonical_plant_area_id"], ["plant_areas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["reverted_by_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_plant_area_merge_history_canonical_plant_area_id",
        "plant_area_merge_history",
        ["canonical_plant_area_id"],
    )
    op.create_index(
        "ix_plant_area_merge_history_status_created",
        "plant_area_merge_history",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_plant_area_merge_history_status_created", table_name="plant_area_merge_history")
    op.drop_index("ix_plant_area_merge_history_canonical_plant_area_id", table_name="plant_area_merge_history")
    op.drop_table("plant_area_merge_history")
    op.drop_index("ix_plant_areas_merged_into_plant_area_id", table_name="plant_areas")
    op.drop_constraint("fk_plant_areas_merged_into_plant_area_id", "plant_areas", type_="foreignkey")
    op.drop_column("plant_areas", "merged_into_plant_area_id")
