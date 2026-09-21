"""Add administrative fields for the dedicated external OT template."""

from alembic import op
import sqlalchemy as sa


revision = "0024_external_ot_admin_fields"
down_revision = "0021_external_work_orders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in (
        "external_quote_number",
        "external_oc_number",
        "external_invoice_number",
        "external_account_number",
        "external_oc_amount",
    ):
        op.add_column(
            "work_orders",
            sa.Column(name, sa.String(length=80), nullable=True),
        )


def downgrade() -> None:
    for name in (
        "external_oc_amount",
        "external_account_number",
        "external_invoice_number",
        "external_oc_number",
        "external_quote_number",
    ):
        op.drop_column("work_orders", name)
