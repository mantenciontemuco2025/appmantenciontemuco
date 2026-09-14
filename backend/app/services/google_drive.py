"""Google Drive + Sheets integration for Work Orders.

Responsibilities:
- Copy OT template → new OT document
- Create year/month folder hierarchy
- Populate OT spreadsheet cells (using centralized ot_mapping)
- Sync OT to monthly tracking sheet (using centralized ot_mapping)
- Diagnostic status check

All cell coordinates live in ot_mapping.py — never hardcoded here.
"""

import logging
from datetime import datetime

from app.core.config import settings
from app.services.google_api_cache import build_cached_service
from app.services.signature_sheet_images import insert_signature_image
from app.services.ot_mapping import (
    OT_FIELD_MAP,
    STATUS_CELL,
    MONTHLY_COLUMN_MAP,
    MONTHLY_DATA_START_ROW,
    MONTHLY_MT_MAP,
    WORKER_COLUMN_KEYS,
    SPANISH_MONTHS,
    build_maintenance_cell_texts,
    build_loto_cell_texts,
    build_status_text,
    build_authorization_text,
    REQUESTED_BY_LABEL,
    REALIZADO_BY_LABEL,
    APPROVED_BY_LABEL,
    get_signature_block,
    get_monthly_sheet_title,
)
# Monthly registry keeps its own centralized mapping (headers, status, HORAS).
# It re-exports the base columns from ot_mapping and adds ESTADO + HORAS rule.
from app.services.monthly_mapping import (
    resolve_monthly_columns,
    is_eligible_for_monthly,
    monthly_status_text,
    compute_horas,
    HorasInput,
    normalize_header,
)

logger = logging.getLogger(__name__)


def _google_credentials_key() -> tuple[str, ...]:
    """Return a non-secret cache discriminator for the active auth config."""
    if settings._google_oauth_configured:
        return (
            "oauth",
            settings.GOOGLE_OAUTH_CLIENT_ID,
            settings.GOOGLE_OAUTH_CLIENT_SECRET,
            settings.GOOGLE_OAUTH_REFRESH_TOKEN,
        )
    return (
        "service-account",
        settings.GOOGLE_SERVICE_ACCOUNT_FILE or "",
        settings.GOOGLE_SERVICE_ACCOUNT_JSON or "",
    )


# ──────────────────────────────────────────────────────────────────────
# Google service builders (lazy imports to keep app start fast)
# ──────────────────────────────────────────────────────────────────────

def _build_drive_service():
    """Build the Drive API v3 service. OAuth (preferred) or Service Account.

    For READ operations. Write operations must use _build_drive_write_service.
    """
    creds = settings.get_google_credentials()
    if creds is None:
        raise RuntimeError("Google no configurado (OAuth o Service Account).")
    return build_cached_service(
        cache_name="drive-read",
        service_name="drive",
        version="v3",
        credentials=creds,
        credentials_key=_google_credentials_key(),
    )


def _build_sheets_service():
    """Build the Sheets API v4 service. OAuth (preferred) or Service Account.

    For READ operations. Write operations must use _build_sheets_write_service.
    """
    creds = settings.get_google_credentials()
    if creds is None:
        raise RuntimeError("Google no configurado (OAuth o Service Account).")
    return build_cached_service(
        cache_name="sheets-read",
        service_name="sheets",
        version="v4",
        credentials=creds,
        credentials_key=_google_credentials_key(),
    )


def _build_drive_write_service():
    """Build the Drive API v3 service for WRITE operations (OAuth ONLY).

    Never falls back to the Service Account. Raises a clear error if OAuth
    is not configured.
    """
    creds = settings.get_google_write_credentials()
    return build_cached_service(
        cache_name="drive-write",
        service_name="drive",
        version="v3",
        credentials=creds,
        credentials_key=_google_credentials_key(),
    )


def _build_sheets_write_service():
    """Build the Sheets API v4 service for WRITE operations (OAuth ONLY).

    Never falls back to the Service Account. Raises a clear error if OAuth
    is not configured.
    """
    creds = settings.get_google_write_credentials()
    return build_cached_service(
        cache_name="sheets-write",
        service_name="sheets",
        version="v4",
        credentials=creds,
        credentials_key=_google_credentials_key(),
    )


# ──────────────────────────────────────────────────────────────────────
# Drive folder helpers
# ──────────────────────────────────────────────────────────────────────

