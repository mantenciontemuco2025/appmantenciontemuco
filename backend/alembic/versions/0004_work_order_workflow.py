"""Add workflow fields to work_orders + M2M participants table.

Adds: responsible_user_id, is_planned, scheduled_date, due_date, lifecycle
timestamps, completion_notes, cancellation_reason, return fields, and the
work_order_participants association table for proper M2M participant tracking.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── work_order_participants association table ────────────────────────
    op.create_table(
        "work_order_participants",
        sa.Column(
            "work_order_id",
            sa.Integer(),
            sa.ForeignKey("work_orders.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    # ── New columns on work_orders (all nullable for legacy data) ────────
    # Responsible
    op.add_column(
        "work_orders",
        sa.Column("responsible_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
    )

    # Planning
    op.add_column("work_orders", sa.Column("is_planned", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("work_orders", sa.Column("scheduled_date", sa.Date(), nullable=True))
    op.add_column("work_orders", sa.Column("due_date", sa.Date(), nullable=True))

    # Start
    op.add_column("work_orders", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "work_orders",
        sa.Column("started_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
    )

    # Complete
    op.add_column("work_orders", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "work_orders",
        sa.Column("completed_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
    )
    op.add_column("work_orders", sa.Column("actual_duration_minutes", sa.Float(), nullable=True))
    op.add_column("work_orders", sa.Column("completion_notes", sa.Text(), nullable=True))

    # Approve
    op.add_column("work_orders", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "work_orders",
        sa.Column("approved_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
    )

    # Cancel
    op.add_column("work_orders", sa.Column("cancellation_reason", sa.Text(), nullable=True))

    # Return (admin sends back to worker)
    op.add_column("work_orders", sa.Column("returned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "work_orders",
        sa.Column("returned_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
    )
    op.add_column("work_orders", sa.Column("return_reason", sa.Text(), nullable=True))

    # Migrate existing participant_names (best-effort): parse comma-separated
    # names and insert into work_order_participants matching by full_name.
    # Uses PostgreSQL-compatible syntax.
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            INSERT INTO work_order_participants (work_order_id, user_id)
            SELECT DISTINCT wo.id, u.id
            FROM work_orders wo
            CROSS JOIN unnest(string_to_array(wo.participant_names, ', ')) AS name_part
            JOIN users u ON TRIM(name_part) = u.full_name
            WHERE wo.participant_names IS NOT NULL
              AND wo.participant_names != ''
            ON CONFLICT DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_table("work_order_participants")

    op.drop_column("work_orders", "return_reason")
    op.drop_column("work_orders", "returned_by_user_id")
    op.drop_column("work_orders", "returned_at")
    op.drop_column("work_orders", "cancellation_reason")
    op.drop_column("work_orders", "approved_by_user_id")
    op.drop_column("work_orders", "approved_at")
    op.drop_column("work_orders", "completion_notes")
    op.drop_column("work_orders", "actual_duration_minutes")
    op.drop_column("work_orders", "completed_by_user_id")
    op.drop_column("work_orders", "completed_at")
    op.drop_column("work_orders", "started_by_user_id")
    op.drop_column("work_orders", "started_at")
    op.drop_column("work_orders", "due_date")
    op.drop_column("work_orders", "scheduled_date")
    op.drop_column("work_orders", "is_planned")
    op.drop_column("work_orders", "responsible_user_id")
