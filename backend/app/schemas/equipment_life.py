from datetime import date, datetime, time
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
    is_historical: bool = False
    hallazgo_folio: str | None = None
    hallazgo_kind: str | None = None
    hallazgo_priority: str | None = None
    hallazgo_status: str | None = None
    hallazgo_review_notes: str | None = None
    hallazgo_reviewed_at: datetime | None = None
    hallazgo_reviewed_by_name: str | None = None
    event_date: date | None = None
    title: str
    description: str | None = None
    performed_by: str | None = None
    observations: str | None = None
    status: str
    maintenance_type: str


class EquipmentLifeDetail(EquipmentLifeSummary):
    records: list[EquipmentLifeRecord]


class EquipmentLifeWorkOrderView(BaseModel):
    """Read-only OT fields exposed from the equipment life history."""

    work_order_id: int
    equipment_id: int
    ot_number: str
    original_ot_number: str | None = None
    event_date: date | None = None
    title: str
    description: str | None = None
    request_date: date | None = None
    execution_date: date | None = None
    scheduled_date: date | None = None
    due_date: date | None = None
    plant_area_name: str | None = None
    section_name: str | None = None
    equipment_name: str
    area_name: str | None = None
    requested_by: str | None = None
    approved_by: str | None = None
    performed_by: str | None = None
    responsible_user: str | None = None
    participants: list[str] = []
    participant_names: list[str] = []
    observations: str | None = None
    completion_notes: str | None = None
    resources_required: str | None = None
    risks: str | None = None
    material_codes: str | None = None
    maintenance_type: str
    estimated_time: str | None = None
    loto_status: str | None = None
    loto_controls: list[str] = []
    status: str
    is_planned: bool = False
    submitted_for_review: bool = False
    is_external_work: bool = False
    external_executor_name: str | None = None
    external_company: str | None = None
    external_quote_number: str | None = None
    external_oc_number: str | None = None
    external_invoice_number: str | None = None
    external_account_number: str | None = None
    work_time_mode: str | None = None
    work_start_time: time | None = None
    work_end_time: time | None = None
    worked_duration_minutes: int | None = None
    actual_duration_minutes: float | None = None
    folio: str | None = None
    voucher_number: str | None = None
    voucher_date: date | None = None
    requested_signature: str | None = None
    approved_signature: str | None = None
    created_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    started_at: datetime | None = None
    started_by: str | None = None
    completed_at: datetime | None = None
    completed_by: str | None = None
    approved_at: datetime | None = None
    approved_by_user: str | None = None
    requires_supervisor_validation: bool = False
    supervisor_review_status: str | None = None
    supervisor_reviewed_at: datetime | None = None
    supervisor_review_notes: str | None = None
    supervisor_validator: str | None = None
    cancellation_reason: str | None = None
    returned_at: datetime | None = None
    return_reason: str | None = None
    evidence: list["EquipmentLifeEvidence"] = []


class EquipmentLifeEvidence(BaseModel):
    id: int
    filename: str
    mime_type: str
    stage: Literal["ISSUE", "WORK"]
    uploaded_by_name: str
    uploaded_at: datetime


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
