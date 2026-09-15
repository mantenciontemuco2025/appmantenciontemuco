"""Store worker-declared work time separately from lifecycle timestamps."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column(
        "work_orders",
        sa.Column("work_time_mode", sa.String(length=10), nullable=True),
    )
    op.add_column(
        "work_orders",
        sa.Column("work_start_time", sa.Time(), nullable=True),
    )
    op.add_column(
        "work_orders",
        sa.Column("work_end_time", sa.Time(), nullable=True),
    )
    op.add_column(
        "work_orders",
        sa.Column("worked_duration_minutes", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("work_orders", "worked_duration_minutes")
    op.drop_column("work_orders", "work_end_time")
    op.drop_column("work_orders", "work_start_time")
    op.drop_column("work_orders", "work_time_mode")
