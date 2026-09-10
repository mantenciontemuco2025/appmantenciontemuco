"""Google Sheets integration service (decoupled from routers).

This service is responsible for:
1. Building the row mapping from a MaintenanceRecord to the spreadsheet columns
   (centralized mapping so the app doesn't depend on column order scattered
   across the codebase).
2. Appending a row to Google Sheets using a Service Account.

The platform works WITHOUT Google configured: if credentials are missing,
sync is simply skipped (record stays PENDING).
"""

import logging
import unicodedata

from app.core.config import settings
from app.models.maintenance import MaintenanceRecord, MaintenanceType

logger = logging.getLogger(__name__)

# Centralized mapping: spreadsheet column name -> value builder.
# The exact order here defines the physical column layout in the sheet.
SHEET_COLUMN_MAPPING: list[dict] = [
    {"column": "FECHA", "key": "fecha"},
    {"column": "AREA", "key": "area"},
    {"column": "SECCION", "key": "seccion"},
    {"column": "EQUIPO", "key": "equipo"},
    {"column": "TRABAJO", "key": "trabajo"},
    # Worker columns must match the physical layout of the target sheet exactly
    # (the sheet has JARA between FABRES and SALAZAR, and HORAS is column R).
    {"column": "ORTIZ", "key": "ortiz"},
    {"column": "VALDES", "key": "valdes"},
    {"column": "FABRES", "key": "fabres"},
    {"column": "JARA", "key": "jara"},
    {"column": "SALAZAR", "key": "salazar"},
    {"column": "MILLAR", "key": "millar"},
    {"column": "JUAN SILVA", "key": "juan_silva"},
    {"column": "INOSTROZA", "key": "inostroza"},
    {"column": "CANIULLAN", "key": "caniullan"},
    {"column": "CONTRERAS", "key": "contreras"},
    {"column": "PREVENTIVO", "key": "preventivo"},
    {"column": "CORRECTIVO", "key": "correctivo"},
    {"column": "HORAS", "key": "horas"},
]


def _normalize_name(name: str) -> str:
    """Strip accents and punctuation, uppercase. 'Valdés' -> 'VALDES'."""
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in nfkd if not unicodedata.combining(c))
    return ascii_only.strip().upper().replace(".", "")


def _participant_key_by_name(full_name: str) -> str | None:
    """Map a participant's full_name to a sheet column key (case/accent-insensitive)."""
    normalized = _normalize_name(full_name)
    mapping = {
        "ORTIZ": "ortiz",
        "VALDES": "valdes",
        "FABRES": "fabres",
        "JARA": "jara",
        "SALAZAR": "salazar",
        "MILLAR": "millar",
        "JUAN SILVA": "juan_silva",
        "INOSTROZA": "inostroza",
        "CANIULLAN": "caniullan",
        "CONTRERAS": "contreras",
    }
    return mapping.get(normalized)


def build_sheet_row(maintenance: MaintenanceRecord) -> list:
    """Build a single spreadsheet row from a MaintenanceRecord.

    The order of values follows SHEET_COLUMN_MAPPING.
    """
    # Build the set of participating sheet-keys (e.g. {"ortiz", "valdes"})
    participant_keys = set()
    for participant in maintenance.participants:
        key = _participant_key_by_name(participant.full_name)
        if key:
            participant_keys.add(key)

    # Determine preventive/corrective check
    preventive = "X" if maintenance.maintenance_type == MaintenanceType.PREVENTIVE else ""
    corrective = "X" if maintenance.maintenance_type == MaintenanceType.CORRECTIVE else ""

    # HORAS = duration in hours, e.g. 210 min => 3.5
    # Kept as a real number so the sheet can sum it.
    hours = round(maintenance.duration_minutes / 60, 2)

    values = {
        # Date as plain text so Google doesn't convert it to a serial (e.g. 46268).
        "fecha": maintenance.date.isoformat(),
        "area": maintenance.area.name if maintenance.area else "",
        "seccion": getattr(maintenance, "section_name", "") or "",
        "equipo": maintenance.equipment.name if maintenance.equipment else "",
        "trabajo": maintenance.description,
        "ortiz": "X" if "ortiz" in participant_keys else "",
        "valdes": "X" if "valdes" in participant_keys else "",
        "fabres": "X" if "fabres" in participant_keys else "",
        "jara": "X" if "jara" in participant_keys else "",
        "salazar": "X" if "salazar" in participant_keys else "",
        "millar": "X" if "millar" in participant_keys else "",
        "juan_silva": "X" if "juan_silva" in participant_keys else "",
        "inostroza": "X" if "inostroza" in participant_keys else "",
        "caniullan": "X" if "caniullan" in participant_keys else "",
        "contreras": "X" if "contreras" in participant_keys else "",
        "preventivo": preventive,
        "correctivo": corrective,
        "horas": hours,  # numeric hours (float), not a string
    }

    row = []
    for mapping in SHEET_COLUMN_MAPPING:
        row.append(values[mapping["key"]])
    return row


