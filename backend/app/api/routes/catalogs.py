"""Catalog CRUD: Areas, Equipment (Area -> Equipment directly).

- Reading catalogs (for the maintenance form) is available to any
  authenticated user.
- Creating/updating is restricted to ADMIN.

Section is NOT part of the catalog — it is free text on each record.
"""

import unicodedata

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import Date, cast, delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dependencies import get_current_user, require_roles
from app.db.session import get_db
from app.models.user import User, UserRole
from app.models.area import Area
from app.models.equipment import Equipment
from app.models.plant_area import PlantArea, plant_area_sections
from app.models.maintenance import MaintenanceRecord
from app.models.work_order import WorkOrder, WorkOrderStatus
from app.models.supervisor_area import supervisor_areas
from app.schemas.catalog import (
    AreaCreate,
    AreaResponse,
    AreaWithEquipment,
    AreaUpdate,
    PlantAreaCreate,
    PlantAreaResponse,
    PlantAreaUpdate,
    PlantAreaSectionCreate,
    PlantAreaWorkOrderBrief,
    EquipmentCreate,
    EquipmentResponse,
    EquipmentUpdate,
    EquipmentInventoryUpdate,
    EquipmentInventoryResponse,
    InventoryImportPayload,
    InventoryImportResult,
    HierarchyEquipment,
    PlantAreaWithSections,
    SectionWithEquipment,
)
from app.services.audit_service import create_audit_log

router = APIRouter(prefix="/api/catalogs", tags=["catalogs"])


async def _section_parent_areas(
    db: AsyncSession, section_ids: set[int]
) -> dict[int, list[tuple[int, str]]]:
    """Map sections to linked parent areas for legacy equipment without a parent id."""
    if not section_ids:
        return {}
    result = await db.execute(
        select(plant_area_sections.c.section_id, PlantArea.id, PlantArea.name)
        .join(PlantArea, PlantArea.id == plant_area_sections.c.plant_area_id)
        .where(plant_area_sections.c.section_id.in_(section_ids))
        .order_by(PlantArea.name)
    )
    parents: dict[int, list[tuple[int, str]]] = {}
    for section_id, plant_area_id, plant_area_name in result.all():
        parents.setdefault(section_id, []).append((plant_area_id, plant_area_name))
    return parents

admin_only = require_roles(UserRole.ADMIN)
catalog_writer = require_roles(UserRole.ADMIN, UserRole.SUPERVISOR)


