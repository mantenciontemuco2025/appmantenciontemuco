"""Maintenance records router.

Permission model:
- WORKER: create, list own records
- SUPERVISOR: create, list all, edit, retry sync
- ADMIN: everything
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dependencies import get_current_user, require_roles
from app.db.session import get_db
from app.models.user import User, UserRole
from app.models.area import Area
from app.models.equipment import Equipment
from app.models.maintenance import MaintenanceRecord, MaintenanceType, SyncStatus
from app.schemas.maintenance import (
    MaintenanceCreate,
    MaintenanceResponse,
    MaintenanceListResponse,
    MaintenanceUpdate,
)
from app.services.audit_service import create_audit_log
from app.services.maintenance_service import calculate_duration
from app.services import google_sheets as sheets_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"])

manager_roles = (UserRole.SUPERVISOR, UserRole.ADMIN)
supervisor_or_admin = require_roles(*manager_roles)


# --------------------------------------------------------------------------
# Validation helpers
# --------------------------------------------------------------------------
async def _validate_catalog(
    db: AsyncSession,
    area_id: int,
    equipment_id: int,
):
    """Validate area exists and equipment belongs to it. Returns (area, equipment)."""
    area = await db.get(Area, area_id)
    if area is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Área no válida")

    equipment = await db.get(Equipment, equipment_id)
    if equipment is None or equipment.area_id != area_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El equipo no pertenece al área seleccionada",
        )
    return area, equipment


async def _validate_participants(db: AsyncSession, participant_ids: list[int]) -> list[User]:
    """Validate all participants exist and are active. Returns User list."""
    if not participant_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debe seleccionar al menos un participante",
        )
    result = await db.execute(
        select(User).where(User.id.in_(participant_ids))
    )
    users = result.scalars().all()
    if len(users) != len(set(participant_ids)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Participante(s) no válido(s)",
        )
    for u in users:
        if not u.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"El participante {u.full_name} está desactivado",
            )
    return users


def _base_query():
    """Return the select with standard relationship loading."""
    return select(MaintenanceRecord).options(
        selectinload(MaintenanceRecord.area),
        selectinload(MaintenanceRecord.equipment),
        selectinload(MaintenanceRecord.created_by),
    )


def _base_query_detail():
    """Return the select with all relationships (for single-record endpoints)."""
    return select(MaintenanceRecord).options(
        selectinload(MaintenanceRecord.area),
        selectinload(MaintenanceRecord.equipment),
        selectinload(MaintenanceRecord.created_by),
        selectinload(MaintenanceRecord.participants),
    )


# --------------------------------------------------------------------------
# Create
# --------------------------------------------------------------------------
@router.post("", response_model=MaintenanceResponse, status_code=status.HTTP_201_CREATED)
async def create_maintenance(
    payload: MaintenanceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Validate catalog: area exists and equipment belongs to it
    area, equipment = await _validate_catalog(db, payload.area_id, payload.equipment_id)

    # Validate participants
    participants = await _validate_participants(db, payload.participant_ids)

    # Validate duration (end > start) and compute minutes
    try:
        duration = calculate_duration(payload.start_time, payload.end_time)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    record = MaintenanceRecord(
        date=payload.date,
        area_id=payload.area_id,
        section_name=payload.section_name,
        equipment_id=payload.equipment_id,
        description=payload.description,
        maintenance_type=payload.maintenance_type,
        start_time=payload.start_time,
        end_time=payload.end_time,
        duration_minutes=duration,
        created_by_user_id=current_user.id,
        sheet_sync_status=SyncStatus.PENDING,
    )
    db.add(record)
    # Assign participants BEFORE flush: on an un-persisted instance
    # SQLAlchemy doesn't need a lazy-load to sync the collection (avoids
    # MissingGreenlet in async contexts).
    record.participants = participants
    await db.flush()

    # Audit CREATE
    await create_audit_log(
        db,
        user_id=current_user.id,
        action="CREATE",
        entity_type="MaintenanceRecord",
        entity_id=record.id,
        new_data={
            "date": str(payload.date),
            "area_id": payload.area_id,
            "section_name": payload.section_name,
            "equipment_id": payload.equipment_id,
            "maintenance_type": payload.maintenance_type.value,
            "duration_minutes": duration,
            "participant_ids": payload.participant_ids,
        },
    )
    await db.flush()

    # Attempt Google Sheets sync (must not prevent record creation).
    # If Google isn't configured, append_row_to_sheet returns False and the
    # record stays PENDING.
    try:
        written = sheets_service.append_row_to_sheet(
            sheets_service.build_sheet_row(record)
        )
        if written:
            record.sheet_sync_status = SyncStatus.SYNCED
            record.sheet_synced_at = datetime.now(timezone.utc)
            record.sheet_sync_error = None
    except Exception as exc:  # noqa: BLE001 - never let Sheets break local record
        logger.exception("Google Sheets sync failed, marking FAILED")
        record.sheet_sync_status = SyncStatus.FAILED
        record.sheet_sync_error = str(exc)

    await db.flush()

    # Reload with relationships
    result = await db.execute(
        _base_query_detail().where(MaintenanceRecord.id == record.id)
    )
    return result.scalar_one()


# --------------------------------------------------------------------------
# List
# --------------------------------------------------------------------------
@router.get("", response_model=list[MaintenanceListResponse])
async def list_maintenance(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    date: str | None = Query(default=None, description="ISO date YYYY-MM-DD"),
    area_id: int | None = Query(default=None),
    maintenance_type: MaintenanceType | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    query = _base_query()

    if current_user.role not in manager_roles:
        query = query.where(MaintenanceRecord.created_by_user_id == current_user.id)

    if date:
        query = query.where(MaintenanceRecord.date == date)
    if area_id:
        query = query.where(MaintenanceRecord.area_id == area_id)
    if maintenance_type:
        query = query.where(MaintenanceRecord.maintenance_type == maintenance_type)

    query = query.order_by(MaintenanceRecord.date.desc(), MaintenanceRecord.id.desc())
    if offset:
        query = query.offset(offset)
    if limit:
        query = query.limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


# --------------------------------------------------------------------------
# Get one
# --------------------------------------------------------------------------
@router.get("/{maintenance_id}", response_model=MaintenanceResponse)
async def get_maintenance(
    maintenance_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        _base_query_detail().where(MaintenanceRecord.id == maintenance_id)
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registro no encontrado")

    # WORKER can only see own records
    if current_user.role not in manager_roles and record.created_by_user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene permiso para ver este registro",
        )
    return record


# --------------------------------------------------------------------------
# Update (managers only)
# --------------------------------------------------------------------------
@router.patch("/{maintenance_id}", response_model=MaintenanceResponse)
async def update_maintenance(
    maintenance_id: int,
    payload: MaintenanceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(supervisor_or_admin),
):
    result = await db.execute(
        _base_query_detail().where(MaintenanceRecord.id == maintenance_id)
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registro no encontrado")

    previous = {
        "description": record.description,
        "maintenance_type": record.maintenance_type.value,
        "start_time": record.start_time,
        "end_time": record.end_time,
        "duration_minutes": record.duration_minutes,
        "participant_ids": [p.id for p in record.participants],
    }

    if payload.description is not None:
        if not payload.description.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La descripción no puede estar vacía")
        record.description = payload.description.strip()
    if payload.maintenance_type is not None:
        record.maintenance_type = payload.maintenance_type

    # Recompute duration if times changed
    new_start = payload.start_time or record.start_time
    new_end = payload.end_time or record.end_time
    if new_start != record.start_time or new_end != record.end_time:
        try:
            record.duration_minutes = calculate_duration(new_start, new_end)
            record.start_time = new_start
            record.end_time = new_end
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    if payload.participant_ids is not None:
        participants = await _validate_participants(db, payload.participant_ids)
        record.participants = participants

    await create_audit_log(
        db,
        user_id=current_user.id,
        action="UPDATE",
        entity_type="MaintenanceRecord",
        entity_id=record.id,
        previous_data=previous,
        new_data={
            "description": record.description,
            "maintenance_type": record.maintenance_type.value,
            "start_time": record.start_time,
            "end_time": record.end_time,
            "duration_minutes": record.duration_minutes,
            "participant_ids": [p.id for p in record.participants],
        },
    )
    await db.flush()

    # Reset sync to PENDING on edit; attempt re-sync (best effort).
    # upsert_row_to_sheet UPDATES the existing row (keyed by FECHA+AREA+EQUIPO+TRABAJO)
    # instead of appending a duplicate. If unconfigured, it returns False / raises
    # and the record stays PENDING or FAILED.
    record.sheet_sync_status = SyncStatus.PENDING
    try:
        written = sheets_service.upsert_row_to_sheet(
            sheets_service.build_sheet_row(record), record
        )
        if written:
            record.sheet_sync_status = SyncStatus.SYNCED
            record.sheet_synced_at = datetime.now(timezone.utc)
            record.sheet_sync_error = None
    except Exception as exc:  # noqa: BLE001
        record.sheet_sync_status = SyncStatus.FAILED
        record.sheet_sync_error = str(exc)

    await db.flush()
    return record


# --------------------------------------------------------------------------
# Retry sync (managers only)
# --------------------------------------------------------------------------
@router.post("/{maintenance_id}/retry-sync", response_model=MaintenanceResponse)
async def retry_sync(
    maintenance_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(supervisor_or_admin),
):
    result = await db.execute(
        _base_query_detail().where(MaintenanceRecord.id == maintenance_id)
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registro no encontrado")

    try:
        written = sheets_service.append_row_to_sheet(
            sheets_service.build_sheet_row(record)
        )
        if written:
            record.sheet_sync_status = SyncStatus.SYNCED
            record.sheet_synced_at = datetime.now(timezone.utc)
            record.sheet_sync_error = None
        else:
            record.sheet_sync_status = SyncStatus.PENDING
    except Exception as exc:  # noqa: BLE001
        record.sheet_sync_status = SyncStatus.FAILED
        record.sheet_sync_error = str(exc)

    await create_audit_log(
        db,
        user_id=current_user.id,
        action="SYNC_GOOGLE_SHEETS",
        entity_type="MaintenanceRecord",
        entity_id=record.id,
        new_data={"sheet_sync_status": record.sheet_sync_status.value},
    )
    await db.flush()
    return record
