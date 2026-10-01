from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class EquipmentLifeSummary(BaseModel):
    equipment_id: int
    equipment_name: str
    section_name: str | None = None
    plant_area_name: str | None = None
    work_order_count: int
    life_sheet_file_id: str | None = None
    life_sheet_url: str | None = None
    life_sheet_sync_status: str
    life_sheet_sync_error: str | None = None
    life_sheet_synced_at: datetime | None = None


class EquipmentLifeRecord(BaseModel):
    work_order_id: int
    ot_number: str
    original_ot_number: str | None = None
    event_date: date | None = None
    title: str
    description: str | None = None
    performed_by: str | None = None
    observations: str | None = None
    status: str
    maintenance_type: str


class EquipmentLifeDetail(EquipmentLifeSummary):
    records: list[EquipmentLifeRecord]


class EquipmentLifeBackfillPayload(BaseModel):
    include_drafts: bool = False


class EquipmentLifeBackfillResult(BaseModel):
    equipment_total: int
    equipment_with_work_orders: int
    sheets_synced: int
    work_orders_synced: int
    work_orders_without_equipment: int
    errors: list[str]
    equipment_skipped: int = 0
    work_orders_skipped: int = 0


class EquipmentLifeBackfillAccepted(BaseModel):
    status: Literal["started"]
    message: str


class EquipmentLifeBackfillStatus(BaseModel):
    status: Literal["idle", "running", "completed", "failed"]
    started_at: datetime | None = None
    finished_at: datetime | None = None
    equipment_total: int = 0
    equipment_processed: int = 0
    equipment_with_work_orders: int = 0
    work_orders_total: int = 0
    work_orders_synced: int = 0
    sheets_synced: int = 0
    current_equipment: str | None = None
    errors_count: int = 0
    result: EquipmentLifeBackfillResult | None = None
    error: str | None = None
