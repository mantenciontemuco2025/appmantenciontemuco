"""Equipment life sheets: database history plus Google Drive copies."""

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dependencies import get_current_user, require_roles
from app.core.config import settings
from app.db.session import get_db
from app.models.equipment import Equipment
from app.models.user import User, UserRole
from app.models.work_order import WorkOrder, WorkOrderStatus
from app.schemas.equipment_life import (
    EquipmentLifeBackfillPayload,
    EquipmentLifeBackfillResult,
    EquipmentLifeDetail,
    EquipmentLifeRecord,
    EquipmentLifeSummary,
)
from app.services import equipment_life as life_service


router = APIRouter(prefix="/api/equipment-life", tags=["equipment-life"])
admin_only = require_roles(UserRole.ADMIN)
_equipment_life_backfill_lock = asyncio.Lock()


def _eligible_work_order(wo: WorkOrder, include_drafts: bool = False) -> bool:
    status_value = str(getattr(wo.status, "value", wo.status) or "").upper()
    if not include_drafts and status_value == WorkOrderStatus.DRAFT.value:
        return False
    if wo.is_hallazgo_report and wo.hallazgo_status != "CONVERTED":
        return False
    return True


def _work_order_event_date(wo: WorkOrder):
    return wo.execution_date or wo.scheduled_date or wo.request_date or (
        wo.created_at.date() if isinstance(wo.created_at, datetime) else wo.created_at
    )


def _performer_name(wo: WorkOrder) -> str | None:
    if wo.is_external_work:
        return wo.external_executor_name or wo.external_company or "Trabajo externo"
    if wo.completed_by_user:
        return wo.completed_by_user.full_name
    if wo.responsible_user:
        return wo.responsible_user.full_name
    return wo.requested_by


def _summary(equipment: Equipment, work_order_count: int) -> EquipmentLifeSummary:
    return EquipmentLifeSummary(
        equipment_id=equipment.id,
        equipment_name=equipment.name,
        section_name=equipment.area.name if equipment.area else None,
        plant_area_name=equipment.plant_area.name if equipment.plant_area else None,
        work_order_count=work_order_count,
        life_sheet_file_id=equipment.life_sheet_file_id,
        life_sheet_url=equipment.life_sheet_url,
        life_sheet_sync_status=equipment.life_sheet_sync_status,
        life_sheet_sync_error=equipment.life_sheet_sync_error,
        life_sheet_synced_at=equipment.life_sheet_synced_at,
    )


def _records(work_orders: list[WorkOrder]) -> list[EquipmentLifeRecord]:
    result = []
    for wo in sorted(work_orders, key=lambda item: (_work_order_event_date(item) or datetime.min.date(), item.ot_number)):
        observations = (wo.observations or "").strip()
        completion_notes = (wo.completion_notes or "").strip()
        if completion_notes and completion_notes != observations:
            observations = f"{observations} | {completion_notes}" if observations else completion_notes
        result.append(
            EquipmentLifeRecord(
                work_order_id=wo.id,
                ot_number=wo.ot_number,
                original_ot_number=wo.original_ot_number,
                event_date=_work_order_event_date(wo),
                title=wo.title,
                description=wo.description,
                performed_by=_performer_name(wo),
                observations=observations or None,
                status=life_service._status_text(wo.status),
                maintenance_type=life_service._maintenance_text(wo.maintenance_type),
            )
        )
    return result


async def _load_catalog_and_orders(db: AsyncSession, include_drafts: bool = False):
    equipment_result = await db.execute(
        select(Equipment)
        .options(selectinload(Equipment.area), selectinload(Equipment.plant_area))
        .order_by(Equipment.name)
    )
    equipment = list(equipment_result.scalars().all())
    order_result = await db.execute(
        select(WorkOrder)
        .options(
            selectinload(WorkOrder.completed_by_user),
            selectinload(WorkOrder.responsible_user),
        )
        .where(WorkOrder.equipment_id.is_not(None))
        .order_by(WorkOrder.execution_date, WorkOrder.ot_number)
    )
    orders_by_equipment: dict[int, list[WorkOrder]] = {item.id: [] for item in equipment}
    for wo in order_result.scalars().all():
        if _eligible_work_order(wo, include_drafts):
            orders_by_equipment.setdefault(wo.equipment_id, []).append(wo)
    return equipment, orders_by_equipment