# --------------------------------------------------------------------------
# Hierarchical inventory catalog (plant area -> section -> physical equipment)
# --------------------------------------------------------------------------
@router.get("/hierarchy", response_model=list[PlantAreaWithSections])
async def get_catalog_hierarchy(
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the inventory hierarchy while preserving the legacy /tree API."""
    if include_inactive and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Solo administradores pueden ver áreas inactivas")
    statement = select(PlantArea).options(
        selectinload(PlantArea.sections).selectinload(Area.equipment)
    )
    if not include_inactive:
        statement = statement.where(PlantArea.is_active.is_(True))
    result = await db.execute(statement.order_by(PlantArea.name))
    response: list[PlantAreaWithSections] = []
    for plant in result.scalars().all():
        sections = []
        for section in plant.sections:
            equipment = [
                HierarchyEquipment.model_validate(item)
                for item in section.equipment
                if item.plant_area_id == plant.id
            ]
            sections.append(
                SectionWithEquipment(
                    id=section.id,
                    name=section.name,
                    equipment=equipment,
                )
            )
        response.append(
            PlantAreaWithSections(
                id=plant.id,
                name=plant.name,
                is_active=plant.is_active,
                sections=sections,
            )
        )
    return response


# --------------------------------------------------------------------------
# Plant areas (general areas) -> sections -> equipment
# --------------------------------------------------------------------------
@router.get("/plant-areas", response_model=list[PlantAreaResponse])
async def list_plant_areas(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(PlantArea).order_by(PlantArea.name))
    return result.scalars().all()


@router.post("/plant-areas/{plant_area_id}/sections", status_code=status.HTTP_201_CREATED)
async def create_or_link_plant_area_section(
    plant_area_id: int,
    payload: PlantAreaSectionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    """Create a section (or reuse its existing catalog row) under an area.

    OTs store their own area/section/equipment snapshot, so linking catalog
    rows here does not rewrite historical work orders.
    """
    plant_area = await db.get(PlantArea, plant_area_id)
    if plant_area is None:
        raise HTTPException(status_code=404, detail="Área general no encontrada")

    name = " ".join(payload.name.split())
    section = await db.scalar(
        select(Area).where(func.lower(func.trim(Area.name)) == name.lower()).limit(1)
    )
    created = section is None
    if section is None:
        section = Area(name=name)
        db.add(section)
        await db.flush()

    linked = await db.scalar(
        select(plant_area_sections.c.section_id).where(
            plant_area_sections.c.plant_area_id == plant_area_id,
            plant_area_sections.c.section_id == section.id,
        )
    )
    if linked is not None:
        raise HTTPException(status_code=409, detail="La sección ya está asociada a esta área")

    await db.execute(
        insert(plant_area_sections).values(
            plant_area_id=plant_area_id,
            section_id=section.id,
        )
    )
    # Legacy equipment rows did not have a plant-area assignment. Attach only
    # those unscoped rows; equipment already scoped elsewhere remains there.
    await db.execute(
        update(Equipment)
        .where(
            Equipment.area_id == section.id,
            Equipment.plant_area_id.is_(None),
        )
        .values(plant_area_id=plant_area_id)
    )
    await create_audit_log(
        db,
        user_id=current_user.id,
        action="LINK",
        entity_type="PlantAreaSection",
        entity_id=section.id,
        new_data={
            "plant_area_id": plant_area.id,
            "plant_area_name": plant_area.name,
            "section_id": section.id,
            "section_name": section.name,
            "created": created,
        },
    )
    await db.flush()
    return {"section_id": section.id, "section_name": section.name, "created": created}


@router.post("/plant-areas/{plant_area_id}/sections/{section_id}", status_code=status.HTTP_201_CREATED)
async def link_existing_plant_area_section(
    plant_area_id: int,
    section_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    plant_area = await db.get(PlantArea, plant_area_id)
    section = await db.get(Area, section_id)
    if plant_area is None or section is None:
        raise HTTPException(status_code=404, detail="Área o sección no encontrada")
    linked = await db.scalar(
        select(plant_area_sections.c.section_id).where(
            plant_area_sections.c.plant_area_id == plant_area_id,
            plant_area_sections.c.section_id == section_id,
        )
    )
    if linked is not None:
        raise HTTPException(status_code=409, detail="La sección ya está asociada a esta área")
    await db.execute(
        insert(plant_area_sections).values(
            plant_area_id=plant_area_id,
            section_id=section_id,
        )
    )
    await db.execute(
        update(Equipment)
        .where(Equipment.area_id == section_id, Equipment.plant_area_id.is_(None))
        .values(plant_area_id=plant_area_id)
    )
    await create_audit_log(
        db,
        user_id=current_user.id,
        action="LINK",
        entity_type="PlantAreaSection",
        entity_id=section.id,
        new_data={"plant_area_id": plant_area.id, "section_id": section.id},
    )
    await db.flush()
    return {"section_id": section.id, "section_name": section.name}


@router.delete(
    "/plant-areas/{plant_area_id}/sections/{section_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unlink_plant_area_section(
    plant_area_id: int,
    section_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    plant_area = await db.get(PlantArea, plant_area_id)
    section = await db.get(Area, section_id)
    if plant_area is None or section is None:
        raise HTTPException(status_code=404, detail="Área o sección no encontrada")
    linked = await db.scalar(
        select(plant_area_sections.c.section_id).where(
            plant_area_sections.c.plant_area_id == plant_area_id,
            plant_area_sections.c.section_id == section_id,
        )
    )
    if linked is None:
        raise HTTPException(status_code=404, detail="La sección no está asociada a esta área")
    await db.execute(
        delete(plant_area_sections).where(
            plant_area_sections.c.plant_area_id == plant_area_id,
            plant_area_sections.c.section_id == section_id,
        )
    )
    await db.execute(
        update(Equipment)
        .where(Equipment.area_id == section_id, Equipment.plant_area_id == plant_area_id)
        .values(plant_area_id=None)
    )
    await create_audit_log(
        db,
        user_id=current_user.id,
        action="UNLINK",
        entity_type="PlantAreaSection",
        entity_id=section.id,
        previous_data={"plant_area_id": plant_area.id, "section_id": section.id},
    )
    await db.flush()


@router.post("/plant-areas", response_model=PlantAreaResponse, status_code=status.HTTP_201_CREATED)
async def create_plant_area(
    payload: PlantAreaCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="El nombre del área general no puede estar vacío")
    duplicate = await db.scalar(select(PlantArea.id).where(PlantArea.name.ilike(name)).limit(1))
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="Ya existe un área general con ese nombre")
    area = PlantArea(name=name)
    db.add(area)
    await db.flush()
    await create_audit_log(
        db, user_id=current_user.id, action="CREATE",
        entity_type="PlantArea", entity_id=area.id, new_data={"name": area.name},
    )
    await db.refresh(area)
    return area


@router.patch("/plant-areas/{plant_area_id}", response_model=PlantAreaResponse)
async def update_plant_area(
    plant_area_id: int,
    payload: PlantAreaUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    area = await db.get(PlantArea, plant_area_id)
    if area is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Área general no encontrada")
    previous = {"name": area.name, "is_active": area.is_active}
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="El nombre del área general no puede estar vacío")
        duplicate = await db.scalar(
            select(PlantArea.id).where(
                PlantArea.id != plant_area_id,
                PlantArea.name.ilike(name),
            ).limit(1)
        )
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="Ya existe un área general con ese nombre")
        area.name = name
    if payload.is_active is not None:
        area.is_active = payload.is_active
    await create_audit_log(
        db, user_id=current_user.id, action="UPDATE",
        entity_type="PlantArea", entity_id=area.id,
        previous_data=previous,
        new_data={"name": area.name, "is_active": area.is_active},
    )
    await db.refresh(area)
    return area


@router.delete("/plant-areas/{plant_area_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_plant_area(
    plant_area_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    area = await db.get(PlantArea, plant_area_id)
    if area is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Área general no encontrada")
    normalized_name = area.name.strip().upper()
    has_work_order = await db.scalar(
        select(WorkOrder.id)
        .where(func.upper(func.trim(WorkOrder.plant_area)) == normalized_name)
        .limit(1)
    )
    if has_work_order is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se puede eliminar el área general porque tiene OTs asociadas",
        )
    await create_audit_log(
        db, user_id=current_user.id, action="DELETE",
        entity_type="PlantArea", entity_id=area.id,
        previous_data={"name": area.name},
    )
    await db.delete(area)


@router.get("/plant-areas/{plant_area_id}/work-orders", response_model=list[PlantAreaWorkOrderBrief])
async def list_plant_area_work_orders(
    plant_area_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    area = await db.get(PlantArea, plant_area_id)
    if area is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Área general no encontrada")
    normalized_name = area.name.strip().upper()
    result = await db.execute(
        select(WorkOrder)
        .where(func.upper(func.trim(WorkOrder.plant_area)) == normalized_name)
        .order_by(WorkOrder.created_at.desc(), WorkOrder.id.desc())
    )
    return result.scalars().all()


@router.post("/inventory/import", response_model=InventoryImportResult)
async def import_inventory_catalog(
    payload: InventoryImportPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
) -> InventoryImportResult:
    """Upsert the workbook's physical inventory without rewriting old OTs."""
    seen_codes: set[str] = set()
    plant_areas: dict[str, PlantArea] = {}
    sections: dict[str, Area] = {}
    areas_created = sections_created = links_created = 0
    equipment_created = equipment_updated = skipped = 0
    errors: list[str] = []

    def clean(value: str | None) -> str:
        return " ".join((value or "").strip().split())

    def key(value: str) -> str:
        return "".join(
            char for char in unicodedata.normalize("NFD", clean(value)).casefold()
            if unicodedata.category(char) != "Mn"
        )

    for item in payload.items:
        code = clean(item.inventory_code)
        plant_name = clean(item.plant_area)
        section_name = clean(item.section)
        equipment_name = clean(item.equipment)
        if not code or not plant_name or not section_name or not equipment_name:
            skipped += 1
            errors.append(f"Registro incompleto para ID {code or '[sin ID]'}.")
            continue
        code = code.upper()
        if code in seen_codes:
            skipped += 1
            errors.append(f"ID de inventario repetido en la importación: {code}.")
            continue
        seen_codes.add(code)

        plant_key = key(plant_name)
        plant = plant_areas.get(plant_key)
        if plant is None:
            plant_rows = (await db.execute(select(PlantArea))).scalars().all()
            plant = next((row for row in plant_rows if key(row.name) == plant_key), None)
            if plant is None:
                plant = PlantArea(name=plant_name)
                db.add(plant)
                await db.flush()
                areas_created += 1
            plant_areas[plant_key] = plant

        section_key = key(section_name)
        section = sections.get(section_key)
        if section is None:
            section_rows = (await db.execute(select(Area))).scalars().all()
            section = next((row for row in section_rows if key(row.name) == section_key), None)
            if section is None:
                section = Area(name=section_name)
                db.add(section)
                await db.flush()
                sections_created += 1
            sections[section_key] = section

        linked = await db.scalar(
            select(plant_area_sections.c.plant_area_id).where(
                plant_area_sections.c.plant_area_id == plant.id,
                plant_area_sections.c.section_id == section.id,
            )
        )
        if linked is None:
            await db.execute(
                insert(plant_area_sections).values(
                    plant_area_id=plant.id,
                    section_id=section.id,
                )
            )
            links_created += 1

        equipment = await db.scalar(
            select(Equipment).where(Equipment.inventory_code == code)
        )
        values = {
            "name": equipment_name,
            "area_id": section.id,
            "plant_area_id": plant.id,
            "inventory_code": code,
        }
        optional_fields = (
            "category",
            "model",
            "dimensions",
            "weight",
            "unit",
            "description",
            "location",
            "purchase_receipt_date",
            "purchased_from",
            "warranty_end",
            "web1",
            "initial_value",
            "impeller_diameter",
            "flow_rate",
            "total_manometric_head",
            "rotation_speed",
            "npsh",
            "operational_status",
            "general_spare_parts",
            "observations",
            "power_hp",
            "power_kw",
            "voltage",
            "current",
            "revolutions",
            "efficiency",
            "capacity",
        )
        for field in optional_fields:
            value = getattr(item, field)
            if isinstance(value, str):
                value = clean(value) or None
            # Empty workbook cells mean "no update". This keeps existing
            # inventory details from being erased by blanks in a new import.
            if value is not None:
                values[field] = value
        if equipment is None:
            db.add(Equipment(**values))
            equipment_created += 1
        else:
            for field, value in values.items():
                setattr(equipment, field, value)
            equipment_updated += 1

    await db.flush()
    await create_audit_log(
        db,
        user_id=current_user.id,
        action="IMPORT",
        entity_type="InventoryCatalog",
        entity_id=None,
        new_data={
            "received": len(payload.items),
            "areas_created": areas_created,
            "sections_created": sections_created,
            "links_created": links_created,
            "equipment_created": equipment_created,
            "equipment_updated": equipment_updated,
            "skipped": skipped,
        },
    )
    return InventoryImportResult(
        received=len(payload.items),
        areas_created=areas_created,
        sections_created=sections_created,
        links_created=links_created,
        equipment_created=equipment_created,
        equipment_updated=equipment_updated,
        skipped=skipped,
        errors=errors[:100],
    )


# --------------------------------------------------------------------------
# Combined tree (areas -> equipment) for the form selectors
# --------------------------------------------------------------------------
@router.get("/tree", response_model=list[AreaWithEquipment])
async def get_catalog_tree(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Area)
        .options(selectinload(Area.equipment))
        .order_by(Area.name)
    )
    return result.scalars().all()