def _is_configured() -> bool:
    # Configured when either OAuth (preferred) or Service Account credentials exist
    return settings.google_auth_method is not None


def _build_service():
    """Build the Sheets API service (READ). Raises a clear error if misconfigured.

    Returns (service, spreadsheet_id, sheet_name). Uses OAuth (preferred) or
    Service Account (fallback) credentials. Only imports the Google libraries
    lazily so the app can start without them installed.
    """
    from googleapiclient.discovery import build

    creds = settings.get_google_credentials()
    if creds is None:
        raise RuntimeError("Google no configurado (OAuth o Service Account).")
    service = build("sheets", "v4", credentials=creds)
    return service, settings.GOOGLE_SPREADSHEET_ID, settings.GOOGLE_SHEET_NAME


def _build_write_service():
    """Build the Sheets API service for WRITE (OAuth ONLY).

    Never falls back to the Service Account for writes. Raises a clear error
    if OAuth is not configured.
    """
    from googleapiclient.discovery import build

    creds = settings.get_google_write_credentials()
    service = build("sheets", "v4", credentials=creds)
    return service, settings.GOOGLE_SPREADSHEET_ID, settings.GOOGLE_SHEET_NAME


def check_google_integration() -> dict:
    """Read-only health check of the Google Sheets integration.

    Returns a safe dict of booleans. Never exposes credentials, JSON, or tokens.
    """
    from googleapiclient.errors import HttpError as GoogleHttpError

    result = {
        "configured": False,
        "credentials_valid": False,
        "spreadsheet_access": False,
        "sheet_found": False,
        "error": None,
    }

    if not _is_configured():
        result["configured"] = False
        result["error"] = "Google Sheets no configurado (faltan credenciales, SPREADSHEET_ID o SHEET_NAME)."
        return result

    result["configured"] = True

    # 1) Credentials must be usable
    try:
        service, spreadsheet_id, sheet_name = _build_service()
        result["credentials_valid"] = True
    except Exception as exc:  # noqa: BLE001 - surface a safe, generic message
        result["error"] = f"No se pudieron construir las credenciales: {type(exc).__name__}"
        return result

    # 2) The spreadsheet must be reachable (read-only GET of metadata)
    try:
        meta = (
            service.spreadsheets()
            .get(spreadsheetId=spreadsheet_id, fields="properties.title,sheets(properties.title)")
            .execute()
        )
        result["spreadsheet_access"] = True
    except GoogleHttpError as exc:
        result["error"] = f"Sin acceso al spreadsheet: {exc.resp.status}"
        return result
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"Error al consultar el spreadsheet: {type(exc).__name__}"
        return result

    # 3) The named sheet must exist
    sheet_titles = [s.get("properties", {}).get("title") for s in meta.get("sheets", [])]
    if sheet_name in sheet_titles:
        result["sheet_found"] = True
    else:
        result["error"] = f"La hoja '{sheet_name}' no existe en el spreadsheet."

    return result


