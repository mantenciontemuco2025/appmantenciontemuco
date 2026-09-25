"""Material-code catalog for work orders."""

import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, require_roles
from app.db.session import get_db
from app.models.material_catalog import MaterialCatalog
from app.models.user import User, UserRole
from app.services.audit_service import create_audit_log


router = APIRouter(prefix="/api/materials", tags=["materials"])
admin_router = APIRouter(prefix="/api/admin/materials", tags=["admin-materials"])
admin_only = require_roles(UserRole.ADMIN)

CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._/]*$")


class MaterialItemOut(BaseModel):
    id: int
    code: str
    description: str
    family: str
    active: bool

    model_config = {"from_attributes": True}


class MaterialWrite(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    description: str = Field(min_length=1, max_length=500)
    family: str = Field(default="Sin familia", min_length=1, max_length=180)
    source_sheet: str | None = Field(default=None, max_length=180)
    active: bool = True


class MaterialUpdate(BaseModel):
    description: str | None = Field(default=None, min_length=1, max_length=500)
    family: str | None = Field(default=None, min_length=1, max_length=180)
    active: bool | None = None


class MaterialImportItem(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    description: str = Field(min_length=1, max_length=500)
    family: str = Field(default="Sin familia", min_length=1, max_length=180)
    source_sheet: str | None = Field(default=None, max_length=180)


class MaterialImportPayload(BaseModel):
    items: list[MaterialImportItem] = Field(min_length=1, max_length=10000)


class MaterialImportResult(BaseModel):
    received: int
    created: int
    updated: int
    skipped: int


class MaterialCatalogPage(BaseModel):
    items: list[MaterialItemOut]
    total: int
    families: list[str]


def _normalize_code(value: str) -> str:
    code = value.strip().upper()
    if not CODE_PATTERN.fullmatch(code):
        raise HTTPException(
            status_code=400,
            detail=f"Código inválido: {value!r}. Usa letras, números, punto, guion bajo o /."
        )
    return code


def _normalize_text(value: str, label: str) -> str:
    text = " ".join(value.strip().split())
    if not text:
        raise HTTPException(status_code=400, detail=f"La {label} no puede estar vacía.")
    return text


@router.get("", response_model=list[MaterialItemOut])
async def list_active_materials(
    query: str = Query(default="", max_length=100),
    family: str | None = Query(default=None, max_length=180),
    limit: int = Query(default=2500, ge=1, le=5000),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[MaterialCatalog]:
    """Search active materials for OT forms."""
    statement = select(MaterialCatalog).where(MaterialCatalog.active.is_(True))
    query = query.strip()
    if query:
        term = f"%{query}%"
        statement = statement.where(
            or_(
                MaterialCatalog.code.ilike(term),
                MaterialCatalog.description.ilike(term),
                MaterialCatalog.family.ilike(term),
            )
        )
    if family:
        statement = statement.where(MaterialCatalog.family == family.strip())
    result = await db.execute(
        statement.order_by(MaterialCatalog.family, MaterialCatalog.code).limit(limit)
    )
    return list(result.scalars().all())


@admin_router.get("", response_model=MaterialCatalogPage)
async def list_material_catalog(
    query: str = Query(default="", max_length=100),
    include_inactive: bool = False,
    limit: int = Query(default=5000, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(admin_only),
) -> MaterialCatalogPage:
    statement = select(MaterialCatalog)
    count_statement = select(func.count()).select_from(MaterialCatalog)
    query = query.strip()
    if not include_inactive:
        statement = statement.where(MaterialCatalog.active.is_(True))
        count_statement = count_statement.where(MaterialCatalog.active.is_(True))
    if query:
        term = f"%{query}%"
        condition = or_(
            MaterialCatalog.code.ilike(term),
            MaterialCatalog.description.ilike(term),
            MaterialCatalog.family.ilike(term),
        )
        statement = statement.where(condition)
        count_statement = count_statement.where(condition)
    total = int((await db.scalar(count_statement)) or 0)
    rows = await db.execute(
        statement.order_by(MaterialCatalog.family, MaterialCatalog.code).offset(offset).limit(limit)
    )
    family_rows = await db.execute(
        select(MaterialCatalog.family)
        .where(MaterialCatalog.active.is_(True))
        .distinct()
        .order_by(MaterialCatalog.family)
    )
    return MaterialCatalogPage(
        items=list(rows.scalars().all()),
        total=total,
        families=list(family_rows.scalars().all()),
    )


@admin_router.post("", response_model=MaterialItemOut, status_code=status.HTTP_201_CREATED)
async def create_material(
    payload: MaterialWrite,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
) -> MaterialCatalog:
    code = _normalize_code(payload.code)
    exists = await db.scalar(select(MaterialCatalog).where(MaterialCatalog.code == code))
    if exists is not None:
        raise HTTPException(status_code=409, detail=f"El código {code} ya existe.")
    material = MaterialCatalog(
        code=code,
        description=_normalize_text(payload.description, "descripción"),
        family=_normalize_text(payload.family, "familia"),
        source_sheet=payload.source_sheet,
        active=payload.active,
    )
    db.add(material)
    await db.flush()
    await create_audit_log(
        db,
        user_id=current_user.id,
        action="CREATE",
        entity_type="MaterialCatalog",
        entity_id=material.id,
        new_data={"code": material.code, "description": material.description, "family": material.family},
    )
    return material


@admin_router.patch("/{material_id}", response_model=MaterialItemOut)
async def update_material(
    material_id: int,
    payload: MaterialUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
) -> MaterialCatalog:
    material = await db.get(MaterialCatalog, material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="Material no encontrado.")
    previous = {"description": material.description, "family": material.family, "active": material.active}
    if payload.description is not None:
        material.description = _normalize_text(payload.description, "descripción")
    if payload.family is not None:
        material.family = _normalize_text(payload.family, "familia")
    if payload.active is not None:
        material.active = payload.active
    await create_audit_log(
        db,
        user_id=current_user.id,
        action="UPDATE",
        entity_type="MaterialCatalog",
        entity_id=material.id,
        previous_data=previous,
        new_data={"description": material.description, "family": material.family, "active": material.active},
    )
    return material


@admin_router.post("/import", response_model=MaterialImportResult)
async def import_materials(
    payload: MaterialImportPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
) -> MaterialImportResult:
    """Upsert a catalog export parsed from the workbook in the admin UI."""
    normalized: dict[str, MaterialImportItem] = {}
    skipped = 0
    for item in payload.items:
        try:
            code = _normalize_code(item.code)
        except HTTPException:
            skipped += 1
            continue
        normalized[code] = item.model_copy(update={"code": code})
    if not normalized:
        raise HTTPException(status_code=400, detail="No hay códigos válidos para importar.")

    existing_rows = await db.execute(
        select(MaterialCatalog).where(MaterialCatalog.code.in_(list(normalized)))
    )
    existing = {row.code: row for row in existing_rows.scalars().all()}
    created = updated = 0
    for code, item in normalized.items():
        description = _normalize_text(item.description, "descripción")
        family = _normalize_text(item.family, "familia")
        material = existing.get(code)
        if material is None:
            db.add(MaterialCatalog(
                code=code,
                description=description,
                family=family,
                source_sheet=item.source_sheet,
                active=True,
            ))
            created += 1
        else:
            material.description = description
            material.family = family
            material.source_sheet = item.source_sheet
            material.active = True
            updated += 1
    await db.flush()
    await create_audit_log(
        db,
        user_id=current_user.id,
        action="IMPORT",
        entity_type="MaterialCatalog",
        entity_id=None,
        new_data={"received": len(payload.items), "created": created, "updated": updated, "skipped": skipped},
    )
    return MaterialImportResult(
        received=len(payload.items), created=created, updated=updated, skipped=skipped
    )