def _find_child(drive, parent_id: str, name: str) -> str | None:
    """Find a child folder/file by exact name inside parent. Returns ID or None."""
    q = (
        f"'{parent_id}' in parents "
        f"and name = '{name}' "
        f"and trashed = false"
    )
    resp = drive.files().list(q=q, fields="files(id, name)", pageSize=5).execute()
    files = resp.get("files", [])
    return files[0]["id"] if files else None


def _create_folder(drive, parent_id: str, name: str) -> str:
    """Create a folder under parent. Returns new folder ID."""
    meta = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = drive.files().create(body=meta, fields="id").execute()
    return folder["id"]


def _ensure_month_folder(year: int, month_index: int) -> str:
    """Find or create year/month folder hierarchy. Returns the month folder ID.

    Hierarchy:
        ROOT_FOLDER/
            2026/
                SEPTIEMBRE/
    """
    drive = _build_drive_write_service()  # creating folders is a WRITE
    root_id = settings.GOOGLE_OT_ROOT_FOLDER_ID

    year_name = str(year)
    month_name = SPANISH_MONTHS[month_index - 1]

    year_id = _find_child(drive, root_id, year_name)
    if year_id is None:
        year_id = _create_folder(drive, root_id, year_name)
        logger.info("Carpeta de ano creada: %s", year_name)

    month_id = _find_child(drive, year_id, month_name)
    if month_id is None:
        month_id = _create_folder(drive, year_id, month_name)
        logger.info("Carpeta de mes creada: %s/%s", year_name, month_name)

    return month_id


def _get_file_parent(drive, file_id: str) -> str | None:
    """Return the first parent folder id of a file, or None."""
    try:
        f = drive.files().get(fileId=file_id, fields="parents").execute()
        parents = f.get("parents") or []
        return parents[0] if parents else None
    except Exception:  # noqa: BLE001 - best-effort parent resolution
        logger.warning("No se pudo resolver el parent de %s", file_id)
        return None


def _find_named_file(drive, parent_id: str, name: str) -> dict | None:
    """Find the most recently modified non-trashed file with an exact name."""
    q = (
        f"'{parent_id}' in parents "
        f"and name = '{name}' "
        f"and trashed = false"
    )
    response = drive.files().list(
        q=q,
        fields="files(id,name,webViewLink,modifiedTime)",
        orderBy="modifiedTime desc",
        pageSize=20,
    ).execute()
    files = response.get("files", [])
    return files[0] if files else None


def _copy_template(ot_number: str, destination_folder_id: str) -> dict:
    """Copy the OT template and move it into the destination folder.

    Returns {"file_id": ..., "url": ...}.
    Never modifies the original template.
    """
    drive = _build_drive_write_service()  # copying the template is a WRITE
    template_id = settings.GOOGLE_OT_TEMPLATE_FILE_ID

    # Drive copies are not transactional with Sheets updates. If a previous
    # attempt copied the file but failed later, reuse that copy instead of
    # creating another file with the same OT number.
    existing = _find_named_file(drive, destination_folder_id, ot_number)
    if existing:
        file_id = existing["id"]
        logger.info("OT %s ya existe en Drive; se reutiliza (file_id=%s)", ot_number, file_id)
        return {
            "file_id": file_id,
            "url": existing.get("webViewLink")
            or f"https://drive.google.com/file/d/{file_id}/view",
        }

    # Resolve the template's current parent folder (e.g. PLANTILLAS/) so we can
    # remove it from the copy's parents.
    template_parent = _get_file_parent(drive, template_id)

    # If a previous copy succeeded but its move into the OT folder failed, it
    # is normally still in the template's parent. Move and reuse it.
    if template_parent:
        orphan = _find_named_file(drive, template_parent, ot_number)
        if orphan and orphan["id"] != template_id:
            file_id = orphan["id"]
            drive.files().update(
                fileId=file_id,
                addParents=destination_folder_id,
                removeParents=template_parent,
                fields="id, webViewLink",
            ).execute()
            logger.info("OT %s encontrada como copia pendiente; se mueve y reutiliza (file_id=%s)", ot_number, file_id)
            return {
                "file_id": file_id,
                "url": orphan.get("webViewLink")
                or f"https://drive.google.com/file/d/{file_id}/view",
            }

    # 1. Copy template with the OT number as the new name
    copy_meta = {"name": ot_number}
    copied = drive.files().copy(
        fileId=template_id, body=copy_meta, fields="id, webViewLink"
    ).execute()
    file_id = copied["id"]

    # 2. Move to the target folder (update parents)
    update_params = {"addParents": destination_folder_id, "fields": "id, webViewLink"}
    if template_parent:
        update_params["removeParents"] = template_parent
    drive.files().update(fileId=file_id, **update_params).execute()

    url = copied.get("webViewLink", f"https://drive.google.com/file/d/{file_id}/view")
    logger.info("OT %s creada en Drive (file_id=%s)", ot_number, file_id)
    return {"file_id": file_id, "url": url}


