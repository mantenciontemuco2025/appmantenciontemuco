"""Allow one supervisor to manage multiple plant areas."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "supervisor_areas",
        sa.Column("supervisor_id", sa.Integer(), nullable=False),
        sa.Column("area_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["supervisor_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["area_id"], ["areas.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("supervisor_id", "area_id"),
    )
    op.create_index(
        "ix_supervisor_areas_area_id", "supervisor_areas", ["area_id"]
    )

    # Preserve the single-area configuration already created by migration 0011.
    op.execute(
        sa.text(
            "INSERT INTO supervisor_areas (supervisor_id, area_id) "
            "SELECT id, area_id FROM users "
            "WHERE role = 'SUPERVISOR' AND area_id IS NOT NULL"
        )
    )


def downgrade() -> None:
    op.drop_index("ix_supervisor_areas_area_id", table_name="supervisor_areas")
    op.drop_table("supervisor_areas")
