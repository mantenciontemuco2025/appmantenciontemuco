from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class GoogleMonthlyRegister(Base):
    """One annual monthly-registry spreadsheet per year.

    Replaces the single fixed GOOGLE_MONTHLY_SPREADSHEET_ID dependency: each
    calendar year owns its own "Registro_Mantencion_<AÑO>" spreadsheet in Drive,
    created lazily from a master template on the first real need.

    PostgreSQL is the source of truth for which spreadsheet belongs to which
    year; Google Sheets is the documentary/summary destination.
    """

    __tablename__ = "google_monthly_registers"

    id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)
    spreadsheet_id: Mapped[str] = mapped_column(String(200), nullable=False)
    spreadsheet_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    created_by = relationship("User", foreign_keys=[created_by_user_id], lazy="selectin")
