"""Associate supervisors with the plant area they manage."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Batch mode also works with the SQLite database used in local/dev runs.
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("area_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_users_area_id_areas", "areas", ["area_id"], ["id"]
        )
        batch_op.create_index("ix_users_area_id", ["area_id"])


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_index("ix_users_area_id")
        batch_op.drop_constraint("fk_users_area_id_areas", type_="foreignkey")
        batch_op.drop_column("area_id")
