from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class HazardousWasteInput(BaseModel):
    entry_date: date
    respel_code: str | None = Field(default=None, max_length=120)
    waste_name: str = Field(min_length=1, max_length=300)
    hazard: str | None = Field(default=None, max_length=200)
    origin: str | None = Field(default=None, max_length=300)
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=16, decimal_places=0)
    unit: str = Field(default="", max_length=80)
    delivered_by: str | None = Field(default=None, max_length=300)
    disposal_date: date | None = None
    manager: str | None = Field(default=None, max_length=300)


class HazardousWasteDisposalInput(BaseModel):
    disposal_date: date
    manager: str = Field(min_length=1, max_length=300)


class HazardousWasteRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    entry_date: date
    respel_code: str | None
    waste_name: str
    hazard: str | None
    origin: str | None
    quantity: Decimal | None
    unit: str
    accumulated_quantity: Decimal | None
    delivered_by: str | None
    disposal_date: date | None
    manager: str | None
    source_sheet: str | None
    sheet_row: int | None
    sync_status: str
    sync_error: str | None
    sheet_synced_at: datetime | None


class HazardousWasteSetupResponse(BaseModel):
    spreadsheet_id: str
    spreadsheet_url: str
    imported: int
    message: str
