"""Add provisional worker hallazgo workflow to work orders."""

from alembic import op
import sqlalchemy as sa


revision = "0030_hallazgo_work_orders"
down_revision = "0029_supervisor_ot_validation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("work_orders", sa.Column("is_hallazgo_report", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("work_orders", sa.Column("hallazgo_folio", sa.String(length=30), nullable=True))
    op.create_unique_constraint("uq_work_orders_hallazgo_folio", "work_orders", ["hallazgo_folio"])
    op.add_column("work_orders", sa.Column("hallazgo_kind", sa.String(length=30), nullable=True))
    op.add_column("work_orders", sa.Column("hallazgo_priority", sa.String(length=20), nullable=True))
    op.add_column("work_orders", sa.Column("hallazgo_status", sa.String(length=20), nullable=True))
    op.add_column("work_orders", sa.Column("hallazgo_review_notes", sa.Text(), nullable=True))
    op.add_column("work_orders", sa.Column("hallazgo_reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("work_orders", sa.Column("hallazgo_reviewed_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))


def downgrade() -> None:
    op.drop_constraint("work_orders_hallazgo_reviewed_by_user_id_fkey", "work_orders", type_="foreignkey")
    op.drop_column("work_orders", "hallazgo_reviewed_by_user_id")
    op.drop_column("work_orders", "hallazgo_reviewed_at")
    op.drop_column("work_orders", "hallazgo_review_notes")
    op.drop_column("work_orders", "hallazgo_status")
    op.drop_column("work_orders", "hallazgo_priority")
    op.drop_column("work_orders", "hallazgo_kind")
    op.drop_constraint("uq_work_orders_hallazgo_folio", "work_orders", type_="unique")
    op.drop_column("work_orders", "hallazgo_folio")
    op.drop_column("work_orders", "is_hallazgo_report")
