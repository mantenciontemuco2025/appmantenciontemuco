"""Persist the legacy work-order plant areas in the admin catalog."""

from alembic import op
import sqlalchemy as sa

from app.core.work_order_areas import WORK_ORDER_AREAS


revision = "0037_seed_legacy_plant_areas"
down_revision = "0036_unclassified_historical_ots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    statement = sa.text(
        "INSERT INTO plant_areas (name) VALUES (:name) "
        "ON CONFLICT (name) DO NOTHING"
    )
    for name in WORK_ORDER_AREAS:
        connection.execute(statement, {"name": name})


def downgrade() -> None:
    # Keep the catalog rows on downgrade so existing OTs are never affected.
    pass
