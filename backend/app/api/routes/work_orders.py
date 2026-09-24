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
import time
from datetime import datetime, timezone, timedelta, date as _date, time as _time
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import noload, selectinload
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import get_current_user, require_roles
from app.core.config import settings
from app.core.work_order_areas import WORK_ORDER_AREAS
from app.core.loto import (
    controls_from_legacy_status,
    legacy_status_from_controls,
    normalize_loto_controls,
)
from app.db.session import get_db, async_session
from app.models.user import User, UserRole
from app.models.area import Area
from app.models.equipment import Equipment
from app.models.work_order import WorkOrder, WorkOrderStatus, SupervisorReviewStatus
from app.models.work_order_evidence import WorkOrderEvidence
from app.models.work_order_participants import work_order_participants
from app.models.worker_column import WorkerColumn
from app.models.sync_job import ExternalSyncJob, SyncJobStatus
from app.models.notification import Notification
from app.schemas.work_order import (
    WorkOrderCreate,
    HallazgoCreate,
    HallazgoReviewPayload,
    HallazgoUpdate,
    WorkOrderUpdate,
    WorkOrderResponse,
    WorkOrderListResponse,
    WorkOrderCounterResponse,
    WorkOrderEvidenceResponse,
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
from app.services.evidence_images import MAX_UPLOAD_BYTES, prepare_evidence_image

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/work-orders", tags=["work-orders"])

manager_roles = (UserRole.SUPERVISOR, UserRole.ADMIN)
supervisor_or_admin = require_roles(*manager_roles)

# The counter is informational and global for administrators. A short cache
# prevents several tabs/users from repeating the same aggregate queries while
# keeping the displayed value fresh after normal navigation.
_COUNTER_CACHE_TTL_SECONDS = 15.0
_counter_cache: tuple[float, object, WorkOrderCounterResponse] | None = None
_counter_cache_lock = asyncio.Lock()


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
    work_time_mode: Literal["RANGE", "MANUAL"] | None = None
    work_start_time: _time | None = None
    work_end_time: _time | None = None
    worked_duration_minutes: int | None = None


def _reported_work_minutes(payload: CompletePayload, wo: WorkOrder) -> int:
    """Validate and calculate the worker-declared duration.

    The app's start/completion timestamps are an audit trail only. They must
    never determine the hours written to the monthly register.
    """
    if payload.work_time_mode is None:
        if wo.work_time_mode and wo.worked_duration_minutes:
            return wo.worked_duration_minutes
        raise HTTPException(
            status_code=400,
            detail="Selecciona cómo registrar las horas trabajadas.",
        )

    if payload.work_time_mode == "RANGE":
        if payload.work_start_time is None or payload.work_end_time is None:
            raise HTTPException(
                status_code=400,
                detail="Indica la hora de inicio y la hora de término del trabajo.",
            )
        if payload.worked_duration_minutes is not None:
            raise HTTPException(
                status_code=400,
                detail="Usa solo un método para registrar las horas.",
            )
        start = payload.work_start_time.hour * 60 + payload.work_start_time.minute
        end = payload.work_end_time.hour * 60 + payload.work_end_time.minute
        if end <= start:
            raise HTTPException(
                status_code=400,
                detail="La hora de término debe ser posterior a la hora de inicio.",
            )
        return end - start

    if payload.work_time_mode != "MANUAL":
        raise HTTPException(
            status_code=400,
            detail="Selecciona cómo registrar las horas trabajadas.",
        )
    if payload.work_start_time is not None or payload.work_end_time is not None:
        raise HTTPException(
            status_code=400,
            detail="Usa solo un método para registrar las horas.",
        )
    if payload.worked_duration_minutes is None or payload.worked_duration_minutes <= 0:
        raise HTTPException(
            status_code=400,
            detail="Indica una duración manual mayor que cero.",
        )
    return payload.worked_duration_minutes


def _format_work_duration(minutes: int) -> str:
    """Format a worker-declared duration for the OT sheet and monthly register."""
    hours, remaining_minutes = divmod(max(0, int(minutes)), 60)
    parts = []
    if hours:
        parts.append(f"{hours} {'hora' if hours == 1 else 'horas'}")
    if remaining_minutes:
        parts.append(
            f"{remaining_minutes} {'minuto' if remaining_minutes == 1 else 'minutos'}"
        )
    return " ".join(parts) if parts else "0 minutos"


def _duration_from_work_order(wo: WorkOrder) -> int | None:
    """Calculate the saved worker duration from either supported input mode."""
    if wo.work_time_mode == "RANGE":
        if wo.work_start_time is None or wo.work_end_time is None:
            return None
        start = wo.work_start_time.hour * 60 + wo.work_start_time.minute
        end = wo.work_end_time.hour * 60 + wo.work_end_time.minute
        return end - start if end > start else None
    if wo.work_time_mode == "MANUAL" and wo.worked_duration_minutes:
        return wo.worked_duration_minutes if wo.worked_duration_minutes > 0 else None
    return None


class ReturnPayload(BaseModel):
    return_reason: str


class ApprovePayload(BaseModel):
    # Kept for backwards compatibility with clients that sent a text field.
    # The server never trusts it: approval always snapshots the authenticated
    # administrator's stored handwritten signature.
    approved_signature: str | None = None


class SupervisorReviewPayload(BaseModel):
    action: Literal["CLAIM", "APPROVE", "RETURN"]
    notes: str | None = None


class CancelPayload(BaseModel):
    cancellation_reason: str


class ReopenPayload(BaseModel):
    """Body for reopening a closed OT. Reason is required (recorded in AuditLog)."""
    reopen_reason: str


class DeleteWorkOrderPayload(BaseModel):
    """Require an exact OT number and reason for an irreversible app deletion."""
    confirm_ot_number: str
    reason: str


class ReassignPayload(BaseModel):
    """Body for reassigning an OT to another responsible/participants."""
    responsible_user_id: int | None = None
    participant_user_ids: list[int] | None = None
    plant_area: str | None = None
    area_id: int | None = None  # section catalog ID; section owns the equipment
    equipment_id: int | None = None


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


async def _next_hallazgo_folio(db: AsyncSession) -> str:
    """Generate a provisional folio without consuming the official OT sequence."""
    year = datetime.now().year
    prefix = f"HALL-{year}-"
    result = await db.execute(
        select(WorkOrder.hallazgo_folio)
        .where(WorkOrder.hallazgo_folio.like(f"{prefix}%"))
        .order_by(WorkOrder.hallazgo_folio.desc())
        .limit(1)
    )
    last = result.scalar_one_or_none()
    try:
        number = int(last.split("-")[-1]) + 1 if last else 1
    except (ValueError, AttributeError):
        number = 1
    return f"{prefix}{number:04d}"


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


def _display_area_name(wo: WorkOrder) -> str | None:
    """New records use plant_area; old records retain their original display."""
    return wo.plant_area or (wo.area.name if wo.area else None)


def _display_section_name(wo: WorkOrder) -> str | None:
    """New sections are catalog-backed and snapshotted in section_name."""
    if wo.plant_area and wo.area:
        return wo.area.name
    return wo.section_name


def _validate_plant_area(value: str | None) -> str:
    normalized = (value or "").strip().upper()
    if normalized not in WORK_ORDER_AREAS:
        raise HTTPException(
            status_code=400,
            detail=f"Selecciona un área válida: {', '.join(WORK_ORDER_AREAS)}",
        )
    return normalized


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
        "is_hallazgo_report": wo.is_hallazgo_report,
        "hallazgo_folio": wo.hallazgo_folio,
        "hallazgo_kind": wo.hallazgo_kind,
        "hallazgo_priority": wo.hallazgo_priority,
        "hallazgo_status": wo.hallazgo_status,
        "hallazgo_review_notes": wo.hallazgo_review_notes,
        "hallazgo_reviewed_at": wo.hallazgo_reviewed_at,
        "hallazgo_reviewed_by_user_id": wo.hallazgo_reviewed_by_user_id,
        "hallazgo_reviewed_by_name": (
            wo.hallazgo_reviewed_by.full_name if wo.hallazgo_reviewed_by else None
        ),
        "title": wo.title,
        "description": wo.description,
        "area_id": wo.area_id,
        "area_name": _display_area_name(wo),
        "plant_area": wo.plant_area,
        "equipment_id": wo.equipment_id,
        "equipment_name": wo.equipment.name if wo.equipment else None,
        "section_name": _display_section_name(wo),
        "maintenance_type": wo.maintenance_type,
        "loto_status": wo.loto_status,
        "loto_controls": wo.loto_controls if wo.loto_controls is not None else controls_from_legacy_status(wo.loto_status),
        "folio": wo.folio,
        "estimated_time": wo.estimated_time,
        "request_date": wo.request_date,
        "execution_date": wo.execution_date,
        "resources_required": wo.resources_required,
        "voucher_number": wo.voucher_number,
        "voucher_date": wo.voucher_date,
        "material_codes": wo.material_codes,
        "risks": wo.risks,
        "observations": wo.observations,
        "requested_by": wo.requested_by,
        "approved_by": wo.approved_by,
        "requested_signature": wo.requested_signature,
        "approved_signature": wo.approved_signature,
        "status": wo.status,
        "submitted_for_review": wo.submitted_for_review,
        "requires_supervisor_validation": wo.requires_supervisor_validation,
        "supervisor_review_status": wo.supervisor_review_status,
        "supervisor_validator_user_id": wo.supervisor_validator_user_id,
        "supervisor_validator_name": (
            wo.supervisor_validator.full_name if wo.supervisor_validator else None
        ),
        "supervisor_reviewed_at": wo.supervisor_reviewed_at,
        "supervisor_review_notes": wo.supervisor_review_notes,
        # ── Workflow fields ──
        "responsible_user_id": wo.responsible_user_id,
        "responsible_user_name": wo.responsible_user.full_name if wo.responsible_user else None,
        "participant_user_ids": participant_user_ids,
        "is_external_work": wo.is_external_work,
        "external_executor_name": wo.external_executor_name,
        "external_company": wo.external_company,
        "external_quote_number": wo.external_quote_number,
        "external_oc_number": wo.external_oc_number,
        "external_invoice_number": wo.external_invoice_number,
        "external_account_number": wo.external_account_number,
        "external_oc_amount": wo.external_oc_amount,
        "coordinator_user_id": wo.coordinator_user_id,
        "is_planned": wo.is_planned,
        "scheduled_date": wo.scheduled_date,
        "due_date": wo.due_date,
        "started_at": wo.started_at,
        "started_by_user_id": wo.started_by_user_id,
        "started_by_name": started_by_name,
        "completed_at": wo.completed_at,
        "completed_by_user_id": wo.completed_by_user_id,
        "completed_by_name": completed_by_name,
        "work_time_mode": wo.work_time_mode,
        "work_start_time": wo.work_start_time,
        "work_end_time": wo.work_end_time,
        "worked_duration_minutes": wo.worked_duration_minutes,
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
        "participant_names": (
            [] if wo.is_external_work else [
                n.strip() for n in (wo.participant_names or "").split(",") if n.strip()
            ]
        ),
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
        selectinload(WorkOrder.supervisor_validator),
        selectinload(WorkOrder.hallazgo_reviewed_by),
    )


