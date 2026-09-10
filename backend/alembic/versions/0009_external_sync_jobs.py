"""Add durable queue for external Google synchronization."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "external_sync_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "work_order_id",
            sa.Integer(),
            sa.ForeignKey("work_orders.id"),
            nullable=False,
        ),
        sa.Column("job_type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.Enum("PENDING", "PROCESSING", "SUCCEEDED", "FAILED", name="syncjobstatus"), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("populate_individual", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("previous_execution_date", sa.Date(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_external_sync_jobs_work_order_id", "external_sync_jobs", ["work_order_id"])
    op.create_index("ix_external_sync_jobs_status", "external_sync_jobs", ["status"])
    op.create_index("ix_external_sync_jobs_next_attempt_at", "external_sync_jobs", ["next_attempt_at"])


def downgrade() -> None:
    op.drop_index("ix_external_sync_jobs_next_attempt_at", table_name="external_sync_jobs")
    op.drop_index("ix_external_sync_jobs_status", table_name="external_sync_jobs")
    op.drop_index("ix_external_sync_jobs_work_order_id", table_name="external_sync_jobs")
    op.drop_table("external_sync_jobs")
    sa.Enum(name="syncjobstatus").drop(op.get_bind(), checkfirst=True)
