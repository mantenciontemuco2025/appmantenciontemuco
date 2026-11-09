import logging
import re

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import get_current_user, require_roles
from app.core.security import hash_password, verify_password
from app.db.session import get_db
from app.models.user import User, UserRole, WaterRegisterPermission
from app.models.area import Area
from app.models.plant_area import PlantArea, plant_area_sections
from app.models.audit_log import AuditLog
from app.models.work_order import WorkOrder
from app.schemas.user import PasswordChange, UserCreate, UserResponse, UserUpdate
from app.services.audit_service import create_audit_log
from app.services.signatures import delete_signature, get_signature_image, upload_signature

router = APIRouter(prefix="/api/users", tags=["users"])
logger = logging.getLogger(__name__)

admin_only = require_roles(UserRole.ADMIN)


async def _validated_supervisor_scope(
    db: AsyncSession,
    *,
    role: UserRole,
    plant_area_ids: list[int] | None,
    excluded_section_ids: list[int] | None,
    legacy_section_ids: list[int] | None,
) -> tuple[list[PlantArea], list[Area], list[Area]]:
    if role != UserRole.SUPERVISOR:
        return [], [], []

    requested_plant_ids = list(dict.fromkeys(plant_area_ids or []))
    requested_exclusions = list(dict.fromkeys(excluded_section_ids or []))
    requested_legacy_ids = list(dict.fromkeys(legacy_section_ids or []))
    if not requested_plant_ids and not requested_legacy_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Asigna al supervisor al menos un área o una sección sin área general.",
        )

    plant_result = await db.execute(
        select(PlantArea)
        .options(selectinload(PlantArea.sections))
        .where(PlantArea.id.in_(requested_plant_ids))
    ) if requested_plant_ids else None
    plants_by_id = {area.id: area for area in plant_result.scalars().all()} if plant_result else {}
    if set(plants_by_id) != set(requested_plant_ids):
        raise HTTPException(status_code=400, detail="Una de las áreas asignadas no existe.")

    linked_section_ids: set[int] = set()
    if requested_plant_ids:
        links = await db.execute(
            select(plant_area_sections.c.section_id).where(
                plant_area_sections.c.plant_area_id.in_(requested_plant_ids)
            )
        )
        linked_section_ids = {row[0] for row in links.all()}
    if not set(requested_exclusions).issubset(linked_section_ids):
        raise HTTPException(
            status_code=400,
            detail="Las secciones excluidas deben pertenecer a un área asignada.",
        )

    section_result = await db.execute(
        select(Area).where(Area.id.in_(requested_legacy_ids + requested_exclusions))
    ) if requested_legacy_ids or requested_exclusions else None
    sections_by_id = {section.id: section for section in section_result.scalars().all()} if section_result else {}
    if set(sections_by_id) != set(requested_legacy_ids + requested_exclusions):
        raise HTTPException(status_code=400, detail="Una de las secciones asignadas no existe.")
    if not ((linked_section_ids - set(requested_exclusions)) | set(requested_legacy_ids)):
        raise HTTPException(
            status_code=400,
            detail="Deja al menos una sección habilitada para el supervisor.",
        )
    legacy_sections = [sections_by_id[section_id] for section_id in requested_legacy_ids]
    excluded_sections = [sections_by_id[section_id] for section_id in requested_exclusions]
    return (
        [plants_by_id[area_id] for area_id in requested_plant_ids],
        excluded_sections,
        legacy_sections,
    )


def _user_scope_options():
    return (
        selectinload(User.supervised_areas),
        selectinload(User.supervised_plant_areas).selectinload(PlantArea.sections),
        selectinload(User.excluded_supervised_sections),
    )


def _detected_image_mime(contents: bytes) -> str | None:
    """Recognize the small set of image formats accepted for signatures."""
    if contents.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if contents.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if contents.startswith(b"RIFF") and contents[8:12] == b"WEBP":
        return "image/webp"
    return None


