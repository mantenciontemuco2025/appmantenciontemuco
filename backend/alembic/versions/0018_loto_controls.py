"""Add multi-select LOTO controls to work orders."""

from alembic import op
import sqlalchemy as sa


revision = "0018_loto_controls"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "work_orders",
        sa.Column(
            "loto_controls",
            sa.JSON(),
            nullable=False,
            server_default='["NOT_APPLICABLE"]',
        ),
    )
    op.alter_column("work_orders", "loto_controls", server_default=None)


def downgrade() -> None:
    op.drop_column("work_orders", "loto_controls")
