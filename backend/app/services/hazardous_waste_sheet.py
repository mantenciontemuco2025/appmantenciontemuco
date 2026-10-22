"""Google Sheets adapter for hazardous-waste register sync."""

import re
import unicodedata
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from app.core.config import settings
from app.services.google_api_cache import build_cached_service

HEADERS = [
    "FECHA INGRESO", "N° RESPEL", "NOMBRE RESPEL", "PELIGROSIDAD", "ORIGEN",
    "CANTIDAD/ UNIDADES", "NOMBRE DE QUIEN ENTREGA", "CANTIDAD ACUMULADA",
    "FECHA DE TRANSPORTE Y DISPOSICIÓN", "NOMBRE DE GESTOR", "ID INTERNO APP",
]


def _normalize(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def _service(spreadsheet_id: str, *, write: bool):
    credentials = settings.get_google_write_credentials() if write else settings.get_google_credentials()
    if credentials is None:
        raise RuntimeError("No hay credenciales de Google configuradas.")
    key = ("oauth", settings.GOOGLE_OAUTH_CLIENT_ID, settings.GOOGLE_OAUTH_CLIENT_SECRET, settings.GOOGLE_OAUTH_REFRESH_TOKEN)
    return build_cached_service(
        cache_name="hazardous-waste-sheets-write" if write else "hazardous-waste-sheets-read",
        service_name="sheets", version="v4", credentials=credentials, credentials_key=key,
    )


def parse_spreadsheet_id(value: str) -> str:
    match = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", value)
    spreadsheet_id = match.group(1) if match else value.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,}", spreadsheet_id):
        raise ValueError("Pega un enlace válido de Google Sheets o el ID del archivo.")
    return spreadsheet_id


