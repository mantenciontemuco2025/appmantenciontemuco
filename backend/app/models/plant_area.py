from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


plant_area_sections = Table(
    "plant_area_sections",
    Base.metadata,
    Column("plant_area_id", Integer, ForeignKey("plant_areas.id", ondelete="CASCADE"), primary_key=True),
    Column("section_id", Integer, ForeignKey("areas.id", ondelete="CASCADE"), primary_key=True),
)


class PlantArea(Base):
    """Plant area used to scope the existing section catalog."""

    __tablename__ = "plant_areas"

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

    sections = relationship(
        "Area",
        secondary=plant_area_sections,
        back_populates="plant_areas",
        # The hierarchy endpoint opts into sections explicitly. Loading them
        # for every PlantArea would expand the whole catalog on simple reads.
        lazy="noload",
    )
    equipment = relationship("Equipment", back_populates="plant_area", lazy="noload")
