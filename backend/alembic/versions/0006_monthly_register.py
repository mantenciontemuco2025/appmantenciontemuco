"""Add GoogleMonthlyRegister table.

Stores one annual monthly-registry spreadsheet per year (year -> spreadsheet_id),
replacing the single fixed GOOGLE_MONTHLY_SPREADSHEET_ID dependency for resolving
which register a WorkOrder syncs into. Structural only: the existing 2026 register
is backfilled separately (backfill_monthly_registers.py) so no env-dependence is
baked into the migration.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "google_monthly_registers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("spreadsheet_id", sa.String(length=200), nullable=False),
        sa.Column("spreadsheet_url", sa.String(length=500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("year", name="uq_google_monthly_registers_year"),
    )
    op.create_index(
        "ix_google_monthly_registers_year",
        "google_monthly_registers",
        ["year"],
    )


def downgrade() -> None:
    op.drop_index("ix_google_monthly_registers_year", table_name="google_monthly_registers")
    op.drop_table("google_monthly_registers")
