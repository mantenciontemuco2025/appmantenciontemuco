"""Equipment life sheets: database history plus Google Drive copies."""

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dependencies import get_current_user, require_roles
from app.core.config import settings
from app.db.session import async_session, get_db
from app.models.equipment import Equipment
from app.models.user import User, UserRole
from app.models.work_order import WorkOrder, WorkOrderStatus
from app.schemas.equipment_life import (
    EquipmentLifeBackfillAccepted,
    EquipmentLifeBackfillPayload,
    EquipmentLifeBackfillResult,
    EquipmentLifeBackfillStatus,
    EquipmentLifeDetail,
    EquipmentLifeRecord,
    EquipmentLifeSummary,
)
from app.services import equipment_life as life_service


router = APIRouter(prefix="/api/equipment-life", tags=["equipment-life"])
admin_only = require_roles(UserRole.ADMIN)
_equipment_life_backfill_lock = asyncio.Lock()
_equipment_life_backfill_task: asyncio.Task | None = None
_equipment_life_backfill_state = EquipmentLifeBackfillStatus(status="idle")
logger = logging.getLogger(__name__)


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
    # The Drive/Sheets rewrite can take seconds. The caller has already
    # flushed the OT changes, so do not keep a PostgreSQL connection checked
    # out while waiting on Google. The equipment fields remain available
    # after commit because the session uses expire_on_commit=False.
    await db.commit()
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
    # Materialize the response data before releasing the connection. This
    # prevents response serialization from keeping a read transaction open.
    response = [_summary(item, len(orders_by_equipment.get(item.id, []))) for item in equipment]
    await db.commit()
    return response


@router.get("/status", response_model=EquipmentLifeBackfillStatus)
async def equipment_life_backfill_status(
    _: User = Depends(get_current_user),
):
    """Return the in-process status of the long-running Drive import."""
    return _equipment_life_backfill_state


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
    response = EquipmentLifeDetail(
        **_summary(equipment, len(work_orders)).model_dump(),
        records=_records(work_orders),
    )
    # Release the read transaction before FastAPI serializes the potentially
    # large OT history response.
    await db.commit()
    return response


async def _run_equipment_life_backfill(
    payload: EquipmentLifeBackfillPayload,
    db: AsyncSession,
):
    """Create/update every equipment sheet from the existing OT database."""
    global _equipment_life_backfill_state
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
    processed_equipment = 0
    total_work_orders = sum(len(items) for items in orders_by_equipment.values())
    equipment_with_work_orders = sum(bool(items) for items in orders_by_equipment.values())
    sync_targets: set[int] = set()
    skipped_equipment = 0
    skipped_work_orders = 0

    for item in equipment:
        work_orders = orders_by_equipment.get(item.id, [])
        synced_at = item.life_sheet_synced_at
        needs_sync = bool(work_orders) and (
            not item.life_sheet_file_id
            or item.life_sheet_sync_status != "SYNCED"
            or not synced_at
            or any(life_service.work_order_needs_sync(order, synced_at) for order in work_orders)
        )
        if needs_sync:
            sync_targets.add(item.id)
        elif item.life_sheet_file_id and item.life_sheet_sync_status == "SYNCED":
            skipped_equipment += 1
            skipped_work_orders += len(work_orders)

    total_work_orders = sum(len(orders_by_equipment.get(item_id, [])) for item_id in sync_targets)

    def update_progress(current_equipment: str | None):
        global _equipment_life_backfill_state
        _equipment_life_backfill_state = _equipment_life_backfill_state.model_copy(
            update={
                "equipment_total": len(equipment),
                "equipment_processed": processed_equipment,
                "equipment_with_work_orders": equipment_with_work_orders,
                "work_orders_total": total_work_orders,
                "work_orders_synced": synced_orders,
                "sheets_synced": synced_sheets,
                "current_equipment": current_equipment,
                "errors_count": len(errors),
            }
        )

    update_progress(None)

    for item in equipment:
        work_orders = orders_by_equipment.get(item.id, [])
        if item.id not in sync_targets:
            processed_equipment += 1
            update_progress(None)
            continue
        update_progress(item.name)
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
        processed_equipment += 1
        update_progress(None)

    return EquipmentLifeBackfillResult(
        equipment_total=len(equipment),
        equipment_with_work_orders=sum(bool(items) for items in orders_by_equipment.values()),
        sheets_synced=synced_sheets,
        work_orders_synced=synced_orders,
        work_orders_without_equipment=without_equipment,
        errors=errors[:50],
        equipment_skipped=skipped_equipment,
        work_orders_skipped=skipped_work_orders,
    )


