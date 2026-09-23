"""Add internal validation for OTs created by supervisors."""

from alembic import op
import sqlalchemy as sa


revision = "0029_supervisor_ot_validation"
down_revision = "0028_water_register_permissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "work_orders",
        sa.Column(
            "requires_supervisor_validation",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "work_orders",
        sa.Column(
            "supervisor_review_status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'NOT_REQUIRED'"),
        ),
    )
    op.add_column(
        "work_orders",
        sa.Column(
            "supervisor_validator_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "work_orders",
        sa.Column("supervisor_reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "work_orders",
        sa.Column("supervisor_review_notes", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("work_orders", "supervisor_review_notes")
    op.drop_column("work_orders", "supervisor_reviewed_at")
    op.drop_constraint(
        "work_orders_supervisor_validator_user_id_fkey",
        "work_orders",
        type_="foreignkey",
    )
    op.drop_column("work_orders", "supervisor_validator_user_id")
    op.drop_column("work_orders", "supervisor_review_status")
    op.drop_column("work_orders", "requires_supervisor_validation")
