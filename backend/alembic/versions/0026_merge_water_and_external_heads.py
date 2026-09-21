"""Merge the water-register and external-work-order migration branches."""

from alembic import op


revision = "0026_merge_water_external_heads"
down_revision = ("0023_multiple_water_dqo_samples", "0025_ot_template_kind")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
