from datetime import date, datetime

from pydantic import BaseModel


class KpiSummary(BaseModel):
    total_ots: int
    completed_ots: int
    pending_ots: int
    in_progress_ots: int
    cancelled_ots: int
    planned_ots: int
    executed_planned_ots: int
    compliance_percent: float | None
    compliance_target_percent: float
    total_hours: float
    total_person_hours: float
    average_hours_per_ot: float
    overdue_ots: int
    stale_pending_ots: int


class KpiMaintenanceRow(BaseModel):
    maintenance_type: str
    total_ots: int
    completed_ots: int
    total_hours: float


class KpiWorkerRow(BaseModel):
    user_id: int
    worker_name: str
    assigned_ots: int
    completed_ots: int
    total_hours: float
    person_hours: float


class KpiWorkerDetailRow(BaseModel):
    user_id: int
    worker_name: str
    area_name: str
    maintenance_type: str
    assigned_ots: int
    completed_ots: int
    person_hours: float


class KpiAreaTypeRow(BaseModel):
    area_name: str
    maintenance_type: str
    total_ots: int
    completed_ots: int
    total_hours: float


class KpiAreaRow(BaseModel):
    area_name: str
    total_ots: int
    completed_ots: int
    total_hours: float
    preventive_ots: int
    corrective_ots: int


class KpiSectionRow(BaseModel):
    area_name: str
    section_name: str
    total_ots: int
    completed_ots: int
    total_hours: float
    preventive_ots: int
    corrective_ots: int


class KpiMonthRow(BaseModel):
    month: str
    total_ots: int
    completed_ots: int
    planned_ots: int
    executed_planned_ots: int
    compliance_percent: float | None
    total_hours: float


class KpiResponse(BaseModel):
    generated_at: datetime
    date_from: date
    date_to: date
    summary: KpiSummary
    by_maintenance_type: list[KpiMaintenanceRow]
    by_worker: list[KpiWorkerRow]
    by_worker_detail: list[KpiWorkerDetailRow]
    by_area: list[KpiAreaRow]
    by_area_type: list[KpiAreaTypeRow]
    by_section: list[KpiSectionRow]
    by_month: list[KpiMonthRow]
