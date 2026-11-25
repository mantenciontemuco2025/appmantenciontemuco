from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PlantAreaMergeHistory(Base):
    __tablename__ = "plant_area_merge_history"
    __table_args__ = (
        Index("ix_plant_area_merge_history_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_plant_area_id: Mapped[int] = mapped_column(
        ForeignKey("plant_areas.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    canonical_plant_area_name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_plant_area_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    source_plant_area_names: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    equipment_moved: Mapped[int] = mapped_column(default=0, nullable=False)
    sections_moved: Mapped[int] = mapped_column(default=0, nullable=False)
    supervisor_assignments_moved: Mapped[int] = mapped_column(default=0, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    reverted_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
