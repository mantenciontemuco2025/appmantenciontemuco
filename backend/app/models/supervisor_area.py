from sqlalchemy import Column, ForeignKey, Integer, Table

from app.db.base import Base


supervisor_areas = Table(
    "supervisor_areas",
    Base.metadata,
    Column("supervisor_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("area_id", Integer, ForeignKey("areas.id", ondelete="CASCADE"), primary_key=True),
)

supervisor_plant_areas = Table(
    "supervisor_plant_areas",
    Base.metadata,
    Column("supervisor_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("plant_area_id", Integer, ForeignKey("plant_areas.id", ondelete="CASCADE"), primary_key=True),
)

supervisor_area_section_exclusions = Table(
    "supervisor_area_section_exclusions",
    Base.metadata,
    Column("supervisor_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("section_id", Integer, ForeignKey("areas.id", ondelete="CASCADE"), primary_key=True),
)