async def sync_equipment_from_database(
    db: AsyncSession,
    equipment_id: int,
    *,
    include_drafts: bool = False,
) -> dict | None:
    """Refresh one equipment sheet from current DB data.

    This helper is used by the OT lifecycle after a worker finishes a job. It
    deliberately swallows Drive errors at the caller so a Drive outage never
    prevents the OT from being saved.
    """
    equipment = await db.scalar(
        select(Equipment)
        .options(selectinload(Equipment.area), selectinload(Equipment.plant_area))
        .where(Equipment.id == equipment_id)
    )
    if equipment is None:
        return None
    result = await db.execute(
        select(WorkOrder)
        .options(
            selectinload(WorkOrder.completed_by_user),
            selectinload(WorkOrder.responsible_user),
        )
        .where(WorkOrder.equipment_id == equipment_id)
    )
    work_orders = [wo for wo in result.scalars().all() if _eligible_work_order(wo, include_drafts)]
    if not work_orders:
        return None
    synced = await asyncio.to_thread(
        life_service.sync_equipment_history,
        equipment_id=equipment.id,
        equipment_name=equipment.name,
        section_name=equipment.area.name if equipment.area else None,
        plant_area_name=equipment.plant_area.name if equipment.plant_area else None,
        existing_file_id=equipment.life_sheet_file_id,
        work_orders=work_orders,
    )
    equipment.life_sheet_file_id = synced["file_id"]
    equipment.life_sheet_url = synced["url"]
    equipment.life_sheet_sync_status = "SYNCED"
    equipment.life_sheet_sync_error = None
    equipment.life_sheet_synced_at = datetime.now(timezone.utc)
    return synced


@router.get("", response_model=list[EquipmentLifeSummary])
async def list_equipment_life(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    equipment, orders_by_equipment = await _load_catalog_and_orders(db)
    return [_summary(item, len(orders_by_equipment.get(item.id, []))) for item in equipment]


@router.get("/{equipment_id}", response_model=EquipmentLifeDetail)
async def get_equipment_life(
    equipment_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    equipment = await db.scalar(
        select(Equipment)
        .options(selectinload(Equipment.area), selectinload(Equipment.plant_area))
        .where(Equipment.id == equipment_id)
    )
    if equipment is None:
        raise HTTPException(status_code=404, detail="Equipo no encontrado")
    result = await db.execute(
        select(WorkOrder)
        .options(
            selectinload(WorkOrder.completed_by_user),
            selectinload(WorkOrder.responsible_user),
        )
        .where(WorkOrder.equipment_id == equipment_id)
        .order_by(WorkOrder.execution_date, WorkOrder.ot_number)
    )
    work_orders = [wo for wo in result.scalars().all() if _eligible_work_order(wo)]
    return EquipmentLifeDetail(
        **_summary(equipment, len(work_orders)).model_dump(),
        records=_records(work_orders),
    )


async def _run_equipment_life_backfill(
    payload: EquipmentLifeBackfillPayload,
    db: AsyncSession,
):
    """Create/update every equipment sheet from the existing OT database."""
    if not life_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configura las variables GOOGLE_EQUIPMENT_LIFE_* en el backend.",
        )

    equipment, orders_by_equipment = await _load_catalog_and_orders(
        db, include_drafts=payload.include_drafts
    )
    all_orders_result = await db.execute(select(WorkOrder.equipment_id))
    without_equipment = sum(1 for (equipment_id,) in all_orders_result.all() if equipment_id is None)
    # Do not keep a PostgreSQL connection checked out while each Google Drive
    # sheet is being created or updated. External calls can take minutes.
    await db.commit()
    synced_sheets = 0
    synced_orders = 0
    errors: list[str] = []

    for item in equipment:
        work_orders = orders_by_equipment.get(item.id, [])
        if not work_orders:
            continue
        try:
            result = await asyncio.to_thread(
                life_service.sync_equipment_history,
                equipment_id=item.id,
                equipment_name=item.name,
                section_name=item.area.name if item.area else None,
                plant_area_name=item.plant_area.name if item.plant_area else None,
                existing_file_id=item.life_sheet_file_id,
                work_orders=work_orders,
            )
            item.life_sheet_file_id = result["file_id"]
            item.life_sheet_url = result["url"]
            item.life_sheet_sync_status = "SYNCED"
            item.life_sheet_sync_error = None
            item.life_sheet_synced_at = datetime.now(timezone.utc)
            synced_sheets += 1
            synced_orders += len(work_orders)
        except Exception as exc:  # noqa: BLE001 - one bad sheet must not stop the backfill
            item.life_sheet_sync_status = "FAILED"
            item.life_sheet_sync_error = str(exc)[:500]
            errors.append(f"{item.name} (ID {item.id}): {str(exc)[:250]}")
        await db.commit()

    return EquipmentLifeBackfillResult(
        equipment_total=len(equipment),
        equipment_with_work_orders=sum(bool(items) for items in orders_by_equipment.values()),
        sheets_synced=synced_sheets,
        work_orders_synced=synced_orders,
        work_orders_without_equipment=without_equipment,
        errors=errors[:50],
    )


@router.post("/backfill", response_model=EquipmentLifeBackfillResult)
async def backfill_equipment_life(
    payload: EquipmentLifeBackfillPayload = EquipmentLifeBackfillPayload(),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(admin_only),
):
    """Run one idempotent import at a time without exhausting the DB pool."""
    if _equipment_life_backfill_lock.locked():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya hay una importación de hojas de vida en curso. Espera a que termine.",
        )
    async with _equipment_life_backfill_lock:
        return await _run_equipment_life_backfill(payload, db)
