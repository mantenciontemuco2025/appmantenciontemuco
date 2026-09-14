"""Per-year monthly registry resolution and creation.

Each calendar year owns one "Registro_Mantencion_<AÑO>" spreadsheet created
lazily from a master template (GOOGLE_MONTHLY_TEMPLATE_FILE_ID) inside REGISTRO
MENSUAL/ (GOOGLE_MONTHLY_ROOT_FOLDER_ID). The mapping year -> spreadsheet_id is
stored in PostgreSQL (GoogleMonthlyRegister); Google Sheets is only the
documentary/summary destination, so a missing/empty register never affects the
source-of-truth WorkOrder rows.

Everything here is derived from, and reuses, the existing Drive/Sheets helpers in
google_drive.py (OAuth-only write gate preserved) and the monthly_mapping headers.
"""

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.monthly_register import GoogleMonthlyRegister
from app.services.ot_mapping import SPANISH_MONTHS

logger = logging.getLogger(__name__)

# Current legacy single register (used only when no per-year row exists yet, so
# an existing install keeps working while the 2026 backfill is applied).
_REGISTER_PREFIX = "Registro_Mantencion_"


def register_filename(year: int) -> str:
    """Obligatory file name: Registro_Mantencion_<AÑO>."""
    return f"{_REGISTER_PREFIX}{year}"


def register_config_available() -> bool:
    """True when both template + monthly root folder are configured."""
    return bool(
        settings.GOOGLE_MONTHLY_TEMPLATE_FILE_ID
        and settings.GOOGLE_MONTHLY_ROOT_FOLDER_ID
    )


# ──────────────────────────────────────────────────────────────────────
# Resolution (PostgreSQL)
# ──────────────────────────────────────────────────────────────────────

async def resolve_register(
    db: AsyncSession, year: int
) -> GoogleMonthlyRegister | None:
    """Return the active register row for `year`, or None."""
    res = await db.execute(
        select(GoogleMonthlyRegister).where(
            GoogleMonthlyRegister.year == year,
            GoogleMonthlyRegister.is_active.is_(True),
        )
    )
    return res.scalar_one_or_none()


# ──────────────────────────────────────────────────────────────────────
# Drive file creation (WRITE, OAuth-only)
# ──────────────────────────────────────────────────────────────────────

def create_register_file(year: int) -> dict:
    """Copy the master template into REGISTRO MENSUAL/ named for `year`.

    Returns {"file_id": ..., "url": ...}. Never modifies the original template.
    Raises RuntimeError if OAuth is not configured or config is missing.
    """
    from app.services import google_drive

    if not register_config_available():
        raise RuntimeError(
            "GOOGLE_MONTHLY_TEMPLATE_FILE_ID y GOOGLE_MONTHLY_ROOT_FOLDER_ID son "
            "requeridos para crear un registro anual."
        )

    drive = google_drive._build_drive_write_service()
    template_id = settings.GOOGLE_MONTHLY_TEMPLATE_FILE_ID
    destination_folder_id = settings.GOOGLE_MONTHLY_ROOT_FOLDER_ID

    # Resolve the template's current parent so we can move the copy out of it.
    template_parent = google_drive._get_file_parent(drive, template_id)

    copy_meta = {"name": register_filename(year)}
    copied = drive.files().copy(
        fileId=template_id, body=copy_meta, fields="id, webViewLink"
    ).execute()
    file_id = copied["id"]

    update_params = {"addParents": destination_folder_id, "fields": "id, webViewLink"}
    if template_parent:
        update_params["removeParents"] = template_parent
    drive.files().update(fileId=file_id, **update_params).execute()

    url = copied.get(
        "webViewLink", f"https://drive.google.com/file/d/{file_id}/view"
    )
    logger.info(
        "Registro anual %s creado en Drive (file_id=%s)",
        register_filename(year), file_id,
    )
    return {"file_id": file_id, "url": url}


def find_register_file_id(year: int) -> str | None:
    """Return the Drive file id of an existing 'Registro_Mantencion_<year>' file
    inside GOOGLE_MONTHLY_ROOT_FOLDER_ID, or None if not found.

    This guards against duplicate files when a Drive copy succeeded but the DB
    row was later rolled back: the exact name match makes `ensure` reuse the
    already-created register instead of making `..._2027 (1)`.
    """
    from app.services import google_drive

    if not register_config_available():
        return None
    drive = google_drive._build_drive_write_service()
    name = register_filename(year)
    q = (
        f"'{settings.GOOGLE_MONTHLY_ROOT_FOLDER_ID}' in parents "
        f"and name = '{name}' and trashed = false"
    )
    resp = drive.files().list(q=q, fields="files(id, name)", pageSize=5).execute()
    files = resp.get("files", [])
    return files[0]["id"] if files else None


def validate_12_tabs(spreadsheet_id: str) -> list[str]:
    """Return the list of missing SPANISH_MONTHS tab titles (empty if all present)."""
    from app.services import google_drive

    sheets = google_drive._build_sheets_service()
    meta = (
        sheets.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, fields="sheets(properties.title)")
        .execute()
    )
    tab_titles = {s.get("properties", {}).get("title") for s in meta.get("sheets", [])}
    return [m for m in SPANISH_MONTHS if m not in tab_titles]