# ──────────────────────────────────────────────────────────────────────
# Sheets helpers (for both OT document and monthly sheet)
# ──────────────────────────────────────────────────────────────────────

def _read_cells(spreadsheet_id: str, ranges: list[str]) -> dict[str, list]:
    """Read cells from a spreadsheet. Returns {range_str: [values]}."""
    sheets = _build_sheets_service()
    resp = sheets.spreadsheets().values().batchGet(
        spreadsheetId=spreadsheet_id, ranges=ranges
    ).execute()
    result = {}
    for v in resp.get("valueRanges", []):
        result[v["range"]] = v.get("values", [[]])
    return result


def _write_cells(spreadsheet_id: str, range_values: list[dict]) -> None:
    """Write cells to a spreadsheet (WRITE -- OAuth only).

    range_values: [{"range": "Sheet!A1", "values": [["val"]]}]
    """
    sheets = _build_sheets_write_service()
    body = {"valueInputOption": "RAW", "data": range_values}
    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id, body=body
    ).execute()


def _write_single(spreadsheet_id: str, range_name: str, value: str) -> None:
    """Write a single cell value (WRITE -- OAuth only)."""
    sheets = _build_sheets_write_service()
    body = {"values": [[value]]}
    sheets.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=range_name,
        valueInputOption="RAW",
        body=body,
    ).execute()


def _clear_cells(spreadsheet_id: str, cells: list[str]) -> None:
    """Clear (empty) a list of individual cells (WRITE -- OAuth only).

    Used to remove stale checkbox glyphs ("☐ ...") that remain in the separate
    cells next to the merged checkbox anchor in copied OT files.
    """
    if not cells:
        return
    sheets = _build_sheets_write_service()
    data = [{"range": cell, "values": [[""]]} for cell in cells]
    body = {"valueInputOption": "RAW", "data": data}
    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id, body=body
    ).execute()


def _search_row_by_col(
    spreadsheet_id: str, sheet_name: str, column: str, value: str
) -> int | None:
    """Search for a value in a column. Returns 1-indexed row number or None.

    Read-only helper; used within write flows (monthly sheet sync).
    """
    sheets = _build_sheets_service()
    range_name = f"{sheet_name}!{column}:{column}"
    resp = (
        sheets.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=range_name)
        .execute()
    )
    rows = resp.get("values", [])
    for i, row in enumerate(rows, start=1):
        if row and str(row[0]).strip().upper() == value.strip().upper():
            return i
    return None


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────

