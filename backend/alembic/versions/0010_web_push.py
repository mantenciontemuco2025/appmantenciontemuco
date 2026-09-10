"""Add Web Push subscriptions and delivery tracking."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("push_sent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("notifications", sa.Column("push_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("notifications", sa.Column("push_next_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("notifications", sa.Column("push_last_error", sa.Text(), nullable=True))
    op.create_index("ix_notifications_push_pending", "notifications", ["push_sent_at", "push_next_attempt_at"])

    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.String(length=255), nullable=False),
        sa.Column("auth", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("endpoint", name="uq_push_subscriptions_endpoint"),
    )
    op.create_index("ix_push_subscriptions_user_id", "push_subscriptions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_push_subscriptions_user_id", table_name="push_subscriptions")
    op.drop_table("push_subscriptions")
    op.drop_index("ix_notifications_push_pending", table_name="notifications")
    op.drop_column("notifications", "push_last_error")
    op.drop_column("notifications", "push_next_attempt_at")
    op.drop_column("notifications", "push_attempts")
    op.drop_column("notifications", "push_sent_at")
