from datetime import datetime, timezone

from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Area(Base):
    __tablename__ = "areas"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Sections are area-scoped; separate plant areas may each have a section
    # with the same visible name, such as "Recepción y Despacho".
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Do not expand the complete equipment catalog whenever an Area is loaded
    # indirectly (for example while authenticating a supervisor). Catalog
    # endpoints request this relationship explicitly when they need it.
    equipment = relationship("Equipment", back_populates="area", lazy="noload")
    # ``Area`` is the legacy section catalog. Parent areas link to independent
    # section rows, while old rows can remain unassigned until an admin places
    # them. Work orders keep their historical section IDs.
    plant_areas = relationship(
        "PlantArea",
        secondary="plant_area_sections",
        back_populates="sections",
        lazy="noload",
    )
