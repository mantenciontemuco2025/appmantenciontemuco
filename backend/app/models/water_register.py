from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    JSON,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class WaterRegisterBaseline(Base):
    """One-time opening meter readings imported from the test/master sheet."""

    __tablename__ = "water_register_baselines"

    meter_key: Mapped[str] = mapped_column(String(40), primary_key=True)
    final_reading: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False)
    reading_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_row: Mapped[int] = mapped_column(Integer, nullable=False)
    initialized_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    initialized_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class WaterRegisterRecord(Base):
    """One app-owned daily water/discharge record; separate from work orders."""

    __tablename__ = "water_register_records"
    __table_args__ = (
        UniqueConstraint("record_date", name="uq_water_register_record_date"),
        Index("ix_water_register_sync_due", "sync_status", "sync_next_attempt_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    record_date: Mapped[date] = mapped_column(Date, nullable=False)
    discharge_flow_m3: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    ph_plc: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    ph_discharge: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    discharge_temp_c: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)

    dqo_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    dqo_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    dqo_pool: Mapped[str | None] = mapped_column(String(120), nullable=True)
    dqo_mg_l: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    dqo_rows_to_clear: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)

    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    # Durable retry state for Google Sheets synchronization.
    sync_status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sync_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sync_next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sync_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    synced_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sheet_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sheet_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    meter_readings = relationship(
        "WaterMeterReading",
        back_populates="record",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="WaterMeterReading.meter_key",
    )
    dqo_samples = relationship(
        "WaterDqoSample",
        back_populates="record",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="WaterDqoSample.position, WaterDqoSample.id",
    )


class WaterDqoSample(Base):
    __tablename__ = "water_dqo_samples"
    __table_args__ = (
        Index("ix_water_dqo_samples_record_position", "record_id", "position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(
        ForeignKey("water_register_records.id", ondelete="CASCADE"), nullable=False
    )
    sample_date: Mapped[date] = mapped_column(Date, nullable=False)
    sample_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    pool: Mapped[str | None] = mapped_column(String(120), nullable=True)
    mg_l: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sheet_row: Mapped[int | None] = mapped_column(Integer, nullable=True)

    record = relationship("WaterRegisterRecord", back_populates="dqo_samples")


class WaterMeterReading(Base):
    __tablename__ = "water_meter_readings"
    __table_args__ = (
        UniqueConstraint(
            "record_id", "meter_key", name="uq_water_meter_reading_record_meter"
        ),
        Index("ix_water_meter_reading_meter_date", "meter_key", "record_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(
        ForeignKey("water_register_records.id", ondelete="CASCADE"), nullable=False
    )
    meter_key: Mapped[str] = mapped_column(String(40), nullable=False)
    initial_reading: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False)
    final_reading: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False)

    @property
    def volume_m3(self) -> Decimal:
        """Match the spreadsheet formula: =SI(final>=inicial, final-inicial, 0)."""
        if self.final_reading >= self.initial_reading:
            return self.final_reading - self.initial_reading
        return Decimal("0")

    record = relationship("WaterRegisterRecord", back_populates="meter_readings")