# --------------------------------------------------------------------------
# Areas
# --------------------------------------------------------------------------
@router.get("/areas", response_model=list[AreaResponse])
async def list_areas(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Area).order_by(Area.name))
    return result.scalars().all()


@router.post("/areas", response_model=AreaResponse, status_code=status.HTTP_201_CREATED)
async def create_area(
    payload: AreaCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="El nombre del área no puede estar vacío")
    duplicate = await db.scalar(select(Area.id).where(Area.name.ilike(name)).limit(1))
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="Ya existe un área con ese nombre")
    area = Area(name=name)
    db.add(area)
    await db.flush()
    await create_audit_log(
        db, user_id=current_user.id, action="CREATE",
        entity_type="Area", entity_id=area.id, new_data={"name": area.name},
    )
    await db.refresh(area)
    return area


@router.patch("/areas/{area_id}", response_model=AreaResponse)
async def update_area(
    area_id: int,
    payload: AreaUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    result = await db.execute(select(Area).where(Area.id == area_id))
    area = result.scalar_one_or_none()
    if area is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Área no encontrada")
    previous = {"name": area.name}
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="El nombre del área no puede estar vacío")
        duplicate = await db.scalar(
            select(Area.id).where(Area.id != area_id, Area.name.ilike(name)).limit(1)
        )
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="Ya existe un área con ese nombre")
        area.name = name
    await create_audit_log(
        db, user_id=current_user.id, action="UPDATE",
        entity_type="Area", entity_id=area.id,
        previous_data=previous, new_data={"name": area.name},
    )
    await db.refresh(area)
    return area


