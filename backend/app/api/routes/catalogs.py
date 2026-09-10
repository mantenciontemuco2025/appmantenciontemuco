"""Catalog CRUD: Areas, Equipment (Area -> Equipment directly).

- Reading catalogs (for the maintenance form) is available to any
  authenticated user.
- Creating/updating is restricted to ADMIN.

Section is NOT part of the catalog — it is free text on each record.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dependencies import get_current_user, require_roles
from app.db.session import get_db
from app.models.user import User, UserRole
from app.models.area import Area
from app.models.equipment import Equipment
from app.schemas.catalog import (
    AreaCreate,
    AreaResponse,
    AreaWithEquipment,
    AreaUpdate,
    EquipmentCreate,
    EquipmentResponse,
    EquipmentUpdate,
)
from app.services.audit_service import create_audit_log

router = APIRouter(prefix="/api/catalogs", tags=["catalogs"])

admin_only = require_roles(UserRole.ADMIN)


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
    area = Area(name=payload.name.strip())
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
        area.name = payload.name.strip()
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


@router.post("/equipment", response_model=EquipmentResponse, status_code=status.HTTP_201_CREATED)
async def create_equipment(
    payload: EquipmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    area = await db.get(Area, payload.area_id)
    if area is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Área no válida")
    equipment = Equipment(name=payload.name.strip(), area_id=payload.area_id)
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
    previous = {"name": equipment.name, "area_id": equipment.area_id}
    if payload.name is not None:
        equipment.name = payload.name.strip()
    if payload.area_id is not None:
        if await db.get(Area, payload.area_id) is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Área no válida")
        equipment.area_id = payload.area_id
    await create_audit_log(
        db, user_id=current_user.id, action="UPDATE",
        entity_type="Equipment", entity_id=equipment.id,
        previous_data=previous,
        new_data={"name": equipment.name, "area_id": equipment.area_id},
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
    await create_audit_log(
        db, user_id=current_user.id, action="DELETE",
        entity_type="Equipment", entity_id=equipment.id,
        previous_data={"name": equipment.name, "area_id": equipment.area_id},
    )
    await db.delete(equipment)
