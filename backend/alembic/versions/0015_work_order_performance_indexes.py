"""Add indexes for common work-order filters and ordering."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_work_orders_area_id", "work_orders", ["area_id"])
    op.create_index(
        "ix_work_orders_execution_date", "work_orders", ["execution_date"]
    )
    op.create_index(
        "ix_work_orders_due_date_status", "work_orders", ["due_date", "status"]
    )
    op.create_index(
        "ix_work_orders_status_created_at", "work_orders", ["status", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_work_orders_status_created_at", table_name="work_orders")
    op.drop_index("ix_work_orders_due_date_status", table_name="work_orders")
    op.drop_index("ix_work_orders_execution_date", table_name="work_orders")
    op.drop_index("ix_work_orders_area_id", table_name="work_orders")
