"""Allow multiple DQO samples per date without changing meter readings."""

from alembic import op
import sqlalchemy as sa


revision = "0023_multiple_water_dqo_samples"
down_revision = "0022_water_register"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "water_register_records",
        sa.Column("dqo_rows_to_clear", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.create_table(
        "water_dqo_samples",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("record_id", sa.Integer(), nullable=False),
        sa.Column("sample_date", sa.Date(), nullable=False),
        sa.Column("sample_time", sa.String(length=5), nullable=True),
        sa.Column("pool", sa.String(length=120), nullable=True),
        sa.Column("mg_l", sa.Numeric(14, 3), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sheet_row", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["record_id"], ["water_register_records.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_water_dqo_samples_record_position",
        "water_dqo_samples",
        ["record_id", "position"],
    )
    op.execute(
        sa.text(
            """
            INSERT INTO water_dqo_samples
                (record_id, sample_date, sample_time, pool, mg_l, position, sheet_row)
            SELECT id, COALESCE(dqo_date, record_date), dqo_time, dqo_pool,
                   dqo_mg_l, 0, sheet_row
            FROM water_register_records
            WHERE dqo_mg_l IS NOT NULL
            """
        )
    )
    op.drop_index("uq_water_register_dqo_date", table_name="water_register_records")


def downgrade() -> None:
    op.drop_index(
        "ix_water_dqo_samples_record_position", table_name="water_dqo_samples"
    )
    op.drop_table("water_dqo_samples")
    op.drop_column("water_register_records", "dqo_rows_to_clear")
    op.create_index(
        "uq_water_register_dqo_date",
        "water_register_records",
        ["dqo_date"],
        unique=True,
        postgresql_where=sa.text("dqo_mg_l IS NOT NULL"),
    )
