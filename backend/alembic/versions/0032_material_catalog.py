"""Add searchable material-code catalog."""

from alembic import op
import sqlalchemy as sa


revision = "0032_material_catalog"
down_revision = "0031_work_order_voucher_details"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "material_catalog",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("family", sa.String(length=180), nullable=False, server_default="Sin familia"),
        sa.Column("source_sheet", sa.String(length=180), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("code", name="uq_material_catalog_code"),
    )
    op.create_index("ix_material_catalog_active_code", "material_catalog", ["active", "code"])
    op.create_index("ix_material_catalog_family", "material_catalog", ["family"])


def downgrade() -> None:
    op.drop_index("ix_material_catalog_family", table_name="material_catalog")
    op.drop_index("ix_material_catalog_active_code", table_name="material_catalog")
    op.drop_table("material_catalog")