def append_row_to_sheet(row: list) -> bool:
    """Append a row to the configured Google Sheet with a white background.

    The target sheet has colored column headers (and pre-colored rows). When
    the app appends a record, we explicitly paint the 18 data cells (A..R) of
    the new row white so the records show up on a clean/blank background
    instead of inheriting the column color.

    Returns True if the row was actually written. Returns False if Google
    Writes require OAuth — the Service Account is never used as a fallback.
    Raises a clear error if OAuth is not configured so the caller marks the
    record FAILED rather than silently skipping or writing as the wrong
    identity.
    """
    from googleapiclient.errors import HttpError as GoogleHttpError

    try:
        service, spreadsheet_id, sheet_name = _build_write_service()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error al construir el servicio de Google Sheets")
        raise RuntimeError(f"Google Sheets config error: {exc}") from exc

    body = {"values": [row]}
    try:
        append_response = (
            service.spreadsheets()
            .values()
            .append(
                spreadsheetId=spreadsheet_id,
                range=f"{sheet_name}!A:R",  # 18 columns: FECHA..HORAS
                # RAW keeps the date as plain text ("2026-09-02") instead of
                # Google auto-converting it to a serial number (e.g. 46268).
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body=body,
            )
            .execute()
        )
    except GoogleHttpError as exc:
        logger.exception("Error al escribir en Google Sheets")
        raise RuntimeError(f"Google Sheets API error: {exc}") from exc

    # Paint the appended row's cells white so records don't inherit the
    # pre-colored background of the sheet's columns.
    updated_range = append_response.get("updates", {}).get("updatedRange", "")
    if updated_range and "!" in updated_range:
        # updatedRange is like "'ENERO 2026'!A8:R8" (title may come single-quoted)
        sheet_title, cell_range = updated_range.rsplit("!", 1)
        sheet_title = sheet_title.strip().strip("'")
        try:
            # cell_range looks like "A8:R8" -> row 8
            start_cell = cell_range.split(":", 1)[0].lstrip("$")
            row_number = "".join(ch for ch in start_cell if ch.isdigit())
            white_fill = {"red": 1, "green": 1, "blue": 1, "alpha": 1}

            batch_request = {
                "requests": [
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": None,  # resolved below from sheet
                                "startRowIndex": int(row_number) - 1,
                                "endRowIndex": int(row_number),
                                "startColumnIndex": 0,  # A
                                "endColumnIndex": len(SHEET_COLUMN_MAPPING),  # R (0..18)
                            },
                            "cell": {"userEnteredFormat": {"backgroundColor": white_fill}},
                            "fields": "userEnteredFormat.backgroundColor",
                        }
                    }
                ]
            }

            # RepeatCell needs the numeric sheetId, which we resolve once.
            sheet_id = _get_sheet_id(service, spreadsheet_id, sheet_title)
            if sheet_id is not None:
                batch_request["requests"][0]["repeatCell"]["range"]["sheetId"] = sheet_id
                service.spreadsheets().batchUpdate(
                    spreadsheetId=spreadsheet_id, body=batch_request
                ).execute()
                logger.info("Celda(s) de la fila %s pintadas de blanco.", row_number)
        except Exception as exc:  # noqa: BLE001 - formatting is best-effort
            logger.warning("No se pudo pintar la fila de blanco: %s", exc)

    return True


def _get_sheet_id(service, spreadsheet_id: str, title: str) -> int | None:
    """Return the numeric sheetId for a sheet title (or None if not found)."""
    try:
        meta = (
            service.spreadsheets()
            .get(spreadsheetId=spreadsheet_id, fields="sheets(properties(sheetId,title))")
            .execute()
        )
        for sheet in meta.get("sheets", []):
            if sheet.get("properties", {}).get("title") == title:
                return sheet["properties"]["sheetId"]
    except Exception:  # noqa: BLE001
        logger.warning("No se pudo resolver el sheetId de '%s'.", title)
    return None


# ─────────────────────────────────────────────────────────────────────
# Upsert (edit-safe) row writing
# ─────────────────────────────────────────────────────────────────────

# Columns that, together, identify a maintenance row in the sheet. The sheet
# has no OT number, so we key on FECHA+AREA+SECCION+EQUIPO (NOT the TRABAJO
# text, which is the most editable field and must not break the lookup).
_UPSERT_KEY_RANGE = "A:D"  # FECHA A, AREA B, SECCION C, EQUIPO D


def _norm(text: str) -> str:
    """Uppercase, strip accents and punctuation (for key comparison)."""
    return unicodedata.normalize("NFKD", str(text))\
        .encode("ascii", "ignore").decode()\
        .strip().upper().replace(".", "").replace("°", "")


def _sheet_key_values(maintenance: MaintenanceRecord) -> list[str]:
    """The identity values used to locate a maintenance row in the sheet."""
    return [
        maintenance.date.isoformat(),                      # FECHA   -> A
        maintenance.area.name if maintenance.area else "",  # AREA    -> B
        maintenance.section_name or "",                     # SECCION -> C
        maintenance.equipment.name if maintenance.equipment else "",  # EQUIPO -> D
    ]


