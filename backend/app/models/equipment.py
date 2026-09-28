from datetime import datetime, timezone

from sqlalchemy import String, ForeignKey, DateTime
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    area = relationship("Area", back_populates="equipment", lazy="selectin")
    plant_area = relationship("PlantArea", back_populates="equipment", lazy="selectin")
