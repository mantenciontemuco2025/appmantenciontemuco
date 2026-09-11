import re

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, require_roles
from app.core.security import hash_password
from app.db.session import get_db
from app.models.user import User, UserRole
from app.models.area import Area
from app.models.audit_log import AuditLog
from app.models.work_order import WorkOrder
from app.schemas.user import UserCreate, UserResponse, UserUpdate
from app.services.audit_service import create_audit_log
from app.services.signatures import delete_signature, get_signature_image, upload_signature

router = APIRouter(prefix="/api/users", tags=["users"])

admin_only = require_roles(UserRole.ADMIN)


async def _legacy_validated_area_id(
    db: AsyncSession, *, role: UserRole, area_id: int | None
) -> int | None:
    """Supervisors must belong to one existing plant area."""
    if role != UserRole.SUPERVISOR:
        return None
    if area_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Un supervisor debe tener un área asignada.",
        )
    if await db.get(Area, area_id) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El área asignada no existe.",
        )
    return area_id


async def _validated_area_ids(
    db: AsyncSession,
    *,
    role: UserRole,
    area_ids: list[int] | None = None,
    legacy_area_id: int | None = None,
) -> list[int]:
    """Validate one or more areas assigned to a supervisor."""
    requested = list(area_ids or [])
    if not requested and legacy_area_id is not None:
        requested = [legacy_area_id]
    requested = list(dict.fromkeys(requested))
    if role != UserRole.SUPERVISOR:
        return []
    if not requested:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Un supervisor debe tener al menos un area asignada.",
        )
    result = await db.execute(select(Area.id).where(Area.id.in_(requested)))
    existing = {row[0] for row in result.all()}
    if existing != set(requested):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Una de las areas asignadas no existe.",
        )
    return requested


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
    query = select(User).order_by(User.full_name)
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
    existing = await db.execute(select(User).where(User.email == payload.email.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe un usuario con ese email",
        )
    assigned_area_ids = await _validated_area_ids(
        db,
        role=payload.role,
        area_ids=payload.area_ids,
        legacy_area_id=payload.area_id,
    )
    assigned_areas = []
    if assigned_area_ids:
        area_result = await db.execute(
            select(Area).where(Area.id.in_(assigned_area_ids))
        )
        by_id = {area.id: area for area in area_result.scalars().all()}
        assigned_areas = [by_id[area_id] for area_id in assigned_area_ids]
    user = User(
        full_name=payload.full_name,
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        role=payload.role,
        area_id=assigned_area_ids[0] if assigned_area_ids else None,
        is_active=payload.is_active,
    )
    user.supervised_areas = assigned_areas
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
            "area_ids": assigned_area_ids,
        },
    )
    await db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    payload: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")

    previous = {
        "full_name": user.full_name,
        "email": user.email,
        "role": user.role.value,
        "is_active": user.is_active,
        "signature": user.signature,
        "area_id": user.area_id,
        "area_ids": user.area_ids,
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
    if payload.area_ids is not None:
        requested_area_ids = payload.area_ids
    elif payload.area_id is not None:
        requested_area_ids = [payload.area_id]
    else:
        requested_area_ids = user.area_ids
    next_area_ids = await _validated_area_ids(
        db,
        role=next_role,
        area_ids=requested_area_ids,
    )
    area_result = await db.execute(
        select(Area).where(Area.id.in_(next_area_ids))
    ) if next_area_ids else None
    area_by_id = {area.id: area for area in area_result.scalars().all()} if area_result else {}

    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.email is not None:
        user.email = payload.email.lower()
    if payload.role is not None:
        user.role = payload.role
    user.area_id = next_area_ids[0] if next_area_ids else None
    user.supervised_areas = [area_by_id[area_id] for area_id in next_area_ids]
    if payload.is_active is not None:
        user.is_active = payload.is_active
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
            "signature": user.signature,
            "area_id": user.area_id,
            "area_ids": next_area_ids,
        },
    )
    await db.refresh(user)
    return user


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
    # 2 MB / 10 million pixel limit before storing it.
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
        url = upload_signature(current_user.id, contents, file.content_type)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    # Save the URL in the user profile
    current_user.signature = url
    await db.commit()
    await db.refresh(current_user)

    # Superseded files stay available when an OT references them. Otherwise
    # they are safe to clean up after the new profile signature is durable.
    if previous_signature and not await _signature_is_referenced(db, previous_signature):
        delete_signature(previous_signature)

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
            delete_signature(previous_signature)
    return {"ok": True}
