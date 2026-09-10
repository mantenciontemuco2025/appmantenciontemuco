"""Add a signature URL to users.

Each user may upload their handwritten signature once (stored as a Google Drive
file URL, made readable to anyone-with-the-link so Google Sheets can render it
as an overlay image on the OT document). Structural only: no secrets, no env
dependence baked into the migration.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("signature", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "signature")
