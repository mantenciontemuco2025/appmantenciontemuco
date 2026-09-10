"""Audit log routes (SUPERVISOR and ADMIN only)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dependencies import require_roles
from app.db.session import get_db
from app.models.user import User, UserRole
from app.models.audit_log import AuditLog
from app.schemas.audit import AuditLogResponse

router = APIRouter(prefix="/api/audit", tags=["audit"])

supervisor_or_admin = require_roles(UserRole.SUPERVISOR, UserRole.ADMIN)


@router.get("", response_model=list[AuditLogResponse])
async def list_audit_logs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(supervisor_or_admin),
    entity_type: str | None = Query(default=None),
    entity_id: int | None = Query(default=None),
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0),
):
    query = select(AuditLog).options(selectinload(AuditLog.user))

    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)
    if entity_id:
        query = query.where(AuditLog.entity_id == entity_id)

    query = query.order_by(AuditLog.created_at.desc())
    if offset:
        query = query.offset(offset)
    query = query.limit(limit)
    result = await db.execute(query)
    return result.scalars().all()
