from datetime import datetime
from pydantic import BaseModel

from app.schemas.user import UserBrief


class AuditLogResponse(BaseModel):
    id: int
    user: UserBrief
    action: str
    entity_type: str
    entity_id: int | None
    previous_data: dict | None
    new_data: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}
