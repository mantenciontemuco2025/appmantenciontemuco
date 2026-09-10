import enum
from datetime import datetime, date, timezone

from sqlalchemy import (
    String,
    ForeignKey,
    DateTime,
    Date,
    Integer,
    Enum,
    Text,
    Table,
    Column,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class MaintenanceType(str, enum.Enum):
    PREVENTIVE = "PREVENTIVE"
    CORRECTIVE = "CORRECTIVE"
    PREDICTIVE = "PREDICTIVE"
    PROYECTO = "PROYECTO"
    MONTAJE = "MONTAJE"


class SyncStatus(str, enum.Enum):
    PENDING = "PENDING"
    SYNCED = "SYNCED"
    FAILED = "FAILED"


maintenance_participants = Table(
    "maintenance_participants",
    Base.metadata,
    Column("maintenance_id", ForeignKey("maintenance_records.id"), primary_key=True),
    Column("user_id", ForeignKey("users.id"), primary_key=True),
)


class MaintenanceRecord(Base):
    __tablename__ = "maintenance_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date)
    area_id: Mapped[int] = mapped_column(ForeignKey("areas.id"))
    # Section is free text written by the user; not a FK into a catalog table.
    section_name: Mapped[str] = mapped_column(String(200))
    equipment_id: Mapped[int] = mapped_column(ForeignKey("equipment.id"))
    description: Mapped[str] = mapped_column(Text)
    maintenance_type: Mapped[MaintenanceType] = mapped_column(Enum(MaintenanceType))
    start_time: Mapped[str] = mapped_column(String(5))  # "HH:MM"
    end_time: Mapped[str] = mapped_column(String(5))  # "HH:MM"
    duration_minutes: Mapped[int] = mapped_column(Integer)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    # Google Sheets sync
    sheet_sync_status: Mapped[SyncStatus] = mapped_column(
        Enum(SyncStatus), default=SyncStatus.PENDING
    )
    sheet_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sheet_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # relationships
    area = relationship("Area", lazy="selectin")
    equipment = relationship("Equipment", lazy="selectin")
    created_by = relationship("User", back_populates="created_maintenances", lazy="selectin")
    participants = relationship(
        "User",
        secondary=maintenance_participants,
        back_populates="participations",
        lazy="selectin",
    )