def _date(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return date(1899, 12, 30) + timedelta(days=int(value))
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date()
        except ValueError:
            continue
    return None


def _quantity(value) -> tuple[Decimal | None, str]:
    text = str(value or "").strip().replace(",", ".")
    if not text:
        return None, ""
    match = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*(.*)$", text)
    if not match:
        return Decimal(0), text
    try:
        number = Decimal(match.group(1))
    except InvalidOperation:
        return Decimal(0), text
    return number, match.group(2).strip()


def _quantity_text(quantity, unit: str | None) -> str:
    """Format a measured amount without insignificant zeroes or rounding."""
    if quantity is None:
        return ""
    value = quantity if isinstance(quantity, Decimal) else Decimal(str(quantity))
    # Group thousands with dots and use a comma for decimals (Spanish locale).
    raw = format(value, ",f")
    whole, separator, fraction = raw.partition(".")
    if separator:
        fraction = fraction.rstrip("0")
        raw = f"{whole}.{fraction}" if fraction else whole
    raw = raw.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    normalized_unit = str(unit or "UNIDADES").strip().upper()
    return f"{raw} {normalized_unit}".strip()


def _find_header_index(values: list[list]) -> int | None:
    for index, row in enumerate(values[:12]):
        joined = " ".join(_normalize(cell) for cell in row)
        if "fechaingreso" in joined and "nombrerespel" in joined:
            return index
    return None


def _find_insert_row(values: list[list], entry_date: date, first_data_row: int) -> tuple[int, bool]:
    """Return the 1-based row to write and whether a row must be inserted."""
    first_index = first_data_row - 1
    last_nonempty_index = first_index - 1
    for index in range(first_index, len(values)):
        row = values[index] if index < len(values) else []
        if not any(str(cell or "").strip() for cell in row):
            # Reuse a blank row before later records (including a row left by
            # an interrupted previous attempt) rather than shifting twice.
            for later in values[index + 1:]:
                later_date = _date(later[0] if later else None)
                if later_date and later_date > entry_date:
                    return index + 1, False
            continue

        last_nonempty_index = index
        row_date = _date(row[0] if row else None)
        if row_date and row_date > entry_date:
            previous = values[index - 1] if index > first_index else []
            if index > first_index and not any(str(cell or "").strip() for cell in previous):
                return index, False
            return index + 1, True

    return max(first_data_row, last_nonempty_index + 2), False


def read_annual_tabs(spreadsheet_id: str) -> list[dict]:
    """Read annual tabs only; stock tab is intentionally not imported twice."""
    service = _service(spreadsheet_id, write=False)
    metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="sheets(properties(title))").execute()
    titles = [sheet["properties"]["title"] for sheet in metadata.get("sheets", [])]
    annual = [title for title in titles if "lista" in _normalize(title) and "controldeingreso" in _normalize(title) and re.search(r"20\d{2}", title)]
    if not annual:
        raise RuntimeError("No se encontraron pestañas anuales 'Lista control de ingreso AÑO'.")
    rows: list[dict] = []
    for title in annual:
        result = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=f"'{title}'!A1:K5000", valueRenderOption="UNFORMATTED_VALUE").execute()
        values = result.get("values", [])
        header_index = _find_header_index(values)
        if header_index is None:
            continue
        header = [_normalize(cell) for cell in values[header_index]]
        def col(*names: str) -> int | None:
            normalized = {_normalize(name) for name in names}
            return next((i for i, cell in enumerate(header) if cell in normalized), None)
        positions = {
            "date": col("FECHA INGRESO"), "code": col("N° RESPEL", "Nº RESPEL", "NUMERO RESPEL"),
            "name": col("NOMBRE RESPEL"), "hazard": col("PELIGROSIDAD"), "origin": col("ORIGEN"),
            "quantity": col("CANTIDAD/ UNIDADES", "CANTIDAD UNIDADES"), "delivered": col("NOMBRE DE QUIEN ENTREGA"),
            "disposal": col("FECHA DE TRANSPORTE Y DISPOSICIÓN", "FECHA DE TRANSPORTE Y DISPOSICION"),
            "manager": col("NOMBRE DE GESTOR"), "id": col("ID INTERNO APP"),
        }
        if positions["date"] is None or positions["name"] is None:
            continue
        for row_number, row in enumerate(values[header_index + 1:], header_index + 2):
            def val(key):
                index = positions[key]
                return row[index] if index is not None and index < len(row) else None
            entered = _date(val("date"))
            name = str(val("name") or "").strip()
            if entered is None or not name:
                continue
            quantity, unit = _quantity(val("quantity"))
            raw_disposal = val("disposal")
            disposal_date = _date(raw_disposal)
            manager = str(val("manager") or "").strip() or None
            if str(raw_disposal or "").strip().casefold() in {"almacenado", "en almacenamiento"}:
                manager = manager or str(raw_disposal).strip()
            rows.append({
                "entry_date": entered, "respel_code": str(val("code") or "").strip() or None,
                "waste_name": name, "hazard": str(val("hazard") or "").strip() or None,
                "origin": str(val("origin") or "").strip() or None, "quantity": quantity,
                "unit": unit, "delivered_by": str(val("delivered") or "").strip() or None,
                "disposal_date": disposal_date, "manager": manager, "source_sheet": title,
                "sheet_row": row_number, "external_key": str(val("id") or "").strip() or None,
            })
    return rows


def ensure_key_column(spreadsheet_id: str, title: str) -> None:
    service = _service(spreadsheet_id, write=True)
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range=f"'{title}'!K2", valueInputOption="RAW",
        body={"values": [[HEADERS[-1]]]},
    ).execute()


def stamp_import_keys(spreadsheet_id: str, rows: list[dict]) -> None:
    if not rows:
        return
    service = _service(spreadsheet_id, write=True)
    titles = sorted({item["source_sheet"] for item in rows})
    updates = [{"range": f"'{title}'!K2", "values": [[HEADERS[-1]]]} for title in titles]
    updates.extend({
        "range": f"'{item['source_sheet']}'!K{item['sheet_row']}",
        "values": [[f"HWR-{item['id']}"]],
    } for item in rows)
    service.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"valueInputOption": "RAW", "data": updates},
    ).execute()


