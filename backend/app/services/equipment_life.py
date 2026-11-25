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


def _authorized_by(work_order) -> str:
    approver = getattr(work_order, "approved_by_user", None)
    return getattr(approver, "full_name", None) or getattr(work_order, "approved_by", None) or ""


def _worked_duration_minutes(work_order) -> int | None:
    minutes = getattr(work_order, "actual_duration_minutes", None)
    if minutes is None or float(minutes) <= 0:
        minutes = getattr(work_order, "worked_duration_minutes", None)
    if minutes is None and getattr(work_order, "work_time_mode", None) == "RANGE":
        start = getattr(work_order, "work_start_time", None)
        end = getattr(work_order, "work_end_time", None)
        if start and end:
            start_minutes = start.hour * 60 + start.minute
            end_minutes = end.hour * 60 + end.minute
            if end_minutes > start_minutes:
                minutes = end_minutes - start_minutes
    if minutes is None:
        return None
    result = int(round(float(minutes)))
    return result if result > 0 else None


def _worked_duration_text(work_order) -> str:
    minutes = _worked_duration_minutes(work_order)
    if minutes is None:
        return ""
    hours, remainder = divmod(minutes, 60)
    if hours and remainder:
        return f"{hours} h {remainder} min"
    if hours:
        return f"{hours} h"
    return f"{remainder} min"


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
        _authorized_by(work_order),
        observations,
        _status_text(work_order.status),
        _maintenance_text(work_order.maintenance_type),
        (work_order.resources_required or "").strip(),
        _worked_duration_text(work_order),
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
    try:
        spreadsheet = sheets.spreadsheets().get(
            spreadsheetId=file_id,
            fields="sheets(properties(sheetId,title,index,gridProperties(columnCount,rowCount)),bandedRanges(bandedRangeId,range))",
        ).execute()
    except Exception as exc:
        # A removed spreadsheet leaves a stale ID in the equipment row. On
        # retry, replace only a confirmed missing file with a fresh template
        # copy; permission, quota, and transient errors must remain visible.
        response = getattr(exc, "resp", None)
        status_code = getattr(response, "status", None) or getattr(exc, "status_code", None)
        if not existing_file_id or status_code not in (404, 410):
            raise
        logger.warning(
            "La hoja de vida %s del equipo %s ya no existe; se creará una copia nueva.",
            existing_file_id,
            equipment_id,
        )
        copied = _copy_template(
            file_name,
            section_folder_id,
            template_file_id=settings.GOOGLE_EQUIPMENT_LIFE_TEMPLATE_FILE_ID,
        )
        file_id = copied["file_id"]
        url = copied.get("url") or f"https://docs.google.com/spreadsheets/d/{file_id}/edit"
        spreadsheet = sheets.spreadsheets().get(
            spreadsheetId=file_id,
            fields="sheets(properties(sheetId,title,index,gridProperties(columnCount,rowCount)),bandedRanges(bandedRangeId,range))",
        ).execute()
    sheet_entries = sorted(
        spreadsheet.get("sheets", []),
        key=lambda item: item.get("properties", {}).get("index", 0),
    )
    if not sheet_entries:
        raise RuntimeError("La hoja de vida no contiene ninguna pestaña.")
    sheet_properties = sheet_entries[0]["properties"]
    sheet_id = sheet_properties["sheetId"]
    sheet_title = sheet_properties["title"]
    grid = sheet_properties.get("gridProperties", {})
    current_columns = int(grid.get("columnCount", 0))
    current_rows = int(grid.get("rowCount", 0))
    rows = [_work_order_row(item) for item in sorted(work_orders, key=_work_order_sort_key)]
    required_rows = max(11, 10 + len(rows))
    requests = []
    if current_columns < 9:
        requests.append({
            "insertDimension": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": current_columns,
                    "endIndex": 9,
                },
                "inheritFromBefore": current_columns > 0,
            }
        })
    if current_rows < required_rows:
        requests.append({
            "insertDimension": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "ROWS",
                    "startIndex": current_rows,
                    "endIndex": required_rows,
                },
                "inheritFromBefore": current_rows > 0,
            }
        })

    end_row_index = max(10, required_rows)
    for existing_band in sheet_entries[0].get("bandedRanges", []):
        band_range = existing_band.get("range", {})
        # A banding returned inside a Sheet can omit range.sheetId because
        # its parent already identifies the sheet. Treat that as this sheet,
        # and check for any overlap with the history table rather than only
        # ranges whose first row is exactly the header row.
        band_sheet_id = band_range.get("sheetId", sheet_id)
        band_start_row = band_range.get("startRowIndex", 0)
        band_end_row = band_range.get("endRowIndex")
        band_start_column = band_range.get("startColumnIndex", 0)
        band_end_column = band_range.get("endColumnIndex")
        overlaps_history = (
            band_start_row < end_row_index
            and (band_end_row is None or band_end_row > 9)
            and band_start_column < 9
            and (band_end_column is None or band_end_column > 0)
        )
        if band_sheet_id == sheet_id and overlaps_history:
            requests.append({"deleteBanding": {"bandedRangeId": existing_band["bandedRangeId"]}})

    requests.extend([
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {"frozenRowCount": 10},
                },
                "fields": "gridProperties.frozenRowCount",
            }
        },
        {
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 2, "startColumnIndex": 0, "endColumnIndex": 9},
                "cell": {"userEnteredFormat": {"backgroundColor": {"red": 0.09, "green": 0.20, "blue": 0.32}, "textFormat": {"foregroundColor": {"red": 1, "green": 1, "blue": 1}, "bold": True, "fontFamily": "Arial", "fontSize": 11}, "verticalAlignment": "MIDDLE"}},
                "fields": "userEnteredFormat(backgroundColor,textFormat,verticalAlignment)",
            }
        },
        {
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 3, "endRowIndex": 4, "startColumnIndex": 0, "endColumnIndex": 9},
                "cell": {"userEnteredFormat": {"backgroundColor": {"red": 0.09, "green": 0.20, "blue": 0.32}, "textFormat": {"foregroundColor": {"red": 1, "green": 1, "blue": 1}, "bold": True, "fontFamily": "Arial", "fontSize": 20}, "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE"}},
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)",
            }
        },
        {
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 4, "endRowIndex": 5, "startColumnIndex": 0, "endColumnIndex": 9},
                "cell": {"userEnteredFormat": {"backgroundColor": {"red": 0.93, "green": 0.68, "blue": 0.13}, "textFormat": {"foregroundColor": {"red": 0.12, "green": 0.17, "blue": 0.24}, "bold": True, "fontFamily": "Arial", "fontSize": 12}, "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE"}},
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)",
            }
        },
        {
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 6, "endRowIndex": 7, "startColumnIndex": 0, "endColumnIndex": 9},
                "cell": {"userEnteredFormat": {"backgroundColor": {"red": 0.91, "green": 0.94, "blue": 0.97}, "textFormat": {"foregroundColor": {"red": 0.09, "green": 0.20, "blue": 0.32}, "bold": True, "fontFamily": "Arial", "fontSize": 14}, "verticalAlignment": "MIDDLE"}},
                "fields": "userEnteredFormat(backgroundColor,textFormat,verticalAlignment)",
            }
        },
        {
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 9, "endRowIndex": 10, "startColumnIndex": 0, "endColumnIndex": 9},
                "cell": {"userEnteredFormat": {"backgroundColor": {"red": 0.09, "green": 0.20, "blue": 0.32}, "textFormat": {"foregroundColor": {"red": 1, "green": 1, "blue": 1}, "bold": True, "fontFamily": "Arial", "fontSize": 10}, "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP"}},
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment,wrapStrategy)",
            }
        },
        {
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 10, "endRowIndex": end_row_index, "startColumnIndex": 0, "endColumnIndex": 9},
                "cell": {"userEnteredFormat": {"textFormat": {"foregroundColor": {"red": 0.12, "green": 0.17, "blue": 0.24}, "fontFamily": "Arial", "fontSize": 10}, "verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP"}},
                "fields": "userEnteredFormat(textFormat,verticalAlignment,wrapStrategy)",
            }
        },
        {
            "addBanding": {
                "bandedRange": {
                    "range": {"sheetId": sheet_id, "startRowIndex": 9, "endRowIndex": end_row_index, "startColumnIndex": 0, "endColumnIndex": 9},
                    "rowProperties": {
                        "headerColor": {"red": 0.09, "green": 0.20, "blue": 0.32},
                        "firstBandColor": {"red": 1, "green": 1, "blue": 1},
                        "secondBandColor": {"red": 0.95, "green": 0.97, "blue": 0.99},
                    },
                }
            }
        },
        {
            "updateBorders": {
                "range": {"sheetId": sheet_id, "startRowIndex": 9, "endRowIndex": end_row_index, "startColumnIndex": 0, "endColumnIndex": 9},
                "top": {"style": "SOLID_MEDIUM", "color": {"red": 0.09, "green": 0.20, "blue": 0.32}},
                "bottom": {"style": "SOLID_MEDIUM", "color": {"red": 0.09, "green": 0.20, "blue": 0.32}},
                "left": {"style": "SOLID", "color": {"red": 0.78, "green": 0.82, "blue": 0.87}},
                "right": {"style": "SOLID", "color": {"red": 0.78, "green": 0.82, "blue": 0.87}},
                "innerHorizontal": {"style": "SOLID", "color": {"red": 0.84, "green": 0.87, "blue": 0.90}},
                "innerVertical": {"style": "SOLID", "color": {"red": 0.84, "green": 0.87, "blue": 0.90}},
            }
        },
        {
            "updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": 9, "endIndex": 10},
                "properties": {"pixelSize": 44},
                "fields": "pixelSize",
            }
        },
        {
            "updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": 10, "endIndex": end_row_index},
                "properties": {"pixelSize": 40},
                "fields": "pixelSize",
            }
        },
    ])
    for column_index, width in enumerate([110, 310, 190, 190, 300, 125, 190, 300, 160]):
        requests.append({
            "updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": column_index, "endIndex": column_index + 1},
                "properties": {"pixelSize": width},
                "fields": "pixelSize",
            }
        })
    sheets.spreadsheets().batchUpdate(
        spreadsheetId=file_id,
        body={"requests": requests},
    ).execute()

    header_values = [
        {"range": _sheet_range(sheet_title, "A5"), "values": [[f"MANTENCIÓN - {plant_area_name or 'ÁREA'}"]]},
        {"range": _sheet_range(sheet_title, "B7"), "values": [[equipment_name]]},
        {
            "range": _sheet_range(sheet_title, "A10:I10"),
            "values": [[
                "Fecha",
                "Descripción del trabajo",
                "Realizado por",
                "Autorizado por",
                "Observaciones",
                "Estado",
                "Tipo de mantenimiento",
                "Repuestos",
                "Tiempo real trabajado",
            ]],
        },
    ]
    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=file_id,
        body={"valueInputOption": "USER_ENTERED", "data": header_values},
    ).execute()

    sheets.spreadsheets().values().clear(
        spreadsheetId=file_id,
        range=_sheet_range(sheet_title, f"A11:I{max(current_rows, required_rows)}"),
        body={},
    ).execute()
    if rows:
        end_row = 10 + len(rows)
        sheets.spreadsheets().values().update(
            spreadsheetId=file_id,
            range=_sheet_range(sheet_title, f"A11:I{end_row}"),
            valueInputOption="USER_ENTERED",
            body={"values": rows},
        ).execute()

    return {
        "file_id": file_id,
        "url": url,
        "sheet_title": sheet_title,
        "row_count": len(rows),
    }
