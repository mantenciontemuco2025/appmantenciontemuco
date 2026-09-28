from datetime import datetime
from pydantic import BaseModel, Field


# Area
class AreaCreate(BaseModel):
    name: str


class AreaUpdate(BaseModel):
    name: str | None = None


class AreaResponse(BaseModel):
    id: int
    name: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AreaBrief(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes": True}


# Equipment (tipo de equipo). Belongs to an Area.
class EquipmentCreate(BaseModel):
    name: str
    area_id: int
    plant_area_id: int | None = None
    inventory_code: str | None = Field(default=None, max_length=50)
    category: str | None = Field(default=None, max_length=180)
    location: str | None = Field(default=None, max_length=250)
    operational_status: str | None = Field(default=None, max_length=80)


class EquipmentUpdate(BaseModel):
    name: str | None = None
    area_id: int | None = None
    plant_area_id: int | None = None
    inventory_code: str | None = Field(default=None, max_length=50)
    category: str | None = Field(default=None, max_length=180)
    location: str | None = Field(default=None, max_length=250)
    operational_status: str | None = Field(default=None, max_length=80)


class EquipmentResponse(BaseModel):
    id: int
    name: str
    area_id: int
    plant_area_id: int | None = None
    inventory_code: str | None = None
    category: str | None = None
    location: str | None = None
    operational_status: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EquipmentBrief(BaseModel):
    id: int
    name: str
    inventory_code: str | None = None
    category: str | None = None
    location: str | None = None
    operational_status: str | None = None

    model_config = {"from_attributes": True}


# Nested response for the form selectors: Area -> Equipment (direct)
class AreaWithEquipment(BaseModel):
    id: int
    name: str
    equipment: list[EquipmentBrief]

    model_config = {"from_attributes": True}


class PlantAreaBrief(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes": True}


class HierarchyEquipment(BaseModel):
    id: int
    name: str
    plant_area_id: int | None = None
    inventory_code: str | None = None
    category: str | None = None
    location: str | None = None
    operational_status: str | None = None

    model_config = {"from_attributes": True}


class SectionWithEquipment(BaseModel):
    id: int
    name: str
    equipment: list[HierarchyEquipment]

    model_config = {"from_attributes": True}


class PlantAreaWithSections(BaseModel):
    id: int
    name: str
    sections: list[SectionWithEquipment]

    model_config = {"from_attributes": True}


class InventoryImportItem(BaseModel):
    # These fields intentionally allow empty values so the importer can skip
    # incomplete workbook rows and report them without rejecting the whole file.
    inventory_code: str = Field(default="", max_length=50)
    plant_area: str = Field(default="", max_length=200)
    section: str = Field(default="", max_length=200)
    equipment: str = Field(default="", max_length=200)
    category: str | None = Field(default=None, max_length=180)
    location: str | None = Field(default=None, max_length=250)
    operational_status: str | None = Field(default=None, max_length=80)


class InventoryImportPayload(BaseModel):
    items: list[InventoryImportItem] = Field(min_length=1, max_length=5000)


class InventoryImportResult(BaseModel):
    received: int
    areas_created: int
    sections_created: int
    links_created: int
    equipment_created: int
    equipment_updated: int
    skipped: int
    errors: list[str]
