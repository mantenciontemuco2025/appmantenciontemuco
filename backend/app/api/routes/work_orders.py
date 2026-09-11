"""Work Order (OT) router.

Full workflow: DRAFT → PENDING → IN_PROGRESS → COMPLETED → APPROVED.
Also supports CANCELLED from any open state, and RETURN (COMPLETED → IN_PROGRESS).

Permission model:
- ADMIN: full access (create, edit, emit, start, complete, return, approve, cancel)
- SUPERVISOR: create, edit, emit, cancel, list all
- WORKER (responsible): view, start, complete
- WORKER (participant): view only
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta, date as _date

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.api.dependencies import get_current_user, require_roles
from app.core.config import settings
from app.db.session import get_db, async_session
from app.models.user import User, UserRole
from app.models.area import Area
from app.models.equipment import Equipment
from app.models.work_order import WorkOrder, WorkOrderStatus
from app.models.work_order_participants import work_order_participants
from app.models.sync_job import ExternalSyncJob, SyncJobStatus
from app.schemas.work_order import (
    WorkOrderCreate,
    WorkOrderUpdate,
    WorkOrderResponse,
    WorkOrderListResponse,
    WorkOrderCounterResponse,
)
from app.services.audit_service import create_audit_log
from app.services import google_drive as drive_service
from app.services.monthly_register import (
    ensure_monthly_register_for_year,
    resolve_register,
    delete_ot_from_register,
)
from app.services.ot_mapping import get_monthly_sheet_title
from app.services.wo_state_machine import validate_transition, InvalidTransitionError
from app.services import wo_permissions as perms
from app.services import notification_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/work-orders", tags=["work-orders"])

manager_roles = (UserRole.SUPERVISOR, UserRole.ADMIN)
supervisor_or_admin = require_roles(*manager_roles)


def _supervisor_area_error(current_user: User, area_id: int) -> str | None:
    """Return a friendly error when a supervisor has no valid area scope."""
    if current_user.role != UserRole.SUPERVISOR:
        return None
    if current_user.area_id is None:
        return "El administrador debe asignarte un área antes de emitir OTs."
    if current_user.area_id != area_id:
        return "Solo puedes crear y gestionar OTs de tu área asignada."
    return None


# ── Helper schemas for transition endpoints ────────────────────────────────

def _supervisor_area_error(current_user: User, area_id: int) -> str | None:
    """Validate an OT area against all areas assigned to a supervisor."""
    if current_user.role != UserRole.SUPERVISOR:
        return None
    area_ids = current_user.area_ids
    if not area_ids:
        return "El administrador debe asignarte al menos un area antes de emitir OTs."
    if area_id not in area_ids:
        return "Solo puedes crear y gestionar OTs de tus areas asignadas."
    return None


class IssuePayload(BaseModel):
    """Empty body — issue uses validated fields from the OT itself."""
    pass


class CompletePayload(BaseModel):
    completion_notes: str | None = None


class ReturnPayload(BaseModel):
    return_reason: str


class ApprovePayload(BaseModel):
    # Kept for backwards compatibility with clients that sent a text field.
    # The server never trusts it: approval always snapshots the authenticated
    # administrator's stored handwritten signature.
    approved_signature: str | None = None


class CancelPayload(BaseModel):
    cancellation_reason: str


class ReopenPayload(BaseModel):
    """Body for reopening a closed OT. Reason is required (recorded in AuditLog)."""
    reopen_reason: str


class ReassignPayload(BaseModel):
    """Body for reassigning an OT to another responsible/participants."""
    responsible_user_id: int | None = None
    participant_user_ids: list[int] | None = None


class BatchIssuePayload(BaseModel):
    """Body for issuing multiple DRAFT OTs at once."""
    ids: list[int]


# ── Helpers ────────────────────────────────────────────────────────────────

async def _next_ot_number(db: AsyncSession) -> str:
    """Generate the next OT number: OT-YYYY-NNNN (zero-padded, 4 digits)."""
    year = datetime.now().year
    prefix = f"OT-{year}-"
    result = await db.execute(
        select(WorkOrder.ot_number)
        .where(WorkOrder.ot_number.like(f"{prefix}%"))
        .order_by(WorkOrder.ot_number.desc())
        .limit(1)
    )
    last = result.scalar_one_or_none()
    if last:
        try:
            n = int(last.split("-")[-1]) + 1
        except (ValueError, IndexError):
            n = 1
    else:
        n = 1
    return f"{prefix}{n:04d}"


async def _validate_area_equipment(
    db: AsyncSession, area_id: int, equipment_id: int | None
) -> tuple[Area, Equipment | None]:
    area = await db.get(Area, area_id)
    if area is None:
        raise HTTPException(status_code=400, detail="Área no válida")
    if equipment_id is not None:
        eq = await db.get(Equipment, equipment_id)
        if eq is None or eq.area_id != area_id:
            raise HTTPException(status_code=400, detail="El equipo no pertenece al área seleccionada")
        return area, eq
    return area, None


def _parse_duration_hours(estimated_time: str | None) -> float:
    """Parse estimated_time (e.g. '2 h 30 min', '90 min', '1.5') into hours."""
    if not estimated_time:
        return 0.0
    text = estimated_time.strip().lower()
    total_minutes = 0.0

    import re
    h_match = re.search(r"(\d+(?:\.\d+)?)\s*h(?:oras?)?", text)
    m_match = re.search(r"(\d+(?:\.\d+)?)\s*m(?:in(?:utos?)?)?", text)
    if h_match:
        total_minutes += float(h_match.group(1)) * 60
    if m_match:
        total_minutes += float(m_match.group(1))
    if total_minutes:
        return round(total_minutes / 60, 2)

    try:
        return round(float(text), 2)
    except ValueError:
        return 0.0


def _work_order_to_response(wo: WorkOrder) -> dict:
    """Build a response dict from a WorkOrder instance, resolving relationships."""
    # Resolve participant IDs from the M2M relationship
    participant_user_ids = []
    try:
        participant_user_ids = [p.id for p in (wo.participants or [])]
    except Exception:
        pass

    # Resolve names for lifecycle users
    started_by_name = None
    if wo.started_by_user_id and wo.started_by_user:
        started_by_name = wo.started_by_user.full_name

    completed_by_name = None
    if wo.completed_by_user_id and wo.completed_by_user:
        completed_by_name = wo.completed_by_user.full_name

    approved_by_name = None
    if wo.approved_by_user_id and wo.approved_by_user:
        approved_by_name = wo.approved_by_user.full_name

    return {
        "id": wo.id,
        "ot_number": wo.ot_number,
        "title": wo.title,
        "description": wo.description,
        "area_id": wo.area_id,
        "area_name": wo.area.name if wo.area else None,
        "equipment_id": wo.equipment_id,
        "equipment_name": wo.equipment.name if wo.equipment else None,
        "section_name": wo.section_name,
        "maintenance_type": wo.maintenance_type,
        "loto_status": wo.loto_status,
        "folio": wo.folio,
        "estimated_time": wo.estimated_time,
        "request_date": wo.request_date,
        "execution_date": wo.execution_date,
        "resources_required": wo.resources_required,
        "voucher_number": wo.voucher_number,
        "risks": wo.risks,
        "observations": wo.observations,
        "requested_by": wo.requested_by,
        "approved_by": wo.approved_by,
        "requested_signature": wo.requested_signature,
        "approved_signature": wo.approved_signature,
        "status": wo.status,
        "submitted_for_review": wo.submitted_for_review,
        # ── Workflow fields ──
        "responsible_user_id": wo.responsible_user_id,
        "responsible_user_name": wo.responsible_user.full_name if wo.responsible_user else None,
        "participant_user_ids": participant_user_ids,
        "is_planned": wo.is_planned,
        "scheduled_date": wo.scheduled_date,
        "due_date": wo.due_date,
        "started_at": wo.started_at,
        "started_by_user_id": wo.started_by_user_id,
        "started_by_name": started_by_name,
        "completed_at": wo.completed_at,
        "completed_by_user_id": wo.completed_by_user_id,
        "completed_by_name": completed_by_name,
        "actual_duration_minutes": wo.actual_duration_minutes,
        "completion_notes": wo.completion_notes,
        "approved_at": wo.approved_at,
        "approved_by_user_id": wo.approved_by_user_id,
        "approved_by_user_name": approved_by_name,
        "cancellation_reason": wo.cancellation_reason,
        "returned_at": wo.returned_at,
        "returned_by_user_id": wo.returned_by_user_id,
        "return_reason": wo.return_reason,
        # ── Google ──
        "google_ot_file_id": wo.google_ot_file_id,
        "google_ot_url": wo.google_ot_url,
        "ot_sheet_sync_status": wo.ot_sheet_sync_status,
        "ot_sheet_sync_error": wo.ot_sheet_sync_error,
        "ot_sheet_synced_at": wo.ot_sheet_synced_at,
        "monthly_sheet_sync_status": wo.monthly_sheet_sync_status,
        "monthly_sheet_sync_error": wo.monthly_sheet_sync_error,
        "monthly_sheet_synced_at": wo.monthly_sheet_synced_at,
        "created_by_user_id": wo.created_by_user_id,
        "created_by_name": wo.created_by.full_name if wo.created_by else None,
        "participant_names": [
            n.strip() for n in (wo.participant_names or "").split(",") if n.strip()
        ],
        "created_at": wo.created_at,
        "updated_at": wo.updated_at,
    }


def _base_query():
    return select(WorkOrder).options(
        selectinload(WorkOrder.area),
        selectinload(WorkOrder.equipment),
        selectinload(WorkOrder.created_by),
        selectinload(WorkOrder.responsible_user),
        selectinload(WorkOrder.participants),
        # Lifecycle users — loaded eagerly so _work_order_to_response can
        # resolve their names without extra queries.
        selectinload(WorkOrder.started_by_user),
        selectinload(WorkOrder.completed_by_user),
        selectinload(WorkOrder.approved_by_user),
    )


async def _ensure_responsible_is_participant(
    db: AsyncSession, wo: WorkOrder
) -> None:
    """Keep the responsible worker included in the OT participant roster."""
    if wo.responsible_user_id is None:
        return
    existing = await db.execute(
        select(work_order_participants.c.user_id).where(
            work_order_participants.c.work_order_id == wo.id,
            work_order_participants.c.user_id == wo.responsible_user_id,
        )
    )
    if existing.scalar_one_or_none() is None:
        await db.execute(
            work_order_participants.insert().values(
                work_order_id=wo.id, user_id=wo.responsible_user_id
            )
        )

    names_result = await db.execute(
        select(User.full_name)
        .join(
            work_order_participants,
            work_order_participants.c.user_id == User.id,
        )
        .where(work_order_participants.c.work_order_id == wo.id)
        .order_by(User.full_name)
    )
    wo.participant_names = ", ".join(row[0] for row in names_result.all()) or None


def _exec_datetime(wo: WorkOrder) -> datetime:
    """Return execution_date as a datetime (defaulting to now)."""
    exec_date = wo.execution_date or datetime.now().date()
    if isinstance(exec_date, _date) and not isinstance(exec_date, datetime):
        return datetime.combine(exec_date, datetime.min.time())
    return exec_date  # type: ignore


def _as_datetime(d: _date) -> datetime:
    """Normalize any date-ish value (date or datetime) to a datetime."""
    if isinstance(d, datetime):
        return d
    return datetime.combine(d, datetime.min.time())


async def _sync_work_order_to_monthly(
    db: AsyncSession,
    wo: WorkOrder,
    user_id: int,
    action: str = "SYNC_MONTHLY_GOOGLE",
    previous_execution_date: _date | None = None,
) -> None:
    """Best-effort sync of a single WorkOrder to the per-year monthly sheet.

    Resolves the annual register for the OT's execution year (creating it from
    the template on first need) and writes/updates the SAME row keyed by N° OT —
    never duplicates. A DRAFT-order is skipped.

    When `previous_execution_date` is given and falls in a different (year, month)
    than the current execution date (a date edit moved the OT across year/month),
    the old row in the previous year's register is deleted first so N° OT stays
    unique. This flag/style is only passed by the edit endpoints that can change
    the execution date.
    """
    exec_dt = _exec_datetime(wo)
    duration_hours = _parse_duration_hours(wo.estimated_time)

    # Use actual_duration_minutes when available (worker has completed)
    actual_minutes = wo.actual_duration_minutes

    # Resolve participant names from M2M relationship (preferred) or TEXT fallback
    participants = []
    try:
        participants = [p.full_name for p in (wo.participants or [])]
    except Exception:
        participants = [
            n.strip() for n in (wo.participant_names or "").split(",") if n.strip()
        ]

    # Resolve responsible name
    responsible_name = wo.responsible_user.full_name if wo.responsible_user else ""

    # Resolve (or lazily create) the annual register for the OT's execution year.
    # commit=False: this runs inside the caller's transaction; the register row is
    # flushed so UNIQUE-year races are still detected, but we don't commit here.
    # When no per-year register can be created (Google not configured), we fall
    # back to the legacy settings.GOOGLE_MONTHLY_SPREADSHEET_ID via spreadsheet_id=None.
    target_spreadsheet_id: str | None = None
    register = await ensure_monthly_register_for_year(
        db, exec_dt.year, user_id, commit=False
    )
    if register is not None:
        target_spreadsheet_id = register.spreadsheet_id
    elif not settings.GOOGLE_MONTHLY_SPREADSHEET_ID:
        logger.warning(
            "OT %s: no hay registro mensual configurado para el año %s "
            "(ni 2026 legacy).", wo.ot_number, exec_dt.year,
        )
        wo.monthly_sheet_sync_status = "FAILED"
        wo.monthly_sheet_sync_error = (
            f"No hay registro mensual configurado para el año {exec_dt.year}."
        )
        await create_audit_log(
            db, user_id=user_id, action=action,
            entity_type="WorkOrder", entity_id=wo.id,
            new_data={"monthly_sheet_sync_status": wo.monthly_sheet_sync_status},
        )
        return

    # Year/month change: delete the old row so N° OT stays unique across registers.
    if previous_execution_date is not None:
        prev_dt = _as_datetime(previous_execution_date)
        if (prev_dt.year, prev_dt.month) != (exec_dt.year, exec_dt.month):
            prev_spreadsheet_id: str | None = None
            prev_register = await resolve_register(db, prev_dt.year)
            if prev_register is not None:
                prev_spreadsheet_id = prev_register.spreadsheet_id
            elif settings.GOOGLE_MONTHLY_SPREADSHEET_ID:
                prev_spreadsheet_id = settings.GOOGLE_MONTHLY_SPREADSHEET_ID
            if prev_spreadsheet_id:
                try:
                    await asyncio.to_thread(
                        delete_ot_from_register,
                        prev_spreadsheet_id,
                        get_monthly_sheet_title(prev_dt.month),
                        wo.ot_number,
                    )
                except Exception as exc:
                    logger.warning(
                        "No se pudo limpiar la fila previa de %s en %s: %s",
                        wo.ot_number, get_monthly_sheet_title(prev_dt.month), exc,
                    )

    try:
        await asyncio.to_thread(
            drive_service.sync_to_monthly_sheet,
            wo.ot_number,
            exec_dt,
            area_name=wo.area.name if wo.area else "",
            section_name=wo.section_name or "",
            equipment_name=wo.equipment.name if wo.equipment else "",
            description=wo.description or "",
            maintenance_type=wo.maintenance_type,
            participants=participants,
            duration_hours=duration_hours,
            status=wo.status,
            actual_duration_minutes=actual_minutes,
            spreadsheet_id=target_spreadsheet_id,
        )
        wo.monthly_sheet_sync_status = "SYNCED"
        wo.monthly_sheet_synced_at = datetime.now(timezone.utc)
        wo.monthly_sheet_sync_error = None
    except Exception as exc:
        logger.warning("Sync mensual fallo para %s: %s", wo.ot_number, exc)
        wo.monthly_sheet_sync_status = "FAILED"
        wo.monthly_sheet_sync_error = str(exc)[:500]

    # Keep the individual OT document in Drive in sync with the current
    # lifecycle state (start/complete/return/approve/cancel/reopen). Best-effort:
    # a failure here is non-fatal — the DB remains the source of truth and the
    # monthly register update above is independent of this one-cell write.
    if wo.google_ot_file_id:
        try:
            await asyncio.to_thread(
                drive_service.update_ot_status, wo.google_ot_file_id, wo.status
            )
            wo.ot_sheet_sync_status = "SYNCED"
            wo.ot_sheet_sync_error = None
            wo.ot_sheet_synced_at = datetime.now(timezone.utc)
        except Exception as ot_exc:
            logger.warning(
                "No se pudo actualizar el estado en la OT %s de Drive: %s",
                wo.ot_number, ot_exc,
            )
            wo.ot_sheet_sync_status = "FAILED"
            wo.ot_sheet_sync_error = str(ot_exc)[:500]

    await create_audit_log(
        db,
        user_id=user_id,
        action=action,
        entity_type="WorkOrder",
        entity_id=wo.id,
        new_data={"monthly_sheet_sync_status": wo.monthly_sheet_sync_status},
    )


# ───────────────────────────────────────────────────────────────────────────
# Create Work Order
# ───────────────────────────────────────────────────────────────────────────
@router.post("", response_model=WorkOrderResponse, status_code=status.HTTP_201_CREATED)
async def create_work_order(
    payload: WorkOrderCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not perms.can_create(current_user):
        raise HTTPException(status_code=403, detail="No tiene permiso para crear OTs")

    area_scope_error = _supervisor_area_error(current_user, payload.area_id)
    if area_scope_error and not payload.emit:
        raise HTTPException(status_code=403, detail=area_scope_error)

    # When emitting directly from the wizard, the admin must provide the same
    # required fields validated at /issue time.
    is_supervisor_submission = (
        current_user.role == UserRole.SUPERVISOR and payload.emit
    )
    is_supervisor = current_user.role == UserRole.SUPERVISOR

    if payload.emit:
        errors = []
        if not payload.description or not payload.description.strip():
            errors.append("Descripción del trabajo")
        if not payload.responsible_user_id and not is_supervisor_submission:
            errors.append("Responsable principal")
        if (
            not payload.participant_user_ids
            and not payload.responsible_user_id
            and not is_supervisor_submission
        ):
            errors.append("Al menos un participante")
        if not current_user.signature:
            errors.append("Firma manuscrita en Mi firma")
        if area_scope_error:
            errors.append("Área asignada al supervisor")
        if errors:
            raise HTTPException(
                status_code=400,
                detail=f"Para emitir la OT, complete los campos obligatorios: {', '.join(errors)}",
            )

    area, equipment = await _validate_area_equipment(
        db, payload.area_id, payload.equipment_id
    )

    # Determine initial status
    initial_status = (
        WorkOrderStatus.DRAFT.value
        if is_supervisor_submission or not payload.emit
        else WorkOrderStatus.PENDING.value
    )
    participant_ids = [] if is_supervisor else list(payload.participant_user_ids)
    if (
        not is_supervisor
        and payload.responsible_user_id is not None
        and payload.responsible_user_id not in participant_ids
    ):
        participant_ids.append(payload.responsible_user_id)

    ot_number = await _next_ot_number(db)

    # Resolve participant names from IDs if provided
    participant_names_str = None
    if participant_ids:
        result = await db.execute(
            select(User.id, User.full_name).where(User.id.in_(participant_ids))
        )
        users_map = {row[0]: row[1] for row in result.all()}
        names = [users_map[uid] for uid in participant_ids if uid in users_map]
        participant_names_str = ", ".join(names) if names else None
    elif payload.participant_names and not is_supervisor:
        participant_names_str = ", ".join(payload.participant_names)

    # SOLICITADO POR: auto-fill with current user's name (creator/emitter)
    requested_by = current_user.full_name if payload.emit else (payload.requested_by or current_user.full_name)

    wo = WorkOrder(
        ot_number=ot_number,
        title=payload.title,
        description=payload.description,
        area_id=payload.area_id,
        equipment_id=payload.equipment_id,
        section_name=payload.section_name,
        maintenance_type=payload.maintenance_type,
        loto_status=payload.loto_status,
        folio=payload.folio,
        estimated_time=payload.estimated_time,
        request_date=payload.request_date,
        execution_date=payload.execution_date,
        resources_required=payload.resources_required,
        voucher_number=payload.voucher_number,
        risks=payload.risks,
        observations=payload.observations,
        requested_by=requested_by,
        # Legacy field used by the template's "REALIZADO POR" block. It is
        # set only when the responsible worker completes the work.
        approved_by=None,
        # A WorkOrder keeps a stable signature URL; later profile changes do
        # not change the signature used when this OT was issued.
        requested_signature=current_user.signature if payload.emit else None,
        participant_names=participant_names_str,
        status=initial_status,
        submitted_for_review=is_supervisor_submission,
        created_by_user_id=current_user.id,
        responsible_user_id=None if is_supervisor else payload.responsible_user_id,
        is_planned=payload.is_planned,
        scheduled_date=payload.scheduled_date,
        due_date=payload.due_date,
    )
    db.add(wo)
    await db.flush()

    # M2M participants
    if participant_ids:
        for uid in participant_ids:
            await db.execute(
                work_order_participants.insert().values(
                    work_order_id=wo.id, user_id=uid
                )
            )
        await db.flush()

    # Audit CREATE_WORK_ORDER
    await create_audit_log(
        db,
        user_id=current_user.id,
        action="CREATE_WORK_ORDER",
        entity_type="WorkOrder",
        entity_id=wo.id,
        new_data={
            "ot_number": wo.ot_number,
            "title": wo.title,
            "area_id": wo.area_id,
            "maintenance_type": wo.maintenance_type,
            "status": wo.status,
        },
    )
    await db.flush()

    if wo.submitted_for_review:
        await notification_service.notify_work_order_submitted_to_admin(
            db, wo, submitted_by=current_user.full_name, link=f"/ordenes/{wo.id}"
        )
    elif wo.status == WorkOrderStatus.PENDING.value:
        await notification_service.notify_work_order_assigned(
            db,
            wo,
            link=f"/mis-ordenes/{wo.id}",
            participant_user_ids=participant_ids,
        )
        if current_user.role == UserRole.SUPERVISOR:
            await notification_service.notify_work_order_submitted_to_admin(
                db, wo, submitted_by=current_user.full_name, link=f"/ordenes/{wo.id}"
            )

    # Google sync: only when emitted (PENDING). Runs in the background so the
    # create request returns instantly. The OT starts with ot_sheet_sync_status
    # / monthly_sheet_sync_status = PENDING and the background task flips them
    # to SYNCED (or FAILED with the error detail) without blocking the user.
    if wo.status == WorkOrderStatus.PENDING.value:
        wo.ot_sheet_sync_status = "PENDING"
        wo.monthly_sheet_sync_status = "PENDING"
        await enqueue_external_sync(
            db, wo.id, job_type="FULL_CREATE", actor_user_id=current_user.id
        )
        await db.commit()
    else:
        await db.flush()

    result = await db.execute(_base_query().where(WorkOrder.id == wo.id))
    wo_reloaded = result.scalar_one()
    return _work_order_to_response(wo_reloaded)


async def _run_ot_sync_in_background(bg_factory, wo_id):
    """Background Google sync: generate the OT document + monthly register row.

    Executed after the create request has already returned, using its OWN
    AsyncSession (built from the request session's bind) so it never touches
    the request's transaction. Any failure is recorded on the WorkOrder as
    ot_sheet_sync_status / monthly_sheet_sync_status = FAILED — never thrown.
    """
    try:
        async with bg_factory() as bg_db:
            try:
                result = await bg_db.execute(
                    _base_query().where(WorkOrder.id == wo_id)
                )
                wo = result.scalar_one()
                area = await bg_db.get(Area, wo.area_id)
                equipment = (
                    await bg_db.get(Equipment, wo.equipment_id)
                    if wo.equipment_id else None
                )
                await _sync_ot_and_monthly(
                    bg_db, wo, area, equipment,
                    _payload_from_wo(wo), wo.created_by_user_id,
                )
                await bg_db.commit()
            except Exception:
                await bg_db.rollback()
                raise
    except Exception as exc:
        logger.warning("Background Google sync failed for WO %s: %s", wo_id, exc)


def _mark_external_sync_pending(wo: WorkOrder) -> None:
    """Mark external integrations as pending before returning to the user."""
    wo.ot_sheet_sync_status = "PENDING"
    wo.monthly_sheet_sync_status = "PENDING"
    wo.ot_sheet_sync_error = None
    wo.monthly_sheet_sync_error = None


async def enqueue_external_sync(
    db: AsyncSession,
    wo_id: int,
    *,
    job_type: str,
    actor_user_id: int | None = None,
    populate_individual: bool = False,
    previous_execution_date: _date | None = None,
) -> ExternalSyncJob:
    """Persist an external sync request before the OT transaction commits."""
    result = await db.execute(
        select(ExternalSyncJob)
        .where(
            ExternalSyncJob.work_order_id == wo_id,
            ExternalSyncJob.job_type == job_type,
            ExternalSyncJob.status.in_((SyncJobStatus.PENDING, SyncJobStatus.FAILED)),
        )
        .order_by(ExternalSyncJob.id.desc())
        .limit(1)
    )
    job = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if job is None:
        job = ExternalSyncJob(
            work_order_id=wo_id,
            job_type=job_type,
            status=SyncJobStatus.PENDING,
            actor_user_id=actor_user_id,
            populate_individual=populate_individual,
            previous_execution_date=previous_execution_date,
            next_attempt_at=now,
        )
        db.add(job)
    else:
        job.status = SyncJobStatus.PENDING
        job.actor_user_id = actor_user_id
        job.populate_individual = populate_individual
        job.previous_execution_date = previous_execution_date
        job.attempts = 0
        job.next_attempt_at = now
        job.last_error = None
    await db.flush()
    return job


async def _claim_external_sync_job() -> int | None:
    now = datetime.now(timezone.utc)
    # A restart should recover a job left mid-request quickly, while still
    # avoiding two workers handling the same live Google call.
    stale_before = now - timedelta(minutes=2)
    async with async_session() as db:
        result = await db.execute(
            select(ExternalSyncJob)
            .where(
                (
                    ExternalSyncJob.status == SyncJobStatus.PENDING
                )
                | (
                    (ExternalSyncJob.status == SyncJobStatus.FAILED)
                    & (ExternalSyncJob.next_attempt_at <= now)
                )
                | (
                    (ExternalSyncJob.status == SyncJobStatus.PROCESSING)
                    & (ExternalSyncJob.updated_at <= stale_before)
                )
            )
            .order_by(ExternalSyncJob.created_at, ExternalSyncJob.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        job = result.scalar_one_or_none()
        if job is None:
            return None
        job.status = SyncJobStatus.PROCESSING
        job.attempts += 1
        job.last_error = None
        await db.commit()
        return job.id


async def _finish_external_sync_job(job_id: int, error: Exception | None = None) -> None:
    async with async_session() as db:
        job = await db.get(ExternalSyncJob, job_id)
        if job is None:
            return
        if error is None:
            job.status = SyncJobStatus.SUCCEEDED
            job.last_error = None
            job.next_attempt_at = None
        else:
            delay_seconds = min(60 * (2 ** max(job.attempts - 1, 0)), 3600)
            job.status = SyncJobStatus.FAILED
            job.last_error = str(error)[:1000]
            # Leave exhausted jobs visibly FAILED; a manual retry can enqueue
            # them again and reset the attempt counter only if desired later.
            job.next_attempt_at = (
                datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
                if job.attempts < 8
                else None
            )
        await db.commit()


async def _process_external_sync_job(job_id: int) -> None:
    async with async_session() as db:
        job = await db.get(ExternalSyncJob, job_id)
        if job is None:
            return
        result = await db.execute(_base_query().where(WorkOrder.id == job.work_order_id))
        wo = result.scalar_one_or_none()
        if wo is None:
            raise RuntimeError(f"OT {job.work_order_id} no encontrada")

        if job.job_type in {"FULL_CREATE", "FULL_SYNC"}:
            area = await db.get(Area, wo.area_id)
            equipment = await db.get(Equipment, wo.equipment_id) if wo.equipment_id else None
            await _sync_ot_and_monthly(
                db, wo, area, equipment, _payload_from_wo(wo), wo.created_by_user_id
            )
        elif job.job_type == "MONTHLY":
            await _sync_work_order_to_monthly(
                db,
                wo,
                job.actor_user_id or wo.created_by_user_id,
                action="SYNC_MONTHLY_QUEUE",
            )
        elif job.job_type == "LIFECYCLE":
            if not wo.google_ot_file_id:
                raise RuntimeError("El documento de Google aún no está disponible")
            individual_failed = False
            if job.populate_individual:
                try:
                    await _populate_individual_ot(wo)
                    wo.ot_sheet_sync_status = "SYNCED"
                    wo.ot_sheet_sync_error = None
                except Exception as exc:
                    individual_failed = True
                    wo.ot_sheet_sync_status = "FAILED"
                    wo.ot_sheet_sync_error = str(exc)[:500]
            await _sync_work_order_to_monthly(
                db,
                wo,
                job.actor_user_id or wo.created_by_user_id,
                action="SYNC_LIFECYCLE_QUEUE",
                previous_execution_date=job.previous_execution_date,
            )
            if individual_failed:
                wo.ot_sheet_sync_status = "FAILED"
        else:
            raise RuntimeError(f"Tipo de sincronización no soportado: {job.job_type}")

        if (
            (job.job_type != "MONTHLY" and wo.ot_sheet_sync_status == "FAILED")
            or wo.monthly_sheet_sync_status == "FAILED"
        ):
            errors = [wo.ot_sheet_sync_error, wo.monthly_sheet_sync_error]
            raise RuntimeError("; ".join(error for error in errors if error) or "Google rechazó la sincronización")
        await db.commit()


async def external_sync_worker() -> None:
    """Keep processing persisted jobs across web restarts."""
    while True:
        try:
            job_id = await _claim_external_sync_job()
            if job_id is None:
                await asyncio.sleep(3)
                continue
            try:
                # A provider/network call must not hold the worker forever.
                # The durable job remains retryable after this timeout.
                await asyncio.wait_for(_process_external_sync_job(job_id), timeout=120)
            except Exception as exc:
                logger.warning("External sync job %s failed: %s", job_id, exc)
                await _finish_external_sync_job(job_id, exc)
            else:
                await _finish_external_sync_job(job_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("External sync worker loop failed")
            await asyncio.sleep(5)


async def _run_lifecycle_sync_in_background(
    bg_factory,
    wo_id: int,
    user_id: int,
    *,
    populate_individual: bool = False,
    previous_execution_date: _date | None = None,
) -> None:
    """Synchronize a persisted lifecycle change without blocking the request.

    The database state is already committed when this task starts. A failure is
    recorded on the OT, so the local workflow remains usable and the existing
    retry action can repair Google later.
    """
    try:
        async with bg_factory() as bg_db:
            result = await bg_db.execute(_base_query().where(WorkOrder.id == wo_id))
            wo = result.scalar_one_or_none()
            if wo is None or not wo.google_ot_file_id:
                return

            individual_failed = False
            if populate_individual:
                try:
                    await _populate_individual_ot(wo)
                    wo.ot_sheet_sync_status = "SYNCED"
                    wo.ot_sheet_sync_error = None
                except Exception as exc:  # noqa: BLE001 - local OT state wins
                    logger.warning("No se pudo actualizar la OT %s en Drive: %s", wo.ot_number, exc)
                    individual_failed = True
                    wo.ot_sheet_sync_status = "FAILED"
                    wo.ot_sheet_sync_error = str(exc)[:500]

            await _sync_work_order_to_monthly(
                bg_db,
                wo,
                user_id,
                action="SYNC_LIFECYCLE_BACKGROUND",
                previous_execution_date=previous_execution_date,
            )
            if individual_failed:
                wo.ot_sheet_sync_status = "FAILED"
            await bg_db.commit()
    except Exception as exc:  # noqa: BLE001 - convert crashes to visible state
        logger.warning("Background lifecycle sync failed for WO %s: %s", wo_id, exc)
        try:
            async with bg_factory() as fail_db:
                result = await fail_db.execute(
                    select(WorkOrder).where(WorkOrder.id == wo_id)
                )
                wo = result.scalar_one_or_none()
                if wo is not None:
                    wo.ot_sheet_sync_status = "FAILED"
                    wo.monthly_sheet_sync_status = "FAILED"
                    wo.ot_sheet_sync_error = str(exc)[:500]
                    wo.monthly_sheet_sync_error = str(exc)[:500]
                    await fail_db.commit()
        except Exception as mark_exc:  # pragma: no cover - last-resort logging
            logger.warning("No se pudo registrar el fallo de sincronización de WO %s: %s", wo_id, mark_exc)


def _payload_from_wo(wo):
    """Reconstruct the sync inputs from a persisted WorkOrder.

    Mirrors the fields that _sync_ot_and_monthly reads off the payload, so the
    background task (and the /issue endpoint) can run without the original
    create payload in memory.
    """
    class _FromWO:
        section_name = wo.section_name
        maintenance_type = wo.maintenance_type
        loto_status = wo.loto_status
        description = wo.description
        estimated_time = wo.estimated_time
        execution_date = wo.execution_date
        resources_required = wo.resources_required
        risks = wo.risks
        observations = wo.observations
        folio = wo.folio
        voucher_number = wo.voucher_number
        requested_by = wo.requested_by
        approved_by = wo.approved_by
        requested_signature = wo.requested_signature
        approved_signature = wo.approved_signature
        participant_names = [
            n.strip() for n in (wo.participant_names or "").split(",") if n.strip()
        ]
        # OAuth-gated writes reuse the same build helpers regardless of who
        # triggered the sync; created_by_user_id is passed separately.
    return _FromWO()


async def _populate_individual_ot(wo: WorkOrder) -> None:
    """Write the current OT state, including immutable signature snapshots."""
    participants = [p.full_name for p in (wo.participants or [])]
    await asyncio.to_thread(
        drive_service.populate_ot_fields,
        wo.google_ot_file_id,
        ot_number=wo.ot_number,
        area_name=wo.area.name if wo.area else "",
        section_name=wo.section_name or "",
        equipment_name=wo.equipment.name if wo.equipment else "",
        maintenance_type=wo.maintenance_type,
        loto_status=wo.loto_status,
        description=wo.description or "",
        participants=participants,
        estimated_time=wo.estimated_time,
        execution_date=wo.execution_date.isoformat() if wo.execution_date else None,
        request_date=wo.request_date.isoformat() if wo.request_date else None,
        resources_required=wo.resources_required,
        risks=wo.risks,
        observations=wo.observations,
        folio=wo.folio,
        voucher_number=wo.voucher_number,
        requested_by=wo.requested_by,
        approved_by=wo.approved_by,
        requested_signature=wo.requested_signature,
        approved_signature=wo.approved_signature,
        status=wo.status,
    )


async def _sync_ot_and_monthly(db, wo, area, equipment, payload, user_id):
    """Sync OT to Google Drive (template + monthly) when emitting."""
    execution_date = payload.execution_date or datetime.now().date()
    participants = []
    try:
        participants = [p.full_name for p in (wo.participants or [])]
    except Exception:
        participants = payload.participant_names or []

    try:
        if isinstance(execution_date, _date) and not isinstance(execution_date, datetime):
            exec_dt = datetime.combine(execution_date, datetime.min.time())
        else:
            exec_dt = execution_date  # type: ignore

        # Idempotent: if a document already exists (background retry after a
        # FAILED monthly sync), REUSE it — never create a second copy in Drive.
        if wo.google_ot_file_id:
            doc_id = wo.google_ot_file_id
        else:
            ot_result = await asyncio.to_thread(
                drive_service.create_ot_file, wo.ot_number, exec_dt
            )
            doc_id = ot_result["file_id"]
            wo.google_ot_file_id = ot_result["file_id"]
            wo.google_ot_url = ot_result["url"]

            # Persist the Drive ID before populating Sheets or calling Apps
            # Script. Those later operations can fail independently. Keeping
            # this commit small makes every retry reuse the same Drive file.
            await db.commit()

        await asyncio.to_thread(
            drive_service.populate_ot_fields,
            doc_id,
            ot_number=wo.ot_number,
            area_name=area.name,
            section_name=payload.section_name or "",
            equipment_name=equipment.name if equipment else "",
            maintenance_type=payload.maintenance_type,
            loto_status=payload.loto_status,
            description=payload.description,
            participants=participants,
            estimated_time=payload.estimated_time,
            execution_date=execution_date.isoformat() if execution_date else None,
            request_date=wo.request_date.isoformat() if wo.request_date else None,
            resources_required=payload.resources_required,
            risks=payload.risks,
            observations=payload.observations,
            folio=payload.folio,
            voucher_number=payload.voucher_number,
            requested_by=payload.requested_by,
            # The REALIZADO POR block is populated only when the responsible
            # worker completes the OT; never accept a pre-filled name here.
            approved_by=wo.approved_by,
            requested_signature=wo.requested_signature,
            approved_signature=wo.approved_signature,
            status="PENDING",
        )
        wo.ot_sheet_sync_status = "SYNCED"
        wo.ot_sheet_synced_at = datetime.now(timezone.utc)

        # Resolve (or lazily create) the annual register for the OT's year.
        register = await ensure_monthly_register_for_year(
            db, exec_dt.year, user_id, commit=False
        )
        # Fall back to the legacy single spreadsheet if no per-year register is
        # available (Google not configured to create one) — preserves old behavior.
        target_spreadsheet_id = (
            register.spreadsheet_id if register is not None
            else settings.GOOGLE_MONTHLY_SPREADSHEET_ID
        )
        if register is None and not settings.GOOGLE_MONTHLY_SPREADSHEET_ID:
            wo.monthly_sheet_sync_status = "FAILED"
            wo.monthly_sheet_sync_error = (
                f"No hay registro mensual configurado para el año {exec_dt.year}."
            )
        else:
            try:
                await asyncio.to_thread(
                    drive_service.sync_to_monthly_sheet,
                    wo.ot_number,
                    exec_dt,
                    area_name=area.name,
                    section_name=payload.section_name or "",
                    equipment_name=equipment.name if equipment else "",
                    description=payload.description or "",
                    maintenance_type=payload.maintenance_type,
                    participants=participants,
                    duration_hours=_parse_duration_hours(payload.estimated_time),
                    status=wo.status,
                    actual_duration_minutes=None,
                    spreadsheet_id=target_spreadsheet_id,
                )
                wo.monthly_sheet_sync_status = "SYNCED"
                wo.monthly_sheet_synced_at = datetime.now(timezone.utc)
                wo.monthly_sheet_sync_error = None
            except Exception as monthly_exc:
                logger.warning("Monthly sync failed for %s: %s", wo.ot_number, monthly_exc)
                wo.monthly_sheet_sync_status = "FAILED"
                wo.monthly_sheet_sync_error = str(monthly_exc)[:500]
    except Exception as exc:
        logger.warning("Google Drive OT creation failed for %s: %s", wo.ot_number, exc)
        wo.ot_sheet_sync_status = "FAILED"
        wo.ot_sheet_sync_error = str(exc)[:500]


# ───────────────────────────────────────────────────────────────────────────
# List Work Orders
# ───────────────────────────────────────────────────────────────────────────
@router.get("", response_model=list[WorkOrderListResponse])
async def list_work_orders(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    status_filter: str | None = Query(default=None, alias="status"),
    area_id: int | None = Query(default=None),
    overdue: bool = Query(default=False),
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    query = _base_query()

    if current_user.role not in manager_roles:
        query = query.where(WorkOrder.created_by_user_id == current_user.id)
    elif current_user.role == UserRole.SUPERVISOR:
        # Supervisors see and manage only their configured plant areas.
        if not current_user.area_ids:
            query = query.where(WorkOrder.id == -1)
        else:
            query = query.where(WorkOrder.area_id.in_(current_user.area_ids))

    if overdue:
        # Panel de OTs vencidas: con fecha límite pasada y aún abiertas.
        today = datetime.now().date()
        query = query.where(
            WorkOrder.due_date.isnot(None),
            WorkOrder.due_date < today,
            WorkOrder.status.in_(
                (WorkOrderStatus.PENDING.value, WorkOrderStatus.IN_PROGRESS.value)
            ),
        )
        query = query.order_by(WorkOrder.due_date.asc())
    else:
        if status_filter:
            query = query.where(WorkOrder.status == status_filter.upper())
        if area_id:
            query = query.where(WorkOrder.area_id == area_id)
        query = query.order_by(WorkOrder.created_at.desc())
    if offset:
        query = query.offset(offset)
    if limit:
        query = query.limit(limit)

    result = await db.execute(query)
    orders = result.scalars().all()

    return [
        WorkOrderListResponse(
            id=wo.id,
            ot_number=wo.ot_number,
            title=wo.title,
            area_name=wo.area.name if wo.area else None,
            equipment_name=wo.equipment.name if wo.equipment else None,
            section_name=wo.section_name,
            maintenance_type=wo.maintenance_type,
            loto_status=wo.loto_status,
            status=wo.status,
            execution_date=wo.execution_date,
            request_date=wo.request_date,
            ot_sheet_sync_status=wo.ot_sheet_sync_status,
            monthly_sheet_sync_status=wo.monthly_sheet_sync_status,
            created_at=wo.created_at,
            submitted_for_review=wo.submitted_for_review,
            responsible_user_id=wo.responsible_user_id,
            responsible_user_name=wo.responsible_user.full_name if wo.responsible_user else None,
            is_planned=wo.is_planned,
            scheduled_date=wo.scheduled_date,
            due_date=wo.due_date,
        )
        for wo in orders
    ]


# ───────────────────────────────────────────────────────────────────────────
# My Work Orders (worker view) — MUST be before /{wo_id}
# ───────────────────────────────────────────────────────────────────────────
@router.get("/my", response_model=list[WorkOrderListResponse])
async def my_work_orders(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """OTs where the current user is responsible or a participant."""
    # Subquery for participant IDs
    participant_wo_ids = select(work_order_participants.c.work_order_id).where(
        work_order_participants.c.user_id == current_user.id
    )

    query = _base_query().where(
        (WorkOrder.responsible_user_id == current_user.id)
        | (WorkOrder.id.in_(participant_wo_ids))
    )

    if status_filter:
        query = query.where(WorkOrder.status == status_filter.upper())

    query = query.order_by(WorkOrder.created_at.desc())
    if offset:
        query = query.offset(offset)
    if limit:
        query = query.limit(limit)

    result = await db.execute(query)
    orders = result.scalars().all()

    return [
        WorkOrderListResponse(
            id=wo.id,
            ot_number=wo.ot_number,
            title=wo.title,
            area_name=wo.area.name if wo.area else None,
            equipment_name=wo.equipment.name if wo.equipment else None,
            section_name=wo.section_name,
            maintenance_type=wo.maintenance_type,
            loto_status=wo.loto_status,
            status=wo.status,
            execution_date=wo.execution_date,
            request_date=wo.request_date,
            ot_sheet_sync_status=wo.ot_sheet_sync_status,
            monthly_sheet_sync_status=wo.monthly_sheet_sync_status,
            created_at=wo.created_at,
            submitted_for_review=wo.submitted_for_review,
            responsible_user_id=wo.responsible_user_id,
            responsible_user_name=wo.responsible_user.full_name if wo.responsible_user else None,
            is_planned=wo.is_planned,
            scheduled_date=wo.scheduled_date,
            due_date=wo.due_date,
        )
        for wo in orders
    ]


# ───────────────────────────────────────────────────────────────────────────
# Counter / next OT number (admin only)
# ───────────────────────────────────────────────────────────────────────────
@router.get("/counter", response_model=WorkOrderCounterResponse)
async def get_work_order_counter(
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Cuantifica las OTs (totales por año y por mes del año actual) y el próximo
    N° OT que se asignará. Solo ADMIN — la planificación los necesita."""
    # Totals per year with execution date. The headline total below is
    # intentionally calculated separately so draft/pending OTs without an
    # execution date are not silently excluded.
    per_year_rows = await db.execute(
        select(
            func.extract("year", WorkOrder.execution_date).label("year"),
            func.count().label("total"),
        )
        .where(WorkOrder.execution_date.isnot(None))
        .group_by("year")
        .order_by("year")
    )
    per_year = {int(r.year): int(r.total) for r in per_year_rows.all() if r.year}

    # Totals per month of the CURRENT year (0 = enero ... 11 = diciembre)
    now = datetime.now(timezone.utc)
    current_year = now.year
    per_month_rows = await db.execute(
        select(
            func.extract("month", WorkOrder.execution_date).label("month"),
            func.count().label("total"),
        )
        .where(
            WorkOrder.execution_date.isnot(None),
            func.extract("year", WorkOrder.execution_date) == current_year,
        )
        .group_by("month")
    )
    per_month = {int(r.month) - 1: int(r.total) for r in per_month_rows.all() if r.month}

    # Next OT number by scanning the max OT-YYYY-NNNN already used this year
    total_all_result = await db.execute(
        select(func.count(WorkOrder.id)).select_from(WorkOrder)
    )
    total_all = int(total_all_result.scalar_one() or 0)
    next_ot = await _next_ot_number(db)

    return WorkOrderCounterResponse(
        current_year=current_year,
        total_all=total_all,
        per_year=per_year,
        per_month=per_month,
        next_ot_number=next_ot,
    )


# ───────────────────────────────────────────────────────────────────────────
# Get one Work Order
# ───────────────────────────────────────────────────────────────────────────
@router.get("/{wo_id}", response_model=WorkOrderResponse)
async def get_work_order(
    wo_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(_base_query().where(WorkOrder.id == wo_id))
    wo = result.scalar_one_or_none()
    if wo is None:
        raise HTTPException(status_code=404, detail="Orden de trabajo no encontrada")

    if not perms.can_view(wo, current_user):
        raise HTTPException(status_code=403, detail="No tiene permiso para ver esta OT")

    return _work_order_to_response(wo)


# ───────────────────────────────────────────────────────────────────────────
# Update Work Order (managers only, blocked for APPROVED)
# ───────────────────────────────────────────────────────────────────────────
@router.patch("/{wo_id}", response_model=WorkOrderResponse)
async def update_work_order(
    wo_id: int,
    payload: WorkOrderUpdate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(supervisor_or_admin),
):
    result = await db.execute(
        _base_query().where(WorkOrder.id == wo_id).with_for_update()
    )
    wo = result.scalar_one_or_none()
    if wo is None:
        raise HTTPException(status_code=404, detail="Orden de trabajo no encontrada")

    if not perms.can_edit(wo, current_user):
        raise HTTPException(
            status_code=403,
            detail="No se puede editar una OT aprobada o cancelada",
        )
    if current_user.role == UserRole.SUPERVISOR and (
        payload.responsible_user_id is not None
        or payload.participant_user_ids is not None
    ):
        raise HTTPException(
            status_code=403,
            detail="Solo el administrador puede asignar responsables y participantes",
        )
    if payload.area_id is not None:
        area_scope_error = _supervisor_area_error(current_user, payload.area_id)
        if area_scope_error:
            raise HTTPException(status_code=403, detail=area_scope_error)

    previous = {"title": wo.title, "status": wo.status}
    previous_execution_date = wo.execution_date

    if payload.title is not None:
        wo.title = payload.title.strip()
    if payload.description is not None:
        wo.description = payload.description
    if payload.area_id is not None:
        await _validate_area_equipment(db, payload.area_id, payload.equipment_id)
        wo.area_id = payload.area_id
    if payload.equipment_id is not None:
        wo.equipment_id = payload.equipment_id
    if payload.section_name is not None:
        wo.section_name = payload.section_name
    if payload.maintenance_type is not None:
        wo.maintenance_type = payload.maintenance_type.upper()
    if payload.loto_status is not None:
        wo.loto_status = payload.loto_status.upper()
    if payload.folio is not None:
        wo.folio = payload.folio
    if payload.estimated_time is not None:
        wo.estimated_time = payload.estimated_time
    if payload.request_date is not None:
        wo.request_date = payload.request_date
    if payload.execution_date is not None:
        wo.execution_date = payload.execution_date
    if payload.resources_required is not None:
        wo.resources_required = payload.resources_required
    if payload.voucher_number is not None:
        wo.voucher_number = payload.voucher_number
    if payload.risks is not None:
        wo.risks = payload.risks
    if payload.observations is not None:
        wo.observations = payload.observations
    if payload.requested_by is not None:
        wo.requested_by = payload.requested_by
    if payload.responsible_user_id is not None:
        wo.responsible_user_id = payload.responsible_user_id
    if payload.is_planned is not None:
        wo.is_planned = payload.is_planned
    if payload.scheduled_date is not None:
        wo.scheduled_date = payload.scheduled_date
    if payload.due_date is not None:
        wo.due_date = payload.due_date

    # Handle M2M participant updates
    if payload.participant_user_ids is not None:
        participant_ids = list(payload.participant_user_ids)
        if wo.responsible_user_id is not None and wo.responsible_user_id not in participant_ids:
            participant_ids.append(wo.responsible_user_id)
        # Clear existing
        await db.execute(
            work_order_participants.delete().where(
                work_order_participants.c.work_order_id == wo.id
            )
        )
        for uid in participant_ids:
            await db.execute(
                work_order_participants.insert().values(
                    work_order_id=wo.id, user_id=uid
                )
            )
        # Update participant_names TEXT for Google Sheets compatibility
        if participant_ids:
            result = await db.execute(
                select(User.full_name).where(User.id.in_(participant_ids))
            )
            names = [row[0] for row in result.all()]
            wo.participant_names = ", ".join(names) if names else None
        else:
            wo.participant_names = None

    await _ensure_responsible_is_participant(db, wo)

    await create_audit_log(
        db,
        user_id=current_user.id,
        action="UPDATE_WORK_ORDER",
        entity_type="WorkOrder",
        entity_id=wo.id,
        previous_data=previous,
        new_data={"title": wo.title, "status": wo.status},
    )
    await db.flush()

    # Keep external integrations out of the request latency budget. The local
    # edit is committed first and Google is synchronized in the background.
    _changed_monthly_fields = {
        "status", "title", "description", "area_id", "equipment_id",
        "section_name", "maintenance_type", "estimated_time",
        "execution_date", "participant_names", "responsible_user_id",
    }
    changed = payload.model_dump(exclude_unset=True)
    monthly_relevant = set(changed) & _changed_monthly_fields
    should_sync = bool(monthly_relevant and wo.google_ot_file_id)

    # Re-populate the OT document whenever an admin/OT-relevant field changed,
    # so the Google OT stays in sync with edits (e.g. changing fecha solicitud
    # after the OT was emitted). Uses the same field set as the worker fulfill path.
    _changed_ot_fields = {
        "title", "description", "area_id", "equipment_id", "section_name",
        "maintenance_type", "loto_status", "estimated_time", "execution_date",
        "request_date", "resources_required", "risks", "observations",
        "folio", "voucher_number", "requested_by",
        "responsible_user_id", "participant_user_ids", "participant_names",
    }
    populate_individual = bool(set(changed) & _changed_ot_fields and wo.google_ot_file_id)
    should_sync = should_sync or populate_individual

    bg_factory = None
    if should_sync:
        _mark_external_sync_pending(wo)
        bg_factory = async_sessionmaker(
            db.bind, class_=AsyncSession, expire_on_commit=False
        )

    if should_sync:
        await enqueue_external_sync(
            db,
            wo.id,
            job_type="LIFECYCLE",
            actor_user_id=current_user.id,
            populate_individual=populate_individual,
            previous_execution_date=previous_execution_date,
        )
    await db.commit()

    result2 = await db.execute(_base_query().where(WorkOrder.id == wo.id))
    return _work_order_to_response(result2.scalar_one())


# ───────────────────────────────────────────────────────────────────────────
# Reassign Work Order (managers only) — change responsible / participants
# ───────────────────────────────────────────────────────────────────────────
@router.post("/{wo_id}/reassign", response_model=WorkOrderResponse)
async def reassign_work_order(
    wo_id: int,
    payload: ReassignPayload,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(supervisor_or_admin),
):
    result = await db.execute(
        _base_query().where(WorkOrder.id == wo_id).with_for_update()
    )
    wo = result.scalar_one_or_none()
    if wo is None:
        raise HTTPException(status_code=404, detail="Orden de trabajo no encontrada")

    if not perms.can_edit(wo, current_user):
        raise HTTPException(
            status_code=403,
            detail="No se puede reasignar una OT aprobada o cancelada",
        )
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=403,
            detail="Solo el administrador puede asignar responsables y participantes",
        )

    if payload.responsible_user_id is None and payload.participant_user_ids is None:
        raise HTTPException(
            status_code=400,
            detail="Debe indicar al menos un responsable o participantes a cambiar",
        )

    previous = {
        "responsible_user_id": wo.responsible_user_id,
        "participants": [p.id for p in (wo.participants or [])],
    }

    # Responsable — validate it's a real, active user once provided.
    if payload.responsible_user_id is not None:
        resp_user = await db.get(User, payload.responsible_user_id)
        if resp_user is None or not resp_user.is_active:
            raise HTTPException(status_code=400, detail="Responsable no válido")
        wo.responsible_user_id = payload.responsible_user_id

    # Participants (M2M) — same pattern as update_work_order.
    if payload.participant_user_ids is not None:
        participant_ids = list(payload.participant_user_ids)
        if wo.responsible_user_id is not None and wo.responsible_user_id not in participant_ids:
            participant_ids.append(wo.responsible_user_id)
        await db.execute(
            work_order_participants.delete().where(
                work_order_participants.c.work_order_id == wo.id
            )
        )
        for uid in participant_ids:
            await db.execute(
                work_order_participants.insert().values(
                    work_order_id=wo.id, user_id=uid
                )
            )
        if participant_ids:
            result_ids = await db.execute(
                select(User.full_name).where(User.id.in_(participant_ids))
            )
            names = [row[0] for row in result_ids.all()]
            wo.participant_names = ", ".join(names) if names else None
        else:
            wo.participant_names = None

    await _ensure_responsible_is_participant(db, wo)

    participant_result = await db.execute(
        select(work_order_participants.c.user_id).where(
            work_order_participants.c.work_order_id == wo.id
        )
    )
    current_participant_ids = [row[0] for row in participant_result.all()]

    await create_audit_log(
        db,
        user_id=current_user.id,
        action="REASSIGN_WORK_ORDER",
        entity_type="WorkOrder",
        entity_id=wo.id,
        previous_data=previous,
        new_data={
            "responsible_user_id": wo.responsible_user_id,
            "participants": current_participant_ids,
        },
    )
    await db.flush()

    # Do not notify workers while a supervisor submission is still awaiting
    # acceptance. The normal assignment notification is sent on /issue.
    if not wo.submitted_for_review:
        await notification_service.notify_work_order_reassigned(
            db,
            wo,
            link=f"/mis-ordenes/{wo.id}",
            previous_recipient_ids={
                uid for uid in [previous["responsible_user_id"], *previous["participants"]]
                if uid is not None
            },
            participant_user_ids=current_participant_ids,
            actor_user_id=current_user.id,
        )

    should_sync = bool(wo.google_ot_file_id)
    bg_factory = None
    if should_sync:
        _mark_external_sync_pending(wo)
        bg_factory = async_sessionmaker(
            db.bind, class_=AsyncSession, expire_on_commit=False
        )

    if should_sync:
        await enqueue_external_sync(
            db,
            wo.id,
            job_type="LIFECYCLE",
            actor_user_id=current_user.id,
            populate_individual=True,
        )
    await db.commit()

    db.expire(wo, ["participants"])
    result2 = await db.execute(_base_query().where(WorkOrder.id == wo.id))
    return _work_order_to_response(result2.scalar_one())


# ───────────────────────────────────────────────────────────────────────────
# Fulfill OT (responsible worker completes the remaining detail fields)
# ───────────────────────────────────────────────────────────────────────────
@router.patch("/{wo_id}/fulfill", response_model=WorkOrderResponse)
async def fulfill_work_order(
    wo_id: int,
    payload: WorkOrderUpdate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Permite al responsable completar los campos de detalle restantes de la
    OT (tipo, LOTO, horas, recursos, riesgos, observaciones, folio,
    participantes, etc.) que el admin dejó vacíos al crearla."""
    result = await db.execute(
        _base_query().where(WorkOrder.id == wo_id).with_for_update()
    )
    wo = result.scalar_one_or_none()
    if wo is None:
        raise HTTPException(status_code=404, detail="Orden de trabajo no encontrada")

    if not perms.can_fulfill(wo, current_user):
        raise HTTPException(
            status_code=403,
            detail="No tiene permiso para completar esta OT",
        )

    previous = {"title": wo.title, "status": wo.status}
    previous_execution_date = wo.execution_date

    if payload.title is not None:
        wo.title = payload.title.strip()
    if payload.description is not None:
        wo.description = payload.description
    if payload.section_name is not None:
        wo.section_name = payload.section_name
    if payload.maintenance_type is not None:
        wo.maintenance_type = payload.maintenance_type.upper()
    if payload.loto_status is not None:
        wo.loto_status = payload.loto_status.upper()
    if payload.folio is not None:
        wo.folio = payload.folio
    if payload.estimated_time is not None:
        wo.estimated_time = payload.estimated_time
    if payload.request_date is not None:
        wo.request_date = payload.request_date
    if payload.execution_date is not None:
        wo.execution_date = payload.execution_date
    if payload.resources_required is not None:
        wo.resources_required = payload.resources_required
    if payload.voucher_number is not None:
        wo.voucher_number = payload.voucher_number
    if payload.risks is not None:
        wo.risks = payload.risks
    if payload.observations is not None:
        wo.observations = payload.observations
    # Participants (M2M)
    if payload.participant_user_ids is not None:
        participant_ids = list(payload.participant_user_ids)
        if wo.responsible_user_id is not None and wo.responsible_user_id not in participant_ids:
            participant_ids.append(wo.responsible_user_id)
        await db.execute(
            work_order_participants.delete().where(
                work_order_participants.c.work_order_id == wo.id
            )
        )
        for uid in participant_ids:
            await db.execute(
                work_order_participants.insert().values(
                    work_order_id=wo.id, user_id=uid
                )
            )
        if participant_ids:
            result = await db.execute(
                select(User.full_name).where(User.id.in_(participant_ids))
            )
            names = [row[0] for row in result.all()]
            wo.participant_names = ", ".join(names) if names else None
        else:
            wo.participant_names = None

    await _ensure_responsible_is_participant(db, wo)

    await create_audit_log(
        db,
        user_id=current_user.id,
        action="UPDATE_WORK_ORDER",
        entity_type="WorkOrder",
        entity_id=wo.id,
        previous_data=previous,
        new_data={"title": wo.title, "status": wo.status, "fulfilled_by": current_user.id},
    )
    await db.flush()

    # Keep the monthly registry in sync (already emitted → update row)
    _changed = {
        "status", "title", "description", "section_name", "maintenance_type",
        "estimated_time", "execution_date", "participant_names", "loto_status",
        "risks", "observations", "resources_required", "folio", "voucher_number",
    }
    changed = payload.model_dump(exclude_unset=True)
    should_sync = bool(set(changed) & _changed and wo.google_ot_file_id)
    bg_factory = None
    if should_sync:
        _mark_external_sync_pending(wo)
        bg_factory = async_sessionmaker(
            db.bind, class_=AsyncSession, expire_on_commit=False
        )

    if should_sync:
        await enqueue_external_sync(
            db,
            wo.id,
            job_type="LIFECYCLE",
            actor_user_id=current_user.id,
            populate_individual=True,
            previous_execution_date=previous_execution_date,
        )
    await db.commit()

    # Re-fetch to reflect M2M changes (expire cached participants first)
    db.expire(wo, ["participants"])
    result2 = await db.execute(_base_query().where(WorkOrder.id == wo.id))
    return _work_order_to_response(result2.scalar_one())


@router.patch("/{wo_id}/fulfill-autosave", response_model=WorkOrderResponse)
async def autosave_fulfill_work_order(
    wo_id: int,
    payload: WorkOrderUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Persist detail-form progress without creating an audit entry per keystroke.

    The worker form sends this endpoint after the user pauses typing. It keeps
    the local OT safe without making the user press a save button. The normal
    ``/fulfill`` endpoint remains available for an explicit, audited save.
    """
    result = await db.execute(
        _base_query().where(WorkOrder.id == wo_id).with_for_update()
    )
    wo = result.scalar_one_or_none()
    if wo is None:
        raise HTTPException(status_code=404, detail="Orden de trabajo no encontrada")

    if not perms.can_fulfill(wo, current_user):
        raise HTTPException(
            status_code=403,
            detail="No tiene permiso para completar esta OT",
        )

    fields = payload.model_fields_set
    if "maintenance_type" in fields and payload.maintenance_type is not None:
        wo.maintenance_type = payload.maintenance_type.upper()
    if "loto_status" in fields and payload.loto_status is not None:
        wo.loto_status = payload.loto_status.upper()
    if "execution_date" in fields:
        wo.execution_date = payload.execution_date
    if "section_name" in fields:
        wo.section_name = payload.section_name
    if "estimated_time" in fields:
        wo.estimated_time = payload.estimated_time
    if "resources_required" in fields:
        wo.resources_required = payload.resources_required
    if "risks" in fields:
        wo.risks = payload.risks
    if "observations" in fields:
        wo.observations = payload.observations
    if "folio" in fields:
        wo.folio = payload.folio
    if "voucher_number" in fields:
        wo.voucher_number = payload.voucher_number

    await db.flush()

    # Autosave is deliberately local and lightweight. Google synchronization
    # is queued at workflow milestones or through the explicit save action,
    # avoiding one external job for every pause while typing.
    await db.commit()
    db.expire(wo, ["participants"])
    result2 = await db.execute(_base_query().where(WorkOrder.id == wo.id))
    return _work_order_to_response(result2.scalar_one())


# ───────────────────────────────────────────────────────────────────────────
# Issue Work Order (DRAFT → PENDING)
# ───────────────────────────────────────────────────────────────────────────
@router.post("/{wo_id}/issue", response_model=WorkOrderResponse)
async def issue_work_order(
    wo_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Emitir OT: validates required fields and transitions DRAFT → PENDING."""
    result = await db.execute(
        _base_query().where(WorkOrder.id == wo_id).with_for_update()
    )
    wo = result.scalar_one_or_none()
    if wo is None:
        raise HTTPException(status_code=404, detail="Orden de trabajo no encontrada")

    if not perms.can_issue(wo, current_user):
        raise HTTPException(status_code=403, detail="No tiene permiso para emitir esta OT")
    if wo.submitted_for_review and current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=403,
            detail="Esta OT fue enviada por un supervisor y debe ser aceptada por un administrador",
        )
    area_scope_error = _supervisor_area_error(current_user, wo.area_id)
    if area_scope_error:
        raise HTTPException(status_code=403, detail=area_scope_error)

    # A supervisor can submit a saved draft for review, but cannot accept it
    # or assign the execution team.
    if current_user.role == UserRole.SUPERVISOR:
        errors = []
        if not wo.description or not wo.description.strip():
            errors.append("DescripciÃ³n del trabajo")
        if not current_user.signature:
            errors.append("Firma manuscrita en Mi firma")
        if errors:
            raise HTTPException(
                status_code=400,
                detail=f"Para enviar la OT a revisiÃ³n, complete: {', '.join(errors)}",
            )
        wo.submitted_for_review = True
        wo.requested_by = current_user.full_name
        wo.requested_signature = current_user.signature
        await create_audit_log(
            db,
            user_id=current_user.id,
            action="SUBMIT_WORK_ORDER_FOR_REVIEW",
            entity_type="WorkOrder",
            entity_id=wo.id,
            previous_data={"status": wo.status},
            new_data={"status": wo.status, "submitted_for_review": True},
        )
        await notification_service.notify_work_order_submitted_to_admin(
            db, wo, submitted_by=current_user.full_name, link=f"/ordenes/{wo.id}"
        )
        await db.commit()
        result2 = await db.execute(_base_query().where(WorkOrder.id == wo.id))
        return _work_order_to_response(result2.scalar_one())

    # Validate required fields for emission.
    # The admin provides: descripción, responsable, participantes (quienes
    # entran en la OT), área/equipo, fecha de solicitud.  Los detalles de
    # ejecución (fecha de ejecución, sección, horas, tipo, etc.) los completa
    # la persona responsable después vía /fulfill.
    errors = []
    if not wo.description or not wo.description.strip():
        errors.append("Descripción del trabajo")
    if not wo.responsible_user_id:
        errors.append("Responsable principal")
    await _ensure_responsible_is_participant(db, wo)
    participant_result = await db.execute(
        select(work_order_participants.c.user_id).where(
            work_order_participants.c.work_order_id == wo.id
        ).limit(1)
    )
    if participant_result.scalar_one_or_none() is None:
        # Participants: who enters/participates in the OT — chosen by admin.
        # Resolve from the M2M relationship (already loaded in _base_query).
        errors.append("Al menos un participante")
    if not current_user.signature:
        errors.append("Firma manuscrita en Mi firma")

    if errors:
        raise HTTPException(
            status_code=400,
            detail=f"Para emitir la OT, complete los campos obligatorios: {', '.join(errors)}",
        )

    previous_status = wo.status
    try:
        validate_transition(wo.status, WorkOrderStatus.PENDING.value)
    except InvalidTransitionError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Keep the original requester when an administrator accepts a supervisor's
    # submission. The admin is the approver/assigner, not the requester, so
    # the supervisor's name and signature must remain in "SOLICITADO POR".
    was_submitted_for_review = wo.submitted_for_review
    wo.status = WorkOrderStatus.PENDING.value
    wo.submitted_for_review = False
    if not was_submitted_for_review:
        wo.requested_by = current_user.full_name
        wo.requested_signature = current_user.signature

    await create_audit_log(
        db,
        user_id=current_user.id,
        action="ISSUE_WORK_ORDER",
        entity_type="WorkOrder",
        entity_id=wo.id,
        previous_data={"status": previous_status},
        new_data={"status": wo.status},
    )

    # Notify responsible + participants that the OT was assigned.
    await notification_service.notify_work_order_assigned(
        db, wo, link=f"/mis-ordenes/{wo.id}"
    )
    if current_user.role == UserRole.SUPERVISOR:
        await notification_service.notify_work_order_submitted_to_admin(
            db, wo, submitted_by=current_user.full_name, link=f"/ordenes/{wo.id}"
        )

    # Google sync (OT template + monthly) runs in the BACKGROUND so emitting
    # responds instantly — the admin can emit many OTs in a row without waiting
    # on Drive/Sheets. Same pattern as create-then-emit. The OT starts with
    # sync statuses PENDING and the background task flips them to SYNCED/FAILED.
    wo.ot_sheet_sync_status = "PENDING"
    wo.monthly_sheet_sync_status = "PENDING"
    await enqueue_external_sync(
        db, wo.id, job_type="FULL_CREATE", actor_user_id=current_user.id
    )
    await db.commit()

    result2 = await db.execute(_base_query().where(WorkOrder.id == wo.id))
    return _work_order_to_response(result2.scalar_one())


# ───────────────────────────────────────────────────────────────────────────
# Batch Issue (managers only) — emit several DRAFT OTs at once
# ───────────────────────────────────────────────────────────────────────────
@router.post("/batch-issue")
async def batch_issue_work_orders(
    payload: BatchIssuePayload,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
):
    """Emitir N borradores en una sola operación (DRAFT → PENDING).

    Reuses the same per-OT validation as `/issue`: description, responsible,
    at least one participant, and the admin's saved signature. Each valid OT
    flips to PENDING and schedules its own background Google sync. Invalid or
    missing IDs are reported per-OT without failing the whole batch.
    """
    if not payload.ids:
        return {"issued": [], "failures": []}
    if len(payload.ids) > 100:
        raise HTTPException(status_code=400, detail="Máximo 100 OTs por lote")

    # Sólo el usuario firmante puede emitir; una firma faltante hace fallar
    # todas las del lote (es la misma regla del issue individual).
    if not current_user.signature:
        raise HTTPException(
            status_code=400,
            detail="Debe cargar su firma manuscrita en Mi firma antes de emitir OTs",
        )

    result = await db.execute(
        _base_query().where(WorkOrder.id.in_(payload.ids)).with_for_update()
    )
    orders = {wo.id: wo for wo in result.scalars().all()}

    issued: list[int] = []
    failures: list[dict] = []

    for wo_id in payload.ids:
        wo = orders.get(wo_id)
        if wo is None:
            failures.append({"id": wo_id, "error": "Orden no encontrada"})
            continue
        if not perms.can_issue(wo, current_user):
            failures.append({"id": wo_id, "error": "No tiene permiso para emitir esta OT"})
            continue
        if wo.submitted_for_review:
            failures.append(
                {
                    "id": wo_id,
                    "error": "Esta OT fue solicitada por un supervisor y debe revisarse y asignarse individualmente",
                }
            )
            continue
        area_scope_error = _supervisor_area_error(current_user, wo.area_id)
        if area_scope_error:
            failures.append({"id": wo_id, "error": area_scope_error})
            continue

        errors = []
        if not wo.description or not wo.description.strip():
            errors.append("Descripción del trabajo")
        if not wo.responsible_user_id:
            errors.append("Responsable principal")
        await _ensure_responsible_is_participant(db, wo)
        participant_result = await db.execute(
            select(work_order_participants.c.user_id).where(
                work_order_participants.c.work_order_id == wo.id
            ).limit(1)
        )
        if participant_result.scalar_one_or_none() is None:
            errors.append("Al menos un participante")
        if errors:
            failures.append(
                {
                    "id": wo_id,
                    "error": "Faltan campos obligatorios: " + ", ".join(errors),
                }
            )
            continue

        try:
            validate_transition(wo.status, WorkOrderStatus.PENDING.value)
        except InvalidTransitionError as e:
            failures.append({"id": wo_id, "error": str(e)})
            continue

        previous_status = wo.status
        wo.status = WorkOrderStatus.PENDING.value
        wo.submitted_for_review = False
        # Batch emission is for administrator-created drafts only, so the
        # administrator's signature is the requester signature in this path.
        wo.requested_by = current_user.full_name
        wo.requested_signature = current_user.signature

        await create_audit_log(
            db,
            user_id=current_user.id,
            action="ISSUE_WORK_ORDER",
            entity_type="WorkOrder",
            entity_id=wo.id,
            previous_data={"status": previous_status},
            new_data={"status": wo.status},
        )
        await notification_service.notify_work_order_assigned(
            db, wo, link=f"/mis-ordenes/{wo.id}"
        )
        if current_user.role == UserRole.SUPERVISOR:
            await notification_service.notify_work_order_submitted_to_admin(
                db, wo, submitted_by=current_user.full_name, link=f"/ordenes/{wo.id}"
            )
        wo.ot_sheet_sync_status = "PENDING"
        wo.monthly_sheet_sync_status = "PENDING"
        issued.append(wo_id)

    if issued:
        # Persist all OT changes and their queue entries atomically.
        for wo_id in issued:
            await enqueue_external_sync(
                db, wo_id, job_type="FULL_CREATE", actor_user_id=current_user.id
            )
        await db.commit()
    else:
        await db.flush()

    return {"issued": issued, "failures": failures}


# ───────────────────────────────────────────────────────────────────────────
# Start Work (PENDING → IN_PROGRESS)
# ───────────────────────────────────────────────────────────────────────────
@router.post("/{wo_id}/start", response_model=WorkOrderResponse)
async def start_work_order(
    wo_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        _base_query().where(WorkOrder.id == wo_id).with_for_update()
    )
    wo = result.scalar_one_or_none()
    if wo is None:
        raise HTTPException(status_code=404, detail="Orden de trabajo no encontrada")

    if not perms.can_start(wo, current_user):
        raise HTTPException(status_code=403, detail="No tiene permiso para iniciar esta OT")

    try:
        validate_transition(wo.status, WorkOrderStatus.IN_PROGRESS.value)
    except InvalidTransitionError as e:
        raise HTTPException(status_code=400, detail=str(e))

    previous_status = wo.status
    wo.status = WorkOrderStatus.IN_PROGRESS.value
    wo.started_at = datetime.now(timezone.utc)
    wo.started_by_user_id = current_user.id
    wo.started_by_user = current_user

    await create_audit_log(
        db,
        user_id=current_user.id,
        action="START_WORK_ORDER",
        entity_type="WorkOrder",
        entity_id=wo.id,
        previous_data={"status": previous_status},
        new_data={"status": wo.status, "started_at": wo.started_at.isoformat()},
    )
    await db.flush()

    should_sync = bool(wo.google_ot_file_id)
    bg_factory = None
    if should_sync:
        _mark_external_sync_pending(wo)
        bg_factory = async_sessionmaker(
            db.bind, class_=AsyncSession, expire_on_commit=False
        )

    if should_sync:
        await enqueue_external_sync(
            db, wo.id, job_type="LIFECYCLE", actor_user_id=current_user.id
        )
    await db.commit()

    result2 = await db.execute(_base_query().where(WorkOrder.id == wo.id))
    return _work_order_to_response(result2.scalar_one())


# ───────────────────────────────────────────────────────────────────────────
# Complete Work (IN_PROGRESS → COMPLETED)
# ───────────────────────────────────────────────────────────────────────────
@router.patch("/{wo_id}/complete", response_model=WorkOrderResponse)
async def complete_work_order(
    wo_id: int,
    background_tasks: BackgroundTasks,
    payload: CompletePayload = CompletePayload(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        _base_query().where(WorkOrder.id == wo_id).with_for_update()
    )
    wo = result.scalar_one_or_none()
    if wo is None:
        raise HTTPException(status_code=404, detail="Orden de trabajo no encontrada")

    if not perms.can_complete(wo, current_user):
        raise HTTPException(status_code=403, detail="No tiene permiso para finalizar esta OT")

    try:
        validate_transition(wo.status, WorkOrderStatus.COMPLETED.value)
    except InvalidTransitionError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not wo.started_at:
        raise HTTPException(
            status_code=400,
            detail="La OT no tiene fecha de inicio registrada",
        )
    if not current_user.signature:
        raise HTTPException(
            status_code=400,
            detail="Debe cargar su firma manuscrita en Mi firma antes de finalizar una OT",
        )

    previous_status = wo.status
    now = datetime.now(timezone.utc)
    wo.status = WorkOrderStatus.COMPLETED.value
    wo.completed_at = now
    wo.completed_by_user_id = current_user.id
    wo.completed_by_user = current_user
    wo.completion_notes = payload.completion_notes
    # The right authorization block belongs to the person who performed the
    # work, not to the administrator who later approves it.
    wo.approved_by = current_user.full_name
    wo.approved_signature = current_user.signature

    # Calculate actual duration (normalize to aware for SQLite compat)
    started = wo.started_at
    if started is not None and started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    delta = now - started
    wo.actual_duration_minutes = round(delta.total_seconds() / 60, 2)

    await create_audit_log(
        db,
        user_id=current_user.id,
        action="COMPLETE_WORK_ORDER",
        entity_type="WorkOrder",
        entity_id=wo.id,
        previous_data={"status": previous_status},
        new_data={
            "status": wo.status,
            "completed_at": now.isoformat(),
            "actual_duration_minutes": wo.actual_duration_minutes,
        },
    )
    await db.flush()

    await notification_service.notify_work_order_completed(
        db, wo, link=f"/ordenes/{wo.id}", exclude_user_id=current_user.id
    )

    should_sync = bool(wo.google_ot_file_id)
    bg_factory = None
    if should_sync:
        _mark_external_sync_pending(wo)
        bg_factory = async_sessionmaker(
            db.bind, class_=AsyncSession, expire_on_commit=False
        )

    if should_sync:
        await enqueue_external_sync(
            db,
            wo.id,
            job_type="LIFECYCLE",
            actor_user_id=current_user.id,
            populate_individual=True,
        )
    await db.commit()

    result2 = await db.execute(_base_query().where(WorkOrder.id == wo.id))
    return _work_order_to_response(result2.scalar_one())


# ───────────────────────────────────────────────────────────────────────────
# Return Work (COMPLETED → IN_PROGRESS) — admin sends back to worker
# ───────────────────────────────────────────────────────────────────────────
@router.post("/{wo_id}/return", response_model=WorkOrderResponse)
async def return_work_order(
    wo_id: int,
    payload: ReturnPayload,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        _base_query().where(WorkOrder.id == wo_id).with_for_update()
    )
    wo = result.scalar_one_or_none()
    if wo is None:
        raise HTTPException(status_code=404, detail="Orden de trabajo no encontrada")

    if not perms.can_return_(wo, current_user):
        raise HTTPException(status_code=403, detail="Solo un administrador puede devolver una OT")

    try:
        validate_transition(wo.status, WorkOrderStatus.IN_PROGRESS.value)
    except InvalidTransitionError as e:
        raise HTTPException(status_code=400, detail=str(e))

    previous_status = wo.status
    now = datetime.now(timezone.utc)
    wo.status = WorkOrderStatus.IN_PROGRESS.value
    wo.returned_at = now
    wo.returned_by_user_id = current_user.id
    wo.return_reason = payload.return_reason
    # Clear current completion snapshot (the event is preserved in AuditLog)
    wo.completed_at = None
    wo.completed_by_user_id = None
    wo.actual_duration_minutes = None
    wo.completion_notes = None

    await create_audit_log(
        db,
        user_id=current_user.id,
        action="RETURN_WORK_ORDER",
        entity_type="WorkOrder",
        entity_id=wo.id,
        previous_data={"status": previous_status},
        new_data={
            "status": wo.status,
            "return_reason": payload.return_reason,
        },
    )
    await db.flush()

    await notification_service.notify_work_order_returned(
        db,
        wo,
        reason=payload.return_reason,
        link=f"/mis-ordenes/{wo.id}",
        exclude_user_id=current_user.id,
    )

    should_sync = bool(wo.google_ot_file_id)
    bg_factory = None
    if should_sync:
        _mark_external_sync_pending(wo)
        bg_factory = async_sessionmaker(
            db.bind, class_=AsyncSession, expire_on_commit=False
        )

    if should_sync:
        await enqueue_external_sync(
            db, wo.id, job_type="LIFECYCLE", actor_user_id=current_user.id
        )
    await db.commit()

    result2 = await db.execute(_base_query().where(WorkOrder.id == wo.id))
    return _work_order_to_response(result2.scalar_one())


# ───────────────────────────────────────────────────────────────────────────
# Approve Work (COMPLETED → APPROVED) — admin signs and closes
# ───────────────────────────────────────────────────────────────────────────
@router.post("/{wo_id}/approve", response_model=WorkOrderResponse)
async def approve_work_order(
    wo_id: int,
    background_tasks: BackgroundTasks,
    payload: ApprovePayload = ApprovePayload(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        _base_query().where(WorkOrder.id == wo_id).with_for_update()
    )
    wo = result.scalar_one_or_none()
    if wo is None:
        raise HTTPException(status_code=404, detail="Orden de trabajo no encontrada")

    if not perms.can_approve(wo, current_user):
        raise HTTPException(status_code=403, detail="Solo un administrador puede aprobar una OT")

    try:
        validate_transition(wo.status, WorkOrderStatus.APPROVED.value)
    except InvalidTransitionError as e:
        raise HTTPException(status_code=400, detail=str(e))

    previous_status = wo.status
    now = datetime.now(timezone.utc)
    wo.status = WorkOrderStatus.APPROVED.value
    wo.approved_at = now
    wo.approved_by_user_id = current_user.id
    if not current_user.signature:
        raise HTTPException(
            status_code=400,
            detail="Debe cargar su firma manuscrita en Mi firma antes de aprobar una OT",
        )
    # The template's right block is "REALIZADO POR" and must retain the
    # worker's completion signature. Approval is recorded by the relationship
    # and audit log below, without overwriting the performed-work evidence.
    # Set the relationship so the response resolves the name correctly
    wo.approved_by_user = current_user

    await create_audit_log(
        db,
        user_id=current_user.id,
        action="APPROVE_WORK_ORDER",
        entity_type="WorkOrder",
        entity_id=wo.id,
        previous_data={"status": previous_status},
        new_data={
            "status": wo.status,
            "approved_at": now.isoformat(),
            "approved_by": current_user.full_name,
        },
    )
    await db.flush()

    await notification_service.notify_work_order_approved(
        db, wo, link=f"/mis-ordenes/{wo.id}", exclude_user_id=current_user.id
    )

    should_sync = bool(wo.google_ot_file_id)
    bg_factory = None
    if should_sync:
        _mark_external_sync_pending(wo)
        bg_factory = async_sessionmaker(
            db.bind, class_=AsyncSession, expire_on_commit=False
        )

    if should_sync:
        await enqueue_external_sync(
            db,
            wo.id,
            job_type="LIFECYCLE",
            actor_user_id=current_user.id,
            populate_individual=True,
        )
    await db.commit()

    result2 = await db.execute(_base_query().where(WorkOrder.id == wo.id))
    return _work_order_to_response(result2.scalar_one())


# ───────────────────────────────────────────────────────────────────────────
# Cancel Work Order (any open state → CANCELLED)
# ───────────────────────────────────────────────────────────────────────────
@router.post("/{wo_id}/cancel", response_model=WorkOrderResponse)
async def cancel_work_order(
    wo_id: int,
    payload: CancelPayload,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        _base_query().where(WorkOrder.id == wo_id).with_for_update()
    )
    wo = result.scalar_one_or_none()
    if wo is None:
        raise HTTPException(status_code=404, detail="Orden de trabajo no encontrada")

    if not perms.can_cancel(wo, current_user):
        raise HTTPException(status_code=403, detail="No tiene permiso para cancelar esta OT")

    try:
        validate_transition(wo.status, WorkOrderStatus.CANCELLED.value)
    except InvalidTransitionError as e:
        raise HTTPException(status_code=400, detail=str(e))

    previous_status = wo.status
    wo.status = WorkOrderStatus.CANCELLED.value
    wo.cancellation_reason = payload.cancellation_reason

    await create_audit_log(
        db,
        user_id=current_user.id,
        action="CANCEL_WORK_ORDER",
        entity_type="WorkOrder",
        entity_id=wo.id,
        previous_data={"status": previous_status},
        new_data={
            "status": wo.status,
            "cancellation_reason": payload.cancellation_reason,
        },
    )
    await db.flush()

    await notification_service.notify_work_order_cancelled(
        db,
        wo,
        reason=payload.cancellation_reason,
        link=f"/mis-ordenes/{wo.id}",
        exclude_user_id=current_user.id,
    )

    should_sync = bool(wo.google_ot_file_id)
    bg_factory = None
    if should_sync:
        _mark_external_sync_pending(wo)
        bg_factory = async_sessionmaker(
            db.bind, class_=AsyncSession, expire_on_commit=False
        )

    if should_sync:
        await enqueue_external_sync(
            db, wo.id, job_type="LIFECYCLE", actor_user_id=current_user.id
        )
    await db.commit()

    result2 = await db.execute(_base_query().where(WorkOrder.id == wo.id))
    return _work_order_to_response(result2.scalar_one())


# ───────────────────────────────────────────────────────────────────────────
# Reopen a closed OT (admin only)
#   APPROVED  -> IN_PROGRESS  (back to the worker)
#   CANCELLED -> DRAFT        (re-plan and re-issue)
# Reason is required and recorded in the audit log.
# ───────────────────────────────────────────────────────────────────────────
@router.post("/{wo_id}/reopen", response_model=WorkOrderResponse)
async def reopen_work_order(
    wo_id: int,
    payload: ReopenPayload,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        _base_query().where(WorkOrder.id == wo_id).with_for_update()
    )
    wo = result.scalar_one_or_none()
    if wo is None:
        raise HTTPException(status_code=404, detail="Orden de trabajo no encontrada")

    if not perms.can_reopen(wo, current_user):
        raise HTTPException(status_code=403, detail="Solo un administrador puede reabrir una OT")

    reason = (payload.reopen_reason or "").strip()
    if not reason:
        raise HTTPException(status_code=422, detail="reopen_reason es obligatorio")

    previous_status = wo.status

    if previous_status == WorkOrderStatus.APPROVED.value:
        # Approval is a local workflow state. Even if Google is still pending,
        # reopening must return the OT to the worker for rework.
        wo.status = WorkOrderStatus.IN_PROGRESS.value
    elif not wo.google_ot_file_id:
        # No document exists yet (CANCELLED before issue) — re-open as DRAFT.
        wo.status = WorkOrderStatus.DRAFT.value
    else:
        # CANCELLED but a document exists — reopen as DRAFT so it can be re-issued.
        wo.status = WorkOrderStatus.DRAFT.value

    now = datetime.now(timezone.utc)
    wo.returned_at = now
    wo.returned_by_user_id = current_user.id
    wo.return_reason = reason

    await create_audit_log(
        db,
        user_id=current_user.id,
        action="REOPEN_WORK_ORDER",
        entity_type="WorkOrder",
        entity_id=wo.id,
        previous_data={"status": previous_status},
        new_data={
            "status": wo.status,
            "reopen_reason": reason,
        },
    )
    await db.flush()

    await notification_service.notify_work_order_reopened(
        db,
        wo,
        reason=reason,
        link=f"/mis-ordenes/{wo.id}",
        exclude_user_id=current_user.id,
    )

    should_sync = bool(wo.google_ot_file_id)
    bg_factory = None
    if should_sync:
        _mark_external_sync_pending(wo)
        bg_factory = async_sessionmaker(
            db.bind, class_=AsyncSession, expire_on_commit=False
        )

    if should_sync:
        await enqueue_external_sync(
            db, wo.id, job_type="LIFECYCLE", actor_user_id=current_user.id
        )
    await db.commit()

    result2 = await db.execute(_base_query().where(WorkOrder.id == wo.id))
    return _work_order_to_response(result2.scalar_one())


# ───────────────────────────────────────────────────────────────────────────
# Full Google re-sync (managers only) — "Reintentar" button
# ───────────────────────────────────────────────────────────────────────────
# Re-runs the ENTIRE sync (OT document + monthly register row) so a previously
# FAILED OT can be retried from the UI. Idempotent: reuses an already created
# document instead of duplicating it in Drive.
@router.post("/{wo_id}/sync-google", response_model=WorkOrderResponse)
async def sync_google(
    wo_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(supervisor_or_admin),
):
    result = await db.execute(
        _base_query().where(WorkOrder.id == wo_id)
    )
    wo = result.scalar_one_or_none()
    if wo is None:
        raise HTTPException(status_code=404, detail="Orden de trabajo no encontrada")

    _mark_external_sync_pending(wo)
    await enqueue_external_sync(
        db, wo.id, job_type="FULL_SYNC", actor_user_id=current_user.id
    )
    await db.commit()

    result2 = await db.execute(_base_query().where(WorkOrder.id == wo.id))
    return _work_order_to_response(result2.scalar_one())


# ───────────────────────────────────────────────────────────────────────────
# Sync to monthly sheet (managers only)
# ───────────────────────────────────────────────────────────────────────────
@router.post("/{wo_id}/sync-monthly", response_model=WorkOrderResponse)
async def sync_monthly(
    wo_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(supervisor_or_admin),
):
    result = await db.execute(
        _base_query().where(WorkOrder.id == wo_id)
    )
    wo = result.scalar_one_or_none()
    if wo is None:
        raise HTTPException(status_code=404, detail="Orden de trabajo no encontrada")

    wo.monthly_sheet_sync_status = "PENDING"
    wo.monthly_sheet_sync_error = None
    await enqueue_external_sync(
        db, wo.id, job_type="MONTHLY", actor_user_id=current_user.id
    )
    await db.commit()

    result2 = await db.execute(_base_query().where(WorkOrder.id == wo.id))
    return _work_order_to_response(result2.scalar_one())
