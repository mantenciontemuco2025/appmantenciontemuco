"""Admin-only routes: integration diagnostics and test endpoints."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.dependencies import require_roles
from app.db.session import get_db
from app.models.user import User, UserRole
from app.models.worker_column import WorkerColumn, WORKER_COLUMN_SLOTS
from app.models.monthly_register import GoogleMonthlyRegister
from app.services.google_sheets import check_google_integration
from app.services import google_drive as drive_service
from app.services.monthly_register import (
    ensure_monthly_register_for_year,
    resolve_register,
)
from app.services.audit_service import create_audit_log
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

router = APIRouter(prefix="/api/admin", tags=["admin"])

admin_only = require_roles(UserRole.ADMIN)


class WorkerColumnOut(BaseModel):
    slot: int
    column_key: str
    column_letter: str
    user_id: int | None = None
    user_name: str | None = None


class WorkerColumnUpdate(BaseModel):
    user_id: int | None = None


def _worker_column_to_out(column: WorkerColumn) -> WorkerColumnOut:
    return WorkerColumnOut(
        slot=column.slot,
        column_key=column.column_key,
        column_letter=column.column_letter,
        user_id=column.user_id,
        user_name=column.user.full_name if column.user else None,
    )


@router.get("/worker-columns", response_model=list[WorkerColumnOut])
async def list_worker_columns(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(admin_only),
) -> list[WorkerColumnOut]:
    """List the ten fixed monthly worker positions (ADMIN only)."""
    result = await db.execute(select(WorkerColumn).order_by(WorkerColumn.slot))
    columns = list(result.scalars().all())
    # This guard makes an incomplete migration immediately visible instead of
    # silently presenting a partial configuration to the administrator.
    if len(columns) != len(WORKER_COLUMN_SLOTS):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="La configuración de columnas mensuales está incompleta.",
        )
    return [_worker_column_to_out(column) for column in columns]


@router.put("/worker-columns/{slot}", response_model=WorkerColumnOut)
async def update_worker_column(
    slot: int,
    payload: WorkerColumnUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
) -> WorkerColumnOut:
    """Assign or clear a worker in one of the ten fixed positions."""
    column = await db.scalar(select(WorkerColumn).where(WorkerColumn.slot == slot))
    if column is None:
        raise HTTPException(status_code=404, detail="Posición mensual no encontrada.")

    selected_user = None
    if payload.user_id is not None:
        selected_user = await db.get(User, payload.user_id)
        if selected_user is None or selected_user.role != UserRole.WORKER:
            raise HTTPException(
                status_code=400,
                detail="Solo se pueden asignar usuarios con rol Trabajador.",
            )
        other = await db.scalar(
            select(WorkerColumn)
            .where(
                WorkerColumn.user_id == payload.user_id,
                WorkerColumn.slot != slot,
            )
            .limit(1)
        )
        if other is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"El trabajador ya está asignado a la posición "
                    f"{other.slot} ({other.column_key})."
                ),
            )

    previous_user_id = column.user_id
    column.user_id = payload.user_id
    column.user = selected_user
    await db.flush()
    await create_audit_log(
        db,
        user_id=current_user.id,
        action="UPDATE_WORKER_COLUMN",
        entity_type="WorkerColumn",
        entity_id=column.id,
        previous_data={"user_id": previous_user_id, "slot": column.slot},
        new_data={
            "user_id": payload.user_id,
            "user_name": selected_user.full_name if selected_user else None,
            "slot": column.slot,
            "column_key": column.column_key,
        },
    )
    return _worker_column_to_out(column)


# ──────────────────────────────────────────────────────────────────────
# Existing: Google Sheets status (monthly spreadsheet only)
# ──────────────────────────────────────────────────────────────────────

class GoogleSheetsStatus(BaseModel):
    configured: bool
    credentials_valid: bool
    spreadsheet_access: bool
    sheet_found: bool
    error: str | None = None


@router.get(
    "/integrations/google-sheets/status",
    response_model=GoogleSheetsStatus,
)
async def google_sheets_status(
    _: User = Depends(admin_only),
) -> GoogleSheetsStatus:
    """Read-only health check of the Google Sheets integration (ADMIN only).

    Checks: config loaded, credentials valid, spreadsheet access, sheet exists.
    Never writes anything and never returns credentials/tokens/JSON.
    """
    return GoogleSheetsStatus(**check_google_integration())


# ──────────────────────────────────────────────────────────────────────
# NEW: Full Google integration status (Drive + OT + Monthly)
# ──────────────────────────────────────────────────────────────────────

class GoogleDriveStatus(BaseModel):
    configured: bool
    auth_method: str | None = None  # "oauth" | "service_account" | null
    write_enabled: bool = False  # True only when OAuth is configured (writes allowed)
    template_access: bool
    ot_folder_access: bool
    monthly_sheet_access: bool
    monthly_tabs_valid: bool
    monthly_root_folder_access: bool = False
    monthly_template_access: bool = False
    current_year: int | None = None
    current_year_register: dict | None = None
    error: str | None = None


@router.get(
    "/integrations/google/status",
    response_model=GoogleDriveStatus,
)
async def google_drive_status(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(admin_only),
) -> GoogleDriveStatus:
    """Comprehensive Google integration diagnostic (ADMIN only).

    Verifies:
    - credentials are valid (OAuth or Service Account)
    - OT template is accessible (read-only)
    - OT root folder is accessible (read-only)
    - Monthly tracking spreadsheet is accessible
    - All 12 monthly tabs (ENERO..DICIEMBRE) exist
    - Monthly root folder + master template access (per-year model)
    - current_year / current_year_register from PostgreSQL (no secrets)

    Never writes, copies, or modifies any files.
    """
    payload = drive_service.check_google_drive_status()
    cy = payload.get("current_year")
    if cy is not None:
        reg = await resolve_register(db, int(cy))
        payload["current_year_register"] = (
            {"configured": True, "spreadsheet_id": reg.spreadsheet_id}
            if reg is not None
            else {"configured": False}
        )
    else:
        payload["current_year_register"] = {"configured": False}
    return GoogleDriveStatus(**payload)


# ──────────────────────────────────────────────────────────────────────
# Test OT: create a test OT-TEST in Drive (ADMIN only)
# ──────────────────────────────────────────────────────────────────────

class TestOTResult(BaseModel):
    success: bool
    ot_number: str
    file_id: str | None = None
    url: str | None = None
    folder: str | None = None
    error: str | None = None


@router.post(
    "/integrations/google/test-ot",
    response_model=TestOTResult,
)
async def create_test_ot(
    _: User = Depends(admin_only),
) -> TestOTResult:
    """Create a test OT-TEST document in Google Drive (ADMIN only).

    Steps:
    1. Copy the OT template
    2. Place it in the current month's folder
    3. Fill in test data
    4. Does NOT sync to the monthly tracking sheet

    Use this to visually validate the OT document before enabling
    the full creation flow.
    """
    from datetime import datetime

    now = datetime.now()
    test_ot_number = f"OT-TEST-{now.strftime('%Y%m%d-%H%M%S')}"

    try:
        # 1. Copy template to current month's folder
        ot_result = drive_service.create_ot_file(test_ot_number, now)

        # 2. Populate test fields
        drive_service.populate_ot_fields(
            ot_result["file_id"],
            ot_number=test_ot_number,
            area_name="TEST — Área de prueba",
            section_name="Sección de prueba",
            equipment_name="Equipo de prueba",
            maintenance_type="PREVENTIVE",
            loto_status="NOT_APPLICABLE",
            description=" Esta es una OT de prueba creada desde la plataforma.\n"
                        " Sirve para validar que la plantilla se completa correctamente.\n"
                        " Puede eliminarse después de la verificación.",
            participants=["Ortiz", "Jara"],
            estimated_time="4 horas",
            execution_date=now.date().isoformat(),
            resources_required="Herramientas básicas, grasa industrial",
            risks="Riesgo eléctrico moderado",
            observations="Verificar LOTO antes de iniciar.\nCerrar válvula de abastecimiento.",
            folio="FOLIO-TEST-001",
            voucher_number="VOUCHER-TEST",
            requested_by="Administrador",
            approved_by="Supervisor",
        )

        return TestOTResult(
            success=True,
            ot_number=test_ot_number,
            file_id=ot_result["file_id"],
            url=ot_result["url"],
            folder=f"{now.year}/{drive_service.SPANISH_MONTHS[now.month - 1]}",
        )

    except Exception as exc:
        return TestOTResult(
            success=False,
            ot_number=test_ot_number,
            error=str(exc)[:500],
        )


# ──────────────────────────────────────────────────────────────────────
# Per-year monthly registry management (ADMIN only)
# ──────────────────────────────────────────────────────────────────────

class MonthlyRegisterOut(BaseModel):
    year: int
    spreadsheet_id: str
    spreadsheet_url: str | None = None
    created_at: datetime
    is_active: bool


class MonthlyRegisterEnsureResult(BaseModel):
    year: int
    spreadsheet_id: str
    spreadsheet_url: str | None = None
    created: bool


def _register_to_out(reg: GoogleMonthlyRegister) -> dict:
    return {
        "year": reg.year,
        "spreadsheet_id": reg.spreadsheet_id,
        "spreadsheet_url": reg.spreadsheet_url,
        "created_at": reg.created_at,
        "is_active": reg.is_active,
    }


@router.get("/google/monthly-registers", response_model=list[MonthlyRegisterOut])
async def list_monthly_registers(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(admin_only),
) -> list[dict]:
    """List all registered annual registries (year -> spreadsheet), newest first."""
    res = await db.execute(
        select(GoogleMonthlyRegister).order_by(GoogleMonthlyRegister.year.desc())
    )
    return [_register_to_out(r) for r in res.scalars().all()]


@router.post(
    "/google/monthly-registers/{year}/ensure",
    response_model=MonthlyRegisterEnsureResult,
)
async def ensure_monthly_register(
    year: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(admin_only),
) -> MonthlyRegisterEnsureResult:
    """Create/verify the annual register for `year` (ADMIN only).

    If it already exists, returns it unchanged (never duplicates). If it does
    not exist, creates it from the master template in REGISTRO MENSUAL/ and
    stores the mapping in PostgreSQL. 400 when Google write is not configured.
    """
    existing = await resolve_register(db, year)
    if existing is not None:
        return MonthlyRegisterEnsureResult(
            year=year,
            spreadsheet_id=existing.spreadsheet_id,
            spreadsheet_url=existing.spreadsheet_url,
            created=False,
        )

    try:
        reg = await ensure_monthly_register_for_year(db, year, None, commit=True)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No se pudo crear el registro anual: {str(exc)[:300]}",
        ) from exc

    if reg is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Google write no configurado (falta OAuth o plantilla/carpeta "
                "mensual). No se creó el registro anual."
            ),
        )

    return MonthlyRegisterEnsureResult(
        year=year,
        spreadsheet_id=reg.spreadsheet_id,
        spreadsheet_url=reg.spreadsheet_url,
        created=True,
    )
