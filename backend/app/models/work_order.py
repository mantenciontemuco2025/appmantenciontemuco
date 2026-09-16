import enum
from datetime import datetime, time, timezone

from sqlalchemy import (
    String,
    ForeignKey,
    DateTime,
    Date,
    Time,
    Integer,
    Enum,
    Text,
    Boolean,
    Float,
    Index,
    JSON,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class WorkOrderStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    APPROVED = "APPROVED"
    CANCELLED = "CANCELLED"


class LotoStatus(str, enum.Enum):
    YES = "YES"
    NO = "NO"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class WorkOrder(Base):
    """Work Order (OT) — individual document created from a Google Drive template."""

    __tablename__ = "work_orders"
    __table_args__ = (
        # Supports overdue queries and status-filtered lists ordered by date.
        Index("ix_work_orders_due_date_status", "due_date", "status"),
        Index("ix_work_orders_status_created_at", "status", "created_at"),
        Index("ix_work_orders_coordinator_user_id", "coordinator_user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ot_number: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    area_id: Mapped[int] = mapped_column(ForeignKey("areas.id"), index=True)
    # The old Area catalog is retained as the Section catalog, since each
    # catalog entry owns its equipment. Nullable for historical work orders.
    plant_area: Mapped[str | None] = mapped_column(String(50), nullable=True)
    equipment_id: Mapped[int | None] = mapped_column(
        ForeignKey("equipment.id"), nullable=True
    )

    maintenance_type: Mapped[str] = mapped_column(String(20))
    loto_status: Mapped[str] = mapped_column(
        String(20), default=LotoStatus.NOT_APPLICABLE.value
    )
    # New multi-select controls. The legacy loto_status remains for old OTs
    # and integrations that still understand YES/NO/NOT_APPLICABLE.
    loto_controls: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=lambda: ["NOT_APPLICABLE"]
    )

    folio: Mapped[str | None] = mapped_column(String(50), nullable=True)
    section_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    estimated_time: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Fecha en que se solicitó la OT. La coloca el admin al solicitar/crear la OT.
    request_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    execution_date: Mapped[datetime | None] = mapped_column(Date, nullable=True, index=True)
    resources_required: Mapped[str | None] = mapped_column(Text, nullable=True)
    voucher_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    risks: Mapped[str | None] = mapped_column(Text, nullable=True)
    observations: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Participant names stored as comma-separated text (for Google Sheets sync)
    participant_names: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), default=WorkOrderStatus.DRAFT.value
    )

    # Supervisor submissions wait for administrative review and assignment.
    submitted_for_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # ── Responsible ──────────────────────────────────────────────────────
    responsible_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    # External performers have no application account. Keep their identity and
    # the internal administrator coordinating/verifying the OT separate from
    # the employee participant list used by person-hour KPIs.
    is_external_work: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    external_executor_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    external_company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    coordinator_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # ── Planning ─────────────────────────────────────────────────────────
    is_planned: Mapped[bool] = mapped_column(Boolean, default=True)
    scheduled_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)

    # ── Lifecycle timestamps ─────────────────────────────────────────────
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    # Worker-declared work time. The lifecycle timestamps above remain an
    # audit trail and are deliberately not used as the worked duration.
    work_time_mode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    work_start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    work_end_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    worked_duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_duration_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    completion_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    returned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    returned_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    return_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Google Drive / Sheets references ─────────────────────────────────
    google_ot_file_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    google_ot_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    google_ot_sheet_id: Mapped[str | None] = mapped_column(String(200), nullable=True)

    ot_sheet_sync_status: Mapped[str] = mapped_column(String(20), default="PENDING")
    ot_sheet_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    ot_sheet_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    monthly_sheet_sync_status: Mapped[str] = mapped_column(String(20), default="PENDING")
    monthly_sheet_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    monthly_sheet_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Signature placeholders (image URLs captured from app in the future)
    requested_signature: Mapped[str | None] = mapped_column(String(500), nullable=True)
    approved_signature: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # ── Relationships ────────────────────────────────────────────────────
    area = relationship("Area", lazy="selectin")
    equipment = relationship("Equipment", lazy="selectin")
    created_by = relationship("User", foreign_keys=[created_by_user_id], lazy="selectin")

    responsible_user = relationship(
        "User", foreign_keys=[responsible_user_id], lazy="selectin"
    )

    started_by_user = relationship(
        "User", foreign_keys=[started_by_user_id], lazy="selectin"
    )
    completed_by_user = relationship(
        "User", foreign_keys=[completed_by_user_id], lazy="selectin"
    )
    approved_by_user = relationship(
        "User", foreign_keys=[approved_by_user_id], lazy="selectin"
    )

    participants = relationship(
        "User",
        secondary="work_order_participants",
        back_populates="work_orders",
        lazy="selectin",
    )
