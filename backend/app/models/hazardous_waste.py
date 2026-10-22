from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class HazardousWasteSettings(Base):
    __tablename__ = "hazardous_waste_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    spreadsheet_id: Mapped[str] = mapped_column(String(120), nullable=False)
    spreadsheet_url: Mapped[str] = mapped_column(String(500), nullable=False)
    drive_folder_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    configured_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    configured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class HazardousWasteRecord(Base):
    __tablename__ = "hazardous_waste_records"
    __table_args__ = (
        Index("ix_hazardous_waste_year_date", "entry_date", "id"),
        Index("ix_hazardous_waste_sync_due", "sync_status", "sync_next_attempt_at"),
        Index("ix_hazardous_waste_identity", "normalized_code", "normalized_name", "unit"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    respel_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    normalized_code: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    waste_name: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(300), nullable=False)
    hazard: Mapped[str | None] = mapped_column(String(200), nullable=True)
    origin: Mapped[str | None] = mapped_column(String(300), nullable=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(16, 3), nullable=True)
    unit: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    accumulated_quantity: Mapped[Decimal | None] = mapped_column(Numeric(16, 3), nullable=True)
    delivered_by: Mapped[str | None] = mapped_column(String(300), nullable=True)
    disposal_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    manager: Mapped[str | None] = mapped_column(String(300), nullable=True)
    source_sheet: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sheet_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    updated_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    sync_status: Mapped[str] = mapped_column(String(20), default="SYNCED", nullable=False)
    sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sync_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sync_next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sync_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    synced_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    sheet_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
