from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EquipmentMergeHistory(Base):
    __tablename__ = "equipment_merge_history"
    __table_args__ = (
        Index("ix_equipment_merge_history_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_equipment_id: Mapped[int] = mapped_column(
        ForeignKey("equipment.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    canonical_equipment_name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_equipment_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    source_equipment_names: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    work_orders_moved: Mapped[int] = mapped_column(default=0, nullable=False)
    maintenance_records_moved: Mapped[int] = mapped_column(default=0, nullable=False)
    preventive_plans_moved: Mapped[int] = mapped_column(default=0, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", nullable=False)
    life_sheet_sync_status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    reverted_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
