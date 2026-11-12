from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator


PERIODICITIES = {"MONTHLY", "QUARTERLY", "SEMIANNUAL", "ANNUAL", "CUSTOM"}


class PreventiveAlertSettingsUpdate(BaseModel):
    alert_days: int = Field(ge=1, le=365)


class PreventiveAlertSettingsResponse(BaseModel):
    alert_days: int
    updated_at: datetime | None = None


class PreventivePlanCreate(BaseModel):
    equipment_id: int
    periodicity: str | None = None
    interval_months: int | None = Field(default=None, ge=1, le=120)
    planned_month: str | None = Field(default=None, max_length=40)
    last_completed_date: date | None = None
    next_due_date: date | None = None
    description: str | None = None
    spare_parts: str | None = None
    estimated_time: str | None = Field(default=None, max_length=80)
    condition: str | None = Field(default=None, max_length=120)
    observations: str | None = None
    responsible_name_hint: str | None = Field(default=None, max_length=200)
    default_responsible_user_id: int | None = None

    @field_validator("periodicity")
    @classmethod
    def normalize_periodicity(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.strip().upper()
        if normalized not in PERIODICITIES:
            raise ValueError("Periodicidad no válida.")
        return normalized


class PreventivePlanUpdate(BaseModel):
    periodicity: str | None = None
    interval_months: int | None = Field(default=None, ge=1, le=120)
    planned_month: str | None = Field(default=None, max_length=40)
    last_completed_date: date | None = None
    next_due_date: date | None = None
    description: str | None = None
    spare_parts: str | None = None
    estimated_time: str | None = Field(default=None, max_length=80)
    condition: str | None = Field(default=None, max_length=120)
    observations: str | None = None
    responsible_name_hint: str | None = Field(default=None, max_length=200)
    default_responsible_user_id: int | None = None
    active: bool | None = None

    @field_validator("periodicity")
    @classmethod
    def normalize_periodicity(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.strip().upper()
        if normalized not in PERIODICITIES:
            raise ValueError("Periodicidad no válida.")
        return normalized


class PreventiveImportItem(BaseModel):
    source_plan_id: str | None = Field(default=None, max_length=80)
    equipment_inventory_id: str = Field(min_length=1, max_length=80)
    area_name: str | None = None
    section_name: str | None = None
    equipment_name: str | None = None
    periodicity: str | None = None
    planned_month: str | None = None
    last_completed_date: date | None = None
    next_due_date: date | None = None
    description: str | None = None
    spare_parts: str | None = None
    estimated_time: str | None = None
    condition: str | None = None
    observations: str | None = None
    responsible_name_hint: str | None = None


class PreventiveImportRequest(BaseModel):
    items: list[PreventiveImportItem] = Field(max_length=1000)


class PreventiveImportMatch(BaseModel):
    source_plan_id: str | None
    equipment_inventory_id: str
    equipment_id: int | None
    equipment_display_name: str | None
    status: str
    reason: str | None = None


class PreventiveImportPreview(BaseModel):
    total_with_id: int
    matched: int
    unmatched: list[PreventiveImportMatch]
    existing: int


class PreventiveImportResult(BaseModel):
    imported: int
    already_imported: int
    unmatched: list[PreventiveImportMatch]


class PreventiveWorkOrderSummary(BaseModel):
    id: int
    ot_number: str
    status: str
    created_at: datetime
    completed_at: datetime | None = None


class GeneratePreventiveWorkOrder(BaseModel):
    responsible_user_id: int | None = None


class PreventivePlanResponse(BaseModel):
    id: int
    equipment_id: int
    equipment_name: str
    inventory_code: str | None = None
    area_name: str | None = None
    section_name: str | None = None
    plant_area: str | None = None
    source_plan_id: str | None = None
    periodicity: str | None = None
    interval_months: int | None = None
    planned_month: str | None = None
    last_completed_date: date | None = None
    next_due_date: date | None = None
    description: str | None = None
    spare_parts: str | None = None
    estimated_time: str | None = None
    condition: str | None = None
    observations: str | None = None
    responsible_name_hint: str | None = None
    default_responsible_user_id: int | None = None
    default_responsible_name: str | None = None
    active: bool
    status: str
    latest_work_order: PreventiveWorkOrderSummary | None = None
    created_at: datetime
    updated_at: datetime