def check_google_drive_status() -> dict:
    """Diagnostic: verify credentials, template, OT folder, monthly sheet.

    Returns safe booleans. Never exposes IDs, credentials, or tokens.
    """
    result = {
        "configured": False,
        "auth_method": None,
        "write_enabled": False,
        "template_access": False,
        "ot_folder_access": False,
        "monthly_sheet_access": False,
        "monthly_tabs_valid": False,
        "monthly_root_folder_access": False,
        "monthly_template_access": False,
        "current_year": None,
        "current_year_register": None,
        "error": None,
    }

    result["auth_method"] = settings.google_auth_method
    result["write_enabled"] = settings.google_write_enabled
    if result["auth_method"] is None:
        result["error"] = "Google no configurado (credenciales o IDs faltantes)."
        return result

    result["configured"] = True

    try:
        drive = _build_drive_service()
    except Exception as exc:
        result["error"] = f"Error al construir servicio Drive: {type(exc).__name__}"
        return result

    # Check template access
    try:
        drive.files().get(
            fileId=settings.GOOGLE_OT_TEMPLATE_FILE_ID, fields="id, name"
        ).execute()
        result["template_access"] = True
    except Exception as exc:
        result["error"] = f"Sin acceso a la plantilla OT: {type(exc).__name__}"
        return result

    # Check OT root folder access
    try:
        drive.files().get(
            fileId=settings.GOOGLE_OT_ROOT_FOLDER_ID, fields="id, name"
        ).execute()
        result["ot_folder_access"] = True
    except Exception as exc:
        result["error"] = f"Sin acceso a la carpeta OT: {type(exc).__name__}"
        return result

    # Check monthly template + monthly root folder (per-year model) access
    if settings.GOOGLE_MONTHLY_TEMPLATE_FILE_ID:
        try:
            drive.files().get(
                fileId=settings.GOOGLE_MONTHLY_TEMPLATE_FILE_ID, fields="id, name"
            ).execute()
            result["monthly_template_access"] = True
        except Exception as exc:
            result["error"] = f"Sin acceso a la plantilla mensual: {type(exc).__name__}"
            return result
    if settings.GOOGLE_MONTHLY_ROOT_FOLDER_ID:
        try:
            drive.files().get(
                fileId=settings.GOOGLE_MONTHLY_ROOT_FOLDER_ID, fields="id, name"
            ).execute()
            result["monthly_root_folder_access"] = True
        except Exception as exc:
            result["error"] = f"Sin acceso a la carpeta REGISTRO MENSUAL: {type(exc).__name__}"
            return result

    result["current_year"] = datetime.now().year

    # Check monthly sheet access + tabs
    try:
        sheets = _build_sheets_service()
        meta = (
            sheets.spreadsheets()
            .get(
                spreadsheetId=settings.GOOGLE_MONTHLY_SPREADSHEET_ID,
                fields="properties.title,sheets(properties.title)",
            )
            .execute()
        )
        result["monthly_sheet_access"] = True

        tab_titles = {
            s.get("properties", {}).get("title")
            for s in meta.get("sheets", [])
        }
        missing = [m for m in SPANISH_MONTHS if m not in tab_titles]
        if not missing:
            result["monthly_tabs_valid"] = True
        else:
            result["error"] = f"Pestanas faltantes en registro mensual: {', '.join(missing)}"
    except Exception as exc:
        result["error"] = f"Sin acceso al registro mensual: {type(exc).__name__}"

    return result


def create_ot_file(ot_number: str, execution_date: datetime) -> dict:
    """Copy the OT template into the correct year/month folder.

    Returns {"file_id": ..., "url": ...}.
    """
    folder_id = _ensure_month_folder(execution_date.year, execution_date.month)
    return _copy_template(ot_number, folder_id)


