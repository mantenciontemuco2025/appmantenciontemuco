"""Admin-managed preventive plans and linked preventive work orders."""

import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.api.routes import work_orders as work_order_routes
from app.db.session import get_db
from app.models import Area, Equipment, PlantArea, PreventiveAlertSettings, PreventivePlan, User, WorkOrder
from app.models.plant_area import plant_area_sections
from app.models.user import UserRole
from app.models.work_order import LotoStatus, WorkOrderStatus
from app.schemas.preventive import (
    PreventiveImportItem,
    PreventiveImportMatch,
    PreventiveImportPreview,
    PreventiveImportRequest,
    PreventiveImportResult,
    GeneratePreventiveWorkOrder,
    PreventivePlanCreate,
    PreventivePlanResponse,
    PreventivePlanUpdate,
    PreventiveAlertSettingsResponse,
    PreventiveAlertSettingsUpdate,
    PreventiveWorkOrderSummary,
)
from app.schemas.work_order import WorkOrderCreate
from app.services.preventive import (
    PERIODICITY_MONTHS,
    periodicity_from_template,
    preventive_source_key,
)
from app.services.preventive_alert_service import create_due_alerts


router = APIRouter(prefix="/api/preventive", tags=["preventive"])
OPEN_STATUSES = (WorkOrderStatus.DRAFT.value, WorkOrderStatus.PENDING.value, WorkOrderStatus.IN_PROGRESS.value)


@router.get("/settings", response_model=PreventiveAlertSettingsResponse)
async def get_alert_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    settings_row = await db.get(PreventiveAlertSettings, 1)
    if settings_row is None:
        return PreventiveAlertSettingsResponse(alert_days=30)
    return PreventiveAlertSettingsResponse(
        alert_days=settings_row.alert_days,
        updated_at=settings_row.updated_at,
    )


