import enum
from datetime import datetime, timezone

from sqlalchemy import String, Boolean, DateTime, Enum, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    SUPERVISOR = "SUPERVISOR"
    WORKER = "WORKER"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.WORKER)
    # Supervisors are scoped to one plant area. Workers/admins keep this NULL.
    area_id: Mapped[int | None] = mapped_column(
        ForeignKey("areas.id"), nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # URL de Drive de la firma manuscrita del usuario (cargada una vez, en su
    # perfil). Se usa para pegarla como imagen en el documento de la OT y para
    # mostrarla en la app. NULL si el usuario aún no ha subido su firma.
    signature: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # relationships
    audit_logs = relationship("AuditLog", back_populates="user", lazy="selectin")
    created_maintenances = relationship(
        "MaintenanceRecord", back_populates="created_by", lazy="selectin"
    )
    participations = relationship(
        "MaintenanceRecord",
        secondary="maintenance_participants",
        back_populates="participants",
        lazy="selectin",
    )
    work_orders = relationship(
        "WorkOrder",
        secondary="work_order_participants",
        back_populates="participants",
        lazy="selectin",
    )
    supervisor_area = relationship("Area", foreign_keys=[area_id], lazy="selectin")
    supervised_areas = relationship(
        "Area",
        secondary="supervisor_areas",
        lazy="selectin",
    )
    worker_column = relationship(
        "WorkerColumn",
        back_populates="user",
        uselist=False,
        foreign_keys="WorkerColumn.user_id",
        # Do not add a query to every user/auth/list response. The admin
        # column screen loads the relationship from WorkerColumn directly.
        lazy="noload",
    )

    @property
    def area_name(self) -> str | None:
        return self.supervisor_area.name if self.supervisor_area else None

    @property
    def area_ids(self) -> list[int]:
        ids = [area.id for area in (self.supervised_areas or [])]
        if ids:
            return ids
        return [self.area_id] if self.area_id is not None else []

    @property
    def area_names(self) -> list[str]:
        names = [area.name for area in (self.supervised_areas or [])]
        if names:
            return names
        return [self.area_name] if self.area_name else []
