"""Add the independent daily water/discharge register."""

from alembic import op
import sqlalchemy as sa


revision = "0022_water_register"
down_revision = "0021_external_work_orders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "water_register_baselines",
        sa.Column("meter_key", sa.String(length=40), primary_key=True),
        sa.Column("final_reading", sa.Numeric(16, 3), nullable=False),
        sa.Column("reading_date", sa.Date(), nullable=False),
        sa.Column("source_row", sa.Integer(), nullable=False),
        sa.Column("initialized_by_user_id", sa.Integer(), nullable=False),
        sa.Column("initialized_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["initialized_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
    )
    op.create_table(
        "water_register_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("record_date", sa.Date(), nullable=False),
        sa.Column("discharge_flow_m3", sa.Numeric(14, 3), nullable=True),
        sa.Column("ph_plc", sa.Numeric(5, 2), nullable=True),
        sa.Column("ph_discharge", sa.Numeric(5, 2), nullable=True),
        sa.Column("discharge_temp_c", sa.Numeric(8, 2), nullable=True),
        sa.Column("dqo_date", sa.Date(), nullable=True),
        sa.Column("dqo_time", sa.String(length=5), nullable=True),
        sa.Column("dqo_pool", sa.String(length=120), nullable=True),
        sa.Column("dqo_mg_l", sa.Numeric(14, 3), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=False),
        sa.Column("sync_status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("sync_error", sa.Text(), nullable=True),
        sa.Column("sync_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sync_next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("synced_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sheet_row", sa.Integer(), nullable=True),
        sa.Column("sheet_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("record_date", name="uq_water_register_record_date"),
    )
    op.create_index(
        "uq_water_register_dqo_date",
        "water_register_records",
        ["dqo_date"],
        unique=True,
        postgresql_where=sa.text("dqo_mg_l IS NOT NULL"),
    )
    op.create_index(
        "ix_water_register_sync_due",
        "water_register_records",
        ["sync_status", "sync_next_attempt_at"],
    )
    op.create_table(
        "water_meter_readings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("record_id", sa.Integer(), nullable=False),
        sa.Column("meter_key", sa.String(length=40), nullable=False),
        sa.Column("initial_reading", sa.Numeric(16, 3), nullable=False),
        sa.Column("final_reading", sa.Numeric(16, 3), nullable=False),
        sa.ForeignKeyConstraint(["record_id"], ["water_register_records.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("record_id", "meter_key", name="uq_water_meter_reading_record_meter"),
    )
    op.create_index(
        "ix_water_meter_reading_meter_date",
        "water_meter_readings",
        ["meter_key", "record_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_water_meter_reading_meter_date", table_name="water_meter_readings")
    op.drop_table("water_meter_readings")
    op.drop_index("ix_water_register_sync_due", table_name="water_register_records")
    op.drop_index("uq_water_register_dqo_date", table_name="water_register_records")
    op.drop_table("water_register_records")
    op.drop_table("water_register_baselines")
