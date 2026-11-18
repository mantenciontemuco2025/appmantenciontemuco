"""Add selected-month schedules to preventive plans."""

from alembic import op
import sqlalchemy as sa


revision = "0051_preventive_selected_months"
down_revision = "0050_equipment_name_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("preventive_plans", sa.Column("scheduled_months", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("preventive_plans", "scheduled_months")
