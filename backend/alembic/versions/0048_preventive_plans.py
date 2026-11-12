"""Add equipment preventive plans and link generated work orders."""

from alembic import op
import sqlalchemy as sa


revision = "0048_preventive_plans"
down_revision = "0047_split_sections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "preventive_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("equipment_id", sa.Integer(), nullable=False),
        sa.Column("source_key", sa.String(length=180), nullable=True),
        sa.Column("source_plan_id", sa.String(length=80), nullable=True),
        sa.Column("periodicity", sa.String(length=30), nullable=True),
        sa.Column("interval_months", sa.Integer(), nullable=True),
        sa.Column("planned_month", sa.String(length=40), nullable=True),
        sa.Column("last_completed_date", sa.Date(), nullable=True),
        sa.Column("next_due_date", sa.Date(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("spare_parts", sa.Text(), nullable=True),
        sa.Column("estimated_time", sa.String(length=80), nullable=True),
        sa.Column("condition", sa.String(length=120), nullable=True),
        sa.Column("observations", sa.Text(), nullable=True),
        sa.Column("responsible_name_hint", sa.String(length=200), nullable=True),
        sa.Column("default_responsible_user_id", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["equipment_id"], ["equipment.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["default_responsible_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.UniqueConstraint("source_key", name="uq_preventive_plans_source_key"),
    )
    op.create_index("ix_preventive_plans_due_active", "preventive_plans", ["active", "next_due_date"])
    op.create_index("ix_preventive_plans_equipment", "preventive_plans", ["equipment_id"])
    op.add_column("work_orders", sa.Column("preventive_plan_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_work_orders_preventive_plan_id_preventive_plans",
        "work_orders", "preventive_plans", ["preventive_plan_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_work_orders_preventive_plan_id", "work_orders", ["preventive_plan_id"])
    op.add_column("work_orders", sa.Column("preventive_previous_last_completed_date", sa.Date(), nullable=True))
    op.add_column("work_orders", sa.Column("preventive_previous_next_due_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("work_orders", "preventive_previous_next_due_date")
    op.drop_column("work_orders", "preventive_previous_last_completed_date")
    op.drop_index("ix_work_orders_preventive_plan_id", table_name="work_orders")
    op.drop_constraint("fk_work_orders_preventive_plan_id_preventive_plans", "work_orders", type_="foreignkey")
    op.drop_column("work_orders", "preventive_plan_id")
    op.drop_index("ix_preventive_plans_equipment", table_name="preventive_plans")
    op.drop_index("ix_preventive_plans_due_active", table_name="preventive_plans")
    op.drop_table("preventive_plans")