async def _signature_is_referenced(db: AsyncSession, signature_url: str | None) -> bool:
    if not signature_url:
        return False
    result = await db.execute(
        select(WorkOrder.id)
        .where(
            or_(
                WorkOrder.requested_signature == signature_url,
                WorkOrder.approved_signature == signature_url,
            )
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


def _effective_water_permission(
    *,
    requested: WaterRegisterPermission,
    legacy_enabled: bool,
) -> WaterRegisterPermission:
    """Map old boolean clients to the new three-level permission."""
    if requested == WaterRegisterPermission.NONE and legacy_enabled:
        return WaterRegisterPermission.EDIT
    return requested


@router.get("/signature-image/{file_id}", include_in_schema=False)
async def signature_image(
    file_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Serve a known signature from our origin so browsers can render it.

    The Drive file remains publicly readable exclusively for Google Sheets,
    but its public response has a restrictive cross-origin policy.  We only
    proxy IDs currently referenced by a user or work order; this endpoint is
    not a general Google Drive downloader.
    """
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", file_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Firma no encontrada")

    signature_match = f"%id={file_id}"
    result = await db.execute(
        select(User.id)
        .where(User.signature.like(signature_match))
        .limit(1)
    )
    known_signature = result.scalar_one_or_none() is not None
    if not known_signature:
        result = await db.execute(
            select(WorkOrder.id)
            .where(
                or_(
                    WorkOrder.requested_signature.like(signature_match),
                    WorkOrder.approved_signature.like(signature_match),
                )
            )
            .limit(1)
        )
        known_signature = result.scalar_one_or_none() is not None
    if not known_signature:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Firma no encontrada")

    try:
        content, mime = get_signature_image(file_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return Response(
        content=content,
        media_type=mime,
        headers={
            "Cache-Control": "public, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/workers", response_model=list[UserResponse])
async def list_workers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List active workers (for participant selection). Access to any
    authenticated user."""
    result = await db.execute(
        select(User)
        .options(*_user_scope_options())
        .where(
            User.role == UserRole.WORKER,
            User.is_active == True,  # noqa: E712
        )
        .order_by(User.full_name)
    )
    return result.scalars().all()


@router.get("", response_model=list[UserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
    limit: int | None = Query(default=None, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    query = select(User).options(*_user_scope_options()).order_by(User.full_name)
    if offset:
        query = query.offset(offset)
    if limit:
        query = query.limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    if payload.can_manage_equipment_inventory and (
        payload.role != UserRole.WORKER or not payload.is_active
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El permiso de inventario solo se puede asignar a un trabajador activo.",
        )
    existing = await db.execute(select(User).where(User.email == payload.email.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe un usuario con ese email",
        )
    uses_new_scope = "plant_area_ids" in payload.model_fields_set
    legacy_section_ids = (
        payload.area_ids
        if uses_new_scope
        else (payload.area_ids or ([payload.area_id] if payload.area_id else []))
    )
    assigned_plant_areas, excluded_sections, assigned_legacy_sections = await _validated_supervisor_scope(
        db,
        role=payload.role,
        plant_area_ids=payload.plant_area_ids if uses_new_scope else [],
        excluded_section_ids=payload.excluded_section_ids if uses_new_scope else [],
        legacy_section_ids=legacy_section_ids,
    )
    assigned_plant_area_ids = [area.id for area in assigned_plant_areas]
    assigned_legacy_section_ids = [section.id for section in assigned_legacy_sections]
    user = User(
        full_name=payload.full_name,
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        role=payload.role,
        area_id=assigned_legacy_section_ids[0] if assigned_legacy_section_ids else None,
        is_active=payload.is_active,
        can_manage_water_register=(
            _effective_water_permission(
                requested=payload.water_register_access,
                legacy_enabled=payload.can_manage_water_register,
            ) == WaterRegisterPermission.EDIT
        ),
        water_register_access=_effective_water_permission(
            requested=payload.water_register_access,
            legacy_enabled=payload.can_manage_water_register,
        ).value,
        can_manage_equipment_inventory=payload.can_manage_equipment_inventory,
    )
    if payload.can_manage_equipment_inventory:
        assigned_result = await db.execute(
            select(User).where(User.can_manage_equipment_inventory == True)  # noqa: E712
        )
        for assigned_user in assigned_result.scalars().all():
            assigned_user.can_manage_equipment_inventory = False
            await create_audit_log(
                db,
                user_id=current_user.id,
                action="UPDATE",
                entity_type="User",
                entity_id=assigned_user.id,
                previous_data={"can_manage_equipment_inventory": True},
                new_data={"can_manage_equipment_inventory": False},
            )
    user.supervised_areas = assigned_legacy_sections
    user.supervised_plant_areas = assigned_plant_areas
    user.excluded_supervised_sections = excluded_sections
    db.add(user)
    await db.flush()

    await create_audit_log(
        db,
        user_id=current_user.id,
        action="CREATE",
        entity_type="User",
        entity_id=user.id,
        new_data={
            "full_name": user.full_name,
            "email": user.email,
            "role": user.role.value,
            "plant_area_ids": assigned_plant_area_ids,
            "excluded_section_ids": [section.id for section in excluded_sections],
            "legacy_section_ids": assigned_legacy_section_ids,
            "can_manage_water_register": user.can_manage_water_register,
            "water_register_access": user.water_register_access,
            "can_manage_equipment_inventory": user.can_manage_equipment_inventory,
        },
    )
    refreshed = await db.execute(
        select(User)
        .options(*_user_scope_options())
        .where(User.id == user.id)
        .execution_options(populate_existing=True)
    )
    return refreshed.scalar_one()


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_my_password(
    payload: PasswordChange,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Change the authenticated user's password after verifying the old one."""
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La contraseÃ±a actual es incorrecta.",
        )
    if verify_password(payload.new_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La nueva contraseÃ±a debe ser diferente.",
        )

    current_user.password_hash = hash_password(payload.new_password)
    await create_audit_log(
        db,
        user_id=current_user.id,
        action="UPDATE",
        entity_type="User",
        entity_id=current_user.id,
        new_data={"password_changed": True},
    )


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    payload: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    result = await db.execute(
        select(User).options(*_user_scope_options()).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")

    previous = {
        "full_name": user.full_name,
        "email": user.email,
        "role": user.role.value,
        "is_active": user.is_active,
        "can_manage_water_register": user.can_manage_water_register,
        "water_register_access": user.water_register_access,
        "can_manage_equipment_inventory": user.can_manage_equipment_inventory,
        "signature": user.signature,
        "area_id": user.area_id,
        "area_ids": user.area_ids,
        "plant_area_ids": user.plant_area_ids,
        "excluded_section_ids": user.excluded_section_ids,
    }

    # ── Protecciones para no dejar el sistema sin acceso administrativo ──────
    # 1) Un administrador no puede desactivarse a sí mismo (error humano común).
    if user.id == current_user.id and payload.password is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No puedes cambiar tu propia contraseña desde aquí.",
        )

    if user.id == current_user.id and payload.is_active is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No puedes desactivar tu propio usuario.",
        )

    # 2) No se puede quitar el último administrador activo del sistema,
    #    ya sea desactivándolo o cambiándole el rol.
    #    Sólo importa si este usuario es ADMIN activo y se muestra inactivo/no-admin.
    is_active_being_removed = (
        user.role == UserRole.ADMIN
        and user.is_active
        and (
            (payload.is_active is False)
            or (payload.role is not None and payload.role != UserRole.ADMIN)
        )
    )
    if is_active_being_removed:
        admin_count = await db.execute(
            select(func.count())
            .select_from(User)
            .where(User.role == UserRole.ADMIN, User.is_active == True)  # noqa: E712
        )
        if admin_count.scalar_one() <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se puede desactivar al último administrador activo.",
            )

    next_role = payload.role or user.role
    next_active = payload.is_active if payload.is_active is not None else user.is_active
    requested_inventory_access = payload.can_manage_equipment_inventory
    next_inventory_access = (
        payload.can_manage_equipment_inventory
        if payload.can_manage_equipment_inventory is not None
        else user.can_manage_equipment_inventory
    )
    if requested_inventory_access is True and (next_role != UserRole.WORKER or not next_active):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El permiso de inventario solo se puede asignar a un trabajador activo.",
        )
    if next_role != UserRole.WORKER or not next_active:
        next_inventory_access = False
    uses_new_scope = "plant_area_ids" in payload.model_fields_set
    if uses_new_scope:
        requested_plant_area_ids = payload.plant_area_ids or []
        requested_excluded_section_ids = (
            payload.excluded_section_ids
            if payload.excluded_section_ids is not None
            else user.excluded_section_ids
        )
        requested_legacy_section_ids = (
            payload.area_ids
            if payload.area_ids is not None
            else user.legacy_section_ids
        )
    elif payload.area_ids is not None or payload.area_id is not None:
        requested_plant_area_ids = []
        requested_excluded_section_ids = []
        requested_legacy_section_ids = payload.area_ids or ([payload.area_id] if payload.area_id else [])
    else:
        requested_plant_area_ids = user.plant_area_ids
        requested_excluded_section_ids = user.excluded_section_ids
        requested_legacy_section_ids = user.legacy_section_ids
    next_plant_areas, next_excluded_sections, next_legacy_sections = await _validated_supervisor_scope(
        db,
        role=next_role,
        plant_area_ids=requested_plant_area_ids,
        excluded_section_ids=requested_excluded_section_ids,
        legacy_section_ids=requested_legacy_section_ids,
    )
    next_plant_area_ids = [area.id for area in next_plant_areas]
    next_legacy_section_ids = [section.id for section in next_legacy_sections]

    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.email is not None:
        user.email = payload.email.lower()
    if payload.role is not None:
        user.role = payload.role
    user.area_id = next_legacy_section_ids[0] if next_legacy_section_ids else None
    user.supervised_areas = next_legacy_sections
    user.supervised_plant_areas = next_plant_areas
    user.excluded_supervised_sections = next_excluded_sections
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if next_inventory_access:
        assigned_result = await db.execute(
            select(User).where(
                User.can_manage_equipment_inventory == True,  # noqa: E712
                User.id != user.id,
            )
        )
        for assigned_user in assigned_result.scalars().all():
            assigned_user.can_manage_equipment_inventory = False
            await create_audit_log(
                db,
                user_id=current_user.id,
                action="UPDATE",
                entity_type="User",
                entity_id=assigned_user.id,
                previous_data={"can_manage_equipment_inventory": True},
                new_data={"can_manage_equipment_inventory": False},
            )
    user.can_manage_equipment_inventory = next_inventory_access
    if payload.water_register_access is not None:
        user.water_register_access = payload.water_register_access.value
        user.can_manage_water_register = payload.water_register_access == WaterRegisterPermission.EDIT
    elif payload.can_manage_water_register is not None:
        user.water_register_access = (
            WaterRegisterPermission.EDIT.value
            if payload.can_manage_water_register
            else WaterRegisterPermission.NONE.value
        )
        user.can_manage_water_register = payload.can_manage_water_register
    if payload.password is not None:
        user.password_hash = hash_password(payload.password)
    await create_audit_log(
        db,
        user_id=current_user.id,
        action="UPDATE",
        entity_type="User",
        entity_id=user.id,
        previous_data=previous,
        new_data={
            "full_name": user.full_name,
            "email": user.email,
            "role": user.role.value,
            "is_active": user.is_active,
            "can_manage_water_register": user.can_manage_water_register,
            "water_register_access": user.water_register_access,
            "can_manage_equipment_inventory": user.can_manage_equipment_inventory,
            "signature": user.signature,
            "area_id": user.area_id,
            "plant_area_ids": next_plant_area_ids,
            "excluded_section_ids": [section.id for section in next_excluded_sections],
            "legacy_section_ids": next_legacy_section_ids,
        },
    )
    refreshed = await db.execute(
        select(User)
        .options(*_user_scope_options())
        .where(User.id == user.id)
        .execution_options(populate_existing=True)
    )
    return refreshed.scalar_one()


@router.post("/me/signature", response_model=dict)
async def upload_my_signature(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload or replace the current user's handwritten signature.

    Validates mime type and size (≤ 2 MB), uploads to Drive (idempotent per
    user), makes it publicly readable (required for Sheets overlay), and
    stores the download URL in the user's `signature` column.
    """
    # Validate declared and actual image type. UploadFile.content_type comes
    # from the browser and must not be trusted on its own.
    allowed_mimes = {"image/png", "image/jpeg", "image/webp"}
    if file.content_type not in allowed_mimes:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Solo se permiten imágenes PNG, JPEG o WebP.",
        )

    # Validate the original upload. The service normalizes it below Google's
    # 2 MB / 1 million pixel Apps Script limit before storing it.
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="La imagen estÃ¡ vacÃ­a.")
    if len(contents) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="La imagen original es demasiado grande (máx. 10 MB).",
        )

    detected_mime = _detected_image_mime(contents)
    if detected_mime != file.content_type:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="El contenido del archivo no coincide con una imagen PNG, JPEG o WebP vÃ¡lida.",
        )

    previous_signature = current_user.signature

    # Upload to Drive and get public URL
    try:
        # Drive's client is synchronous. Keep it off the event loop so a slow
        # Google response cannot block login, counters, or other users.
        url = await run_in_threadpool(
            upload_signature,
            current_user.id,
            contents,
            file.content_type,
        )
    except RuntimeError as exc:
        logger.exception("No se pudo cargar la firma del usuario %s", current_user.id)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    # Save the URL in the user profile
    current_user.signature = url
    await db.commit()
    await db.refresh(current_user)

    # Superseded files stay available when an OT references them. Otherwise
    # they are safe to clean up after the new profile signature is durable.
    if previous_signature and not await _signature_is_referenced(db, previous_signature):
        await run_in_threadpool(delete_signature, previous_signature)

    return {"url": url}


@router.delete("/me/signature", response_model=dict)
async def delete_my_signature(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete the current user's signature (from Drive and DB)."""
    if current_user.signature:
        previous_signature = current_user.signature
        current_user.signature = None
        await db.commit()
        await db.refresh(current_user)
        if not await _signature_is_referenced(db, previous_signature):
            await run_in_threadpool(delete_signature, previous_signature)
    return {"ok": True}
