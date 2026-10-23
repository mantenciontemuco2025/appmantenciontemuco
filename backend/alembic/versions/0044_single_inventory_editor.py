"""Allow assigning inventory editing access to one worker."""

from alembic import op
import sqlalchemy as sa


revision = "0044_single_inventory_editor"
down_revision = "0043_equipment_inventory_details"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "can_manage_equipment_inventory",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # A partial unique index makes the one-worker assignment invariant hold
    # even if two administrators submit changes at nearly the same time.
    op.create_index(
        "uq_users_single_equipment_inventory_editor",
        "users",
        ["can_manage_equipment_inventory"],
        unique=True,
        postgresql_where=sa.text("can_manage_equipment_inventory IS TRUE"),
        sqlite_where=sa.text("can_manage_equipment_inventory = 1"),
    )


def downgrade() -> None:
    op.drop_index("uq_users_single_equipment_inventory_editor", table_name="users")
    op.drop_column("users", "can_manage_equipment_inventory")
