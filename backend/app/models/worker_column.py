"""Stable worker-to-column assignments for the monthly Google register."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


# The monthly template has ten worker columns between EQUIPO/TRABAJO and the
# maintenance-type columns. Keep these logical keys stable even when a user's
# display name changes.
WORKER_COLUMN_SLOTS = (
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


class WorkerColumn(Base):
    """Assignment of one worker to one existing monthly-sheet column."""

    __tablename__ = "worker_columns"

    id: Mapped[int] = mapped_column(primary_key=True)
    slot: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    column_key: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    column_letter: Mapped[str] = mapped_column(String(2), unique=True, nullable=False)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        unique=True,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user = relationship(
        "User",
        back_populates="worker_column",
        foreign_keys=[user_id],
        lazy="joined",
    )