@router.delete("/areas/{area_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_area(
    area_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    result = await db.execute(select(Area).where(Area.id == area_id))
    area = result.scalar_one_or_none()
    if area is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Área no encontrada")
    dependencies = [
        ("tipos de equipo", select(Equipment.id).where(Equipment.area_id == area_id)),
        ("órdenes de trabajo", select(WorkOrder.id).where(WorkOrder.area_id == area_id)),
        ("registros de mantención", select(MaintenanceRecord.id).where(MaintenanceRecord.area_id == area_id)),
        ("usuarios", select(User.id).where(User.area_id == area_id)),
        ("asignaciones de supervisores", select(supervisor_areas.c.supervisor_id).where(supervisor_areas.c.area_id == area_id)),
    ]
    for label, query in dependencies:
        if (await db.execute(query.limit(1))).first() is not None:
            raise HTTPException(
                status_code=409,
                detail=f"No se puede eliminar el área porque tiene {label} asociados",
            )
    await create_audit_log(
        db, user_id=current_user.id, action="DELETE",
        entity_type="Area", entity_id=area.id, previous_data={"name": area.name},
    )
    await db.delete(area)


# --------------------------------------------------------------------------
# Equipment (types, belongs directly to an area)
# --------------------------------------------------------------------------
@router.get("/equipment", response_model=list[EquipmentResponse])
async def list_equipment(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Equipment).order_by(Equipment.name))
    return result.scalars().all()