def _find_row_by_key(sheets, spreadsheet_id: str, sheet_name: str, key: list[str]) -> int | None:
    """Return 1-indexed row number of the first row matching the key, or None.

    The key is compared on the FECHA/AREA/SECCION/EQUIPO columns (A,B,C,D).
    Matching is case/accent-insensitive to tolerate manual edits of the sheet.
    """
    lookup = [_norm(v) for v in key]
    resp = (
        sheets.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=f"{sheet_name}!{_UPSERT_KEY_RANGE}")
        .execute()
    )
    rows = resp.get("values", [])
    for i, row_vals in enumerate(rows, start=1):
        if not row_vals:
            continue
        candidate = [
            row_vals[0] if len(row_vals) > 0 else "",
            row_vals[1] if len(row_vals) > 1 else "",
            row_vals[2] if len(row_vals) > 2 else "",
            row_vals[3] if len(row_vals) > 3 else "",
        ]
        if [_norm(c) for c in candidate] == lookup:
            return i
    return None


def upsert_row_to_sheet(row: list, maintenance: MaintenanceRecord) -> bool:
    """Update the existing maintenance row in the sheet, or append a new one.

    Idempotent for edits: instead of appending a fresh row on every update
    (which left duplicate rows for the same maintenance after an edit), we
    locate the original row via the FECHA+AREA+SECCION+EQUIPO key and UPDATE
    it in place. If the key isn't found (e.g. the row was manually removed),
    we fall back to append_row_to_sheet so the data is never lost.

    Also works like append_row_to_sheet regarding OAuth: writes require OAuth;
    without it, append_row_to_sheet returns False and the record stays PENDING.

    Returns True if a row was written (update or append). Raises on Google
    errors, so the caller can mark the record FAILED.
    """
    sheets, spreadsheet_id, sheet_name = _build_write_service()
    existing = _find_row_by_key(sheets, spreadsheet_id, sheet_name, _sheet_key_values(maintenance))

    if existing is None:
        # Fall back to the append path (keeps current white-background logic).
        return append_row_to_sheet(row)

    # Update the SAME row (all 18 columns, A..R).
    range_name = f"{sheet_name}!A{existing}:{'R'}{existing}"
    body = {"values": [row]}
    try:
        sheets.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption="RAW",
            body=body,
        ).execute()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error al actualizar la fila de mantención en Google Sheets")
        raise RuntimeError(f"Google Sheets API error: {exc}") from exc

    logger.info("Mantención actualizada en fila %d del registro mensual", existing)

    # Clean up duplicate rows (from earlier edits) that share the same key.
    # We exclude the canonical row we just updated and delete every other
    # matching row. Deleting is best-effort: a failure here must NOT fail the
    # whole update, so we log and continue.
    _delete_duplicate_rows(sheets, spreadsheet_id, sheet_name, _sheet_key_values(maintenance), keep=int(existing))

    return True


def _delete_duplicate_rows(
    sheets, spreadsheet_id: str, sheet_name: str, key: list[str], *, keep: int
) -> None:
    """Delete rows (other than ``keep``) that match the given key.

    Best-effort helper: dependency rows deleted first so indices stay correct.
    """
    lookup = [_norm(v) for v in key]
    resp = (
        sheets.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=f"{sheet_name}!{_UPSERT_KEY_RANGE}")
        .execute()
    )
    rows = resp.get("values", [])

    # Collect the sheet rows to delete, excluding the canonical one.
    to_delete: list[int] = []
    for i, row_vals in enumerate(rows, start=1):
        if i == keep:
            continue
        if not row_vals:
            continue
        candidate = [
            row_vals[0] if len(row_vals) > 0 else "",
            row_vals[1] if len(row_vals) > 1 else "",
            row_vals[2] if len(row_vals) > 2 else "",
            row_vals[3] if len(row_vals) > 3 else "",
        ]
        if [_norm(c) for c in candidate] == lookup:
            to_delete.append(i)

    if not to_delete:
        return

    # Delete highest rows first so earlier indices don't shift.
    sheet_id = _get_sheet_id(sheets, spreadsheet_id, sheet_name)
    if sheet_id is None:
        logger.warning("No se pudo resolver sheetId; no se limpiaron duplicados.")
        return

    requests = [
        {
            "deleteDimension": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "ROWS",
                    "startIndex": int(r) - 1,
                    "endIndex": int(r),
                }
            }
        }
        for r in reversed(sorted(to_delete))
    ]
    try:
        sheets.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": requests}
        ).execute()
        logger.info("Se eliminaron %d fila(s) duplicada(s) de mantención.", len(to_delete))
    except Exception as exc:  # noqa: BLE001 - cleanup is best-effort
        logger.warning("No se pudo limpiar filas duplicadas: %s", exc)
