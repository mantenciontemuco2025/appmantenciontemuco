"""Google Drive/Sheets synchronization for equipment life sheets.

The database remains the source of truth. Each physical equipment receives one
copy of the master template; its rows are rebuilt from the associated work
orders, making retries idempotent and preventing duplicate OT rows.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime

from app.core.config import settings
from app.services.google_drive import (
    _build_drive_write_service,
    _build_sheets_write_service,
    _copy_template,
    _find_child,
    _get_file_parent,
)

logger = logging.getLogger(__name__)

_STATUS_LABELS = {
    "DRAFT": "Borrador",
    "PENDING": "Pendiente",
    "IN_PROGRESS": "En proceso",
    "COMPLETED": "Finalizada",
    "APPROVED": "Aprobada",
    "CANCELLED": "Cancelada",
}
_MAINTENANCE_LABELS = {
    "PREVENTIVE": "Preventivo",
    "CORRECTIVE": "Correctivo",
    "PREDICTIVE": "Predictivo",
    "PROYECTO": "Proyecto",
    "MONTAJE": "Montaje",
    "URGENTE": "Urgente",
}


def is_configured() -> bool:
    return bool(
        settings.GOOGLE_EQUIPMENT_LIFE_TEMPLATE_FILE_ID
        and settings.GOOGLE_EQUIPMENT_LIFE_ROOT_FOLDER_ID
    )


def _sheet_range(sheet_title: str, cell_range: str) -> str:
    safe_title = sheet_title.replace("'", "''")
    return f"'{safe_title}'!{cell_range}"


def _first_sheet_title(sheets, spreadsheet_id: str) -> str:
    metadata = sheets.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="sheets(properties(sheetId,title,index))",
    ).execute()
    entries = sorted(
        metadata.get("sheets", []),
        key=lambda item: (item.get("properties", {}).get("index", 0)),
    )
    if not entries:
        raise RuntimeError("La plantilla de hoja de vida no contiene ninguna pestaña.")
    return entries[0]["properties"]["title"]


def _ensure_section_folder(section_name: str) -> str:
    drive = _build_drive_write_service()
    root_id = settings.GOOGLE_EQUIPMENT_LIFE_ROOT_FOLDER_ID
    clean_section = " ".join((section_name or "SIN SECCIÓN").strip().split())
    folder_name = f"SECCIÓN - {clean_section}"
    section_id = _find_child(drive, root_id, folder_name)
    if section_id:
        return section_id
    return drive.files().create(
        body={
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [root_id],
        },
        fields="id",
    ).execute()["id"]


def _date_text(value) -> str:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.strftime("%d-%m-%Y")
    return ""


def _status_text(value) -> str:
    raw = str(getattr(value, "value", value) or "").upper()
    return _STATUS_LABELS.get(raw, raw or "Sin estado")


def _maintenance_text(value) -> str:
    raw = str(getattr(value, "value", value) or "").upper()
    return _MAINTENANCE_LABELS.get(raw, raw or "")


def _performed_by(work_order) -> str:
    if getattr(work_order, "is_external_work", False):
        return work_order.external_executor_name or work_order.external_company or "Trabajo externo"
    completed = getattr(work_order, "completed_by_user", None)
    responsible = getattr(work_order, "responsible_user", None)
    return (
        getattr(completed, "full_name", None)
        or getattr(responsible, "full_name", None)
        or work_order.requested_by
        or ""
    )


def _work_order_row(work_order) -> list[str]:
    description = (work_order.description or work_order.title or "").strip()
    observations = (work_order.observations or "").strip()
    completion_notes = (work_order.completion_notes or "").strip()
    if completion_notes and completion_notes != observations:
        observations = f"{observations} | {completion_notes}" if observations else completion_notes
    event_date = (
        work_order.execution_date
        or work_order.scheduled_date
        or work_order.request_date
        or work_order.created_at
    )
    return [
        _date_text(event_date),
        description,
        _performed_by(work_order),
        observations,
        _status_text(work_order.status),
        _maintenance_text(work_order.maintenance_type),
    ]


def _work_order_sort_key(work_order):
    event_date = (
        work_order.execution_date
        or work_order.scheduled_date
        or work_order.request_date
        or work_order.created_at
    )
    if isinstance(event_date, datetime):
        event_date = event_date.date()
    return (event_date or date.min, work_order.ot_number or "")


def sync_equipment_history(
    *,
    equipment_id: int,
    equipment_name: str,
    section_name: str | None,
    plant_area_name: str | None,
    existing_file_id: str | None,
    work_orders: list,
) -> dict:
    """Create/update one equipment file and rewrite its OT rows idempotently."""
    if not is_configured():
        raise RuntimeError(
            "Faltan GOOGLE_EQUIPMENT_LIFE_TEMPLATE_FILE_ID y "
            "GOOGLE_EQUIPMENT_LIFE_ROOT_FOLDER_ID."
        )

    section_folder_id = _ensure_section_folder(section_name or "SIN SECCIÓN")
    file_name = f"HV - {equipment_name.strip()} (BD-{equipment_id})"
    if existing_file_id:
        file_id = existing_file_id
        url = f"https://docs.google.com/spreadsheets/d/{file_id}/edit"
    else:
        copied = _copy_template(
            file_name,
            section_folder_id,
            template_file_id=settings.GOOGLE_EQUIPMENT_LIFE_TEMPLATE_FILE_ID,
        )
        file_id = copied["file_id"]
        url = copied.get("url") or f"https://docs.google.com/spreadsheets/d/{file_id}/edit"

    sheets = _build_sheets_write_service()
    sheet_title = _first_sheet_title(sheets, file_id)
    header_values = [
        {"range": _sheet_range(sheet_title, "A5"), "values": [[f"MANTENCIÓN - {plant_area_name or 'ÁREA'}"]]},
        {"range": _sheet_range(sheet_title, "B7"), "values": [[equipment_name]]},
    ]
    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=file_id,
        body={"valueInputOption": "USER_ENTERED", "data": header_values},
    ).execute()

    rows = [_work_order_row(item) for item in sorted(work_orders, key=_work_order_sort_key)]
    sheets.spreadsheets().values().clear(
        spreadsheetId=file_id,
        range=_sheet_range(sheet_title, "A11:F10000"),
        body={},
    ).execute()
    if rows:
        end_row = 10 + len(rows)
        sheets.spreadsheets().values().update(
            spreadsheetId=file_id,
            range=_sheet_range(sheet_title, f"A11:F{end_row}"),
            valueInputOption="USER_ENTERED",
            body={"values": rows},
        ).execute()

    return {
        "file_id": file_id,
        "url": url,
        "sheet_title": sheet_title,
        "row_count": len(rows),
    }
