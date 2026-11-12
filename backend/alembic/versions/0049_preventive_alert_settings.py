"""Add configurable preventive alert lead time."""

from alembic import op
import sqlalchemy as sa


revision = "0049_preventive_alert_settings"
down_revision = "0048_preventive_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "preventive_alert_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("alert_days", sa.Integer(), server_default="30", nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("alert_days >= 1 AND alert_days <= 365", name="ck_preventive_alert_days_range"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.execute(sa.text(
        "INSERT INTO preventive_alert_settings (id, alert_days, updated_at) "
        "VALUES (1, 30, CURRENT_TIMESTAMP)"
    ))


def downgrade() -> None:
    op.drop_table("preventive_alert_settings")