def _list_query():
    """Load only relationships used by paginated list responses.

    Work-order detail and workflow endpoints continue using ``_base_query``.
    The list endpoints do not need participant or lifecycle-user collections,
    so explicitly disabling those select-in relationships avoids extra SQL
    queries for every page.
    """
    return select(WorkOrder).options(
        selectinload(WorkOrder.area),
        selectinload(WorkOrder.equipment),
        selectinload(WorkOrder.responsible_user),
        noload(WorkOrder.created_by),
        noload(WorkOrder.participants),
        noload(WorkOrder.started_by_user),
        noload(WorkOrder.completed_by_user),
        noload(WorkOrder.approved_by_user),
        noload(WorkOrder.supervisor_validator),
        noload(WorkOrder.hallazgo_reviewed_by),
    )


async def _monthly_worker_columns(
    db: AsyncSession, participant_user_ids: list[int]
) -> dict[int, str]:
    """Resolve stable user IDs to monthly-sheet logical column keys."""
    if not participant_user_ids:
        return {}
    result = await db.execute(
        select(WorkerColumn.user_id, WorkerColumn.column_key).where(
            WorkerColumn.user_id.in_(participant_user_ids)
        )
    )
    return {int(user_id): column_key for user_id, column_key in result.all()}


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
    participant_user_ids: list[int] | None = None
    try:
        participant_objects = list(wo.participants or [])
        participant_user_ids = [p.id for p in participant_objects]
        participants = [p.full_name for p in participant_objects]
    except Exception:
        participants = [
            n.strip() for n in (wo.participant_names or "").split(",") if n.strip()
        ]
    if wo.is_external_work and wo.external_executor_name:
        participants.append(wo.external_executor_name)
    participant_column_keys = await _monthly_worker_columns(
        db, participant_user_ids or []
    ) if participant_user_ids is not None else None

    # Resolve responsible name
    responsible_name = wo.responsible_user.full_name if wo.responsible_user else ""

    # Resolve (or lazily create) the annual register for the OT's execution year.
    # commit=False: this runs inside the caller's transaction; the register row is
    # flushed so UNIQUE-year races are still detected, but we don't commit here.
    # When no per-year register can be created (Google not configured), we fall
    # back to the legacy settings.GOOGLE_MONTHLY_SPREADSHEET_ID via spreadsheet_id=None.
    target_spreadsheet_id: str | None = None
    register = await ensure_monthly_register_for_year(
        db,
        exec_dt.year,
        user_id,
        commit=False,
        release_before_external=True,
    )
    # The register lookup may have opened a transaction. Do not retain its
    # connection during the following Google Sheets/Drive calls.
    await db.commit()
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
            await db.commit()
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
        # Release any connection opened by the register lookup before calling
        # Google Sheets.
        await db.commit()
        await asyncio.to_thread(
            drive_service.sync_to_monthly_sheet,
            wo.ot_number,
            exec_dt,
            area_name=_display_area_name(wo) or "",
            section_name=_display_section_name(wo) or "",
            equipment_name=wo.equipment.name if wo.equipment else "",
            description=wo.description or "",
            maintenance_type=wo.maintenance_type,
            participants=participants,
            participant_user_ids=participant_user_ids,
            participant_column_keys=participant_column_keys,
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
            await db.commit()
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

    plant_area = _validate_plant_area(payload.plant_area)
    if payload.equipment_id is None:
        raise HTTPException(status_code=400, detail="Selecciona un equipo para la OT")

    area_scope_error = _supervisor_area_error(current_user, payload.area_id)
    if area_scope_error and not payload.emit:
        raise HTTPException(status_code=403, detail=area_scope_error)

    # When emitting directly from the wizard, the admin must provide the same
    # required fields validated at /issue time.
    is_supervisor_submission = (
        current_user.role == UserRole.SUPERVISOR and payload.emit
    )
    is_supervisor = current_user.role == UserRole.SUPERVISOR

    if is_supervisor and payload.is_external_work:
        raise HTTPException(
            status_code=403,
            detail="Solo el administrador puede crear o convertir una OT en trabajo externo",
        )

    if payload.emit:
        errors = []
        if not payload.description or not payload.description.strip():
            errors.append("Descripción del trabajo")
        if not payload.is_external_work and not payload.responsible_user_id and not is_supervisor_submission:
            errors.append("Responsable principal")
        if (
            not payload.is_external_work
            and not payload.participant_user_ids
            and not payload.responsible_user_id
            and not is_supervisor_submission
        ):
            errors.append("Al menos un participante")
        if not is_supervisor_submission and not current_user.signature:
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
    is_external_work = payload.is_external_work
    participant_ids = (
        [] if is_supervisor or is_external_work else list(payload.participant_user_ids)
    )
    if (
        not is_supervisor
        and not is_external_work
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
    loto_controls = normalize_loto_controls(payload.loto_controls)
    if loto_controls is None:
        loto_controls = ["NOT_APPLICABLE"]
    loto_status = legacy_status_from_controls(loto_controls, payload.loto_status)

    wo = WorkOrder(
        ot_number=ot_number,
        title=payload.title,
        description=payload.description,
        area_id=payload.area_id,
        plant_area=plant_area,
        equipment_id=payload.equipment_id,
        # area_id points to the section catalog; snapshot its display name.
        section_name=area.name,
        maintenance_type=payload.maintenance_type,
        loto_status=loto_status,
        loto_controls=loto_controls,
        folio=payload.folio,
        estimated_time=payload.estimated_time,
        request_date=payload.request_date,
        execution_date=payload.execution_date,
        resources_required=payload.resources_required,
        voucher_number=payload.voucher_number,
        voucher_date=payload.voucher_date,
        material_codes=payload.material_codes,
        risks=payload.risks,
        observations=payload.observations,
        requested_by=requested_by,
        # Legacy field used by the template's "REALIZADO POR" block. It is
        # set only when the responsible worker completes the work.
        approved_by=None,
        # A WorkOrder keeps a stable signature URL; later profile changes do
        # not change the signature used when this OT was issued.
        # Supervisors only submit the request. The administrator signs when
        # accepting it; a supervisor signature is not required or stored.
        requested_signature=(
            None if is_supervisor_submission else (current_user.signature if payload.emit else None)
        ),
        participant_names=participant_names_str,
        status=initial_status,
        submitted_for_review=is_supervisor_submission,
        requires_supervisor_validation=is_supervisor,
        supervisor_review_status=SupervisorReviewStatus.NOT_REQUIRED.value,
        created_by_user_id=current_user.id,
        responsible_user_id=(
            None if is_supervisor or is_external_work else payload.responsible_user_id
        ),
        is_external_work=is_external_work,
        external_executor_name=(payload.external_executor_name if is_external_work else None),
        external_company=(payload.external_company if is_external_work else None),
        external_quote_number=(payload.external_quote_number if is_external_work else None),
        external_oc_number=(payload.external_oc_number if is_external_work else None),
        external_invoice_number=(payload.external_invoice_number if is_external_work else None),
        external_account_number=(payload.external_account_number if is_external_work else None),
        external_oc_amount=(payload.external_oc_amount if is_external_work else None),
        coordinator_user_id=(
            current_user.id
            if is_external_work and current_user.role == UserRole.ADMIN
            else None
        ),
        # All new OTs are planned. If no separate scheduled date is supplied,
        # use the request date so the KPI has a stable planning period.
        is_planned=True,
        scheduled_date=payload.scheduled_date or payload.request_date,
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
            "is_external_work": wo.is_external_work,
            "external_executor_name": wo.external_executor_name,
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
                await bg_db.commit()
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

        # All data needed by the job is loaded. Release the database
        # connection before any Google/network operation.
        await db.commit()

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
                    await db.commit()
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

            # This task reads from PostgreSQL and then calls Google. Release
            # the connection before the external operation begins.
            await bg_db.commit()

            individual_failed = False
            if populate_individual:
                try:
                    await bg_db.commit()
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
        loto_controls = wo.loto_controls
        description = wo.description
        estimated_time = wo.estimated_time
        execution_date = wo.execution_date
        resources_required = wo.resources_required
        risks = wo.risks
        observations = wo.observations
        folio = wo.folio
        voucher_number = wo.voucher_number
        voucher_date = wo.voucher_date
        material_codes = wo.material_codes
        external_company = wo.external_company
        external_quote_number = wo.external_quote_number
        external_oc_number = wo.external_oc_number
        external_invoice_number = wo.external_invoice_number
        external_account_number = wo.external_account_number
        external_oc_amount = wo.external_oc_amount
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
    uses_external_template = getattr(wo, "google_ot_template_kind", None) == "EXTERNAL"
    if getattr(wo, "is_external_work", False) and getattr(wo, "external_executor_name", None):
        participants.append(wo.external_executor_name)
    await asyncio.to_thread(
        drive_service.populate_ot_fields,
        wo.google_ot_file_id,
        ot_number=wo.ot_number,
        area_name=_display_area_name(wo) or "",
        section_name=_display_section_name(wo) or "",
        equipment_name=wo.equipment.name if wo.equipment else "",
        maintenance_type=wo.maintenance_type,
        loto_status=wo.loto_status,
        loto_controls=wo.loto_controls,
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
            voucher_date=(
                getattr(wo, "voucher_date", None).isoformat()
                if getattr(wo, "voucher_date", None)
                else None
            ),
            material_codes=getattr(wo, "material_codes", None),
        is_external_work=uses_external_template,
        external_company=getattr(wo, "external_company", None),
        external_quote_number=getattr(wo, "external_quote_number", None),
        external_oc_number=getattr(wo, "external_oc_number", None),
        external_invoice_number=getattr(wo, "external_invoice_number", None),
        external_account_number=getattr(wo, "external_account_number", None),
        external_oc_amount=getattr(wo, "external_oc_amount", None),
        requested_by=wo.requested_by,
        approved_by=wo.approved_by,
        requested_signature=wo.requested_signature,
        approved_signature=wo.approved_signature,
        status=wo.status,
    )


async def _sync_ot_and_monthly(db, wo, area, equipment, payload, user_id):
    """Sync OT to Google Drive (template + monthly) when emitting."""
    # The worker has already loaded the OT, area and equipment. Release that
    # read transaction before the first potentially slow Google call.
    await db.commit()
    execution_date = payload.execution_date or datetime.now().date()
    participants = []
    participant_user_ids: list[int] | None = None
    try:
        participant_objects = list(wo.participants or [])
        participant_user_ids = [p.id for p in participant_objects]
        participants = [p.full_name for p in participant_objects]
    except Exception:
        participants = payload.participant_names or []
    if wo.is_external_work and wo.external_executor_name:
        participants.append(wo.external_executor_name)
    participant_column_keys = await _monthly_worker_columns(
        db, participant_user_ids or []
    ) if participant_user_ids is not None else None

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
            template_kind = (
                "EXTERNAL"
                if wo.is_external_work and settings.GOOGLE_EXTERNAL_OT_TEMPLATE_FILE_ID
                else "REGULAR"
            )
            ot_result = await asyncio.to_thread(
                drive_service.create_ot_file,
                wo.ot_number,
                exec_dt,
                is_external_work=wo.is_external_work,
            )
            doc_id = ot_result["file_id"]
            wo.google_ot_file_id = ot_result["file_id"]
            wo.google_ot_url = ot_result["url"]
            wo.google_ot_template_kind = template_kind

            # Persist the Drive ID before populating Sheets or calling Apps
            # Script. Those later operations can fail independently. Keeping
            # this commit small makes every retry reuse the same Drive file.
            await db.commit()

        await asyncio.to_thread(
            drive_service.populate_ot_fields,
            doc_id,
            ot_number=wo.ot_number,
            area_name=wo.plant_area or area.name,
            section_name=wo.section_name or "",
            equipment_name=equipment.name if equipment else "",
            maintenance_type=payload.maintenance_type,
            loto_status=wo.loto_status,
            loto_controls=wo.loto_controls,
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
            voucher_date=payload.voucher_date.isoformat() if payload.voucher_date else None,
            material_codes=payload.material_codes,
            is_external_work=wo.google_ot_template_kind == "EXTERNAL",
            external_company=wo.external_company,
            external_quote_number=wo.external_quote_number,
            external_oc_number=wo.external_oc_number,
            external_invoice_number=wo.external_invoice_number,
            external_account_number=wo.external_account_number,
            external_oc_amount=wo.external_oc_amount,
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
                    area_name=wo.plant_area or area.name,
                    section_name=wo.section_name or "",
                    equipment_name=equipment.name if equipment else "",
                    description=payload.description or "",
                    maintenance_type=payload.maintenance_type,
                    participants=participants,
                    participant_user_ids=participant_user_ids,
                    participant_column_keys=participant_column_keys,
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
    search: str | None = Query(default=None, min_length=1, max_length=100),
    responsible: str | None = Query(default=None, min_length=1, max_length=100),
    overdue: bool = Query(default=False),
    created_by_me: bool = Query(default=False),
    pending_review: bool = Query(default=False),
    supervisor_validation_pending: bool = Query(default=False),
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    query = _list_query()

    if current_user.role not in manager_roles:
        query = query.where(WorkOrder.created_by_user_id == current_user.id)
    elif current_user.role == UserRole.SUPERVISOR:
        # Supervisors see and manage only their configured plant areas.
        if not current_user.area_ids:
            query = query.where(WorkOrder.id == -1)
        else:
            query = query.where(WorkOrder.area_id.in_(current_user.area_ids))

    if created_by_me:
        # Tracking view for supervisors: include submitted review drafts, but
        # exclude drafts that have not yet been sent to admin.
        query = query.where(
            WorkOrder.created_by_user_id == current_user.id,
            or_(
                WorkOrder.status != WorkOrderStatus.DRAFT.value,
                WorkOrder.submitted_for_review.is_(True),
            ),
        )
    elif not pending_review:
        # Hallazgos tienen su propio flujo y solo aparecen en la bandeja de
        # revisión o en la vista del usuario que los reportó.
        query = query.where(
            or_(
                WorkOrder.is_hallazgo_report.is_(False),
                WorkOrder.hallazgo_status == "CONVERTED",
            )
        )

    if pending_review:
        if current_user.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=403,
                detail="Solo el administrador puede consultar las OTs pendientes de revisión",
            )
        query = query.where(WorkOrder.submitted_for_review.is_(True))

    if supervisor_validation_pending:
        if current_user.role != UserRole.SUPERVISOR:
            raise HTTPException(
                status_code=403,
                detail="Solo los supervisores pueden consultar sus validaciones pendientes",
            )
        query = query.where(
            WorkOrder.requires_supervisor_validation.is_(True),
            WorkOrder.status == WorkOrderStatus.COMPLETED.value,
            WorkOrder.supervisor_review_status.in_(
                (SupervisorReviewStatus.PENDING.value, SupervisorReviewStatus.CLAIMED.value)
            ),
        )

    if search and search.strip():
        search_value = f"%{search.strip()}%"
        query = query.where(
            or_(
                WorkOrder.ot_number.ilike(search_value),
                WorkOrder.title.ilike(search_value),
            )
        )

    if responsible and responsible.strip():
        responsible_value = f"%{responsible.strip()}%"
        query = query.where(
            or_(
                WorkOrder.responsible_user.has(User.full_name.ilike(responsible_value)),
                WorkOrder.external_executor_name.ilike(responsible_value),
            )
        )

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
            area_name=_display_area_name(wo),
            plant_area=wo.plant_area,
            equipment_name=wo.equipment.name if wo.equipment else None,
            section_name=_display_section_name(wo),
            maintenance_type=wo.maintenance_type,
            loto_status=wo.loto_status,
            status=wo.status,
            execution_date=wo.execution_date,
            request_date=wo.request_date,
            ot_sheet_sync_status=wo.ot_sheet_sync_status,
            monthly_sheet_sync_status=wo.monthly_sheet_sync_status,
            created_at=wo.created_at,
            is_hallazgo_report=wo.is_hallazgo_report,
            hallazgo_folio=wo.hallazgo_folio,
            hallazgo_kind=wo.hallazgo_kind,
            hallazgo_priority=wo.hallazgo_priority,
            hallazgo_status=wo.hallazgo_status,
            submitted_for_review=wo.submitted_for_review,
            requires_supervisor_validation=wo.requires_supervisor_validation,
            supervisor_review_status=wo.supervisor_review_status,
            supervisor_validator_user_id=wo.supervisor_validator_user_id,
            responsible_user_id=wo.responsible_user_id,
            responsible_user_name=wo.responsible_user.full_name if wo.responsible_user else None,
            is_external_work=wo.is_external_work,
            external_executor_name=wo.external_executor_name,
            external_company=wo.external_company,
            coordinator_user_id=wo.coordinator_user_id,
            is_planned=wo.is_planned,
            scheduled_date=wo.scheduled_date,
            due_date=wo.due_date,
        )
        for wo in orders
    ]


# ───────────────────────────────────────────────────────────────────────────
# Provisional hallazgos — MUST be before /{wo_id}
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/hallazgos", response_model=WorkOrderResponse, status_code=status.HTTP_201_CREATED)
async def create_hallazgo(
    payload: HallazgoCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a worker report without consuming an official OT number."""
    if current_user.role != UserRole.WORKER:
        raise HTTPException(status_code=403, detail="Solo los trabajadores pueden crear hallazgos")
    area_scope_error = _supervisor_area_error(current_user, payload.area_id)
    if area_scope_error:
        raise HTTPException(status_code=403, detail=area_scope_error)

    area, equipment = await _validate_area_equipment(db, payload.area_id, payload.equipment_id)
    folio = await _next_hallazgo_folio(db)
    now = datetime.now(timezone.utc)
    participant_ids = list(dict.fromkeys([current_user.id, *payload.participant_user_ids]))
    names_result = await db.execute(
        select(User.id, User.full_name).where(User.id.in_(participant_ids))
    )
    names_map = {row[0]: row[1] for row in names_result.all()}
    participant_names = ", ".join(
        names_map[uid] for uid in participant_ids if uid in names_map
    )
    loto_controls = normalize_loto_controls(payload.loto_controls) or ["NOT_APPLICABLE"]

    wo = WorkOrder(
        ot_number=folio,
        is_hallazgo_report=True,
        hallazgo_folio=folio,
        hallazgo_kind=payload.report_kind,
        hallazgo_priority=payload.priority,
        hallazgo_status="PENDING_REVIEW",
        title=payload.title,
        description=payload.description,
        area_id=payload.area_id,
        plant_area=payload.plant_area,
        equipment_id=payload.equipment_id,
        section_name=area.name,
        maintenance_type=payload.maintenance_type,
        loto_status=legacy_status_from_controls(loto_controls, "NOT_APPLICABLE"),
        loto_controls=loto_controls,
        request_date=payload.report_date,
        execution_date=payload.report_date,
        scheduled_date=payload.report_date,
        risks=payload.risks,
        observations=payload.observations,
        resources_required=payload.resources_required,
        requested_by=current_user.full_name,
        participant_names=participant_names,
        # Cuando el trabajador informa un trabajo ya realizado, queda como
        # responsable de ejecución. En un hallazgo que requiere atención, el
        # administrador lo asignará al aceptar y convertirlo en OT.
        responsible_user_id=(current_user.id if payload.report_kind == "COMPLETED" else None),
        status=WorkOrderStatus.DRAFT.value,
        submitted_for_review=True,
        # Solo una OT oficial aceptada participa en el KPI planificado.
        is_planned=False,
        created_by_user_id=current_user.id,
        work_time_mode=payload.work_time_mode,
        work_start_time=payload.work_start_time,
        work_end_time=payload.work_end_time,
        worked_duration_minutes=payload.worked_duration_minutes,
        folio=payload.folio.strip() if payload.folio else None,
        voucher_number=payload.voucher_number.strip() if payload.voucher_number else None,
        voucher_date=payload.voucher_date,
        material_codes=payload.material_codes.strip() if payload.material_codes else None,
        completed_by_user_id=(current_user.id if payload.report_kind == "COMPLETED" else None),
        completed_at=(now if payload.report_kind == "COMPLETED" else None),
    )
    db.add(wo)
    await db.flush()
    await db.execute(
        work_order_participants.insert(),
        [
            {"work_order_id": wo.id, "user_id": user_id}
            for user_id in participant_ids
        ],
    )
    await create_audit_log(
        db,
        user_id=current_user.id,
        action="CREATE_HALLAZGO",
        entity_type="WorkOrder",
        entity_id=wo.id,
        new_data={"folio": folio, "kind": payload.report_kind, "priority": payload.priority},
    )
    await notification_service.notify_work_order_submitted_to_admin(
        db, wo, submitted_by=current_user.full_name, link=f"/ordenes/{wo.id}"
    )
    await db.commit()

    result = await db.execute(_base_query().where(WorkOrder.id == wo.id))
    return _work_order_to_response(result.scalar_one())


@router.get("/hallazgos", response_model=list[WorkOrderListResponse])
async def list_hallazgos(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List provisional reports for the reporter or administrative reviewers."""
    if current_user.role not in (UserRole.ADMIN, UserRole.WORKER):
        raise HTTPException(status_code=403, detail="Los supervisores no tienen acceso al módulo de hallazgos")
    query = _list_query().where(WorkOrder.is_hallazgo_report.is_(True))
    if current_user.role == UserRole.ADMIN:
        pass
    else:
        query = query.where(WorkOrder.created_by_user_id == current_user.id)
    result = await db.execute(query.order_by(WorkOrder.created_at.desc()))
    orders = result.scalars().all()
    return [
        WorkOrderListResponse(
            id=wo.id, ot_number=wo.ot_number, title=wo.title,
            area_name=_display_area_name(wo), plant_area=wo.plant_area,
            equipment_name=wo.equipment.name if wo.equipment else None,
            section_name=_display_section_name(wo), maintenance_type=wo.maintenance_type,
            loto_status=wo.loto_status, status=wo.status,
            submitted_for_review=wo.submitted_for_review,
            requires_supervisor_validation=wo.requires_supervisor_validation,
            supervisor_review_status=wo.supervisor_review_status,
            supervisor_validator_user_id=wo.supervisor_validator_user_id,
            execution_date=wo.execution_date, request_date=wo.request_date,
            ot_sheet_sync_status=wo.ot_sheet_sync_status,
            monthly_sheet_sync_status=wo.monthly_sheet_sync_status,
            created_at=wo.created_at, is_hallazgo_report=True,
            hallazgo_folio=wo.hallazgo_folio, hallazgo_kind=wo.hallazgo_kind,
            hallazgo_priority=wo.hallazgo_priority, hallazgo_status=wo.hallazgo_status,
            responsible_user_id=wo.responsible_user_id,
            responsible_user_name=wo.responsible_user.full_name if wo.responsible_user else None,
            is_planned=wo.is_planned, scheduled_date=wo.scheduled_date, due_date=wo.due_date,
        )
        for wo in orders
    ]


@router.patch("/{wo_id}/hallazgo", response_model=WorkOrderResponse)
async def update_hallazgo(
    wo_id: int,
    payload: HallazgoUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Allow the reporter to correct a returned report and resubmit it."""
    result = await db.execute(_base_query().where(WorkOrder.id == wo_id).with_for_update())
    wo = result.scalar_one_or_none()
    if wo is None or not wo.is_hallazgo_report:
        raise HTTPException(status_code=404, detail="Hallazgo no encontrado")
    if current_user.role not in (UserRole.ADMIN, UserRole.WORKER):
        raise HTTPException(status_code=403, detail="Los supervisores no tienen acceso al módulo de hallazgos")
    if current_user.role != UserRole.ADMIN and wo.created_by_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Solo el reportante o el administrador puede editar este hallazgo")
    if wo.hallazgo_status not in ("PENDING_REVIEW", "RETURNED"):
        raise HTTPException(status_code=400, detail="Este hallazgo ya fue cerrado")
    if current_user.role != UserRole.ADMIN and wo.hallazgo_status != "RETURNED":
        raise HTTPException(status_code=400, detail="Solo puedes editar un hallazgo devuelto")

    for field in ("title", "description", "hallazgo_priority", "work_time_mode", "work_start_time", "work_end_time", "worked_duration_minutes", "folio", "voucher_number", "material_codes", "risks", "observations"):
        value = getattr(payload, field.removeprefix("hallazgo_") if field == "hallazgo_priority" else field, None)
        if value is not None:
            if field in ("folio", "voucher_number", "material_codes"):
                value = value.strip() or None
            setattr(wo, field, value)
    if payload.report_kind is not None:
        wo.hallazgo_kind = payload.report_kind
    if payload.resubmit:
        if not wo.title.strip() or not (wo.description or "").strip():
            raise HTTPException(status_code=400, detail="Completa el título y la descripción antes de reenviar")
        if wo.hallazgo_kind == "COMPLETED":
            if wo.work_time_mode == "RANGE" and (wo.work_start_time is None or wo.work_end_time is None or wo.work_end_time <= wo.work_start_time):
                raise HTTPException(status_code=400, detail="Revisa las horas de inicio y término")
            if wo.work_time_mode == "MANUAL" and (not wo.worked_duration_minutes or wo.worked_duration_minutes <= 0):
                raise HTTPException(status_code=400, detail="Revisa la duración manual")
        wo.hallazgo_status = "PENDING_REVIEW"
        wo.submitted_for_review = True
        wo.hallazgo_review_notes = None
        await notification_service.notify_work_order_submitted_to_admin(db, wo, submitted_by=current_user.full_name, link=f"/ordenes/{wo.id}")
    await create_audit_log(db, user_id=current_user.id, action="UPDATE_HALLAZGO", entity_type="WorkOrder", entity_id=wo.id, new_data={"resubmit": payload.resubmit})
    await db.commit()
    # The review updates foreign keys and the participant association table.
    # Refresh eagerly-loaded relationships so the response immediately shows
    # the selected equipment and responsible/participant names.
    refreshed = await db.execute(
        _base_query()
        .where(WorkOrder.id == wo.id)
        .execution_options(populate_existing=True)
    )
    return _work_order_to_response(refreshed.scalar_one())


@router.post("/{wo_id}/hallazgo-review", response_model=WorkOrderResponse)
async def review_hallazgo(
    wo_id: int,
    payload: HallazgoReviewPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
):
    """Accept, return or reject a provisional report from the admin queue."""
    result = await db.execute(_base_query().where(WorkOrder.id == wo_id).with_for_update())
    wo = result.scalar_one_or_none()
    if wo is None or not wo.is_hallazgo_report:
        raise HTTPException(status_code=404, detail="Hallazgo no encontrado")
    if wo.hallazgo_status not in ("PENDING_REVIEW", "RETURNED") or not wo.submitted_for_review:
        raise HTTPException(status_code=400, detail="Este hallazgo ya no está pendiente de revisión")

    now = datetime.now(timezone.utc)
    wo.hallazgo_review_notes = (payload.notes or "").strip() or None
    wo.hallazgo_reviewed_at = now
    wo.hallazgo_reviewed_by_user_id = current_user.id

    if payload.action == "RETURN":
        wo.hallazgo_status = "RETURNED"
        wo.submitted_for_review = False
        await create_audit_log(db, user_id=current_user.id, action="RETURN_HALLAZGO", entity_type="WorkOrder", entity_id=wo.id, new_data={"notes": wo.hallazgo_review_notes})
    elif payload.action == "REJECT":
        wo.hallazgo_status = "REJECTED"
        wo.submitted_for_review = False
        await create_audit_log(db, user_id=current_user.id, action="REJECT_HALLAZGO", entity_type="WorkOrder", entity_id=wo.id, new_data={"notes": wo.hallazgo_review_notes})
    else:
        if not current_user.signature:
            raise HTTPException(status_code=400, detail="El administrador debe tener una firma configurada para aceptar el hallazgo")
        if payload.maintenance_type:
            maintenance_type = payload.maintenance_type.upper().strip()
            if maintenance_type not in {"PREVENTIVE", "CORRECTIVE", "PREDICTIVE", "PROYECTO", "MONTAJE", "URGENTE"}:
                raise HTTPException(status_code=400, detail="Tipo de mantenimiento inválido")
            wo.maintenance_type = maintenance_type
        if payload.loto_controls is not None:
            controls = normalize_loto_controls(payload.loto_controls) or ["NOT_APPLICABLE"]
            wo.loto_controls = controls
            wo.loto_status = legacy_status_from_controls(controls, wo.loto_status)
        if payload.resources_required is not None:
            wo.resources_required = payload.resources_required.strip() or None
        if payload.folio is not None:
            wo.folio = payload.folio.strip() or None
        if payload.voucher_number is not None:
            wo.voucher_number = payload.voucher_number.strip() or None
        if "voucher_date" in payload.model_fields_set:
            wo.voucher_date = payload.voucher_date
        if "material_codes" in payload.model_fields_set:
            wo.material_codes = payload.material_codes.strip() if payload.material_codes else None
        if "equipment_id" in payload.model_fields_set:
            _, equipment = await _validate_area_equipment(
                db, wo.area_id, payload.equipment_id
            )
            wo.equipment_id = equipment.id if equipment else None
        if payload.scheduled_date is not None:
            wo.scheduled_date = payload.scheduled_date
        if payload.due_date is not None:
            wo.due_date = payload.due_date
        if payload.estimated_time is not None:
            wo.estimated_time = payload.estimated_time.strip() or None
        elif wo.hallazgo_kind == "COMPLETED":
            # A completed hallazgo must carry its declared duration to the
            # individual OT in Drive and to the monthly register. For RANGE,
            # calculate the minutes before formatting the value used by both
            # integrations; for MANUAL, keep the already stored total.
            declared_minutes = _duration_from_work_order(wo)
            if declared_minutes:
                wo.worked_duration_minutes = declared_minutes
                wo.estimated_time = _format_work_duration(declared_minutes)
        if wo.hallazgo_kind == "REQUIRES_ATTENTION":
            if not payload.responsible_user_id:
                raise HTTPException(status_code=400, detail="Asigna un trabajador para convertir este hallazgo en OT")
            responsible = await db.get(User, payload.responsible_user_id)
            if responsible is None or responsible.role != UserRole.WORKER or not responsible.is_active:
                raise HTTPException(status_code=400, detail="El responsable debe ser un trabajador activo")
            wo.responsible_user_id = responsible.id
            participant_ids = list(dict.fromkeys([responsible.id, *payload.participant_user_ids]))
            await db.execute(delete(work_order_participants).where(work_order_participants.c.work_order_id == wo.id))
            names_result = await db.execute(select(User.id, User.full_name).where(User.id.in_(participant_ids)))
            names_map = {row[0]: row[1] for row in names_result.all()}
            wo.participant_names = ", ".join(names_map[uid] for uid in participant_ids if uid in names_map)
            for uid in participant_ids:
                await db.execute(work_order_participants.insert().values(work_order_id=wo.id, user_id=uid))
            wo.status = WorkOrderStatus.PENDING.value
        else:
            wo.status = WorkOrderStatus.APPROVED.value
            wo.completed_by_user_id = wo.completed_by_user_id or wo.created_by_user_id
            wo.completed_at = wo.completed_at or now
            wo.approved_at = now
            wo.approved_by_user_id = current_user.id
            wo.approved_by = current_user.full_name
            wo.approved_signature = current_user.signature
        wo.ot_number = await _next_ot_number(db)
        wo.hallazgo_status = "CONVERTED"
        wo.is_planned = True
        wo.submitted_for_review = False
        wo.requested_signature = current_user.signature
        wo.ot_sheet_sync_status = "PENDING"
        wo.monthly_sheet_sync_status = "PENDING"
        await enqueue_external_sync(db, wo.id, job_type="FULL_CREATE", actor_user_id=current_user.id)
        await create_audit_log(db, user_id=current_user.id, action="CONVERT_HALLAZGO_TO_OT", entity_type="WorkOrder", entity_id=wo.id, new_data={"ot_number": wo.ot_number, "kind": wo.hallazgo_kind})
        if wo.status == WorkOrderStatus.PENDING.value:
            await notification_service.notify_work_order_assigned(db, wo, link=f"/mis-ordenes/{wo.id}", participant_user_ids=[wo.responsible_user_id] if wo.responsible_user_id else [])

    await db.commit()
    refreshed = await db.execute(
        _base_query()
        .where(WorkOrder.id == wo.id)
        .execution_options(populate_existing=True)
    )
    return _work_order_to_response(refreshed.scalar_one())


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
    """OTs where the current user is responsible, coordinator, or participant."""
    # Subquery for participant IDs
    participant_wo_ids = select(work_order_participants.c.work_order_id).where(
        work_order_participants.c.user_id == current_user.id
    )

    query = _list_query().where(
        (WorkOrder.responsible_user_id == current_user.id)
        | (WorkOrder.coordinator_user_id == current_user.id)
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
            area_name=_display_area_name(wo),
            plant_area=wo.plant_area,
            equipment_name=wo.equipment.name if wo.equipment else None,
            section_name=_display_section_name(wo),
            maintenance_type=wo.maintenance_type,
            loto_status=wo.loto_status,
            status=wo.status,
            execution_date=wo.execution_date,
            request_date=wo.request_date,
            ot_sheet_sync_status=wo.ot_sheet_sync_status,
            monthly_sheet_sync_status=wo.monthly_sheet_sync_status,
            created_at=wo.created_at,
            is_hallazgo_report=wo.is_hallazgo_report,
            hallazgo_folio=wo.hallazgo_folio,
            hallazgo_kind=wo.hallazgo_kind,
            hallazgo_priority=wo.hallazgo_priority,
            hallazgo_status=wo.hallazgo_status,
            submitted_for_review=wo.submitted_for_review,
            requires_supervisor_validation=wo.requires_supervisor_validation,
            supervisor_review_status=wo.supervisor_review_status,
            supervisor_validator_user_id=wo.supervisor_validator_user_id,
            responsible_user_id=wo.responsible_user_id,
            responsible_user_name=wo.responsible_user.full_name if wo.responsible_user else None,
            is_external_work=wo.is_external_work,
            external_executor_name=wo.external_executor_name,
            external_company=wo.external_company,
            coordinator_user_id=wo.coordinator_user_id,
            is_planned=wo.is_planned,
            scheduled_date=wo.scheduled_date,
            due_date=wo.due_date,
        )
        for wo in orders
    ]


# ───────────────────────────────────────────────────────────────────────────
# Counter / next OT number (admin only)
# ───────────────────────────────────────────────────────────────────────────
async def _build_work_order_counter(
    view: Literal["ALL", "CREATED_BY_ME", "PENDING_REVIEW", "SUPERVISOR_VALIDATION"],
    current_user: User,
    db: AsyncSession,
) -> WorkOrderCounterResponse:
    """Cuantifica las OTs (totales por año y por mes del año actual) y el próximo
    N° OT que se asignará. Solo ADMIN — la planificación los necesita."""
    global _counter_cache
    scope_key = (
        id(db.bind),
        current_user.id,
        current_user.role.value,
        tuple(sorted(current_user.area_ids or [])),
        view,
    )
    cached = _counter_cache
    if (
        cached is not None
        and cached[1] == scope_key
        and time.monotonic() - cached[0] < _COUNTER_CACHE_TTL_SECONDS
    ):
        return cached[2]

    # Serialize cache misses so a burst of administrators does not stampede
    # PostgreSQL with identical aggregate queries.
    async with _counter_cache_lock:
        cached = _counter_cache
        if (
            cached is not None
            and cached[1] == scope_key
            and time.monotonic() - cached[0] < _COUNTER_CACHE_TTL_SECONDS
        ):
            return cached[2]

        now = datetime.now(timezone.utc)
        current_year = now.year

        # Use the same visibility rules as the paginated list endpoint so the
        # tab counters represent the complete result set, not only one page.
        scope_conditions = []
        if current_user.role == UserRole.SUPERVISOR:
            if not current_user.area_ids:
                scope_conditions.append(WorkOrder.id == -1)
            else:
                scope_conditions.append(WorkOrder.area_id.in_(current_user.area_ids))
        elif current_user.role not in manager_roles:
            scope_conditions.append(WorkOrder.created_by_user_id == current_user.id)

        if view == "CREATED_BY_ME":
            scope_conditions.extend(
                [
                    WorkOrder.created_by_user_id == current_user.id,
                    or_(
                        WorkOrder.status != WorkOrderStatus.DRAFT.value,
                        WorkOrder.submitted_for_review.is_(True),
                    ),
                ]
            )
        elif view == "PENDING_REVIEW":
            if current_user.role != UserRole.ADMIN:
                raise HTTPException(status_code=403, detail="Solo el administrador puede consultar esta vista")
            scope_conditions.append(WorkOrder.submitted_for_review.is_(True))
        elif view == "SUPERVISOR_VALIDATION":
            if current_user.role != UserRole.SUPERVISOR:
                raise HTTPException(status_code=403, detail="Solo los supervisores pueden consultar esta vista")
            scope_conditions.extend(
                [
                    WorkOrder.requires_supervisor_validation.is_(True),
                    WorkOrder.status == WorkOrderStatus.COMPLETED.value,
                    WorkOrder.supervisor_review_status.in_(
                        (SupervisorReviewStatus.PENDING.value, SupervisorReviewStatus.CLAIMED.value)
                    ),
                ]
            )

        if view == "ALL":
            scope_conditions.append(
                or_(
                    WorkOrder.is_hallazgo_report.is_(False),
                    WorkOrder.hallazgo_status == "CONVERTED",
                )
            )

        # One grouped query provides yearly and current-year monthly totals.
        date_rows = await db.execute(
            select(
                func.extract("year", WorkOrder.execution_date).label("year"),
                func.extract("month", WorkOrder.execution_date).label("month"),
                func.count().label("total"),
            )
            .where(WorkOrder.execution_date.isnot(None), *scope_conditions)
            .group_by("year", "month")
            .order_by("year", "month")
        )
        per_year: dict[int, int] = {}
        per_month: dict[int, int] = {}
        for row in date_rows.all():
            if not row.year:
                continue
            year = int(row.year)
            total = int(row.total)
            per_year[year] = per_year.get(year, 0) + total
            if year == current_year and row.month:
                per_month[int(row.month) - 1] = total

        status_rows = await db.execute(
            select(WorkOrder.status, func.count(WorkOrder.id))
            .where(*scope_conditions)
            .group_by(WorkOrder.status)
        )
        status_counts = {str(status): int(total) for status, total in status_rows.all()}

        total_all_result = await db.execute(
            select(func.count(WorkOrder.id)).select_from(WorkOrder).where(*scope_conditions)
        )
        total_all = int(total_all_result.scalar_one() or 0)
        overdue_result = await db.execute(
            select(func.count(WorkOrder.id))
            .where(
                *scope_conditions,
                WorkOrder.due_date.isnot(None),
                WorkOrder.due_date < now.date(),
                WorkOrder.status.in_((WorkOrderStatus.PENDING.value, WorkOrderStatus.IN_PROGRESS.value)),
            )
        )
        overdue_count = int(overdue_result.scalar_one() or 0)
        next_ot = await _next_ot_number(db) if current_user.role == UserRole.ADMIN else ""

        response = WorkOrderCounterResponse(
            current_year=current_year,
            total_all=total_all,
            per_year=per_year,
            per_month=per_month,
            next_ot_number=next_ot,
            status_counts=status_counts,
            overdue_count=overdue_count,
        )
        _counter_cache = (time.monotonic(), scope_key, response)
        return response


@router.get("/counter", response_model=WorkOrderCounterResponse)
async def get_work_order_counter(
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Administrative counter used by the planning panel."""
    return await _build_work_order_counter("ALL", current_user, db)


@router.get("/status-counts", response_model=WorkOrderCounterResponse)
async def get_work_order_status_counts(
    view: Literal["ALL", "CREATED_BY_ME", "PENDING_REVIEW", "SUPERVISOR_VALIDATION"] = Query(default="ALL"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Complete status totals for the paginated order tabs."""
    return await _build_work_order_counter(view, current_user, db)


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


@router.get("/{wo_id}/evidence", response_model=list[WorkOrderEvidenceResponse])
async def list_work_order_evidence(
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

    evidence_result = await db.execute(
        select(WorkOrderEvidence)
        .where(WorkOrderEvidence.work_order_id == wo_id)
        .order_by(WorkOrderEvidence.uploaded_at, WorkOrderEvidence.id)
    )
    return list(evidence_result.scalars().all())


@router.post(
    "/{wo_id}/evidence",
    response_model=WorkOrderEvidenceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_work_order_evidence(
    wo_id: int,
    file: UploadFile = File(...),
    stage: Literal["ISSUE", "WORK"] = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        _base_query().where(WorkOrder.id == wo_id).with_for_update()
    )
    wo = result.scalar_one_or_none()
    if wo is None:
        raise HTTPException(status_code=404, detail="Orden de trabajo no encontrada")
    if not perms.can_view(wo, current_user):
        raise HTTPException(status_code=403, detail="No tiene permiso para ver esta OT")

    if stage == "ISSUE":
        can_reporter_attach = (
            wo.is_hallazgo_report
            and wo.created_by_user_id == current_user.id
            and wo.hallazgo_status in ("PENDING_REVIEW", "RETURNED")
        )
        if not can_reporter_attach and (
            current_user.role not in manager_roles or not perms.can_issue(wo, current_user)
        ):
            raise HTTPException(status_code=403, detail="No tiene permiso para adjuntar evidencia de emisión")
        if wo.status not in (WorkOrderStatus.DRAFT.value, WorkOrderStatus.PENDING.value):
            raise HTTPException(status_code=400, detail="La evidencia de emisión se adjunta antes de iniciar el trabajo")
    else:
        if current_user.role not in (UserRole.ADMIN, UserRole.SUPERVISOR, UserRole.WORKER):
            raise HTTPException(status_code=403, detail="No tiene permiso para adjuntar evidencia del trabajo")
        if current_user.role == UserRole.WORKER and not perms.can_complete(wo, current_user):
            raise HTTPException(status_code=403, detail="Solo el trabajador responsable puede adjuntar evidencia del trabajo")
        if current_user.role == UserRole.SUPERVISOR and not perms.can_issue(wo, current_user):
            raise HTTPException(status_code=403, detail="No tiene permiso para adjuntar evidencia en esta área")
        if wo.status not in (WorkOrderStatus.PENDING.value, WorkOrderStatus.IN_PROGRESS.value):
            raise HTTPException(status_code=400, detail="La evidencia del trabajo se adjunta mientras la OT está pendiente o en proceso")

    file_bytes = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        image_bytes, mime_type = prepare_evidence_image(file_bytes, file.content_type)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    count_result = await db.execute(
        select(func.count(WorkOrderEvidence.id)).where(
            WorkOrderEvidence.work_order_id == wo_id,
            WorkOrderEvidence.uploaded_by_user_id == current_user.id,
        )
    )
    if int(count_result.scalar_one() or 0) >= 2:
        raise HTTPException(status_code=409, detail="Ya subiste el máximo de 2 fotos para esta OT")

    try:
        drive_file_id = await run_in_threadpool(
            drive_service.upload_ot_evidence,
            wo.ot_number,
            _exec_datetime(wo),
            wo.google_ot_file_id,
            image_bytes,
            mime_type,
            stage,
        )
    except Exception as exc:  # noqa: BLE001 - Google API errors vary by transport.
        logger.exception("No se pudo subir evidencia de %s a Google Drive", wo.ot_number)
        raise HTTPException(status_code=502, detail="No se pudo guardar la foto en Google Drive") from exc

    original_name = (file.filename or "evidencia.jpg").replace("\\", "/").split("/")[-1]
    evidence = WorkOrderEvidence(
        work_order_id=wo_id,
        drive_file_id=drive_file_id,
        filename=original_name[:255] or "evidencia.jpg",
        mime_type=mime_type,
        stage=stage,
        uploaded_by_user_id=current_user.id,
        uploaded_by_name=current_user.full_name,
    )
    db.add(evidence)
    try:
        await db.flush()
        await db.commit()
    except Exception as exc:
        await db.rollback()
        try:
            await run_in_threadpool(drive_service.trash_ot_file, drive_file_id)
        except Exception:
            logger.exception("No se pudo limpiar foto huérfana de Drive %s", drive_file_id)
        raise HTTPException(status_code=500, detail="No se pudo registrar la foto en la OT") from exc

    return evidence


@router.delete("/{wo_id}/evidence/{evidence_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_work_order_evidence(
    wo_id: int,
    evidence_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove an evidence photo from Drive and its metadata from the OT.

    The uploader may remove their own photo while the corresponding stage is
    still editable. Administrators may correct any photo until the OT is
    approved or cancelled. The Drive file is trashed before deleting metadata
    so a database failure never leaves a visible orphan in the OT folder.
    """
    result = await db.execute(
        _base_query().where(WorkOrder.id == wo_id).with_for_update()
    )
    wo = result.scalar_one_or_none()
    if wo is None:
        raise HTTPException(status_code=404, detail="Orden de trabajo no encontrada")
    if not perms.can_view(wo, current_user):
        raise HTTPException(status_code=403, detail="No tiene permiso para ver esta OT")

    evidence = await db.scalar(
        select(WorkOrderEvidence)
        .where(
            WorkOrderEvidence.id == evidence_id,
            WorkOrderEvidence.work_order_id == wo_id,
        )
        .with_for_update()
    )
    if evidence is None:
        raise HTTPException(status_code=404, detail="Foto de evidencia no encontrada")

    closed_statuses = {
        WorkOrderStatus.APPROVED.value,
        WorkOrderStatus.CANCELLED.value,
    }
    if wo.status in closed_statuses:
        raise HTTPException(
            status_code=400,
            detail="No se pueden modificar fotos de una OT aprobada o cancelada",
        )

    is_admin = current_user.role == UserRole.ADMIN
    if not is_admin:
        if evidence.uploaded_by_user_id != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="Solo puedes eliminar tus propias fotos",
            )

        if evidence.stage == "ISSUE":
            allowed = (
                (
                    wo.is_hallazgo_report
                    and evidence.uploaded_by_user_id == current_user.id
                    and wo.hallazgo_status in ("PENDING_REVIEW", "RETURNED")
                )
                or (
                    current_user.role in manager_roles
                    and perms.can_issue(wo, current_user)
                )
                and wo.status in (
                    WorkOrderStatus.DRAFT.value,
                    WorkOrderStatus.PENDING.value,
                )
            )
        else:
            allowed = (
                wo.status in (
                    WorkOrderStatus.PENDING.value,
                    WorkOrderStatus.IN_PROGRESS.value,
                )
                and (
                    (current_user.role == UserRole.WORKER
                     and perms.can_complete(wo, current_user))
                    or (current_user.role == UserRole.SUPERVISOR
                        and perms.can_issue(wo, current_user))
                )
            )
        if not allowed:
            raise HTTPException(
                status_code=403,
                detail="La foto ya no se puede modificar en esta etapa de la OT",
            )

    try:
        await run_in_threadpool(drive_service.trash_ot_file, evidence.drive_file_id)
    except Exception as exc:  # noqa: BLE001 - Google API errors vary by transport.
        logger.exception("No se pudo eliminar evidencia %s desde Drive", evidence.id)
        raise HTTPException(
            status_code=502,
            detail="No se pudo eliminar la foto de Google Drive",
        ) from exc

    deleted_data = {
        "filename": evidence.filename,
        "stage": evidence.stage,
        "uploaded_by_user_id": evidence.uploaded_by_user_id,
        "drive_file_id": evidence.drive_file_id,
    }
    await db.delete(evidence)
    await create_audit_log(
        db,
        user_id=current_user.id,
        action="DELETE_WORK_ORDER_EVIDENCE",
        entity_type="WorkOrderEvidence",
        entity_id=evidence_id,
        previous_data=deleted_data,
        new_data={"work_order_id": wo_id, "ot_number": wo.ot_number},
    )
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail="La foto fue retirada de Drive, pero no se pudo actualizar la OT",
        ) from exc

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{wo_id}/evidence/{evidence_id}/content")
async def get_work_order_evidence_content(
    wo_id: int,
    evidence_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(_base_query().where(WorkOrder.id == wo_id))
    wo = result.scalar_one_or_none()
    if wo is None:
        raise HTTPException(status_code=404, detail="Orden de trabajo no encontrada")
    if not perms.can_view(wo, current_user):
        raise HTTPException(status_code=403, detail="No tiene permiso para ver esta OT")

    evidence = await db.scalar(
        select(WorkOrderEvidence).where(
            WorkOrderEvidence.id == evidence_id,
            WorkOrderEvidence.work_order_id == wo_id,
        )
    )
    if evidence is None:
        raise HTTPException(status_code=404, detail="Foto de evidencia no encontrada")
    try:
        contents = await run_in_threadpool(
            drive_service.download_ot_evidence, evidence.drive_file_id
        )
    except Exception as exc:  # noqa: BLE001 - Google API errors vary by transport.
        logger.exception("No se pudo leer evidencia %s desde Drive", evidence.id)
        raise HTTPException(status_code=502, detail="No se pudo cargar la foto desde Google Drive") from exc
    return Response(
        contents,
        media_type=evidence.mime_type,
        headers={"Cache-Control": "private, max-age=300"},
    )


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

    next_external_mode = (
        payload.is_external_work
        if "is_external_work" in payload.model_fields_set
        else wo.is_external_work
    )
    next_external_name = (
        payload.external_executor_name
        if "external_executor_name" in payload.model_fields_set
        else wo.external_executor_name
    )
    if current_user.role == UserRole.SUPERVISOR and next_external_mode:
        raise HTTPException(
            status_code=403,
            detail="Solo el administrador puede crear o convertir una OT en trabajo externo",
        )
    if next_external_mode and not next_external_name:
        raise HTTPException(
            status_code=400,
            detail="Indica el nombre de la persona externa que realizará el trabajo",
        )
    if next_external_mode and (
        payload.responsible_user_id is not None
        or (payload.participant_user_ids is not None and payload.participant_user_ids)
    ):
        raise HTTPException(
            status_code=400,
            detail="Una OT externa no puede asignar trabajadores internos como ejecutores",
        )
    if "is_external_work" in payload.model_fields_set:
        wo.is_external_work = bool(payload.is_external_work)
        if wo.is_external_work:
            wo.responsible_user_id = None
            await db.execute(
                work_order_participants.delete().where(
                    work_order_participants.c.work_order_id == wo.id
                )
            )
            wo.coordinator_user_id = (
                current_user.id if current_user.role == UserRole.ADMIN else None
            )
        else:
            wo.external_executor_name = None
            wo.external_company = None
            wo.external_quote_number = None
            wo.external_oc_number = None
            wo.external_invoice_number = None
            wo.external_account_number = None
            wo.external_oc_amount = None
            wo.coordinator_user_id = None
    if "external_executor_name" in payload.model_fields_set:
        wo.external_executor_name = payload.external_executor_name
    if "external_company" in payload.model_fields_set:
        wo.external_company = payload.external_company
    for field in (
        "external_quote_number",
        "external_oc_number",
        "external_invoice_number",
        "external_account_number",
        "external_oc_amount",
    ):
        if field in payload.model_fields_set:
            setattr(wo, field, getattr(payload, field))
    if wo.is_external_work:
        wo.participant_names = None
    else:
        # Do not leave contractor metadata attached after changing the OT back
        # to the regular employee workflow.
        wo.external_executor_name = None
        wo.external_company = None
        wo.external_quote_number = None
        wo.external_oc_number = None
        wo.external_invoice_number = None
        wo.external_account_number = None
        wo.external_oc_amount = None
        wo.coordinator_user_id = None

    if payload.title is not None:
        wo.title = payload.title.strip()
    if payload.description is not None:
        wo.description = payload.description
    if payload.area_id is not None:
        if payload.area_id != wo.area_id and payload.equipment_id is None:
            raise HTTPException(status_code=400, detail="Selecciona un equipo de la sección elegida")
        effective_equipment_id = payload.equipment_id or wo.equipment_id
        section, equipment = await _validate_area_equipment(
            db, payload.area_id, effective_equipment_id
        )
        wo.area_id = payload.area_id
        wo.equipment_id = equipment.id if equipment else None
        if wo.plant_area:
            wo.section_name = section.name
    elif payload.equipment_id is not None:
        await _validate_area_equipment(db, wo.area_id, payload.equipment_id)
        wo.equipment_id = payload.equipment_id
    if payload.plant_area is not None:
        wo.plant_area = _validate_plant_area(payload.plant_area)
    if payload.section_name is not None:
        wo.section_name = payload.section_name
    if payload.maintenance_type is not None:
        wo.maintenance_type = payload.maintenance_type.upper()
    if payload.loto_status is not None:
        wo.loto_status = payload.loto_status.upper()
    if "loto_controls" in payload.model_fields_set:
        wo.loto_controls = normalize_loto_controls(payload.loto_controls) or ["NOT_APPLICABLE"]
        wo.loto_status = legacy_status_from_controls(wo.loto_controls, wo.loto_status)
    if payload.folio is not None:
        wo.folio = payload.folio
    if payload.estimated_time is not None:
        wo.estimated_time = payload.estimated_time
    if "work_time_mode" in payload.model_fields_set:
        wo.work_time_mode = payload.work_time_mode
    if "work_start_time" in payload.model_fields_set:
        wo.work_start_time = payload.work_start_time
    if "work_end_time" in payload.model_fields_set:
        wo.work_end_time = payload.work_end_time
    if "worked_duration_minutes" in payload.model_fields_set:
        wo.worked_duration_minutes = payload.worked_duration_minutes
    if {"work_time_mode", "work_start_time", "work_end_time", "worked_duration_minutes"} & payload.model_fields_set:
        declared_duration = _duration_from_work_order(wo)
        wo.estimated_time = (
            _format_work_duration(declared_duration)
            if declared_duration is not None
            else None
        )
        # Once an OT is completed, an administrator correction becomes the
        # official duration used by KPIs and the monthly register. The
        # original worker value remains available in the audit history.
        if wo.status == WorkOrderStatus.COMPLETED.value and declared_duration is not None:
            wo.actual_duration_minutes = float(declared_duration)
    if payload.request_date is not None:
        wo.request_date = payload.request_date
    if payload.execution_date is not None:
        wo.execution_date = payload.execution_date
    # Persist the worker's selected time method during the explicit save too.
    # Autosave already handles these fields; keeping both endpoints aligned
    # prevents the form from appearing empty after pressing "Guardar ahora".
    if "work_time_mode" in payload.model_fields_set:
        wo.work_time_mode = payload.work_time_mode
    if "work_start_time" in payload.model_fields_set:
        wo.work_start_time = payload.work_start_time
    if "work_end_time" in payload.model_fields_set:
        wo.work_end_time = payload.work_end_time
    if "worked_duration_minutes" in payload.model_fields_set:
        wo.worked_duration_minutes = payload.worked_duration_minutes
    if payload.resources_required is not None:
        wo.resources_required = payload.resources_required
    if payload.voucher_number is not None:
        wo.voucher_number = payload.voucher_number.strip() or None
    if "voucher_date" in payload.model_fields_set:
        wo.voucher_date = payload.voucher_date
    if "material_codes" in payload.model_fields_set:
        wo.material_codes = payload.material_codes.strip() if payload.material_codes else None
    if "external_executor_name" in payload.model_fields_set:
        wo.external_executor_name = payload.external_executor_name
    if "external_company" in payload.model_fields_set:
        wo.external_company = payload.external_company
    for field in (
        "external_quote_number",
        "external_oc_number",
        "external_invoice_number",
        "external_account_number",
        "external_oc_amount",
    ):
        if field in payload.model_fields_set:
            setattr(wo, field, getattr(payload, field))
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
    if payload.participant_user_ids is not None and not wo.is_external_work:
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
        "status", "title", "description", "area_id", "plant_area", "equipment_id",
        "section_name", "maintenance_type", "estimated_time",
        "execution_date", "participant_names", "responsible_user_id",
        "is_external_work", "external_executor_name", "external_company",
        "external_quote_number", "external_oc_number", "external_invoice_number",
        "external_account_number", "external_oc_amount",
        "work_time_mode", "work_start_time", "work_end_time", "worked_duration_minutes",
    }
    changed = payload.model_dump(exclude_unset=True)
    monthly_relevant = set(changed) & _changed_monthly_fields
    should_sync = bool(monthly_relevant and wo.google_ot_file_id)

    # Re-populate the OT document whenever an admin/OT-relevant field changed,
    # so the Google OT stays in sync with edits (e.g. changing fecha solicitud
    # after the OT was emitted). Uses the same field set as the worker fulfill path.
    _changed_ot_fields = {
        "title", "description", "area_id", "plant_area", "equipment_id", "section_name",
        "maintenance_type", "loto_status", "loto_controls", "estimated_time", "execution_date",
        "request_date", "resources_required", "risks", "observations",
        "folio", "voucher_number", "voucher_date", "material_codes", "requested_by",
        "responsible_user_id", "participant_user_ids", "participant_names",
        "work_time_mode", "work_start_time", "work_end_time", "worked_duration_minutes",
        "is_external_work", "external_executor_name", "external_company",
        "external_quote_number", "external_oc_number", "external_invoice_number",
        "external_account_number", "external_oc_amount",
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
    if wo.is_external_work and (
        payload.responsible_user_id is not None
        or (payload.participant_user_ids is not None and payload.participant_user_ids)
    ):
        raise HTTPException(
            status_code=400,
            detail="Una OT externa no puede asignar trabajadores internos como ejecutores",
        )

    if all(value is None for value in (
        payload.responsible_user_id,
        payload.participant_user_ids,
        payload.plant_area,
        payload.area_id,
        payload.equipment_id,
    )):
        raise HTTPException(
            status_code=400,
            detail="Indica cambios de asignación o ubicación de la OT",
        )

    if payload.area_id is not None or payload.equipment_id is not None:
        target_section_id = payload.area_id or wo.area_id
        if target_section_id != wo.area_id and payload.equipment_id is None:
            raise HTTPException(status_code=400, detail="Selecciona un equipo de la sección elegida")
        target_equipment_id = payload.equipment_id or wo.equipment_id
        section, equipment = await _validate_area_equipment(
            db, target_section_id, target_equipment_id
        )
        if equipment is None:
            raise HTTPException(status_code=400, detail="Selecciona un equipo para la OT")
        wo.area_id = section.id
        wo.equipment_id = equipment.id
        wo.section_name = section.name
    if payload.plant_area is not None:
        wo.plant_area = _validate_plant_area(payload.plant_area)

    previous = {
        "responsible_user_id": wo.responsible_user_id,
        "participants": [p.id for p in (wo.participants or [])],
        "plant_area": wo.plant_area,
        "section_id": wo.area_id,
        "equipment_id": wo.equipment_id,
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
            "plant_area": wo.plant_area,
            "section_id": wo.area_id,
            "equipment_id": wo.equipment_id,
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
    if payload.maintenance_type is not None:
        wo.maintenance_type = payload.maintenance_type.upper()
    if payload.loto_status is not None:
        wo.loto_status = payload.loto_status.upper()
    if "loto_controls" in payload.model_fields_set:
        wo.loto_controls = normalize_loto_controls(payload.loto_controls) or ["NOT_APPLICABLE"]
        wo.loto_status = legacy_status_from_controls(wo.loto_controls, wo.loto_status)
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
        wo.voucher_number = payload.voucher_number.strip() or None
    if "voucher_date" in payload.model_fields_set:
        wo.voucher_date = payload.voucher_date
    if "material_codes" in payload.model_fields_set:
        wo.material_codes = payload.material_codes.strip() if payload.material_codes else None
    if "external_executor_name" in payload.model_fields_set:
        wo.external_executor_name = payload.external_executor_name
    if "external_company" in payload.model_fields_set:
        wo.external_company = payload.external_company
    for field in (
        "external_quote_number",
        "external_oc_number",
        "external_invoice_number",
        "external_account_number",
        "external_oc_amount",
    ):
        if field in payload.model_fields_set:
            setattr(wo, field, getattr(payload, field))
    if payload.risks is not None:
        wo.risks = payload.risks
    if payload.observations is not None:
        wo.observations = payload.observations
    if "work_time_mode" in payload.model_fields_set:
        wo.work_time_mode = payload.work_time_mode
    if "work_start_time" in payload.model_fields_set:
        wo.work_start_time = payload.work_start_time
    if "work_end_time" in payload.model_fields_set:
        wo.work_end_time = payload.work_end_time
    if "worked_duration_minutes" in payload.model_fields_set:
        wo.worked_duration_minutes = payload.worked_duration_minutes
    # Participants (M2M)
    if payload.participant_user_ids is not None:
        if wo.is_external_work and payload.participant_user_ids:
            raise HTTPException(
                status_code=400,
                detail="Una OT externa no puede registrar trabajadores internos como ejecutores",
            )
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

    # Tiempo estimado is the duration shown in the OT template. Once the
    # worker has provided a valid manual duration or time range, store that
    # declared duration there in the same readable Spanish format.
    worker_duration = _duration_from_work_order(wo)
    if worker_duration is not None:
        wo.estimated_time = _format_work_duration(worker_duration)

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
        "status", "title", "description", "maintenance_type",
        "estimated_time", "execution_date", "participant_names", "loto_status", "loto_controls",
        "work_time_mode", "work_start_time", "work_end_time", "worked_duration_minutes",
        "risks", "observations", "resources_required", "folio", "voucher_number",
        "voucher_date", "material_codes",
        "request_date", "external_executor_name", "external_company",
        "external_quote_number", "external_oc_number", "external_invoice_number",
        "external_account_number", "external_oc_amount",
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
    if "loto_controls" in fields:
        wo.loto_controls = normalize_loto_controls(payload.loto_controls) or ["NOT_APPLICABLE"]
        wo.loto_status = legacy_status_from_controls(wo.loto_controls, wo.loto_status)
    if "execution_date" in fields:
        wo.execution_date = payload.execution_date
    if "section_name" in fields:
        wo.section_name = payload.section_name
    if "estimated_time" in fields:
        wo.estimated_time = payload.estimated_time
    if "work_time_mode" in fields:
        wo.work_time_mode = payload.work_time_mode
    if "work_start_time" in fields:
        wo.work_start_time = payload.work_start_time
    if "work_end_time" in fields:
        wo.work_end_time = payload.work_end_time
    if "worked_duration_minutes" in fields:
        wo.worked_duration_minutes = payload.worked_duration_minutes
    if "resources_required" in fields:
        wo.resources_required = payload.resources_required
    if "risks" in fields:
        wo.risks = payload.risks
    if "observations" in fields:
        wo.observations = payload.observations
    if "folio" in fields:
        wo.folio = payload.folio
    if "voucher_number" in fields:
        wo.voucher_number = payload.voucher_number.strip() if payload.voucher_number else None
    if "voucher_date" in fields:
        wo.voucher_date = payload.voucher_date
    if "material_codes" in fields:
        wo.material_codes = payload.material_codes.strip() if payload.material_codes else None
    if "request_date" in fields:
        wo.request_date = payload.request_date
    if "external_executor_name" in fields:
        wo.external_executor_name = payload.external_executor_name
    if "external_company" in fields:
        wo.external_company = payload.external_company
    for field in (
        "external_quote_number",
        "external_oc_number",
        "external_invoice_number",
        "external_account_number",
        "external_oc_amount",
    ):
        if field in fields:
            setattr(wo, field, getattr(payload, field))

    # Keep the OT's displayed duration aligned with either worker input mode.
    # Autosave may run while a range is incomplete, so only replace the value
    # when the current entry forms a valid positive duration.
    worker_duration = _duration_from_work_order(wo)
    if worker_duration is not None:
        wo.estimated_time = _format_work_duration(worker_duration)

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
        if errors:
            raise HTTPException(
                status_code=400,
                detail=f"Para enviar la OT a revisiÃ³n, complete: {', '.join(errors)}",
            )
        wo.submitted_for_review = True
        wo.requested_by = current_user.full_name
        wo.requested_signature = None
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
    if wo.is_external_work and not wo.external_executor_name:
        errors.append("Nombre de la persona externa")
    if not wo.is_external_work and not wo.responsible_user_id:
        errors.append("Responsable principal")
    if not wo.is_external_work:
        await _ensure_responsible_is_participant(db, wo)
        participant_result = await db.execute(
            select(work_order_participants.c.user_id).where(
                work_order_participants.c.work_order_id == wo.id
            ).limit(1)
        )
        if participant_result.scalar_one_or_none() is None:
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
    # submission. The admin is the authorizer/assigner, not the requester, so
    # the supervisor's name remains in "SOLICITADO POR".
    was_submitted_for_review = wo.submitted_for_review
    wo.status = WorkOrderStatus.PENDING.value
    wo.submitted_for_review = False
    if wo.is_external_work:
        # The accepting administrator is accountable for inspecting and
        # closing the contractor's work, but is not recorded as a performer.
        wo.responsible_user_id = None
        wo.coordinator_user_id = current_user.id
        await db.execute(
            work_order_participants.delete().where(
                work_order_participants.c.work_order_id == wo.id
            )
        )
        wo.participant_names = None
    if not was_submitted_for_review:
        wo.requested_by = current_user.full_name
    # Only the administrator authorizes the emitted OT.
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
        if wo.is_external_work:
            if not wo.external_executor_name:
                errors.append("Nombre de la persona externa")
        else:
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
        if wo.is_external_work:
            wo.responsible_user_id = None
            wo.coordinator_user_id = current_user.id
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

    reported_minutes = _reported_work_minutes(payload, wo)
    effective_mode = payload.work_time_mode or wo.work_time_mode
    effective_start = payload.work_start_time or wo.work_start_time
    effective_end = payload.work_end_time or wo.work_end_time

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

    # Store the duration declared by the worker. The app lifecycle timestamps
    # remain available for audit but are never used as worked hours.
    wo.work_time_mode = effective_mode
    wo.work_start_time = effective_start
    wo.work_end_time = effective_end
    wo.worked_duration_minutes = reported_minutes
    wo.actual_duration_minutes = float(reported_minutes)
    if wo.requires_supervisor_validation:
        wo.supervisor_review_status = SupervisorReviewStatus.PENDING.value
        wo.supervisor_validator_user_id = None
        wo.supervisor_reviewed_at = None
        wo.supervisor_review_notes = None
    # Use the worker's declared duration in the existing "Tiempo estimado"
    # cell of the OT document, irrespective of whether it was entered as a
    # manual duration or calculated from a start/end range.
    wo.estimated_time = _format_work_duration(reported_minutes)

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
            "work_time_mode": wo.work_time_mode,
            "worked_duration_minutes": wo.worked_duration_minutes,
        },
    )
    await db.flush()

    await notification_service.notify_work_order_completed(
        db, wo, link=f"/ordenes/{wo.id}", exclude_user_id=current_user.id
    )
    if wo.requires_supervisor_validation:
        await notification_service.notify_supervisor_validation_pending(
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
@router.post("/{wo_id}/supervisor-validation", response_model=WorkOrderResponse)
async def review_supervisor_work_order(
    wo_id: int,
    payload: SupervisorReviewPayload,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Claim, approve or return a completed OT created by a supervisor.

    The status remains COMPLETED while it waits for this internal review, so
    existing Drive/KPI behavior is preserved. RETURN sends it to IN_PROGRESS.
    """
    result = await db.execute(
        _base_query().where(WorkOrder.id == wo_id).with_for_update()
    )
    wo = result.scalar_one_or_none()
    if wo is None:
        raise HTTPException(status_code=404, detail="Orden de trabajo no encontrada")
    if not perms.can_review_supervisor(wo, current_user):
        raise HTTPException(
            status_code=403,
            detail="Solo un supervisor asignado al área puede revisar esta OT.",
        )

    action = payload.action
    notes = (payload.notes or "").strip() or None
    if action == "CLAIM":
        if wo.supervisor_review_status == SupervisorReviewStatus.APPROVED.value:
            raise HTTPException(status_code=409, detail="La OT ya fue validada.")
        if wo.supervisor_review_status == SupervisorReviewStatus.CLAIMED.value:
            if wo.supervisor_validator_user_id == current_user.id:
                wo.supervisor_validator = current_user
                return _work_order_to_response(wo)
            raise HTTPException(status_code=409, detail="Otro supervisor ya tomó la revisión de esta OT.")
        if wo.supervisor_review_status != SupervisorReviewStatus.PENDING.value:
            raise HTTPException(status_code=409, detail="Esta OT no está pendiente de validación de supervisor.")
        wo.supervisor_review_status = SupervisorReviewStatus.CLAIMED.value
        wo.supervisor_validator_user_id = current_user.id
        wo.supervisor_validator = current_user
        wo.supervisor_reviewed_at = None
        wo.supervisor_review_notes = None
        await create_audit_log(
            db, user_id=current_user.id, action="CLAIM_SUPERVISOR_REVIEW",
            entity_type="WorkOrder", entity_id=wo.id,
            previous_data={"supervisor_review_status": SupervisorReviewStatus.PENDING.value},
            new_data={"supervisor_review_status": SupervisorReviewStatus.CLAIMED.value,
                      "supervisor_validator_user_id": current_user.id},
        )
        await db.commit()
        result2 = await db.execute(_base_query().where(WorkOrder.id == wo.id))
        return _work_order_to_response(result2.scalar_one())

    if wo.supervisor_review_status != SupervisorReviewStatus.CLAIMED.value:
        raise HTTPException(status_code=409, detail="Primero debes tomar la revisión de esta OT.")
    if wo.supervisor_validator_user_id != current_user.id:
        raise HTTPException(status_code=409, detail="La revisión de esta OT está tomada por otro supervisor.")
    if action == "RETURN" and not notes:
        raise HTTPException(status_code=422, detail="Indica el motivo por el que devuelves la OT al trabajador.")

    previous_review_status = wo.supervisor_review_status
    now = datetime.now(timezone.utc)
    wo.supervisor_reviewed_at = now
    wo.supervisor_review_notes = notes
    if action == "APPROVE":
        wo.supervisor_review_status = SupervisorReviewStatus.APPROVED.value
        await create_audit_log(
            db, user_id=current_user.id, action="APPROVE_SUPERVISOR_REVIEW",
            entity_type="WorkOrder", entity_id=wo.id,
            previous_data={"supervisor_review_status": previous_review_status},
            new_data={"supervisor_review_status": wo.supervisor_review_status,
                      "supervisor_review_notes": notes},
        )
        await notification_service.notify_supervisor_reviewed(
            db, wo, approved=True, reviewer_name=current_user.full_name,
            notes=notes, link=f"/ordenes/{wo.id}"
        )
        await db.commit()
        result2 = await db.execute(_base_query().where(WorkOrder.id == wo.id))
        return _work_order_to_response(result2.scalar_one())

    validate_transition(wo.status, WorkOrderStatus.IN_PROGRESS.value)
    wo.status = WorkOrderStatus.IN_PROGRESS.value
    wo.supervisor_review_status = SupervisorReviewStatus.RETURNED.value
    wo.returned_at = now
    wo.returned_by_user_id = current_user.id
    wo.return_reason = notes
    wo.completed_at = None
    wo.completed_by_user_id = None
    wo.work_time_mode = None
    wo.work_start_time = None
    wo.work_end_time = None
    wo.worked_duration_minutes = None
    wo.actual_duration_minutes = None
    wo.completion_notes = None
    await create_audit_log(
        db, user_id=current_user.id, action="RETURN_SUPERVISOR_REVIEW",
        entity_type="WorkOrder", entity_id=wo.id,
        previous_data={"status": WorkOrderStatus.COMPLETED.value,
                       "supervisor_review_status": previous_review_status},
        new_data={"status": wo.status,
                  "supervisor_review_status": wo.supervisor_review_status,
                  "return_reason": notes},
    )
    await notification_service.notify_supervisor_reviewed(
        db, wo, approved=False, reviewer_name=current_user.full_name,
        notes=notes, link=f"/mis-ordenes/{wo.id}"
    )
    if wo.google_ot_file_id:
        _mark_external_sync_pending(wo)
        await enqueue_external_sync(
            db, wo.id, job_type="LIFECYCLE", actor_user_id=current_user.id
        )
    await db.commit()
    result2 = await db.execute(_base_query().where(WorkOrder.id == wo.id))
    return _work_order_to_response(result2.scalar_one())


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
    wo.work_time_mode = None
    wo.work_start_time = None
    wo.work_end_time = None
    wo.worked_duration_minutes = None
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

    if (
        wo.requires_supervisor_validation
        and wo.supervisor_review_status != SupervisorReviewStatus.APPROVED.value
    ):
        raise HTTPException(
            status_code=409,
            detail="Esta OT debe ser validada primero por un supervisor del área.",
        )

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
@router.delete("/{wo_id}", response_model=dict)
async def delete_work_order(
    wo_id: int,
    payload: DeleteWorkOrderPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
):
    """Remove an erroneous OT from the app and its Google records (admin only)."""
    result = await db.execute(
        select(WorkOrder).where(WorkOrder.id == wo_id).with_for_update()
    )
    wo = result.scalar_one_or_none()
    if wo is None:
        raise HTTPException(status_code=404, detail="Orden de trabajo no encontrada")

    reason = (payload.reason or "").strip()
    if payload.confirm_ot_number.strip() != wo.ot_number:
        raise HTTPException(
            status_code=422,
            detail="Escribe el número exacto de la OT para confirmar el borrado.",
        )
    if len(reason) < 8:
        raise HTTPException(
            status_code=422,
            detail="Indica un motivo de al menos 8 caracteres.",
        )

    # Lock queue rows so the worker cannot start another Google sync while the
    # external records are being removed. A live request must finish first.
    job_result = await db.execute(
        select(ExternalSyncJob)
        .where(ExternalSyncJob.work_order_id == wo.id)
        .with_for_update()
    )
    jobs = list(job_result.scalars().all())
    if any(job.status == SyncJobStatus.PROCESSING for job in jobs):
        raise HTTPException(
            status_code=409,
            detail="La OT se está sincronizando con Google. Espera y vuelve a intentar.",
        )

    ot_number = wo.ot_number
    drive_file_id = wo.google_ot_file_id
    evidence_result = await db.execute(
        select(WorkOrderEvidence).where(WorkOrderEvidence.work_order_id == wo.id)
    )
    evidence_items = list(evidence_result.scalars().all())
    execution_dt = _exec_datetime(wo)
    register = await resolve_register(db, execution_dt.year)
    spreadsheet_id = (
        register.spreadsheet_id if register else settings.GOOGLE_MONTHLY_SPREADSHEET_ID
    )
    monthly_cleanup_needed = bool(drive_file_id) or wo.monthly_sheet_sync_status in {
        "SYNCED", "FAILED"
    }
    drive_trashed = False
    monthly_cleanup_attempted = bool(spreadsheet_id and monthly_cleanup_needed)

    # Google APIs and the database do not share a transaction. Perform
    # idempotent external cleanup first; if any call fails, keep the OT in the
    # app so an administrator can retry without losing its source data.
    try:
        if monthly_cleanup_attempted:
            await asyncio.to_thread(
                delete_ot_from_register,
                spreadsheet_id,
                get_monthly_sheet_title(execution_dt.month),
                ot_number,
            )
        if drive_file_id:
            drive_trashed = await asyncio.to_thread(
                drive_service.trash_ot_file, drive_file_id
            )
        for evidence in evidence_items:
            await asyncio.to_thread(
                drive_service.trash_ot_file, evidence.drive_file_id
            )
    except Exception as exc:  # noqa: BLE001 - report a retryable integration failure.
        await db.rollback()
        logger.exception("No se pudo completar el borrado externo de %s", ot_number)
        raise HTTPException(
            status_code=502,
            detail=(
                "No se eliminó la OT de la aplicación porque falló la limpieza de "
                "Google. Puede que una parte externa ya se haya quitado; revisa y "
                "vuelve a intentar."
            ),
        ) from exc

    await db.execute(
        delete(ExternalSyncJob).where(ExternalSyncJob.work_order_id == wo.id)
    )
    notification_result = await db.execute(
        delete(Notification).where(
            or_(
                Notification.link.in_((f"/ordenes/{wo.id}", f"/mis-ordenes/{wo.id}")),
                Notification.message == ot_number,
                Notification.message.contains(f" {ot_number} ", autoescape=True),
                Notification.message.startswith(f"{ot_number} ", autoescape=True),
                Notification.message.endswith(f" {ot_number}.", autoescape=True),
                Notification.message.endswith(f" {ot_number}", autoescape=True),
            )
        )
    )
    notifications_removed = max(notification_result.rowcount or 0, 0)

    await db.execute(
        delete(WorkOrderEvidence).where(WorkOrderEvidence.work_order_id == wo.id)
    )
    await db.delete(wo)
    await db.flush()
    await create_audit_log(
        db,
        user_id=current_user.id,
        action="DELETE_WORK_ORDER",
        entity_type="WorkOrder",
        entity_id=None,
        new_data={
            "ot_number": ot_number,
            "reason": reason,
            "drive_moved_to_trash": drive_trashed,
            "monthly_cleanup_attempted": monthly_cleanup_attempted,
            "notifications_removed": notifications_removed,
            "evidence_files_removed": len(evidence_items),
        },
    )
    await db.commit()

    global _counter_cache
    _counter_cache = None
    return {
        "deleted": True,
        "ot_number": ot_number,
        "drive_moved_to_trash": drive_trashed,
        "monthly_cleanup_attempted": monthly_cleanup_attempted,
        "notifications_removed": notifications_removed,
        "evidence_files_removed": len(evidence_items),
    }


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
