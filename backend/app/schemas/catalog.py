from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, Field, field_validator


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


# Plant area (general area that groups sections)
class PlantAreaCreate(BaseModel):
    name: str


class PlantAreaUpdate(BaseModel):
    name: str | None = None


class PlantAreaResponse(BaseModel):
    id: int
    name: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PlantAreaWorkOrderBrief(BaseModel):
    id: int
    ot_number: str
    title: str
    plant_area: str | None = None
    status: str
    execution_date: date | None = None
    created_at: datetime

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


class EquipmentCustomAttribute(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    value: str = Field(default="", max_length=5000)

    @field_validator("label")
    @classmethod
    def clean_label(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El título del atributo no puede quedar vacío")
        return value


class EquipmentInventoryUpdate(BaseModel):
    category: str | None = Field(default=None, max_length=180)
    model: str | None = Field(default=None, max_length=200)
    dimensions: str | None = Field(default=None, max_length=200)
    weight: Decimal | None = Field(default=None, ge=0, le=99999999999)
    unit: str | None = Field(default=None, max_length=40)
    description: str | None = Field(default=None, max_length=10000)
    location: str | None = Field(default=None, max_length=250)
    purchase_receipt_date: date | None = None
    purchased_from: str | None = Field(default=None, max_length=250)
    warranty_end: date | None = None
    web1: str | None = Field(default=None, max_length=500)
    initial_value: Decimal | None = Field(default=None, ge=0, le=999999999999)
    impeller_diameter: str | None = Field(default=None, max_length=100)
    flow_rate: str | None = Field(default=None, max_length=100)
    total_manometric_head: str | None = Field(default=None, max_length=100)
    rotation_speed: str | None = Field(default=None, max_length=100)
    npsh: str | None = Field(default=None, max_length=100)
    operational_status: str | None = Field(default=None, max_length=80)
    last_maintenance_date: date | None = None
    general_spare_parts: str | None = Field(default=None, max_length=10000)
    observations: str | None = Field(default=None, max_length=10000)
    power_hp: str | None = Field(default=None, max_length=80)
    power_kw: str | None = Field(default=None, max_length=80)
    voltage: str | None = Field(default=None, max_length=80)
    current: str | None = Field(default=None, max_length=80)
    revolutions: str | None = Field(default=None, max_length=80)
    efficiency: str | None = Field(default=None, max_length=80)
    capacity: str | None = Field(default=None, max_length=120)
    custom_attributes: list[EquipmentCustomAttribute] = Field(default_factory=list, max_length=50)

    @field_validator("custom_attributes")
    @classmethod
    def unique_custom_attribute_labels(cls, attributes: list[EquipmentCustomAttribute]):
        labels = [item.label.casefold() for item in attributes]
        if len(labels) != len(set(labels)):
            raise ValueError("Los títulos de los atributos personalizados no se pueden repetir")
        return attributes


class EquipmentInventoryResponse(BaseModel):
    id: int
    name: str
    inventory_code: str | None = None
    area_name: str | None = None
    plant_area_name: str | None = None
    category: str | None = None
    model: str | None = None
    dimensions: str | None = None
    weight: Decimal | None = None
    unit: str | None = None
    description: str | None = None
    location: str | None = None
    purchase_receipt_date: date | None = None
    purchased_from: str | None = None
    warranty_end: date | None = None
    web1: str | None = None
    initial_value: Decimal | None = None
    impeller_diameter: str | None = None
    flow_rate: str | None = None
    total_manometric_head: str | None = None
    rotation_speed: str | None = None
    npsh: str | None = None
    operational_status: str | None = None
    last_maintenance_date: date | None = None
    general_spare_parts: str | None = None
    observations: str | None = None
    power_hp: str | None = None
    power_kw: str | None = None
    voltage: str | None = None
    current: str | None = None
    revolutions: str | None = None
    efficiency: str | None = None
    capacity: str | None = None
    custom_attributes: list[EquipmentCustomAttribute] = Field(default_factory=list)


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
