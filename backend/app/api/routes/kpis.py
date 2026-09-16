"""Operational KPI reporting for administrators and supervisors."""

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dependencies import require_roles
from app.db.session import get_db
from app.models.user import User, UserRole
from app.models.work_order import WorkOrder
from app.core.work_order_areas import WORK_ORDER_AREAS
from app.schemas.kpi import (
    KpiMaintenanceRow,
    KpiMonthRow,
    KpiAreaRow,
    KpiAreaTypeRow,
    KpiResponse,
    KpiSectionRow,
    KpiSummary,
    KpiWorkerRow,
    KpiWorkerDetailRow,
)


router = APIRouter(prefix="/api/kpis", tags=["kpis"])
manager_roles = require_roles(UserRole.ADMIN, UserRole.SUPERVISOR)
EXECUTED_STATUSES = {"COMPLETED", "APPROVED"}
VALID_MAINTENANCE_TYPES = {"PREVENTIVE", "CORRECTIVE", "PREDICTIVE", "PROYECTO", "MONTAJE"}
MONTH_NAMES = (
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
)
COMPLIANCE_TARGET_PERCENT = 90.0


def _parse_estimated_minutes(value: str | None) -> float:
    """Parse the legacy duration text used by older and open OTs."""
    if not value:
        return 0.0
    text = value.strip().lower().replace(",", ".")
    hours = re.search(r"(\d+(?:\.\d+)?)\s*h(?:oras?)?", text)
    minutes = re.search(r"(\d+(?:\.\d+)?)\s*m(?:in(?:utos?)?)?", text)
    total = 0.0
    if hours:
        total += float(hours.group(1)) * 60
    if minutes:
        total += float(minutes.group(1))
    if total:
        return total
    try:
        return float(text) * 60
    except ValueError:
        return 0.0


def _duration_minutes(wo: WorkOrder) -> float:
    status = str(getattr(wo.status, "value", wo.status)).upper()
    if status in EXECUTED_STATUSES:
        declared = wo.worked_duration_minutes
        if declared is not None and declared > 0:
            return float(declared)
        if wo.actual_duration_minutes is not None and wo.actual_duration_minutes > 0:
            return float(wo.actual_duration_minutes)
    return _parse_estimated_minutes(wo.estimated_time)


def _report_date(wo: WorkOrder) -> date:
    if wo.execution_date:
        return wo.execution_date
    if wo.scheduled_date:
        return wo.scheduled_date
    created = wo.created_at
    if isinstance(created, datetime):
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return created.date()
    return created


