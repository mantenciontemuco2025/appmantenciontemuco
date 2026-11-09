import enum
from datetime import datetime, timezone

from sqlalchemy import String, Boolean, DateTime, Enum, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    SUPERVISOR = "SUPERVISOR"
    WORKER = "WORKER"


class WaterRegisterPermission(str, enum.Enum):
    NONE = "NONE"
    VIEW = "VIEW"
    EDIT = "EDIT"


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
    # Permite habilitar el mÃ³dulo de registro de agua para usuarios que no
    # tienen rol de supervisor. Los administradores y supervisores conservan
    # el acceso por su rol.
    can_manage_water_register: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    # Permiso explÃ­cito del mÃ³dulo de agua. Se conserva el booleano anterior
    # para compatibilidad con clientes antiguos; este nivel es la fuente nueva.
    water_register_access: Mapped[str] = mapped_column(
        String(10), default=WaterRegisterPermission.NONE.value,
        server_default=WaterRegisterPermission.NONE.value, nullable=False
    )
    # Solo un trabajador a la vez puede editar las fichas del inventario.
    can_manage_equipment_inventory: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
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
    # These reverse collections can contain thousands of rows. Loading them
    # with every authenticated User query made requests such as /auth/me and
    # notifications keep a transaction open while all OT/history rows were
    # fetched. Load them explicitly only in the endpoints that need them.
    audit_logs = relationship("AuditLog", back_populates="user", lazy="noload")
    created_maintenances = relationship(
        "MaintenanceRecord", back_populates="created_by", lazy="noload"
    )
    participations = relationship(
        "MaintenanceRecord",
        secondary="maintenance_participants",
        back_populates="participants",
        lazy="noload",
    )
    work_orders = relationship(
        "WorkOrder",
        secondary="work_order_participants",
        back_populates="participants",
        lazy="noload",
    )
    supervisor_area = relationship("Area", foreign_keys=[area_id], lazy="selectin")
    supervised_areas = relationship(
        "Area",
        secondary="supervisor_areas",
        lazy="selectin",
    )
    supervised_plant_areas = relationship(
        "PlantArea",
        secondary="supervisor_plant_areas",
        lazy="noload",
    )
    excluded_supervised_sections = relationship(
        "Area",
        secondary="supervisor_area_section_exclusions",
        lazy="noload",
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
        if self.supervised_plant_areas:
            return self.supervised_plant_areas[0].name
        return self.supervisor_area.name if self.supervisor_area else None

    @property
    def area_ids(self) -> list[int]:
        legacy_ids = {area.id for area in (self.supervised_areas or [])}
        if self.area_id is not None:
            legacy_ids.add(self.area_id)
        excluded_ids = {area.id for area in (self.excluded_supervised_sections or [])}
        inherited_ids = {
            section.id
            for plant_area in (self.supervised_plant_areas or [])
            for section in (plant_area.sections or [])
        }
        return sorted(legacy_ids | (inherited_ids - excluded_ids))

    @property
    def plant_area_ids(self) -> list[int]:
        return sorted(area.id for area in (self.supervised_plant_areas or []))

    @property
    def plant_area_names(self) -> list[str]:
        return [area.name for area in sorted(self.supervised_plant_areas or [], key=lambda item: item.name.casefold())]

    @property
    def excluded_section_ids(self) -> list[int]:
        return sorted(area.id for area in (self.excluded_supervised_sections or []))

    @property
    def legacy_section_ids(self) -> list[int]:
        ids = {area.id for area in (self.supervised_areas or [])}
        if self.area_id is not None:
            ids.add(self.area_id)
        return sorted(ids)

    @property
    def area_names(self) -> list[str]:
        names = self.plant_area_names
        names.extend(area.name for area in sorted(self.supervised_areas or [], key=lambda item: item.name.casefold()))
        if not names and self.supervisor_area:
            names.append(self.supervisor_area.name)
        return names