def write_record(spreadsheet_id: str, record: dict) -> int:
    service = _service(spreadsheet_id, write=True)
    title = record["source_sheet"] or f"Lista  control de ingreso {record['entry_date'].year}"
    metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="sheets(properties(sheetId,title))").execute()
    sheets = metadata.get("sheets", [])
    match = next((sheet for sheet in sheets if sheet["properties"]["title"] == title), None)
    sheet_id = match["properties"]["sheetId"] if match else None
    if match is None:
        templates = [sheet for sheet in sheets if "lista" in _normalize(sheet["properties"]["title"]) and "controldeingreso" in _normalize(sheet["properties"]["title"]) ]
        if not templates:
            raise RuntimeError("No hay una pestaña anual que sirva de plantilla para crear el nuevo año.")
        template = max(templates, key=lambda sheet: int(re.search(r"20\d{2}", sheet["properties"]["title"]).group(0)) if re.search(r"20\d{2}", sheet["properties"]["title"]) else 0)
        copied = service.spreadsheets().sheets().copyTo(
            spreadsheetId=spreadsheet_id, sheetId=template["properties"]["sheetId"],
            body={"destinationSpreadsheetId": spreadsheet_id},
        ).execute()
        new_sheet_id = copied["sheetId"]
        service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": [
            {"updateSheetProperties": {"properties": {"sheetId": new_sheet_id, "title": title}, "fields": "title"}},
            {"repeatCell": {"range": {"sheetId": new_sheet_id, "startRowIndex": 2, "endRowIndex": 5000, "startColumnIndex": 0, "endColumnIndex": 11}, "cell": {"userEnteredValue": {"stringValue": ""}}, "fields": "userEnteredValue"}},
        ]}).execute()
        sheet_id = new_sheet_id
        service.spreadsheets().values().update(spreadsheetId=spreadsheet_id, range=f"'{title}'!K2", valueInputOption="RAW", body={"values": [[HEADERS[-1]]]}).execute()
    values = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=f"'{title}'!A1:K5000", valueRenderOption="UNFORMATTED_VALUE"
    ).execute().get("values", [])
    key = f"HWR-{record['id']}"
    # Row numbers change whenever a historical entry is inserted. The stable
    # internal ID must therefore take precedence over the cached sheet_row.
    row_number = next(
        (i + 1 for i, row in enumerate(values) if len(row) > 10 and str(row[10]).strip() == key),
        None,
    )
    insert_row = False
    if row_number is None and record.get("sheet_row"):
        # Compatibility for legacy rows that have not yet received an ID.
        row_number = record["sheet_row"]
    if row_number is None:
        header_index = _find_header_index(values)
        first_data_row = (header_index + 2) if header_index is not None else 3
        row_number, insert_row = _find_insert_row(values, record["entry_date"], first_data_row)
    quantity_text = _quantity_text(record.get("quantity"), record.get("unit"))
    accumulated_text = _quantity_text(record.get("accumulated_quantity"), record.get("unit"))
    disposal = record.get("disposal_date")
    row = [
        record["entry_date"].strftime("%d/%m/%Y"), record.get("respel_code") or "", record["waste_name"],
        record.get("hazard") or "", record.get("origin") or "", quantity_text,
        record.get("delivered_by") or "", accumulated_text,
        disposal.strftime("%d/%m/%Y") if disposal else "ALMACENADO", record.get("manager") or "", key,
    ]
    if insert_row:
        if sheet_id is None:
            raise RuntimeError("No se pudo identificar la pestaña para insertar el registro por fecha.")
        insert_index = row_number - 1
        first_data_index = first_data_row - 1
        service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": [{
            "insertDimension": {
                "range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": insert_index, "endIndex": insert_index + 1},
                "inheritFromBefore": insert_index > first_data_index,
            }
        }]}).execute()

    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range=f"'{title}'!A{row_number}:K{row_number}",
        valueInputOption="USER_ENTERED", body={"values": [row]},
    ).execute()
    return row_number
