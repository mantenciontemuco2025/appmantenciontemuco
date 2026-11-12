"""Preserve equipment names on work orders when catalog names change."""

from alembic import op
import sqlalchemy as sa


revision = "0050_equipment_name_snapshot"
down_revision = "0049_preventive_alert_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "work_orders",
        sa.Column("equipment_name_snapshot", sa.String(length=250), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE work_orders AS wo "
            "SET equipment_name_snapshot = equipment.name "
            "FROM equipment "
            "WHERE wo.equipment_id = equipment.id"
        )
    )
    op.execute(
        sa.text(
            "UPDATE work_orders AS wo "
            "SET section_name = areas.name "
            "FROM areas "
            "WHERE wo.area_id = areas.id "
            "AND (wo.section_name IS NULL OR trim(wo.section_name) = '')"
        )
    )


def downgrade() -> None:
    op.drop_column("work_orders", "equipment_name_snapshot")
