from sqlalchemy import Column, ForeignKey, Integer, Table

from app.db.base import Base


supervisor_areas = Table(
    "supervisor_areas",
    Base.metadata,
    Column("supervisor_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("area_id", Integer, ForeignKey("areas.id", ondelete="CASCADE"), primary_key=True),
)
