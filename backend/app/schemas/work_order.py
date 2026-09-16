from datetime import datetime, date, time
from typing import Literal
from pydantic import BaseModel, field_validator

from app.models.work_order import WorkOrderStatus, LotoStatus
from app.core.loto import normalize_loto_controls
from app.core.work_order_areas import WORK_ORDER_AREAS


class WorkOrderCreate(BaseModel):
    title: str
    description: str | None = None
    area_id: int
    plant_area: str
    equipment_id: int | None = None
    section_name: str | None = None
    maintenance_type: str  # PREVENTIVE, CORRECTIVE, PREDICTIVE, PROYECTO, MONTAJE
    loto_status: str = LotoStatus.NOT_APPLICABLE.value
    loto_controls: list[str] | None = None
    folio: str | None = None
    estimated_time: str | None = None
    # Fecha de solicitud de la OT — la coloca el admin al crear/solicitar la OT.
    request_date: date | None = None
    execution_date: date | None = None
    resources_required: str | None = None
    voucher_number: str | None = None
    risks: str | None = None
    observations: str | None = None
    requested_by: str | None = None
    approved_by: str | None = None
    participant_names: list[str] = []

    # ── Workflow fields ──────────────────────────────────────────────────
    responsible_user_id: int | None = None
    participant_user_ids: list[int] = []
    # Every new OT participates in the planned-compliance KPI.
    is_planned: bool = True
    scheduled_date: date | None = None
    due_date: date | None = None

    # When True, OT is created as PENDING (emitted).  When False (default),
    # it starts as DRAFT and must be explicitly issued via /issue.
    emit: bool = False

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("El título no puede estar vacío")
        return v.strip()

    @field_validator("maintenance_type")
    @classmethod
    def valid_maintenance_type(cls, v: str) -> str:
        valid = {"PREVENTIVE", "CORRECTIVE", "PREDICTIVE", "PROYECTO", "MONTAJE"}
        if v.upper() not in valid:
            raise ValueError(f"Tipo de mantención inválido. Use: {', '.join(sorted(valid))}")
        return v.upper()

    @field_validator("loto_status")
    @classmethod
    def valid_loto_status(cls, v: str) -> str:
        valid = {"YES", "NO", "NOT_APPLICABLE"}
        if v.upper() not in valid:
            raise ValueError(f"Estado LOTO inválido. Use: {', '.join(sorted(valid))}")
        return v.upper()

    @field_validator("loto_controls")
    @classmethod
    def valid_loto_controls(cls, v: list[str] | None) -> list[str] | None:
        return normalize_loto_controls(v)

    @field_validator("plant_area")
    @classmethod
    def valid_plant_area(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in WORK_ORDER_AREAS:
            raise ValueError(f"Área no válida. Use: {', '.join(WORK_ORDER_AREAS)}")
        return normalized


class WorkOrderUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    area_id: int | None = None
    plant_area: str | None = None
    equipment_id: int | None = None
    section_name: str | None = None
    maintenance_type: str | None = None
    loto_status: str | None = None
    loto_controls: list[str] | None = None
    folio: str | None = None
    estimated_time: str | None = None
    request_date: date | None = None
    execution_date: date | None = None
    resources_required: str | None = None
    voucher_number: str | None = None
    risks: str | None = None
    observations: str | None = None
    requested_by: str | None = None
    approved_by: str | None = None
    status: str | None = None

    # ── Workflow fields ──────────────────────────────────────────────────
    responsible_user_id: int | None = None
    participant_user_ids: list[int] | None = None
    is_planned: bool | None = None
    scheduled_date: date | None = None
    due_date: date | None = None
    completion_notes: str | None = None
    work_time_mode: Literal["RANGE", "MANUAL"] | None = None
    work_start_time: time | None = None
    work_end_time: time | None = None
    worked_duration_minutes: int | None = None
    cancellation_reason: str | None = None
    return_reason: str | None = None

    @field_validator("loto_controls")
    @classmethod
    def valid_loto_controls(cls, v: list[str] | None) -> list[str] | None:
        return normalize_loto_controls(v)

    @field_validator("plant_area")
    @classmethod
    def valid_plant_area(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if normalized not in WORK_ORDER_AREAS:
            raise ValueError(f"Área no válida. Use: {', '.join(WORK_ORDER_AREAS)}")
        return normalized


class WorkOrderResponse(BaseModel):
    id: int
    ot_number: str
    title: str
    description: str | None
    area_id: int
    plant_area: str | None = None
    area_name: str | None = None
    equipment_id: int | None
    equipment_name: str | None = None
    section_name: str | None
    maintenance_type: str
    loto_status: str
    loto_controls: list[str] = []
    folio: str | None
    estimated_time: str | None
    request_date: date | None
    execution_date: date | None
    resources_required: str | None
    voucher_number: str | None
    risks: str | None
    observations: str | None
    requested_by: str | None
    approved_by: str | None
    requested_signature: str | None = None
    approved_signature: str | None = None
    status: str
    submitted_for_review: bool = False

    # ── Workflow fields ──────────────────────────────────────────────────
    responsible_user_id: int | None = None
    responsible_user_name: str | None = None
    participant_user_ids: list[int] = []
    is_planned: bool = False
    scheduled_date: date | None = None
    due_date: date | None = None
    started_at: datetime | None = None
    started_by_user_id: int | None = None
    started_by_name: str | None = None
    completed_at: datetime | None = None
    completed_by_user_id: int | None = None
    completed_by_name: str | None = None
    work_time_mode: str | None = None
    work_start_time: time | None = None
    work_end_time: time | None = None
    worked_duration_minutes: int | None = None
    actual_duration_minutes: float | None = None
    completion_notes: str | None = None
    approved_at: datetime | None = None
    approved_by_user_id: int | None = None
    approved_by_user_name: str | None = None
    cancellation_reason: str | None = None
    returned_at: datetime | None = None
    returned_by_user_id: int | None = None
    return_reason: str | None = None

    # ── Google ───────────────────────────────────────────────────────────
    google_ot_file_id: str | None
    google_ot_url: str | None
    ot_sheet_sync_status: str
    ot_sheet_sync_error: str | None
    ot_sheet_synced_at: datetime | None
    monthly_sheet_sync_status: str
    monthly_sheet_sync_error: str | None
    monthly_sheet_synced_at: datetime | None
    created_by_user_id: int
    created_by_name: str | None = None
    participant_names: list[str] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkOrderCounterResponse(BaseModel):
    """OT counting for the admin panel: totals per year/month + next number.

    per_year: {year: total} across all years.
    per_month: {0: enero ... 11: diciembre} of the CURRENT year.
    """
    current_year: int
    total_all: int
    per_year: dict[int, int]
    per_month: dict[int, int]
    next_ot_number: str


class WorkOrderListResponse(BaseModel):
    id: int
    ot_number: str
    title: str
    area_name: str | None = None
    plant_area: str | None = None
    equipment_name: str | None = None
    section_name: str | None
    maintenance_type: str
    loto_status: str
    status: str
    submitted_for_review: bool = False
    execution_date: date | None
    request_date: date | None = None
    ot_sheet_sync_status: str
    monthly_sheet_sync_status: str
    created_at: datetime

    # ── Workflow fields ──────────────────────────────────────────────────
    responsible_user_id: int | None = None
    responsible_user_name: str | None = None
    is_planned: bool = False
    scheduled_date: date | None = None
    due_date: date | None = None

    model_config = {"from_attributes": True}