def populate_ot_fields(
    spreadsheet_id: str,
    *,
    ot_number: str,
    area_name: str,
    section_name: str,
    equipment_name: str,
    maintenance_type: str,
    loto_status: str,
    description: str | None,
    participants: list[str],
    estimated_time: str | None,
    execution_date: str | None,
    request_date: str | None = None,
    resources_required: str | None = None,
    risks: str | None = None,
    observations: str | None = None,
    folio: str | None = None,
    voucher_number: str | None = None,
    requested_by: str | None = None,
    approved_by: str | None = None,
    requested_signature: str | None = None,
    approved_signature: str | None = None,
    status: str = "PENDING",
) -> None:
    """Write all OT fields into the template spreadsheet.

    Uses centralized OT_FIELD_MAP for text fields and text-based checkbox
    builders for maintenance_type, loto_status, and status.

    NEVER inserts/deletes rows or columns. It preserves template formatting
    except for a signed authorization block, whose merge and row height are
    adjusted solely to display the handwritten signature image.
    Writes only to the top-left cell of each merged range.
    """
    range_values = []

    # ── Text fields (from OT_FIELD_MAP) ──
    text_fields = {
        "ot_number":          ot_number,
        "area":               area_name,
        "section":            section_name or "",
        "equipment":          equipment_name or "",
        "description":        description or "",
        "participants":       ", ".join(participants) if participants else "",
        "estimated_time":     estimated_time or "",
        "execution_date":     execution_date or "",
        "request_date":       request_date or "",
        "resources_required": resources_required or "",
        "voucher_number":     voucher_number or "",
        "folio":              folio or "",
        "risks":              risks or "",
        "observations":       observations or "",
        # Autorización cells hold label + name + firma line; build the full text.
    }

    # An unsigned block retains the template's original three-row merge. A
    # signed one is rendered below as title + IMAGE() formula instead.
    if not requested_signature:
        text_fields["requested_by"] = build_authorization_text(REQUESTED_BY_LABEL, requested_by)
    if not approved_signature:
        text_fields["performed_by"] = build_authorization_text(REALIZADO_BY_LABEL, approved_by)

    for field, value in text_fields.items():
        if value and field in OT_FIELD_MAP:
            range_values.append({
                "range": OT_FIELD_MAP[field],
                "values": [[str(value)]],
            })

    # Write all text fields in one batch
    if range_values:
        _write_cells(spreadsheet_id, range_values)

    # ── Checkbox fields (text-based, per-option cells) ──
    # In this template each option is its OWN un-merged cell (C9..G9 for type,
    # C10..E10 for LOTO). Write "[X] Label" to the selected option cell and
    # "[ ] Label" to every other option cell. These option cells are the write
    # targets themselves — no stale glyph cells to clear.

    # Maintenance type (per-cell)
    for cell, text in build_maintenance_cell_texts(maintenance_type).items():
        _write_single(spreadsheet_id, cell, text)

    # LOTO status (per-cell)
    for cell, text in build_loto_cell_texts(loto_status).items():
        _write_single(spreadsheet_id, cell, text)

    # Status: single cell with wide spacing between options (B36:G36 merged).
    status_text = build_status_text(status)
    _write_single(spreadsheet_id, STATUS_CELL, status_text)

    # ── Signature overlay images (best-effort) ──
    if requested_signature:
        write_signature_image(
            spreadsheet_id,
            "requested_by",
            build_authorization_title(REQUESTED_BY_LABEL, requested_by),
            requested_signature,
        )
    if approved_signature:
        write_signature_image(
            spreadsheet_id,
            "approved_by",
            build_authorization_title(REALIZADO_BY_LABEL, approved_by),
            approved_signature,
        )


def update_ot_status(spreadsheet_id: str, status: str) -> None:
    """Update ONLY the status cell of an individual OT document in Drive.

    Called on each WorkOrder transition (start/complete/return/approve/cancel/
    reopen) so the OT's Google document reflects the current lifecycle state —
    not just the monthly register. Lightweight: writes a single cell.
    """
    _write_single(spreadsheet_id, STATUS_CELL, build_status_text(status))


def build_authorization_title(role_label: str, name: str | None) -> str:
    """Return the compact title shown above a handwritten signature."""
    return f"{role_label} {(name or '').strip()}".rstrip()


def _grid_range(sheet_id: int, values: dict[str, int]) -> dict[str, int]:
    return {
        "sheetId": sheet_id,
        "startRowIndex": values["start_row"],
        "endRowIndex": values["end_row"],
        "startColumnIndex": values["start_col"],
        "endColumnIndex": values["end_col"],
    }


def write_signature_image(
    spreadsheet_id: str,
    field: str,
    title: str,
    signature_url: str | None,
) -> None:
    """Render a handwritten signature as a real image above the OT grid.

    Sheets REST arranges the target block and Apps Script inserts the Drive
    blob itself. No IMAGE() formula or external URL remains in the document.
    """
    if not signature_url:
        return

    block = get_signature_block(field)
    if not block:
        raise ValueError(f"Bloque de firma no configurado: {field}")

    sheets = _build_sheets_write_service()
    metadata = sheets.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="sheets(properties(sheetId,index,title))",
    ).execute()
    sheet_id = metadata.get("sheets", [{}])[0].get("properties", {}).get("sheetId")
    if sheet_id is None:
        raise RuntimeError("No se pudo resolver la hoja de la OT para insertar la firma.")

    whole = _grid_range(sheet_id, block["whole"])
    label = _grid_range(sheet_id, block["label"])
    image = _grid_range(sheet_id, block["image"])
    requests = [
        {"unmergeCells": {"range": whole}},
        {"mergeCells": {"range": label, "mergeType": "MERGE_ALL"}},
        {"mergeCells": {"range": image, "mergeType": "MERGE_ALL"}},
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "ROWS",
                    "startIndex": block["image"]["start_row"],
                    "endIndex": block["image"]["end_row"],
                },
                "properties": {"pixelSize": 40},
                "fields": "pixelSize",
            }
        },
        {
            "updateCells": {
                "range": label,
                "rows": [{"values": [{"userEnteredValue": {"stringValue": title}}]}],
                "fields": "userEnteredValue",
            }
        },
        {
            # Clear an old IMAGE() formula before Apps Script overlays the
            # actual image blob. This makes re-sync repair existing OTs too.
            "updateCells": {
                "range": image,
                "rows": [{"values": [{"userEnteredValue": {"stringValue": ""}}]}],
                "fields": "userEnteredValue",
            }
        },
    ]
    sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body={"requests": requests}
    ).execute()
    sheet_name = metadata.get("sheets", [{}])[0].get("properties", {}).get("title")
    if not sheet_name:
        raise RuntimeError("No se pudo resolver el nombre de la hoja de la OT para insertar la firma.")
    insert_signature_image(spreadsheet_id, sheet_name, field, signature_url)
    logger.info("Firma insertada como imagen en OT %s (%s)", spreadsheet_id, field)


