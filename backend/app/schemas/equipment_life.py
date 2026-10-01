from datetime import date, datetime

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