@router.patch("/settings", response_model=PreventiveAlertSettingsResponse)
async def update_alert_settings(
    payload: PreventiveAlertSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    settings_row = await db.get(PreventiveAlertSettings, 1)
    if settings_row is None:
        settings_row = PreventiveAlertSettings(id=1)
        db.add(settings_row)
    settings_row.alert_days = payload.alert_days
    settings_row.updated_by_user_id = current_user.id
    await db.commit()
    await create_due_alerts(db)
    await db.refresh(settings_row)
    return PreventiveAlertSettingsResponse(
        alert_days=settings_row.alert_days,
        updated_at=settings_row.updated_at,
    )


def _require_admin(current_user: User) -> None:
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Solo administradores pueden gestionar el plan preventivo.")


def _today() -> date:
    return datetime.now(ZoneInfo("America/Santiago")).date()


def _normal(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in text if not unicodedata.combining(char)).strip().casefold()


def _import_mismatch(item: PreventiveImportItem, equipment: Equipment, area: Area,
                     plant_area: PlantArea | None) -> str | None:
    differences = []
    if item.equipment_name and _normal(equipment.name) != _normal(item.equipment_name):
        differences.append("nombre del equipo")
    if item.section_name and _normal(area.name) != _normal(item.section_name):
        differences.append("sección")
    if item.area_name and plant_area and _normal(plant_area.name) != _normal(item.area_name):
        differences.append("área")
    if differences:
        return "No coincide " + ", ".join(differences) + " con el catálogo actual; no se importó para evitar asignarlo mal."
    return None


def _interval(periodicity: str | None, months: int | None) -> int | None:
    return months or PERIODICITY_MONTHS.get(periodicity or "")


async def _alert_days(db: AsyncSession) -> int:
    settings_row = await db.get(PreventiveAlertSettings, 1)
    return settings_row.alert_days if settings_row is not None else 30


def _status(plan: PreventivePlan, latest: WorkOrder | None, alert_days: int = 30) -> str:
    if not plan.active:
        return "INACTIVE"
    if latest and latest.status in OPEN_STATUSES:
        return "OT_OPEN"
    if not plan.periodicity or not _interval(plan.periodicity, plan.interval_months) or not plan.next_due_date:
        return "NEEDS_CONFIGURATION"
    due = plan.next_due_date
    today = _today()
    if due < today:
        return "OVERDUE"
    if due <= today + timedelta(days=alert_days):
        return "DUE_SOON"
    return "ON_TIME"


async def _load_import_catalog(db: AsyncSession, items: list[PreventiveImportItem]):
    codes = {item.equipment_inventory_id.strip() for item in items if item.equipment_inventory_id.strip()}
    numeric_ids = {int(code) for code in codes if code.isdigit()}
    if not codes:
        return {}, {}
    rows = (await db.execute(
        select(Equipment, Area, PlantArea)
        .join(Area, Equipment.area_id == Area.id)
        .outerjoin(PlantArea, Equipment.plant_area_id == PlantArea.id)
        .where(or_(Equipment.inventory_code.in_(codes), Equipment.id.in_(numeric_ids)))
    )).all()
    by_code = defaultdict(list)
    by_id = {}
    for row in rows:
        equipment = row[0]
        if equipment.inventory_code:
            by_code[equipment.inventory_code.strip()].append(row)
        by_id[equipment.id] = row
    return by_code, by_id


def _resolve_equipment(item: PreventiveImportItem, by_code, by_id):
    code = item.equipment_inventory_id.strip()
    code_rows = by_code.get(code, [])
    if len(code_rows) == 1:
        return code_rows[0], None
    if len(code_rows) > 1:
        exact = [row for row in code_rows if not _import_mismatch(item, row[0], row[1], row[2])]
        if len(exact) == 1:
            return exact[0], None
        return None, "El código de inventario está repetido y no se pudo distinguir el equipo."

    # Some historic catalogs stored id_inv as the database ID. Accept it only
    # when name and section also match, to avoid linking the wrong machine.
    row = by_id.get(int(code)) if code.isdigit() else None
    if row and item.equipment_name and item.section_name and not _import_mismatch(item, row[0], row[1], row[2]):
        return row, None
    return None, "No coincide el ID con un código de inventario y equipo existente."


def _plan_response(plan: PreventivePlan, equipment: Equipment, area: Area,
                   plant_area: PlantArea | None, latest: WorkOrder | None,
                   responsible_name: str | None = None, alert_days: int = 30) -> PreventivePlanResponse:
    latest_summary = PreventiveWorkOrderSummary(
        id=latest.id,
        ot_number=latest.ot_number,
        status=latest.status,
        created_at=latest.created_at,
        completed_at=latest.completed_at,
    ) if latest else None
    return PreventivePlanResponse(
        id=plan.id,
        equipment_id=equipment.id,
        equipment_name=equipment.name,
        inventory_code=equipment.inventory_code,
        area_name=plant_area.name if plant_area else None,
        section_name=area.name,
        plant_area=plant_area.name if plant_area else None,
        source_plan_id=plan.source_plan_id,
        periodicity=plan.periodicity,
        interval_months=plan.interval_months,
        planned_month=plan.planned_month,
        last_completed_date=plan.last_completed_date,
        next_due_date=plan.next_due_date,
        description=plan.description,
        spare_parts=plan.spare_parts,
        estimated_time=plan.estimated_time,
        condition=plan.condition,
        observations=plan.observations,
        responsible_name_hint=plan.responsible_name_hint,
        default_responsible_user_id=plan.default_responsible_user_id,
        default_responsible_name=responsible_name,
        active=plan.active,
        status=_status(plan, latest, alert_days),
        latest_work_order=latest_summary,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


async def _get_plan_with_equipment(db: AsyncSession, plan_id: int, *, lock: bool = False):
    query = (
        select(PreventivePlan, Equipment, Area, PlantArea)
        .join(Equipment, PreventivePlan.equipment_id == Equipment.id)
        .join(Area, Equipment.area_id == Area.id)
        .outerjoin(PlantArea, Equipment.plant_area_id == PlantArea.id)
        .where(PreventivePlan.id == plan_id)
    )
    if lock:
        query = query.with_for_update(of=PreventivePlan)
    return (await db.execute(query)).one_or_none()


async def _latest_work_orders(db: AsyncSession, plan_ids: list[int]) -> dict[int, WorkOrder]:
    if not plan_ids:
        return {}
    ranked = select(
        WorkOrder.id.label("work_order_id"),
        WorkOrder.preventive_plan_id.label("plan_id"),
        func.row_number().over(
            partition_by=WorkOrder.preventive_plan_id,
            order_by=(
                case((WorkOrder.status.in_(OPEN_STATUSES), 1), else_=0).desc(),
                WorkOrder.created_at.desc(),
                WorkOrder.id.desc(),
            ),
        ).label("position"),
    ).where(WorkOrder.preventive_plan_id.in_(plan_ids)).subquery()
    rows = (await db.execute(
        select(WorkOrder).join(ranked, ranked.c.work_order_id == WorkOrder.id).where(ranked.c.position == 1)
    )).scalars().all()
    return {row.preventive_plan_id: row for row in rows if row.preventive_plan_id is not None}


@router.get("/plans", response_model=list[PreventivePlanResponse])
async def list_plans(
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    query = (
        select(PreventivePlan, Equipment, Area, PlantArea)
        .join(Equipment, PreventivePlan.equipment_id == Equipment.id)
        .join(Area, Equipment.area_id == Area.id)
        .outerjoin(PlantArea, Equipment.plant_area_id == PlantArea.id)
    )
    if not include_inactive:
        query = query.where(PreventivePlan.active.is_(True))
    rows = (await db.execute(query.order_by(PreventivePlan.next_due_date, Equipment.name, PreventivePlan.id))).all()
    plans = [row[0] for row in rows]
    latest = await _latest_work_orders(db, [plan.id for plan in plans])
    responsible_ids = {plan.default_responsible_user_id for plan in plans if plan.default_responsible_user_id}
    responsible_rows = (await db.execute(select(User.id, User.full_name).where(User.id.in_(responsible_ids)))).all() if responsible_ids else []
    responsible_names = {user_id: name for user_id, name in responsible_rows}
    alert_days = await _alert_days(db)
    return [_plan_response(plan, equipment, area, plant_area, latest.get(plan.id), responsible_names.get(plan.default_responsible_user_id), alert_days)
            for plan, equipment, area, plant_area in rows]


@router.post("/plans", response_model=PreventivePlanResponse, status_code=status.HTTP_201_CREATED)
async def create_plan(
    payload: PreventivePlanCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    if payload.equipment_id <= 0:
        raise HTTPException(status_code=422, detail="Selecciona un equipo del inventario.")
    responsible = None
    if payload.default_responsible_user_id:
        responsible = await db.get(User, payload.default_responsible_user_id)
        if not responsible or not responsible.is_active:
            raise HTTPException(status_code=422, detail="El responsable seleccionado no está activo.")
    equipment_row = (await db.execute(
        select(Equipment, Area, PlantArea)
        .join(Area, Equipment.area_id == Area.id)
        .outerjoin(PlantArea, Equipment.plant_area_id == PlantArea.id)
        .where(Equipment.id == payload.equipment_id)
    )).one_or_none()
    if not equipment_row:
        raise HTTPException(status_code=404, detail="Equipo no encontrado en el inventario.")
    values = payload.model_dump()
    plan = PreventivePlan(**values, created_by_user_id=current_user.id)
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    equipment, area, plant_area = equipment_row
    return _plan_response(plan, equipment, area, plant_area, None, responsible.full_name if responsible else None, await _alert_days(db))


@router.patch("/plans/{plan_id}", response_model=PreventivePlanResponse)
async def update_plan(
    plan_id: int,
    payload: PreventivePlanUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    row = await _get_plan_with_equipment(db, plan_id, lock=True)
    if not row:
        raise HTTPException(status_code=404, detail="Plan preventivo no encontrado.")
    plan, equipment, area, plant_area = row
    changes = payload.model_dump(exclude_unset=True)
    responsible = None
    responsible_id = changes.get("default_responsible_user_id", plan.default_responsible_user_id)
    if responsible_id is not None:
        responsible = await db.get(User, responsible_id)
        if not responsible or not responsible.is_active:
            raise HTTPException(status_code=422, detail="El responsable seleccionado no está activo.")
    if "active" in changes and changes["active"] is False:
        open_order = await db.scalar(select(WorkOrder.id).where(
            WorkOrder.preventive_plan_id == plan.id,
            WorkOrder.status.in_(OPEN_STATUSES),
        ).limit(1))
        if open_order:
            raise HTTPException(status_code=409, detail="No puedes desactivar un plan que tiene una OT abierta.")
    for key, value in changes.items():
        setattr(plan, key, value)
    await db.commit()
    await db.refresh(plan)
    latest = (await _latest_work_orders(db, [plan.id])).get(plan.id)
    return _plan_response(plan, equipment, area, plant_area, latest, responsible.full_name if responsible else None, await _alert_days(db))


@router.post("/import/preview", response_model=PreventiveImportPreview)
async def preview_import(
    payload: PreventiveImportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    by_code, by_id = await _load_import_catalog(db, payload.items)
    keys = {preventive_source_key(item.source_plan_id, item) for item in payload.items}
    existing_keys = set((await db.execute(select(PreventivePlan.source_key).where(PreventivePlan.source_key.in_(keys)))).scalars().all()) if keys else set()
    matched = 0
    existing = 0
    unmatched: list[PreventiveImportMatch] = []
    for item in payload.items:
        if not item.equipment_inventory_id.strip():
            continue
        row, reason = _resolve_equipment(item, by_code, by_id)
        if not row:
            unmatched.append(PreventiveImportMatch(
                source_plan_id=item.source_plan_id,
                equipment_inventory_id=item.equipment_inventory_id,
                equipment_id=None,
                equipment_display_name=None,
                status="UNMATCHED",
                reason=reason,
            ))
            continue
        equipment, area, _plant = row
        key = preventive_source_key(item.source_plan_id, item)
        if key in existing_keys:
            existing += 1
        elif _import_mismatch(item, equipment, area, _plant):
            unmatched.append(PreventiveImportMatch(
                source_plan_id=item.source_plan_id,
                equipment_inventory_id=item.equipment_inventory_id,
                equipment_id=equipment.id,
                equipment_display_name=f"{equipment.name} · {area.name}",
                status="NAME_DIFFERS",
                reason=_import_mismatch(item, equipment, area, _plant),
            ))
        else:
            matched += 1
    return PreventiveImportPreview(
        total_with_id=len([item for item in payload.items if item.equipment_inventory_id.strip()]),
        matched=matched,
        unmatched=unmatched,
        existing=existing,
    )


@router.post("/import", response_model=PreventiveImportResult)
async def import_plans(
    payload: PreventiveImportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    by_code, by_id = await _load_import_catalog(db, payload.items)
    keys = {preventive_source_key(item.source_plan_id, item) for item in payload.items}
    existing_keys = set((await db.execute(select(PreventivePlan.source_key).where(PreventivePlan.source_key.in_(keys)))).scalars().all()) if keys else set()
    imported = 0
    already_imported = 0
    unmatched: list[PreventiveImportMatch] = []
    seen_keys = set(existing_keys)
    for item in payload.items:
        code = item.equipment_inventory_id.strip()
        if not code:
            continue
        source_key = preventive_source_key(item.source_plan_id, item)
        if source_key in seen_keys:
            already_imported += 1
            continue
        row, reason = _resolve_equipment(item, by_code, by_id)
        if not row:
            unmatched.append(PreventiveImportMatch(
                source_plan_id=item.source_plan_id,
                equipment_inventory_id=code,
                equipment_id=None,
                equipment_display_name=None,
                status="UNMATCHED",
                reason=reason,
            ))
            continue
        equipment, area, plant = row
        mismatch = _import_mismatch(item, equipment, area, plant)
        if mismatch:
            unmatched.append(PreventiveImportMatch(
                source_plan_id=item.source_plan_id,
                equipment_inventory_id=code,
                equipment_id=equipment.id,
                equipment_display_name=f"{equipment.name} · {area.name}",
                status="NAME_DIFFERS",
                reason=mismatch,
            ))
            continue
        seen_keys.add(source_key)
        periodicity, interval = periodicity_from_template(item.periodicity)
        db.add(PreventivePlan(
            equipment_id=equipment.id,
            source_key=source_key,
            source_plan_id=item.source_plan_id,
            periodicity=periodicity,
            interval_months=interval,
            planned_month=item.planned_month,
            last_completed_date=item.last_completed_date,
            next_due_date=item.next_due_date,
            description=item.description,
            spare_parts=item.spare_parts,
            estimated_time=item.estimated_time,
            condition=item.condition,
            observations=item.observations,
            # The spreadsheet's "personal asignado" is informational only;
            # users select the actual responsible worker inside the app.
            responsible_name_hint=None,
            created_by_user_id=current_user.id,
        ))
        imported += 1
    await db.commit()
    return PreventiveImportResult(imported=imported, already_imported=already_imported, unmatched=unmatched)


@router.post("/plans/{plan_id}/generate-ot")
async def generate_work_order(
    plan_id: int,
    payload: GeneratePreventiveWorkOrder,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    row = await _get_plan_with_equipment(db, plan_id, lock=True)
    if not row:
        raise HTTPException(status_code=404, detail="Plan preventivo no encontrado.")
    plan, equipment, area, plant_area = row
    if not plan.active:
        raise HTTPException(status_code=409, detail="El plan preventivo está inactivo.")
    if not plan.description or not plan.description.strip():
        raise HTTPException(status_code=409, detail="Completa la descripción del preventivo antes de generar la OT.")
    if not plan.next_due_date or not _interval(plan.periodicity, plan.interval_months):
        raise HTTPException(status_code=409, detail="Completa la periodicidad y próxima fecha del preventivo antes de generar la OT.")
    open_order = await db.scalar(select(WorkOrder.id).where(
        WorkOrder.preventive_plan_id == plan.id,
        WorkOrder.status.in_(OPEN_STATUSES),
    ).limit(1))
    if open_order:
        raise HTTPException(status_code=409, detail="Este preventivo ya tiene una OT abierta.")
    responsible_id = payload.responsible_user_id or plan.default_responsible_user_id
    responsible = await db.get(User, responsible_id) if responsible_id else None
    if not responsible or not responsible.is_active:
        raise HTTPException(status_code=422, detail="Selecciona un responsable activo para la OT preventiva.")

    parent = plant_area
    if parent is None:
        parents = (await db.execute(
            select(PlantArea)
            .join(plant_area_sections, plant_area_sections.c.plant_area_id == PlantArea.id)
            .where(plant_area_sections.c.section_id == equipment.area_id, PlantArea.is_active.is_(True))
        )).scalars().all()
        if len(parents) == 1:
            parent = parents[0]
    if parent is None:
        raise HTTPException(status_code=409, detail="Asigna el equipo a un área general activa en el inventario antes de generar la OT.")

    today = _today()
    request = WorkOrderCreate(
        title=f"Preventivo: {equipment.name}"[:300],
        description=plan.description.strip(),
        area_id=area.id,
        plant_area=parent.name,
        equipment_id=equipment.id,
        maintenance_type="PREVENTIVE",
        loto_status=LotoStatus.NOT_APPLICABLE.value,
        loto_controls=["NOT_APPLICABLE"],
        estimated_time=plan.estimated_time,
        request_date=today,
        execution_date=None,
        resources_required=plan.spare_parts,
        observations=plan.observations,
        responsible_user_id=responsible.id,
        participant_user_ids=[responsible.id],
        is_planned=True,
        scheduled_date=plan.next_due_date,
        due_date=plan.next_due_date,
        emit=True,
        preventive_plan_id=plan.id,
    )
    return await work_order_routes.create_work_order(request, background_tasks, db, current_user)


@router.get("/plans/{plan_id}/work-orders", response_model=list[PreventiveWorkOrderSummary])
async def list_plan_work_orders(
    plan_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    if not await db.get(PreventivePlan, plan_id):
        raise HTTPException(status_code=404, detail="Plan preventivo no encontrado.")
    rows = (await db.execute(
        select(WorkOrder)
        .where(WorkOrder.preventive_plan_id == plan_id)
        .order_by(WorkOrder.created_at.desc(), WorkOrder.id.desc())
    )).scalars().all()
    return [PreventiveWorkOrderSummary(
        id=wo.id, ot_number=wo.ot_number, status=wo.status, created_at=wo.created_at, completed_at=wo.completed_at
    ) for wo in rows]