@router.post("/backfill-legacy", response_model=EquipmentLifeBackfillResult)
async def backfill_equipment_life(
    payload: EquipmentLifeBackfillPayload = EquipmentLifeBackfillPayload(),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(admin_only),
):
    """Start one idempotent import without holding an HTTP request open."""
    if _equipment_life_backfill_lock.locked():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya hay una importación de hojas de vida en curso. Espera a que termine.",
        )
    async with _equipment_life_backfill_lock:
        return await _run_equipment_life_backfill(payload, db)


async def _run_equipment_life_backfill_job(payload: EquipmentLifeBackfillPayload):
    global _equipment_life_backfill_state
    async with _equipment_life_backfill_lock:
        try:
            # The background job owns its session. The HTTP request can return
            # immediately while the Google Drive calls continue.
            async with async_session() as db:
                result = await _run_equipment_life_backfill(payload, db)
                await db.commit()
            _equipment_life_backfill_state = EquipmentLifeBackfillStatus(
                status="completed",
                started_at=_equipment_life_backfill_state.started_at,
                finished_at=datetime.now(timezone.utc),
                equipment_total=result.equipment_total,
                equipment_processed=result.equipment_total,
                equipment_with_work_orders=result.equipment_with_work_orders,
                work_orders_total=_equipment_life_backfill_state.work_orders_total,
                work_orders_synced=result.work_orders_synced,
                sheets_synced=result.sheets_synced,
                errors_count=len(result.errors),
                result=result,
            )
        except Exception as exc:  # noqa: BLE001 - persist a safe job error
            logger.exception("Error en la importación de hojas de vida")
            _equipment_life_backfill_state = EquipmentLifeBackfillStatus(
                status="failed",
                started_at=_equipment_life_backfill_state.started_at,
                finished_at=datetime.now(timezone.utc),
                equipment_total=_equipment_life_backfill_state.equipment_total,
                equipment_processed=_equipment_life_backfill_state.equipment_processed,
                equipment_with_work_orders=_equipment_life_backfill_state.equipment_with_work_orders,
                work_orders_total=_equipment_life_backfill_state.work_orders_total,
                work_orders_synced=_equipment_life_backfill_state.work_orders_synced,
                sheets_synced=_equipment_life_backfill_state.sheets_synced,
                errors_count=_equipment_life_backfill_state.errors_count + 1,
                error=str(exc)[:500],
            )


@router.post("/backfill", response_model=EquipmentLifeBackfillAccepted, status_code=202)
async def start_equipment_life_backfill(
    payload: EquipmentLifeBackfillPayload = EquipmentLifeBackfillPayload(),
    _: User = Depends(admin_only),
):
    """Start one idempotent import without holding an HTTP request open."""
    global _equipment_life_backfill_task, _equipment_life_backfill_state
    if (_equipment_life_backfill_task and not _equipment_life_backfill_task.done()) or _equipment_life_backfill_lock.locked():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ya hay una importación en curso.")
    _equipment_life_backfill_state = EquipmentLifeBackfillStatus(
        status="running",
        started_at=datetime.now(timezone.utc),
    )
    _equipment_life_backfill_task = asyncio.create_task(
        _run_equipment_life_backfill_job(payload)
    )
    return EquipmentLifeBackfillAccepted(
        status="started",
        message="La importación comenzó en segundo plano.",
    )
