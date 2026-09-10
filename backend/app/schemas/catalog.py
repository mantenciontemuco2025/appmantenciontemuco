from datetime import datetime
from pydantic import BaseModel


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


class EquipmentUpdate(BaseModel):
    name: str | None = None
    area_id: int | None = None


class EquipmentResponse(BaseModel):
    id: int
    name: str
    area_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EquipmentBrief(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes": True}


# Nested response for the form selectors: Area -> Equipment (direct)
class AreaWithEquipment(BaseModel):
    id: int
    name: str
    equipment: list[EquipmentBrief]

    model_config = {"from_attributes": True}
