from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PreventiveAlertSettings(Base):
    """Singleton settings for preventive-maintenance alert timing."""

    __tablename__ = "preventive_alert_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    alert_days: Mapped[int] = mapped_column(Integer, default=30, server_default="30", nullable=False)
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )


class PreventivePlan(Base):
    """Recurring preventive task configured for one inventory equipment item."""

    __tablename__ = "preventive_plans"
    __table_args__ = (
        Index("ix_preventive_plans_due_active", "active", "next_due_date"),
        Index("ix_preventive_plans_equipment", "equipment_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    equipment_id: Mapped[int] = mapped_column(
        ForeignKey("equipment.id", ondelete="RESTRICT"), nullable=False
    )
    source_key: Mapped[str | None] = mapped_column(String(180), unique=True, nullable=True)
    source_plan_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    periodicity: Mapped[str | None] = mapped_column(String(30), nullable=True)
    interval_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    planned_month: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_completed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    spare_parts: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_time: Mapped[str | None] = mapped_column(String(80), nullable=True)
    condition: Mapped[str | None] = mapped_column(String(120), nullable=True)
    observations: Mapped[str | None] = mapped_column(Text, nullable=True)
    responsible_name_hint: Mapped[str | None] = mapped_column(String(200), nullable=True)
    default_responsible_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )

    equipment = relationship("Equipment", lazy="selectin")
    default_responsible = relationship("User", foreign_keys=[default_responsible_user_id], lazy="selectin")
    created_by = relationship("User", foreign_keys=[created_by_user_id], lazy="noload")
