from datetime import datetime, date
from pydantic import BaseModel, field_validator

from app.models.maintenance import MaintenanceType, SyncStatus
from app.schemas.catalog import AreaBrief, EquipmentBrief
from app.schemas.user import UserBrief


class MaintenanceCreate(BaseModel):
    date: date
    area_id: int
    section_name: str  # free text written by the user
    equipment_id: int
    description: str
    maintenance_type: MaintenanceType
    start_time: str  # "HH:MM"
    end_time: str  # "HH:MM"
    participant_ids: list[int]

    @field_validator("section_name")
    @classmethod
    def section_name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("La sección no puede estar vacía")
        return v.strip()

    @field_validator("description")
    @classmethod
    def description_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("La descripción no puede estar vacía")
        return v.strip()

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        parts = v.split(":")
        if len(parts) != 2:
            raise ValueError("Formato de hora inválido, use HH:MM")
        h, m = int(parts[0]), int(parts[1])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError("Hora fuera de rango")
        return v


class MaintenanceUpdate(BaseModel):
    description: str | None = None
    maintenance_type: MaintenanceType | None = None
    start_time: str | None = None
    end_time: str | None = None
    participant_ids: list[int] | None = None


class MaintenanceResponse(BaseModel):
    id: int
    date: date
    area: AreaBrief
    section_name: str
    equipment: EquipmentBrief
    description: str
    maintenance_type: MaintenanceType
    start_time: str
    end_time: str
    duration_minutes: int
    created_by: UserBrief
    participants: list[UserBrief]
    sheet_sync_status: SyncStatus
    sheet_sync_error: str | None
    sheet_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MaintenanceListResponse(BaseModel):
    id: int
    date: date
    area: AreaBrief
    section_name: str
    equipment: EquipmentBrief
    maintenance_type: MaintenanceType
    duration_minutes: int
    sheet_sync_status: SyncStatus
    created_at: datetime

    model_config = {"from_attributes": True}