@router.get("", response_model=KpiResponse)
async def get_kpis(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    area_id: int | None = Query(default=None, ge=1),
    plant_area: str | None = Query(default=None),
    section_name: str | None = Query(default=None),
    maintenance_type: str | None = Query(default=None),
    current_user: User = Depends(manager_roles),
    db: AsyncSession = Depends(get_db),
):
    today = date.today()
    start = date_from or date(today.year, 1, 1)
    end = date_to or today
    if start > end:
        raise HTTPException(status_code=400, detail="La fecha inicial no puede ser posterior a la fecha final")

    selected_type = maintenance_type.upper() if maintenance_type else None
    if selected_type and selected_type not in VALID_MAINTENANCE_TYPES:
        raise HTTPException(status_code=400, detail="Tipo de mantenimiento no válido")

    report_date = func.coalesce(
        WorkOrder.execution_date,
        WorkOrder.scheduled_date,
        cast(WorkOrder.created_at, Date),
    )
    query = (
        select(WorkOrder)
        .options(
            selectinload(WorkOrder.area),
            selectinload(WorkOrder.participants),
            selectinload(WorkOrder.responsible_user),
        )
        .where(report_date >= start, report_date <= end)
    )

    if current_user.role == UserRole.SUPERVISOR:
        allowed_areas = current_user.area_ids
        if not allowed_areas:
            query = query.where(WorkOrder.id == -1)
        else:
            query = query.where(WorkOrder.area_id.in_(allowed_areas))
    if area_id is not None:
        query = query.where(WorkOrder.area_id == area_id)
    if plant_area and plant_area.strip():
        normalized_area = plant_area.strip().upper()
        if normalized_area not in WORK_ORDER_AREAS:
            raise HTTPException(status_code=400, detail="Área no válida")
        query = query.where(WorkOrder.plant_area == normalized_area)
    if section_name and section_name.strip():
        query = query.where(func.lower(func.coalesce(WorkOrder.section_name, "")) == section_name.strip().lower())
    if selected_type:
        query = query.where(WorkOrder.maintenance_type == selected_type)

    orders = (await db.execute(query.order_by(report_date, WorkOrder.ot_number))).scalars().all()

    status_counts: dict[str, int] = defaultdict(int)
    type_counts: dict[str, dict[str, float]] = defaultdict(lambda: {"total": 0, "completed": 0, "minutes": 0.0})
    worker_counts: dict[int, dict[str, float | str]] = {}
    worker_detail_counts: dict[tuple[int, str, str], dict[str, float | str]] = {}
    area_counts: dict[str, dict[str, float | int]] = {}
    area_type_counts: dict[tuple[str, str], dict[str, float | int]] = {}
    section_counts: dict[tuple[str, str], dict[str, float | int]] = {}
    month_counts: dict[str, dict[str, float | int]] = {}
    planned = executed_planned = completed = total_minutes = total_person_minutes = 0
    overdue_ots = stale_pending_ots = 0
    stale_cutoff = today - timedelta(days=7)

    for wo in orders:
        status = str(getattr(wo.status, "value", wo.status)).upper()
        status_counts[status] += 1
        is_completed = status in EXECUTED_STATUSES
        if is_completed:
            completed += 1
        if wo.is_planned:
            planned += 1
            if is_completed:
                executed_planned += 1

        minutes = _duration_minutes(wo)
        total_minutes += minutes
        kind = str(wo.maintenance_type).upper()
        type_row = type_counts[kind]
        type_row["total"] += 1
        type_row["completed"] += int(is_completed)
        type_row["minutes"] += minutes

        if (
            status in {"PENDING", "IN_PROGRESS"}
            and wo.due_date is not None
            and wo.due_date < today
        ):
            overdue_ots += 1
        age_date = wo.scheduled_date or wo.request_date
        if age_date is None and wo.created_at:
            created = wo.created_at
            if isinstance(created, datetime):
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                age_date = created.date()
        if status in {"PENDING", "IN_PROGRESS"} and age_date and age_date < stale_cutoff:
            stale_pending_ots += 1

        area = wo.plant_area or (wo.area.name if wo.area else "Sin área")
        area_row = area_counts.setdefault(area, {
            "total": 0, "completed": 0, "minutes": 0.0,
            "preventive": 0, "corrective": 0,
        })
        area_row["total"] += 1
        area_row["completed"] += int(is_completed)
        area_row["minutes"] += minutes
        area_row["preventive"] += int(kind == "PREVENTIVE")
        area_row["corrective"] += int(kind == "CORRECTIVE")

        area_type_key = (area, kind)
        area_type_row = area_type_counts.setdefault(area_type_key, {
            "total": 0, "completed": 0, "minutes": 0.0,
        })
        area_type_row["total"] += 1
        area_type_row["completed"] += int(is_completed)
        area_type_row["minutes"] += minutes

        section_value = wo.area.name if wo.plant_area and wo.area else wo.section_name
        section = (section_value or "Sin sección").strip() or "Sin sección"
        section_key = (area, section)
        section_row = section_counts.setdefault(section_key, {
            "total": 0, "completed": 0, "minutes": 0.0,
            "preventive": 0, "corrective": 0,
        })
        section_row["total"] += 1
        section_row["completed"] += int(is_completed)
        section_row["minutes"] += minutes
        section_row["preventive"] += int(kind == "PREVENTIVE")
        section_row["corrective"] += int(kind == "CORRECTIVE")

        report_month = _report_date(wo).strftime("%Y-%m")
        month_row = month_counts.setdefault(report_month, {
            "total": 0, "completed": 0, "planned": 0,
            "executed_planned": 0, "minutes": 0.0,
        })
        month_row["total"] += 1
        month_row["completed"] += int(is_completed)
        month_row["planned"] += int(wo.is_planned)
        month_row["executed_planned"] += int(wo.is_planned and is_completed)
        month_row["minutes"] += minutes

        participants = list(wo.participants or [])
        if not participants and wo.responsible_user:
            participants = [wo.responsible_user]
        total_person_minutes += minutes * len(participants)
        for worker in participants:
            row = worker_counts.setdefault(worker.id, {
                "name": worker.full_name, "assigned": 0, "completed": 0, "minutes": 0.0,
            })
            row["assigned"] += 1
            row["completed"] += int(is_completed)
            # Each participant receives the full OT duration, per the agreed rule.
            row["minutes"] += minutes
            detail_key = (worker.id, area, kind)
            detail_row = worker_detail_counts.setdefault(detail_key, {
                "name": worker.full_name, "area": area, "kind": kind,
                "assigned": 0, "completed": 0, "minutes": 0.0,
            })
            detail_row["assigned"] += 1
            detail_row["completed"] += int(is_completed)
            detail_row["minutes"] += minutes

    def hours(minutes: float) -> float:
        return round(minutes / 60, 2)

    maintenance_rows = [
        KpiMaintenanceRow(
            maintenance_type=kind,
            total_ots=int(row["total"]),
            completed_ots=int(row["completed"]),
            total_hours=hours(row["minutes"]),
        )
        for kind, row in sorted(type_counts.items())
    ]
    worker_detail_rows = [
        KpiWorkerDetailRow(
            user_id=user_id,
            worker_name=str(row["name"]),
            area_name=str(row["area"]),
            maintenance_type=str(row["kind"]),
            assigned_ots=int(row["assigned"]),
            completed_ots=int(row["completed"]),
            person_hours=hours(row["minutes"]),
        )
        for (user_id, _area, _kind), row in sorted(
            worker_detail_counts.items(),
            key=lambda item: (str(item[1]["name"]).lower(), str(item[1]["area"]).lower(), str(item[1]["kind"])),
        )
    ]
    worker_rows = [
        KpiWorkerRow(
            user_id=user_id,
            worker_name=str(row["name"]),
            assigned_ots=int(row["assigned"]),
            completed_ots=int(row["completed"]),
            total_hours=hours(row["minutes"]),
            person_hours=hours(row["minutes"]),
        )
        for user_id, row in sorted(worker_counts.items(), key=lambda item: str(item[1]["name"]).lower())
    ]
    section_rows = [
        KpiSectionRow(
            area_name=area,
            section_name=section,
            total_ots=int(row["total"]),
            completed_ots=int(row["completed"]),
            total_hours=hours(row["minutes"]),
            preventive_ots=int(row["preventive"]),
            corrective_ots=int(row["corrective"]),
        )
        for (area, section), row in sorted(section_counts.items())
    ]
    area_rows = [
        KpiAreaRow(
            area_name=area,
            total_ots=int(row["total"]),
            completed_ots=int(row["completed"]),
            total_hours=hours(row["minutes"]),
            preventive_ots=int(row["preventive"]),
            corrective_ots=int(row["corrective"]),
        )
        for area, row in sorted(area_counts.items())
    ]
    area_type_rows = [
        KpiAreaTypeRow(
            area_name=area,
            maintenance_type=kind,
            total_ots=int(row["total"]),
            completed_ots=int(row["completed"]),
            total_hours=hours(row["minutes"]),
        )
        for (area, kind), row in sorted(area_type_counts.items())
    ]
    month_rows = [
        KpiMonthRow(
            month=key,
            total_ots=int(row["total"]),
            completed_ots=int(row["completed"]),
            planned_ots=int(row["planned"]),
            executed_planned_ots=int(row["executed_planned"]),
            compliance_percent=round(
                int(row["executed_planned"]) * 100 / int(row["planned"]), 1
            ) if row["planned"] else None,
            total_hours=hours(row["minutes"]),
        )
        for key, row in sorted(month_counts.items())
    ]

    return KpiResponse(
        generated_at=datetime.now(timezone.utc),
        date_from=start,
        date_to=end,
        summary=KpiSummary(
            total_ots=len(orders),
            completed_ots=completed,
            pending_ots=status_counts["PENDING"],
            in_progress_ots=status_counts["IN_PROGRESS"],
            cancelled_ots=status_counts["CANCELLED"],
            planned_ots=planned,
            executed_planned_ots=executed_planned,
            compliance_percent=round(executed_planned * 100 / planned, 1) if planned else None,
            compliance_target_percent=COMPLIANCE_TARGET_PERCENT,
            total_hours=hours(total_minutes),
            total_person_hours=hours(total_person_minutes),
            average_hours_per_ot=hours(total_minutes / len(orders)) if orders else 0.0,
            overdue_ots=overdue_ots,
            stale_pending_ots=stale_pending_ots,
        ),
        by_maintenance_type=maintenance_rows,
        by_worker=worker_rows,
        by_worker_detail=worker_detail_rows,
        by_area=area_rows,
        by_area_type=area_type_rows,
        by_section=section_rows,
        by_month=month_rows,
    )
