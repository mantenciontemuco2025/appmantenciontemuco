"""Add stable assignments for the ten worker columns in the monthly register."""

from typing import Sequence, Union
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


_SLOTS = (
    (1, "ORTIZ", "G"),
    (2, "VALDES", "H"),
    (3, "FABRES", "I"),
    (4, "JARA", "J"),
    (5, "SALAZAR", "K"),
    (6, "MILLAR", "L"),
    (7, "JUAN_SILVA", "M"),
    (8, "INOSTROZA", "N"),
    (9, "CANIULLAN", "O"),
    (10, "CONTRERAS", "P"),
)


def _normalize(value: str) -> str:
    import unicodedata

    text = unicodedata.normalize("NFKD", value)
    return "".join(c for c in text if not unicodedata.combining(c)).strip().upper()


def upgrade() -> None:
    op.create_table(
        "worker_columns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slot", sa.Integer(), nullable=False),
        sa.Column("column_key", sa.String(length=30), nullable=False),
        sa.Column("column_letter", sa.String(length=2), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("slot", name="uq_worker_columns_slot"),
        sa.UniqueConstraint("column_key", name="uq_worker_columns_key"),
        sa.UniqueConstraint("column_letter", name="uq_worker_columns_letter"),
        sa.UniqueConstraint("user_id", name="uq_worker_columns_user"),
    )

    # Insert the ten known positions. They correspond to the existing G:P
    # columns; no Google Sheet columns are added or removed by this migration.
    worker_columns = sa.table(
        "worker_columns",
        sa.column("slot", sa.Integer()),
        sa.column("column_key", sa.String()),
        sa.column("column_letter", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(timezone.utc)
    op.bulk_insert(
        worker_columns,
        [
            {
                "slot": slot,
                "column_key": key,
                "column_letter": letter,
                "created_at": now,
                "updated_at": now,
            }
            for slot, key, letter in _SLOTS
        ],
    )

    # Best-effort migration for existing workers whose names match the old
    # fixed headers. Unmatched workers remain visible in PARTICIPANTES and can
    # be assigned safely from the admin screen.
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, full_name FROM users WHERE role = 'WORKER'")
    ).fetchall()
    by_name: dict[str, list[int]] = {}
    for user_id, full_name in rows:
        by_name.setdefault(_normalize(str(full_name)), []).append(int(user_id))

    for slot, key, _letter in _SLOTS:
        matches = by_name.get(key.replace("_", " "), [])
        if len(matches) == 1:
            bind.execute(
                sa.text(
                    "UPDATE worker_columns SET user_id = :user_id "
                    "WHERE slot = :slot"
                ),
                {"user_id": matches[0], "slot": slot},
            )


def downgrade() -> None:
    op.drop_table("worker_columns")
