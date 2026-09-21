"""Remember which Google OT template was used for each document."""

from alembic import op
import sqlalchemy as sa


revision = "0025_ot_template_kind"
down_revision = "0024_external_ot_admin_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "work_orders",
        sa.Column("google_ot_template_kind", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("work_orders", "google_ot_template_kind")
