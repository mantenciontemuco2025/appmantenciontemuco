"""Build a clean annual master template from the existing 2026 register.

Copies Registro_Mantencion_2026 (settings.GOOGLE_MONTHLY_SPREADSHEET_ID) into a
new file named "Plantilla_Registro_Mensual" and REMOVES ONLY the data rows from
each of the 12 tabs (ENERO..DICIEMBRE), preserving headers, formats, widths, and
the tabs themselves. Reads-only from the 2026 original — it is never modified.

The resulting file's Drive id is printed so you can set GOOGLE_MONTHLY_TEMPLATE_FILE_ID.
You may move it into PLANTILLAS/ afterward if you like.

Usage:
    python scripts/build_monthly_template_from_2026.py
    python scripts/build_monthly_template_from_2026.py --folder <folder_id>
      --folder: Drive folder to place the template in (default GOOGLE_MONTHLY_ROOT_FOLDER_ID)
"""

import argparse
import io
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from googleapiclient.discovery import build  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services.ot_mapping import MONTHLY_DATA_START_ROW, SPANISH_MONTHS  # noqa: E402

TEMPLATE_NAME = "Plantilla_Registro_Mensual"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", default=None, help="Destination folder id (default GOOGLE_MONTHLY_ROOT_FOLDER_ID).")
    args = parser.parse_args()

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    source_id = settings.GOOGLE_MONTHLY_SPREADSHEET_ID
    if not source_id:
        print("ERROR: GOOGLE_MONTHLY_SPREADSHEET_ID no configurado (el 2026 existente).")
        return
    if not settings.google_write_enabled:
        print("ERROR: OAuth no configurado; se requiere para copiar y editar en Drive/Sheets.")
        return

    destination_folder = args.folder or settings.GOOGLE_MONTHLY_ROOT_FOLDER_ID
    if not destination_folder:
        print("ERROR: falta folder destino (--folder o GOOGLE_MONTHLY_ROOT_FOLDER_ID).")
        return

    creds = settings.get_google_credentials()
    drive = build("drive", "v3", credentials=creds)
    sheets = build("sheets", "v4", credentials=creds)

    # 1. Copy the 2026 register (read-only source, never modified)
    copied = drive.files().copy(
        fileId=source_id, body={"name": TEMPLATE_NAME}, fields="id, webViewLink"
    ).execute()
    new_id = copied["id"]

    # 2. Move to destination folder
    meta = drive.files().get(fileId=new_id, fields="parents").execute()
    parents = meta.get("parents", [])
    update = {"addParents": destination_folder, "fields": "id"}
    if parents:
        update["removeParents"] = parents[0]
    drive.files().update(fileId=new_id, **update).execute()

    # 3. Resolve sheet/tab ids and delete ONLY data rows in each tab.
    spread_meta = (
        sheets.spreadsheets()
        .get(spreadsheetId=new_id, fields="sheets(properties)")
        .execute()
    )
    sheet_id_by_title = {
        s.get("properties", {}).get("title"): s.get("properties", {}).get("sheetId")
        for s in spread_meta.get("sheets", [])
    }

    found = [m for m in SPANISH_MONTHS if m in sheet_id_by_title]
    missing = [m for m in SPANISH_MONTHS if m not in sheet_id_by_title]
    print(f"Pestañas encontradas: {len(found)}/12. Faltan: {missing or 'ninguna'}.")

    requests = []
    for month in SPANISH_MONTHS:
        sid = sheet_id_by_title.get(month)
        if sid is None:
            continue
        # Find the last data row by reading the N° OT column (B) of this tab.
        col_b = (
            sheets.spreadsheets()
            .values()
            .get(spreadsheetId=new_id, range=f"{month}!B:B", valueRenderOption="FORMATTED_VALUE")
            .execute()
            .get("values", [])
        )
        last_data_row = MONTHLY_DATA_START_ROW - 1
        for i, cell in enumerate(col_b, start=1):
            if i >= MONTHLY_DATA_START_ROW and cell and str(cell[0]).strip():
                last_data_row = i
        if last_data_row < MONTHLY_DATA_START_ROW:
            continue  # no data rows to remove in this tab
        requests.append(
            {
                "deleteDimension": {
                    "range": {
                        "sheetId": sid,
                        "dimension": "ROWS",
                        "startIndex": MONTHLY_DATA_START_ROW - 1,
                        "endIndex": last_data_row,
                    }
                }
            }
        )

    if requests:
        sheets.spreadsheets().batchUpdate(
            spreadsheetId=new_id, body={"requests": requests}
        ).execute()

    url = copied.get("webViewLink", f"https://drive.google.com/file/d/{new_id}/view")
    print(f"OK: plantilla creada con {len(requests)} tab(s) limpiada(s).")
    print(f"  name      : {TEMPLATE_NAME}")
    print(f"  file_id   : {new_id}")
    print(f"  url       : {url}")
    print("Configura GOOGLE_MONTHLY_TEMPLATE_FILE_ID=<file_id> en backend/.env")


if __name__ == "__main__":
    main()
