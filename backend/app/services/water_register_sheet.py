"""Isolated Google Sheets adapter for the daily water register."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from app.core.config import settings
from app.core.water_register import (
    WATER_METERS,
    WATER_REGISTER_DATA_START_ROW,
    WATER_REGISTER_HEADER_ANCHORS,
)
from app.services.google_api_cache import build_cached_service


def _column_number(column: str) -> int:
    value = 0
    for character in column.upper():
        value = value * 26 + ord(character) - 64
    return value


def _column_letter(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _date_from_sheet(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return date(1899, 12, 30) + timedelta(days=int(value))
    text_value = str(value).strip()
    for format_string in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text_value, format_string).date()
        except ValueError:
            pass
    return None


def _date_serial(value: date) -> int:
    return (value - date(1899, 12, 30)).days


def _time_fraction(value: str | time) -> float:
    if isinstance(value, time):
        minutes = value.hour * 60 + value.minute + value.second / 60
    else:
        hour_text, minute_text = str(value).split(":", 1)
        minutes = int(hour_text) * 60 + int(minute_text[:2])
    return minutes / 1440


def _time_from_sheet(value) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        total_minutes = round(float(value) * 1440) % 1440
        return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"
    text_value = str(value).strip()
    if ":" in text_value:
        hour_text, minute_text = text_value.split(":", 1)
        return f"{int(hour_text):02d}:{int(minute_text[:2]):02d}"
    return None


def _number(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        result = Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _build_water_service(*, write: bool):
    if not settings.GOOGLE_WATER_REGISTER_SPREADSHEET_ID:
        raise RuntimeError("Falta GOOGLE_WATER_REGISTER_SPREADSHEET_ID.")
    credentials = (
        settings.get_google_write_credentials()
        if write
        else settings.get_google_credentials()
    )
    if credentials is None:
        raise RuntimeError("Google Sheets no tiene credenciales configuradas.")
    credential_key = (
        "oauth",
        settings.GOOGLE_OAUTH_CLIENT_ID,
        settings.GOOGLE_OAUTH_CLIENT_SECRET,
        settings.GOOGLE_OAUTH_REFRESH_TOKEN,
    )
    service = build_cached_service(
        cache_name="water-register-sheets-write" if write else "water-register-sheets-read",
        service_name="sheets",
        version="v4",
        credentials=credentials,
        credentials_key=credential_key,
    )
    return service, settings.GOOGLE_WATER_REGISTER_SPREADSHEET_ID


def _worksheet_id(service, spreadsheet_id: str) -> int:
    metadata = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="sheets(properties(sheetId,title))",
    ).execute()
    for sheet in metadata.get("sheets", []):
        properties = sheet.get("properties", {})
        if properties.get("title") == settings.GOOGLE_WATER_REGISTER_SHEET_NAME:
            return int(properties["sheetId"])
    raise RuntimeError(
        f"No existe la pestaña '{settings.GOOGLE_WATER_REGISTER_SHEET_NAME}' en el registro de agua."
    )


def _validate_template(service, spreadsheet_id: str) -> int:
    sheet_id = _worksheet_id(service, spreadsheet_id)
    response = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'{settings.GOOGLE_WATER_REGISTER_SHEET_NAME}'!A3:AG3",
        valueRenderOption="FORMULA",
    ).execute()
    cells = (response.get("values") or [[]])[0]
    for address, expected in WATER_REGISTER_HEADER_ANCHORS.items():
        column = address.rstrip("0123456789")
        position = _column_number(column) - 1
        actual = cells[position] if position < len(cells) else ""
        if str(actual).strip().casefold() != expected.casefold():
            raise RuntimeError(
                f"La plantilla no coincide en {address}: se esperaba '{expected}' y se encontró '{actual}'."
            )
    return sheet_id


def _format_dqo_columns(service, spreadsheet_id: str, sheet_id: int) -> None:
    """Format DQO date/time cells without changing their stored values."""
    start_row = WATER_REGISTER_DATA_START_ROW - 1
    end_row = 1200
    requests = [
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": start_row,
                    "endRowIndex": end_row,
                    "startColumnIndex": _column_number("AD") - 1,
                    "endColumnIndex": _column_number("AD"),
                },
                "cell": {
                    "userEnteredFormat": {
                        "numberFormat": {"type": "DATE", "pattern": "dd/mm/yyyy"}
                    }
                },
                "fields": "userEnteredFormat.numberFormat",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": start_row,
                    "endRowIndex": end_row,
                    "startColumnIndex": _column_number("AE") - 1,
                    "endColumnIndex": _column_number("AE"),
                },
                "cell": {
                    "userEnteredFormat": {
                        "numberFormat": {"type": "TIME", "pattern": "hh:mm"}
                    }
                },
                "fields": "userEnteredFormat.numberFormat",
            }
        },
    ]
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests},
    ).execute()


def read_latest_meter_baselines() -> list[dict]:
    """Get the last positive final reading per meter, ignoring template zeros."""
    service, spreadsheet_id = _build_water_service(write=False)
    _validate_template(service, spreadsheet_id)
    sheet = settings.GOOGLE_WATER_REGISTER_SHEET_NAME
    last_row = 1200
    ranges = [f"'{sheet}'!A{WATER_REGISTER_DATA_START_ROW}:A{last_row}"]
    ranges.extend(
        f"'{sheet}'!{meter.final_column}{WATER_REGISTER_DATA_START_ROW}:{meter.final_column}{last_row}"
        for meter in WATER_METERS
    )
    response = service.spreadsheets().values().batchGet(
        spreadsheetId=spreadsheet_id,
        ranges=ranges,
        valueRenderOption="UNFORMATTED_VALUE",
    ).execute()
    value_ranges = response.get("valueRanges", [])
    if len(value_ranges) != len(ranges):
        raise RuntimeError("Google Sheets no devolvió todas las columnas de lecturas.")
    dates = [row[0] if row else None for row in value_ranges[0].get("values", [])]
    baselines = []
    for meter, values in zip(WATER_METERS, value_ranges[1:]):
        finals = [row[0] if row else None for row in values.get("values", [])]
        found = None
        for index in range(max(len(dates), len(finals)) - 1, -1, -1):
            reading = _number(finals[index] if index < len(finals) else None)
            reading_date = _date_from_sheet(dates[index] if index < len(dates) else None)
            if reading is not None and reading > 0 and reading_date is not None:
                found = {
                    "meter_key": meter.key,
                    "final_reading": reading,
                    "reading_date": reading_date,
                    "source_row": WATER_REGISTER_DATA_START_ROW + index,
                }
                break
        if found is None:
            raise RuntimeError(f"No se encontró una lectura final válida para {meter.label}.")
        baselines.append(found)
    return baselines


def _find_record_row(service, spreadsheet_id: str, record_date: date) -> int:
    sheet = settings.GOOGLE_WATER_REGISTER_SHEET_NAME
    start = WATER_REGISTER_DATA_START_ROW
    end = 1200
    response = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'{sheet}'!A{start}:A{end}",
        valueRenderOption="UNFORMATTED_VALUE",
    ).execute()
    for index, row in enumerate(response.get("values", [])):
        if row and _date_from_sheet(row[0]) == record_date:
            return start + index
    raise RuntimeError(
        f"La plantilla no tiene una fila con fecha {record_date:%d-%m-%Y}; no se insertó una fila nueva."
    )


def read_historical_range(start_date: date, end_date: date) -> list[dict]:
    """Read existing spreadsheet rows for a date range without importing them."""
    service, spreadsheet_id = _build_water_service(write=False)
    _validate_template(service, spreadsheet_id)
    sheet = settings.GOOGLE_WATER_REGISTER_SHEET_NAME
    response = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'{sheet}'!A{WATER_REGISTER_DATA_START_ROW}:AG1200",
        valueRenderOption="UNFORMATTED_VALUE",
    ).execute()

    def cell(row: list, column: str):
        index = _column_number(column) - 1
        return row[index] if index < len(row) else None

    rows: list[dict] = []
    current_date: date | None = None
    for offset, raw_row in enumerate(response.get("values", [])):
        row = list(raw_row)
        row_number = WATER_REGISTER_DATA_START_ROW + offset
        parsed_date = _date_from_sheet(cell(row, "A"))
        if parsed_date is not None:
            current_date = parsed_date
        if current_date is None or not (start_date <= current_date <= end_date):
            continue

        meter_values = []
        for meter in WATER_METERS:
            initial = _number(cell(row, meter.initial_column))
            final = _number(cell(row, meter.final_column))
            volume = _number(cell(row, meter.volume_column))
            if initial is None and final is None:
                continue
            if volume is None and initial is not None and final is not None:
                volume = final - initial if final >= initial else Decimal("0")
            meter_values.append({
                "meter_key": meter.key,
                "label": meter.label,
                "initial_reading": initial,
                "final_reading": final,
                "volume_m3": volume,
            })

        dqo_date = _date_from_sheet(cell(row, "AD")) or current_date
        dqo_time = _time_from_sheet(cell(row, "AE"))
        dqo_pool = cell(row, "AF")
        dqo_mg_l = _number(cell(row, "AG"))
        dqo = None
        if dqo_time or dqo_pool not in (None, "") or dqo_mg_l is not None:
            dqo = {
                "date": dqo_date,
                "time": dqo_time,
                "pool": str(dqo_pool) if dqo_pool not in (None, "") else None,
                "mg_l": dqo_mg_l,
            }

        general = [cell(row, column) for column in ("B", "C", "D", "E")]
        if not (any(value not in (None, "") for value in general) or meter_values or dqo):
            continue
        rows.append({
            "sheet_row": row_number,
            "record_date": current_date,
            "discharge_flow_m3": _number(cell(row, "B")),
            "ph_plc": _number(cell(row, "C")),
            "ph_discharge": _number(cell(row, "D")),
            "discharge_temp_c": _number(cell(row, "E")),
            "meters": meter_values,
            "dqo": dqo,
        })
    return rows


def _has_legacy_data(service, spreadsheet_id: str, row_number: int) -> bool:
    sheet = settings.GOOGLE_WATER_REGISTER_SHEET_NAME
    response = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'{sheet}'!A{row_number}:AG{row_number}",
        valueRenderOption="FORMULA",
    ).execute()
    values = (response.get("values") or [[]])[0]
    # Date, formula-based initial cells and computed volume cells are expected.
    input_columns = ["B", "C", "D", "E", "G", "J", "M", "P", "S", "V", "Y", "AB", "AD", "AE", "AF", "AG"]
    for meter in WATER_METERS:
        input_columns.append(meter.initial_column)
    for column in input_columns:
        index = _column_number(column) - 1
        value = values[index] if index < len(values) else ""
        if isinstance(value, str) and value.startswith("="):
            continue
        if value in (None, "", 0, 0.0, "0"):
            continue
        return True
    return False


def write_daily_record(record: dict, *, allow_existing: bool = False) -> dict:
    """Write the daily row and DQO samples without touching volume formulas.

    DQO samples after the first one use only AD:AG on an otherwise unused DQO
    row. The rest of those rows, including all meter/formula columns, is left
    untouched.
    """
    service, spreadsheet_id = _build_water_service(write=True)
    sheet_id = _validate_template(service, spreadsheet_id)
    record_date: date = record["record_date"]
    row_number = _find_record_row(service, spreadsheet_id, record_date)
    if not allow_existing and _has_legacy_data(service, spreadsheet_id, row_number):
        raise RuntimeError(
            "La fila de esa fecha ya contiene datos que no pertenecen a la app; se protegió para no sobrescribirlos."
        )
    sheet = settings.GOOGLE_WATER_REGISTER_SHEET_NAME
    updates: list[dict] = []

    def add_cell_range(start_column: str, end_column: str, values: list):
        updates.append({
            "range": f"'{sheet}'!{start_column}{row_number}:{end_column}{row_number}",
            "values": [values],
        })

    add_cell_range("A", "E", [
        _date_serial(record_date),
        record.get("discharge_flow_m3"),
        record.get("ph_plc"),
        record.get("ph_discharge"),
        record.get("discharge_temp_c"),
    ])
    readings = record.get("readings", {})
    for meter in WATER_METERS:
        reading = readings.get(meter.key)
        pair = [reading["initial_reading"], reading["final_reading"]] if reading else ["", ""]
        add_cell_range(meter.initial_column, meter.final_column, pair)
    # Read only the DQO columns so we can clear removed samples and allocate
    # extra samples without ever inspecting or writing the meter formulas.
    dqo_rows_to_clear = set(record.get("dqo_rows_to_clear", []))
    samples = list(record.get("dqo_samples", []))
    existing_sample_rows = {
        int(sample["sheet_row"])
        for sample in samples
        if sample.get("sheet_row") is not None
    }
    dqo_response = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'{sheet}'!AD{WATER_REGISTER_DATA_START_ROW}:AG1200",
        valueRenderOption="UNFORMATTED_VALUE",
    ).execute()
    dqo_values_by_row = {
        WATER_REGISTER_DATA_START_ROW + index: (row + [""] * 4)[:4]
        for index, row in enumerate(dqo_response.get("values", []))
    }

    available_rows = {
        candidate
        for candidate in range(row_number + 1, 1201)
        if not any(
            value not in (None, "")
            for value in dqo_values_by_row.get(candidate, ["", "", "", ""])
        )
    }
    dqo_rows: list[int] = []
    for index, sample in enumerate(samples):
        sample_row = sample.get("sheet_row")
        if sample_row is None:
            if index == 0:
                sample_row = row_number
            else:
                candidates = sorted(
                    candidate
                    for candidate in available_rows
                    if candidate not in existing_sample_rows
                    and candidate not in dqo_rows_to_clear
                )
                if not candidates:
                    raise RuntimeError("No hay filas disponibles para agregar otra muestra DQO.")
                sample_row = candidates[0]
            sample["sheet_row"] = sample_row
        dqo_rows.append(int(sample_row))
        available_rows.discard(int(sample_row))
        dqo_rows_to_clear.discard(int(sample_row))

    for old_row in sorted(dqo_rows_to_clear):
        updates.append({
            "range": f"'{sheet}'!AD{old_row}:AG{old_row}",
            "values": [["", "", "", ""]],
        })

    for sample, sample_row in zip(samples, dqo_rows):
        updates.append({
            "range": f"'{sheet}'!AD{sample_row}:AG{sample_row}",
            "values": [[
                _date_serial(sample["date"]),
                _time_fraction(sample["time"]),
                sample["pool"],
                sample["mg_l"],
            ]],
        })

    service.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"valueInputOption": "RAW", "data": updates},
    ).execute()
    _format_dqo_columns(service, spreadsheet_id, sheet_id)
    return {"record_row": row_number, "dqo_rows": dqo_rows}