@router.get("/equipment-inventory", response_model=list[EquipmentInventoryResponse])
async def list_equipment_inventory(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Equipment, Area.id, Area.name, PlantArea.id, PlantArea.name)
        .outerjoin(Area, Equipment.area_id == Area.id)
        .outerjoin(PlantArea, Equipment.plant_area_id == PlantArea.id)
        .order_by(Equipment.name, Equipment.id)
    )
    equipment_rows = result.all()
    equipment_ids = [equipment.id for equipment, *_ in equipment_rows]
    section_ids = {equipment.area_id for equipment, *_ in equipment_rows}
    parent_areas = await _section_parent_areas(db, section_ids)
    latest_work_order_dates: dict[int, object] = {}
    if equipment_ids:
        execution_date = func.coalesce(
            WorkOrder.execution_date, cast(WorkOrder.completed_at, Date)
        )
        latest_result = await db.execute(
            select(WorkOrder.equipment_id, func.max(execution_date))
            .where(
                WorkOrder.equipment_id.in_(equipment_ids),
                WorkOrder.status.in_(
                    [WorkOrderStatus.COMPLETED.value, WorkOrderStatus.APPROVED.value]
                ),
                execution_date.is_not(None),
            )
            .group_by(WorkOrder.equipment_id)
        )
        latest_work_order_dates = dict(latest_result.all())

    rows = []
    for equipment, area_id, area_name, plant_area_id, plant_area_name in equipment_rows:
        # Older catalog equipment may only have the legacy section (area_id).
        # If that section belongs to one parent area, display it in that area;
        # when the section belongs to several, keep it explicitly unassigned.
        if plant_area_id is None:
            candidates = parent_areas.get(equipment.area_id, [])
            if len(candidates) == 1:
                plant_area_id, plant_area_name = candidates[0]
        item = EquipmentInventoryResponse(
            **{
                field: getattr(equipment, field)
                for field in EquipmentInventoryResponse.model_fields
                if field not in {"area_id", "plant_area_id", "area_name", "plant_area_name"}
            },
            area_id=area_id,
            plant_area_id=plant_area_id,
            area_name=area_name,
            plant_area_name=plant_area_name,
        )
        item.last_maintenance_date = latest_work_order_dates.get(equipment.id)
        if current_user.role != UserRole.ADMIN:
            item.initial_value = None
        rows.append(item)
    return rows


