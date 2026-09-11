"""Add email delivery tracking to notifications."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("email_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "notifications",
        sa.Column("email_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "notifications",
        sa.Column("email_next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "notifications",
        sa.Column("email_last_error", sa.Text(), nullable=True),
    )
    # Do not email historical notifications when email delivery is enabled.
    op.execute(
        sa.text("UPDATE notifications SET email_sent_at = CURRENT_TIMESTAMP")
    )
    op.create_index(
        "ix_notifications_email_pending",
        "notifications",
        ["email_sent_at", "email_next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_email_pending", table_name="notifications")
    op.drop_column("notifications", "email_last_error")
    op.drop_column("notifications", "email_next_attempt_at")
    op.drop_column("notifications", "email_attempts")
    op.drop_column("notifications", "email_sent_at")
