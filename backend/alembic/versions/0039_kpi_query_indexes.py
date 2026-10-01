"""Add indexes used by dashboard date and catalog filters."""

from alembic import op


revision = "0039_kpi_query_indexes"
down_revision = "0038_equipment_life_sheets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_work_orders_request_date", "work_orders", ["request_date"])
    op.create_index("ix_work_orders_scheduled_date", "work_orders", ["scheduled_date"])
    op.create_index("ix_work_orders_due_date", "work_orders", ["due_date"])
    op.create_index("ix_work_orders_created_at", "work_orders", ["created_at"])
    op.create_index("ix_work_orders_plant_area", "work_orders", ["plant_area"])
    op.create_index("ix_work_orders_section_name", "work_orders", ["section_name"])


def downgrade() -> None:
    op.drop_index("ix_work_orders_section_name", table_name="work_orders")
    op.drop_index("ix_work_orders_plant_area", table_name="work_orders")
    op.drop_index("ix_work_orders_created_at", table_name="work_orders")
    op.drop_index("ix_work_orders_due_date", table_name="work_orders")
    op.drop_index("ix_work_orders_scheduled_date", table_name="work_orders")
    op.drop_index("ix_work_orders_request_date", table_name="work_orders")
