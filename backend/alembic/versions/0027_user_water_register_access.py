"""Add per-user access for the water register module."""

from alembic import op
import sqlalchemy as sa


revision = "0027_user_water_register_access"
down_revision = "0026_merge_water_external_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "can_manage_water_register",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "can_manage_water_register")
