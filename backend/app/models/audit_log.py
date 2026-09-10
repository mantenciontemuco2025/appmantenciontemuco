import enum
from datetime import datetime, timezone

from sqlalchemy import String, ForeignKey, DateTime, Text, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AuditAction(str, enum.Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    LOGIN = "LOGIN"
    SYNC_GOOGLE_SHEETS = "SYNC_GOOGLE_SHEETS"
    # Work Order actions
    CREATE_WORK_ORDER = "CREATE_WORK_ORDER"
    UPDATE_WORK_ORDER = "UPDATE_WORK_ORDER"
    ISSUE_WORK_ORDER = "ISSUE_WORK_ORDER"
    SYNC_OT_GOOGLE = "SYNC_OT_GOOGLE"
    SYNC_MONTHLY_GOOGLE = "SYNC_MONTHLY_GOOGLE"
    START_WORK_ORDER = "START_WORK_ORDER"
    COMPLETE_WORK_ORDER = "COMPLETE_WORK_ORDER"
    RETURN_WORK_ORDER = "RETURN_WORK_ORDER"
    APPROVE_WORK_ORDER = "APPROVE_WORK_ORDER"
    CANCEL_WORK_ORDER = "CANCEL_WORK_ORDER"
    REOPEN_WORK_ORDER = "REOPEN_WORK_ORDER"
    REASSIGN_WORK_ORDER = "REASSIGN_WORK_ORDER"


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(50))
    entity_type: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[int | None] = mapped_column(nullable=True)
    # JSON type with a JSONB variant for PostgreSQL (portable to SQLite in tests)
    json_type = JSON().with_variant(JSONB(), "postgresql")
    previous_data: Mapped[dict | None] = mapped_column(json_type, nullable=True)
    new_data: Mapped[dict | None] = mapped_column(json_type, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    user = relationship("User", back_populates="audit_logs", lazy="selectin")
