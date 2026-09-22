from datetime import datetime
from pydantic import BaseModel, EmailStr, field_validator

from app.models.user import UserRole, WaterRegisterPermission


class UserBase(BaseModel):
    full_name: str
    email: EmailStr
    role: UserRole = UserRole.WORKER
    area_id: int | None = None
    area_ids: list[int] = []
    is_active: bool = True
    can_manage_water_register: bool = False
    water_register_access: WaterRegisterPermission = WaterRegisterPermission.NONE


class UserCreate(UserBase):
    password: str


class UserUpdate(BaseModel):
    full_name: str | None = None
    email: EmailStr | None = None
    role: UserRole | None = None
    area_id: int | None = None
    area_ids: list[int] | None = None
    is_active: bool | None = None
    can_manage_water_register: bool | None = None
    water_register_access: WaterRegisterPermission | None = None
    password: str | None = None

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str | None) -> str | None:
        if v is not None and len(v) < 6:
            raise ValueError("La contraseña debe tener al menos 6 caracteres.")
        return v


class PasswordChange(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def new_password_min_length(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("La contraseña debe tener al menos 6 caracteres.")
        return v


class UserResponse(UserBase):
    id: int
    area_name: str | None = None
    area_names: list[str] = []
    signature: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserBrief(BaseModel):
    id: int
    full_name: str

    model_config = {"from_attributes": True}