def _merge_monthly_columns_with_headers(
    spread_sheets_service, spreadsheet_id: str, sheet_title: str,
) -> dict[str, str]:
    """Resolve monthly column letters by reading the real headers.

    Returns {logical_key: column_letter}. Delegates to monthly_mapping's
    resolve_monthly_columns (header-driven first, static fallback), which also
    picks up the ESTADO header when present.
    """
    try:
        header_row = MONTHLY_DATA_START_ROW - 1  # 3
        range_name = f"{sheet_title}!A{header_row}:AA{header_row}"
        resp = spread_sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, range=range_name
        ).execute()
        values = resp.get("values", [[]])
        headers = values[0] if values else []
        return resolve_monthly_columns(headers)
    except Exception:  # noqa: BLE001
        logger.warning("No se pudieron resolver encabezados de %s via Google; usando estaticos.", sheet_title)
        return dict(MONTHLY_COLUMN_MAP)


def sync_to_monthly_sheet(
    ot_number: str,
    execution_date: datetime,
    *,
    area_name: str,
    section_name: str,
    equipment_name: str,
    description: str,
    maintenance_type: str,
    participants: list[str],
    duration_hours: float,
    status: str = "PENDING",
    actual_duration_minutes: float | None = None,
    spreadsheet_id: str | None = None,
) -> bool:
    """Append or update a single row in the monthly tracking sheet.

    Idempotent: N° OT (column B) is the unique key. If it already exists in the
    target month's tab, that SAME row is updated — never duplicated.

    Column positions are resolved header-driven from the real sheet
    (resolve_monthly_columns), with static fallback. This picks up any ESTADO
    column that has been appended after HORAS.

    ESTADO is written from the WorkOrder status via the approved mapping:
        PENDING->PENDIENTE, IN_PROGRESS->EN PROCESO, COMPLETED->FINALIZADO,
        CANCELLED->CANCELADA.  (DRAFT rows are never synced.)

    HORAS follows the approved rule (compute_horas): currently estimated_time
    parsed to hours; the real-time path (actual_duration_minutes, COMPLETED)
    is prepared but not yet fed by the data model.

    `spreadsheet_id` selects which annual register to write into (per-year model).
    When omitted it falls back to the legacy settings.GOOGLE_MONTHLY_SPREADSHEET_ID
    for backward compatibility.

    Returns True if written successfully.
    Raises RuntimeError if OAuth credentials are not configured.
    """
    if not is_eligible_for_monthly(status):
        logger.info("OT %s con status %s no se sincroniza al registro mensual (DRAFT).", ot_number, status)
        return False

    sheets = _build_sheets_write_service()

    sheet_title = get_monthly_sheet_title(execution_date.month)
    monthly_id = spreadsheet_id or settings.GOOGLE_MONTHLY_SPREADSHEET_ID
    col = _merge_monthly_columns_with_headers(sheets, monthly_id, sheet_title)

    # Search for existing row with this OT number (idempotency key)
    existing_row = _search_row_by_col(
        monthly_id, sheet_title, col["N_O_T"], ot_number
    )

    # Build the full row up to the last known column. HORAS -> V, ESTADO -> W
    # (or wherever the header says). Determine the widest present column.
    known_end = col.get("HORAS") or MONTHLY_LAST_COLUMN
    if "ESTADO" in col:
        if ord(col["ESTADO"]) > ord(known_end):
            known_end = col["ESTADO"]
    if "PARTICIPANTES" in col:
        if ord(col["PARTICIPANTES"]) > ord(known_end):
            known_end = col["PARTICIPANTES"]
    last_idx = ord(known_end) - ord("A") + 1
    row_values = [""] * last_idx

    def _put(col_letter: str, value: str):
        idx = ord(col_letter) - ord("A")
        row_values[idx] = str(value) if value else ""

    # Date format: DD-MM-YYYY (matching real sheet data)
    _put(col["FECHA"], execution_date.strftime("%d-%m-%Y"))
    _put(col["N_O_T"], ot_number)
    _put(col["AREA"], area_name)
    _put(col["SECCION"], section_name or "")
    _put(col["EQUIPO"], equipment_name or "")
    _put(col["TRABAJO"], description or "")

    # Worker columns: mark X for each participant.
    # Participant columns continue syncing individually. RESPONSABLE is NOT
    # derived from the first participant (see monthly_mapping notes).
    for p_name in participants:
        normalized = normalize_header(p_name)
        key = WORKER_COLUMN_KEYS.get(normalized)
        if key and key in col:
            _put(col[key], "X")

    # The named worker columns above are kept for compatibility with the
    # existing template. PARTICIPANTES is the future-proof summary column:
    # it includes every participant, including workers added after the
    # original template was created.
    if "PARTICIPANTES" in col:
        _put(col["PARTICIPANTES"], ", ".join(participants))

    # Maintenance type: mark X for the selected type
    mt_key = MONTHLY_MT_MAP.get(maintenance_type.upper())
    if mt_key and mt_key in col:
        _put(col[mt_key], "X")

    # ESTADO: approved status mapping (if the column exists in the sheet).
    if "ESTADO" in col:
        _put(col["ESTADO"], monthly_status_text(status))

    # HORAS: approved rule via compute_horas (currently estimated-time based).
    horas = compute_horas(
        HorasInput(
            estimated_minutes=round(duration_hours * 60, 2),
            status=status,
            actual_duration_minutes=actual_duration_minutes,
        )
    )
    _put(col["HORAS"], str(horas))

    if existing_row:
        # Update the SAME row (N° OT matched).
        range_name = f"{sheet_title}!A{existing_row}:{known_end}{existing_row}"
        body = {"values": [row_values]}
        sheets.spreadsheets().values().update(
            spreadsheetId=monthly_id,
            range=range_name,
            valueInputOption="RAW",
            body=body,
        ).execute()
        logger.info("OT %s actualizada en fila %d del registro mensual", ot_number, existing_row)
    else:
        # Append a new row AT THE FIRST FREE ROW right after the last real data
        # row (the header lives on the MONTHLY_DATA_START_ROW-1 line). Google's
        # native values().append writes at the END of the sheet's data extent,
        # which can be far below the visible data (stray formatted rows make the
        # extent huge), so rows would land several hundred rows down and look
        # "missing". Instead we compute the exact first empty row in column B
        # (the N° OT key column) and write there explicitly — the OT always
        # lands immediately under the header / last real entry.
        B = col["N_O_T"]
        resp = sheets.spreadsheets().values().get(
            spreadsheetId=monthly_id, range=f"{sheet_title}!{B}:{B}"
        ).execute()
        col_b = resp.get("values", [])
        # Find the first empty row at/after MONTHLY_DATA_START_ROW. col_b[i]
        # corresponds to spreadsheet row i+1.
        next_row = MONTHLY_DATA_START_ROW
        for i, cell in enumerate(col_b):
            row_no = i + 1
            if row_no < MONTHLY_DATA_START_ROW:
                continue
            if not cell or not str(cell[0]).strip():
                next_row = row_no
                break
        else:
            # The column is full up to the returned extent (or empty) -> the
            # next free row is after the last returned row, but never before
            # the data start row.
            next_row = max(MONTHLY_DATA_START_ROW, len(col_b) + 1)
        range_name = f"{sheet_title}!A{next_row}:{known_end}{next_row}"
        body = {"values": [row_values]}
        sheets.spreadsheets().values().update(
            spreadsheetId=monthly_id,
            range=range_name,
            valueInputOption="RAW",
            body=body,
        ).execute()
        logger.info(
            "OT %s agregada al registro mensual (%s, fila %d)",
            ot_number, sheet_title, next_row,
        )

    return True
