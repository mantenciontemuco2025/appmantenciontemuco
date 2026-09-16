"""Store photo evidence metadata for work orders."""

from alembic import op
import sqlalchemy as sa


revision = "0020_work_order_evidence"
down_revision = "0019_work_order_plant_area"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "work_order_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("work_order_id", sa.Integer(), nullable=False),
        sa.Column("drive_file_id", sa.String(length=200), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("stage", sa.String(length=20), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Integer(), nullable=True),
        sa.Column("uploaded_by_name", sa.String(length=200), nullable=False),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("stage IN ('ISSUE', 'WORK')", name="ck_wo_evidence_stage"),
        sa.ForeignKeyConstraint(
            ["work_order_id"], ["work_orders.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("drive_file_id", name="uq_wo_evidence_drive_file_id"),
    )
    op.create_index(
        "ix_wo_evidence_order_stage",
        "work_order_evidence",
        ["work_order_id", "stage"],
    )


def downgrade() -> None:
    op.drop_index("ix_wo_evidence_order_stage", table_name="work_order_evidence")
    op.drop_table("work_order_evidence")