# ──────────────────────────────────────────────────────────────────────
# Ensure (idempotent, concurrency-safe)
# ──────────────────────────────────────────────────────────────────────

async def ensure_monthly_register_for_year(
    db: AsyncSession,
    year: int,
    user_id: int | None = None,
    *,
    commit: bool = True,
    release_before_external: bool = False,
) -> GoogleMonthlyRegister | None:
    """Return the register row for `year`, creating it from the template if needed.

    Idempotent: if the row already exists it is returned untouched. If it does
    not exist, the file is created in Drive (OAuth required) and row inserted.
    On a UNIQUE(year) race (two OTs for the same new year at once) it rolls back
    and re-selects the row another process already inserted — never duplicates.

    `commit=False` is used when called inside an existing transaction (e.g. the
    WorkOrder monthly sync mid-edit): the row is flushed (so UNIQUE races are
    still detected) but the caller's transaction owns the eventual commit.

    `release_before_external=True` is for background sync jobs whose state is
    already committed. It releases the connection after the initial lookup
    before calling Google Drive.

    Returns None when Google write is not possible (no OAuth / no template /
    no monthly root folder) so the caller marks the WorkOrder sync FAILED without
    losing it. Raises on a true Drive/Sheets error (also handled as FAILED).
    """
    existing = await resolve_register(db, year)
    if existing is not None:
        return existing

    if release_before_external:
        # A SELECT starts a transaction in PostgreSQL. Do not hold its
        # connection while waiting for a potentially slow Drive operation.
        await db.commit()

    if not settings.google_write_enabled or not register_config_available():
        logger.info(
            "No se pudo crear el registro mensual %s: OAuth/plantilla/carpeta "
            "no configurados.", year,
        )
        return None

    # Idempotency guard: reuse an already-created Drive file of the same name even
    # if its DB row was lost (e.g. a transaction rolled back after a Drive copy),
    # instead of creating "Registro_Mantencion_2027 (1)".
    existing_id = find_register_file_id(year)
    if existing_id is not None:
        register = GoogleMonthlyRegister(
            year=year,
            spreadsheet_id=existing_id,
            spreadsheet_url=f"https://drive.google.com/file/d/{existing_id}/view",
            is_active=True,
            created_by_user_id=user_id,
        )
        db.add(register)
        try:
            await db.flush()
            if commit:
                await db.commit()
            if register.id is None:
                await db.refresh(register)
            return register
        except IntegrityError:
            await db.rollback()
            existing = await resolve_register(db, year)
            return existing

    file_info = create_register_file(year)

    missing = validate_12_tabs(file_info["file_id"])
    if missing:
        logger.warning(
            "Registro %s no tiene todas las pestañas: faltan %s",
            register_filename(year), ", ".join(missing),
        )

    register = GoogleMonthlyRegister(
        year=year,
        spreadsheet_id=file_info["file_id"],
        spreadsheet_url=file_info.get("url"),
        is_active=True,
        created_by_user_id=user_id,
    )
    db.add(register)
    try:
        await db.flush()
        if commit:
            await db.commit()
        if register.id is None:
            await db.refresh(register)
        return register
    except IntegrityError:
        # Another process just inserted this year — rollback our copy and reuse it.
        await db.rollback()
        logger.info(
            "Otro proceso creó el registro %s; reutilizando el existente.", year,
        )
        existing = await resolve_register(db, year)
        return existing


# ──────────────────────────────────────────────────────────────────────
# Remove a WorkOrder row (year-change cleanup)
# ──────────────────────────────────────────────────────────────────────

def delete_ot_from_register(
    spreadsheet_id: str, sheet_title: str, ot_number: str
) -> None:
    """Delete the full row whose N° OT matches `ot_number` in `sheet_title`.

    Uses Sheets deleteDimension so the entire row (a year/months change cleanup)
    is removed, keeping N° OT unique. Best-effort: if the OT is not found, no-op.
    """
    from app.services import google_drive

    row = google_drive._search_row_by_col(
        spreadsheet_id, sheet_title, google_drive.MONTHLY_COLUMN_MAP["N_O_T"], ot_number
    )
    if row is None:
        logger.info(
            "OT %s no encontrada en %s; nada que borrar.", ot_number, sheet_title,
        )
        return

    sheets = google_drive._build_sheets_write_service()
    body = {
        "requests": [
            {
                "deleteDimension": {
                    "range": {
                        "sheetId": None,  # resolved below by title
                        "dimension": "ROWS",
                        "startIndex": row - 1,
                        "endIndex": row,
                    }
                }
            }
        ]
    }

    # deleteDimension needs the sheet (tab) id, not the name. Resolve it first.
    meta = (
        sheets.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, fields="sheets(properties)")
        .execute()
    )
    sheet_id = None
    for s in meta.get("sheets", []):
        props = s.get("properties", {})
        if props.get("title") == sheet_title:
            sheet_id = props.get("sheetId")
            break
    if sheet_id is None:
        logger.warning("No se encontró la pestaña %s; no se borró la OT %s.", sheet_title, ot_number)
        return

    body["requests"][0]["deleteDimension"]["range"]["sheetId"] = sheet_id
    sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body=body
    ).execute()
    logger.info("OT %s eliminada de %s (fila %d).", ot_number, sheet_title, row)
