"""Track external OT performers and their internal coordinator."""

from alembic import op
import sqlalchemy as sa


revision = "0021_external_work_orders"
down_revision = "0020_work_order_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "work_orders",
        sa.Column(
            "is_external_work",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "work_orders",
        sa.Column("external_executor_name", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "work_orders",
        sa.Column("external_company", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "work_orders",
        sa.Column("coordinator_user_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_work_orders_coordinator_user_id_users",
        "work_orders",
        "users",
        ["coordinator_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_work_orders_coordinator_user_id",
        "work_orders",
        ["coordinator_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_work_orders_coordinator_user_id", table_name="work_orders")
    op.drop_constraint(
        "fk_work_orders_coordinator_user_id_users",
        "work_orders",
        type_="foreignkey",
    )
    op.drop_column("work_orders", "coordinator_user_id")
    op.drop_column("work_orders", "external_company")
    op.drop_column("work_orders", "external_executor_name")
    op.drop_column("work_orders", "is_external_work")
