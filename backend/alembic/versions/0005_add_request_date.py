"""Add request_date to work_orders.

The admin sets the request date (fecha de solicitud de la OT) when requesting
the OT. It is distinct from execution_date, which the responsible worker fills
when the work actually happens.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "work_orders",
        sa.Column("request_date", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("work_orders", "request_date")