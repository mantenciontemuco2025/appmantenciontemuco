from datetime import date, datetime, timezone

from sqlalchemy import String, ForeignKey, DateTime, Date, Numeric, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Equipment(Base):
    """Physical equipment entry. Legacy rows may not have an inventory code."""

    __tablename__ = "equipment"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    area_id: Mapped[int] = mapped_column(ForeignKey("areas.id"))
    plant_area_id: Mapped[int | None] = mapped_column(
        ForeignKey("plant_areas.id", ondelete="SET NULL"), nullable=True, index=True
    )
    inventory_code: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    category: Mapped[str | None] = mapped_column(String(180), nullable=True)
    location: Mapped[str | None] = mapped_column(String(250), nullable=True)
    operational_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    dimensions: Mapped[str | None] = mapped_column(String(200), nullable=True)
    weight: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    purchase_receipt_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    purchased_from: Mapped[str | None] = mapped_column(String(250), nullable=True)
    warranty_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    web1: Mapped[str | None] = mapped_column(String(500), nullable=True)
    initial_value: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    impeller_diameter: Mapped[str | None] = mapped_column(String(100), nullable=True)
    flow_rate: Mapped[str | None] = mapped_column(String(100), nullable=True)
    total_manometric_head: Mapped[str | None] = mapped_column(String(100), nullable=True)
    rotation_speed: Mapped[str | None] = mapped_column(String(100), nullable=True)
    npsh: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_maintenance_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    general_spare_parts: Mapped[str | None] = mapped_column(Text, nullable=True)
    observations: Mapped[str | None] = mapped_column(Text, nullable=True)
    power_hp: Mapped[str | None] = mapped_column(String(80), nullable=True)
    power_kw: Mapped[str | None] = mapped_column(String(80), nullable=True)
    voltage: Mapped[str | None] = mapped_column(String(80), nullable=True)
    current: Mapped[str | None] = mapped_column(String(80), nullable=True)
    revolutions: Mapped[str | None] = mapped_column(String(80), nullable=True)
    efficiency: Mapped[str | None] = mapped_column(String(80), nullable=True)
    capacity: Mapped[str | None] = mapped_column(String(120), nullable=True)
    custom_attributes: Mapped[list[dict[str, str]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    # Google Drive hoja de vida. La OT y sus datos siguen siendo la fuente de
    # verdad; estos campos solo guardan la referencia de la copia creada desde
    # la plantilla maestra.
    life_sheet_file_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    life_sheet_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    life_sheet_sync_status: Mapped[str] = mapped_column(
        String(20), default="PENDING", server_default="PENDING", nullable=False
    )
    life_sheet_sync_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    life_sheet_synced_at: Mapped[datetime | None] = mapped_column(
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

    # Most responses only need the foreign-key IDs. The equipment-life
    # endpoints opt into both relationships explicitly because they need the
    # display names; keeping them unloaded avoids catalog fan-out elsewhere.
    area = relationship("Area", back_populates="equipment", lazy="noload")
    plant_area = relationship("PlantArea", back_populates="equipment", lazy="noload")