@router.patch("/equipment/{equipment_id}/inventory", response_model=EquipmentInventoryResponse)
async def update_equipment_inventory(
    equipment_id: int,
    payload: EquipmentInventoryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    can_edit_inventory = current_user.role == UserRole.ADMIN or (
        current_user.role == UserRole.WORKER
        and current_user.can_manage_equipment_inventory
    )
    if not can_edit_inventory:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para editar el inventario de equipos.",
        )
    if (
        current_user.role != UserRole.ADMIN
        and "initial_value" in payload.model_fields_set
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo un administrador puede modificar el valor inicial.",
        )
    result = await db.execute(
        select(Equipment, Area.id, Area.name, PlantArea.id, PlantArea.name)
        .outerjoin(Area, Equipment.area_id == Area.id)
        .outerjoin(PlantArea, Equipment.plant_area_id == PlantArea.id)
        .where(Equipment.id == equipment_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Equipo no encontrado")
    equipment, area_id, area_name, plant_area_id, plant_area_name = row
    if plant_area_id is None:
        candidates = (await _section_parent_areas(db, {equipment.area_id})).get(
            equipment.area_id, []
        )
        if len(candidates) == 1:
            plant_area_id, plant_area_name = candidates[0]
    changes = payload.model_dump(exclude_unset=True, mode="json")
    previous = {
        key: (getattr(equipment, key).isoformat() if hasattr(getattr(equipment, key), "isoformat") else getattr(equipment, key))
        for key in changes
    }
    for key, value in payload.model_dump(exclude_unset=True).items():
        if isinstance(value, str):
            value = value.strip() or None
        setattr(equipment, key, value)
    await create_audit_log(
        db,
        user_id=current_user.id,
        action="UPDATE",
        entity_type="EquipmentInventory",
        entity_id=equipment.id,
        previous_data=jsonable_encoder(previous),
        new_data=changes,
    )
    await db.flush()
    response = EquipmentInventoryResponse(
        **{
            field: getattr(equipment, field)
            for field in EquipmentInventoryResponse.model_fields
            if field not in {"area_id", "plant_area_id", "area_name", "plant_area_name"}
        },
        area_id=area_id,
        plant_area_id=plant_area_id,
        area_name=area_name,
        plant_area_name=plant_area_name,
    )
    execution_date = func.coalesce(
        WorkOrder.execution_date, cast(WorkOrder.completed_at, Date)
    )
    response.last_maintenance_date = await db.scalar(
        select(func.max(execution_date)).where(
            WorkOrder.equipment_id == equipment.id,
            WorkOrder.status.in_(
                [WorkOrderStatus.COMPLETED.value, WorkOrderStatus.APPROVED.value]
            ),
            execution_date.is_not(None),
        )
    )
    if current_user.role != UserRole.ADMIN:
        response.initial_value = None
    return response


@router.post("/equipment", response_model=EquipmentResponse, status_code=status.HTTP_201_CREATED)
async def create_equipment(
    payload: EquipmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(catalog_writer),
):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="El nombre del tipo de equipo no puede estar vacío")
    area = await db.get(Area, payload.area_id)
    if area is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Área no válida")
    if (
        current_user.role == UserRole.SUPERVISOR
        and payload.area_id not in current_user.area_ids
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo puedes agregar equipos a tus secciones asignadas",
        )
    duplicate_id = await db.scalar(
        select(Equipment.id).where(
            Equipment.area_id == payload.area_id,
            func.lower(func.trim(Equipment.name)) == name.lower(),
        ).limit(1)
    )
    if duplicate_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe un equipo con ese nombre en esta sección",
        )
    inventory_code = (payload.inventory_code or "").strip().upper() or None
    if inventory_code:
        duplicate_code = await db.scalar(
            select(Equipment.id).where(Equipment.inventory_code == inventory_code).limit(1)
        )
        if duplicate_code is not None:
            raise HTTPException(status_code=409, detail="Ya existe un equipo con ese ID de inventario")
    plant_area_id = payload.plant_area_id
    if plant_area_id is not None and await db.get(PlantArea, plant_area_id) is None:
        raise HTTPException(status_code=400, detail="Área de planta no válida")
    if plant_area_id is not None:
        linked = await db.scalar(
            select(plant_area_sections.c.section_id).where(
                plant_area_sections.c.plant_area_id == plant_area_id,
                plant_area_sections.c.section_id == payload.area_id,
            )
        )
        if linked is None:
            raise HTTPException(
                status_code=400,
                detail="Primero vincula la sección seleccionada con esa área.",
            )
    equipment = Equipment(
        name=name,
        area_id=payload.area_id,
        plant_area_id=plant_area_id,
        inventory_code=inventory_code,
        category=(payload.category or "").strip() or None,
        location=(payload.location or "").strip() or None,
        operational_status=(payload.operational_status or "").strip() or None,
    )
    db.add(equipment)
    await db.flush()
    await create_audit_log(
        db, user_id=current_user.id, action="CREATE",
        entity_type="Equipment", entity_id=equipment.id,
        new_data={"name": equipment.name, "area_id": equipment.area_id},
    )
    await db.refresh(equipment)
    return equipment


