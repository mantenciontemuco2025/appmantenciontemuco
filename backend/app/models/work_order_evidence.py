from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkOrderEvidence(Base):
    """Metadata for photos stored privately in Google Drive."""

    __tablename__ = "work_order_evidence"
    __table_args__ = (
        CheckConstraint("stage IN ('ISSUE', 'WORK')", name="ck_wo_evidence_stage"),
        Index("ix_wo_evidence_order_stage", "work_order_id", "stage"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    work_order_id: Mapped[int] = mapped_column(
        ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False
    )
    drive_file_id: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    stage: Mapped[str] = mapped_column(String(20), nullable=False)
    uploaded_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    uploaded_by_name: Mapped[str] = mapped_column(String(200), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
