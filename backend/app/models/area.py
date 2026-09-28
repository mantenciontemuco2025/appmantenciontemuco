from datetime import datetime, timezone

from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Area(Base):
    __tablename__ = "areas"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    equipment = relationship("Equipment", back_populates="area", lazy="selectin")
    # ``Area`` is the legacy section catalog. Keep its IDs stable and add a
    # many-to-many link so a section can legitimately exist in more than one
    # plant area without breaking existing OTs or supervisor assignments.
    plant_areas = relationship(
        "PlantArea",
        secondary="plant_area_sections",
        back_populates="sections",
        lazy="selectin",
    )