@router.patch("/equipment/{equipment_id}", response_model=EquipmentResponse)
async def update_equipment(
    equipment_id: int,
    payload: EquipmentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    result = await db.execute(select(Equipment).where(Equipment.id == equipment_id))
    equipment = result.scalar_one_or_none()
    if equipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Equipo no encontrado")
    previous = {
        "name": equipment.name,
        "area_id": equipment.area_id,
        "plant_area_id": equipment.plant_area_id,
        "inventory_code": equipment.inventory_code,
        "category": equipment.category,
        "location": equipment.location,
        "operational_status": equipment.operational_status,
    }
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="El nombre del tipo de equipo no puede estar vacío")
        equipment.name = name
    if payload.area_id is not None:
        if await db.get(Area, payload.area_id) is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Área no válida")
        equipment.area_id = payload.area_id
    if payload.plant_area_id is not None:
        if await db.get(PlantArea, payload.plant_area_id) is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Área de planta no válida")
        equipment.plant_area_id = payload.plant_area_id
    target_area_id = payload.area_id if payload.area_id is not None else equipment.area_id
    target_plant_area_id = (
        payload.plant_area_id
        if payload.plant_area_id is not None
        else equipment.plant_area_id
    )
    if target_plant_area_id is not None:
        linked = await db.scalar(
            select(plant_area_sections.c.section_id).where(
                plant_area_sections.c.plant_area_id == target_plant_area_id,
                plant_area_sections.c.section_id == target_area_id,
            )
        )
        if linked is None:
            raise HTTPException(
                status_code=400,
                detail="La sección no está asociada al área general seleccionada.",
            )
    if payload.inventory_code is not None:
        inventory_code = payload.inventory_code.strip().upper() or None
        duplicate = await db.scalar(
            select(Equipment.id).where(
                Equipment.inventory_code == inventory_code,
                Equipment.id != equipment_id,
            ).limit(1)
        ) if inventory_code else None
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="Ya existe un equipo con ese ID de inventario")
        equipment.inventory_code = inventory_code
    if payload.category is not None:
        equipment.category = payload.category.strip() or None
    if payload.location is not None:
        equipment.location = payload.location.strip() or None
    if payload.operational_status is not None:
        equipment.operational_status = payload.operational_status.strip() or None
    await create_audit_log(
        db, user_id=current_user.id, action="UPDATE",
        entity_type="Equipment", entity_id=equipment.id,
        previous_data=previous,
        new_data={
            "name": equipment.name,
            "area_id": equipment.area_id,
            "plant_area_id": equipment.plant_area_id,
            "inventory_code": equipment.inventory_code,
            "category": equipment.category,
            "location": equipment.location,
            "operational_status": equipment.operational_status,
        },
    )
    await db.refresh(equipment)
    return equipment


@router.delete("/equipment/{equipment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_equipment(
    equipment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    result = await db.execute(select(Equipment).where(Equipment.id == equipment_id))
    equipment = result.scalar_one_or_none()
    if equipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Equipo no encontrado")
    references = [
        select(WorkOrder.id).where(WorkOrder.equipment_id == equipment_id),
        select(MaintenanceRecord.id).where(MaintenanceRecord.equipment_id == equipment_id),
    ]
    for query in references:
        if (await db.execute(query.limit(1))).first() is not None:
            raise HTTPException(
                status_code=409,
                detail="No se puede eliminar el tipo de equipo porque está usado en registros existentes",
            )
    await create_audit_log(
        db, user_id=current_user.id, action="DELETE",
        entity_type="Equipment", entity_id=equipment.id,
        previous_data={"name": equipment.name, "area_id": equipment.area_id},
    )
    await db.delete(equipment)
