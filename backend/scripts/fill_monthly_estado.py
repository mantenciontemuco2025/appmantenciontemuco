"""One-off backfill: fill the ESTADO column (W) of the monthly registry for
rows whose status cell is empty.

Reads the WorkOrder status from the DB (read-only) and writes ONLY the ESTADO
cell (column resolved by header, e.g. W) for each row in the CURRENT month that
matches an existing OT number and whose status cell is currently empty. Leaves
everything else untouched (no row/col insert/delete, no format changes).

Usage:  python scripts/fill_monthly_estado.py
        python scripts/fill_monthly_estado.py --month SEPTIEMBRE
        python scripts/fill_monthly_estado.py --month SEPTIEMBRE --force
    --force : also overwrite non-empty ESTADO cells with the DB status.
"""

import argparse
import asyncio
import io
import sys
from datetime import date
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from googleapiclient.discovery import build  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.models.work_order import WorkOrder  # noqa: E402
from app.services.monthly_mapping import (  # noqa: E402
    MONTHLY_COLUMN_MAP,
    MONTHLY_DATA_START_ROW,
    SPANISH_MONTHS,
    get_monthly_sheet_title,
    monthly_status_text,
    resolve_monthly_columns,
)
from sqlalchemy import select  # noqa: E402


async def db_status_by_ot() -> dict[str, str]:
    """Map ot_number -> status from the DB (read-only)."""
    async with engine.connect() as conn:
        rows = (
            await conn.execute(select(WorkOrder.ot_number, WorkOrder.status))
        ).all()
    return {ot: (status.value if hasattr(status, "value") else status) for ot, status in rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", default=None, help="Tab name (e.g. SEPTIEMBRE). Defaults to current month.")
    parser.add_argument("--force", action="store_true", help="Overwrite non-empty ESTADO cells too.")
    args = parser.parse_args()

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    now = date.today()
    sheet_title = args.month or get_monthly_sheet_title(now.month)
    print(f"Tab objetivo: {sheet_title}")

    creds = settings.get_google_credentials()
    if creds is None:
        print("ERROR: No hay credenciales.")
        return
    sheets = build("sheets", "v4", credentials=creds)
    monthly_id = settings.GOOGLE_MONTHLY_SPREADSHEET_ID

    # Read header row (row 3) to resolve columns.
    headers_resp = (
        sheets.spreadsheets()
        .values()
        .get(spreadsheetId=monthly_id, range=f"{sheet_title}!A3:AF3")
        .execute()
    )
    header_cells = headers_resp.get("values", [])
    if not header_cells:
        print("ERROR: No se pudo leer la fila de encabezados (A3).")
        return
    headers = header_cells[0]
    cols = resolve_monthly_columns(headers)

    n_ot_letter = cols.get("N_O_T") or MONTHLY_COLUMN_MAP["N_O_T"]
    estado_letter = cols.get("ESTADO")
    if estado_letter is None:
        print("ERROR: No se encontró la columna ESTADO en los encabezados.")
        return
    print(f"  Columna N° OT = {n_ot_letter}, Columna ESTADO = {estado_letter} (resuelta por header)")

    # Read all rows (A..Z to be safe) with formatted values.
    all_resp = (
        sheets.spreadsheets()
        .values()
        .get(spreadsheetId=monthly_id, range=f"{sheet_title}!A1:Z{1000}", valueRenderOption="FORMATTED_VALUE")
        .execute()
    )
    all_rows = all_resp.get("values", [])
    status_map = asyncio.run(db_status_by_ot())
    print(f"  {len(status_map)} OTs en BD")

    # Collect (1-indexed row, ot_number, current value, new value).
    n_ot_idx = ord(n_ot_letter) - ord("A")
    estado_idx = ord(estado_letter) - ord("A")
    updates = []
    for i in range(MONTHLY_DATA_START_ROW, len(all_rows) + 1):
        row = all_rows[i - 1]
        if n_ot_idx >= len(row):
            continue
        ot_number = str(row[n_ot_idx]).strip()
        if not ot_number:
            continue
        current = str(row[estado_idx]).strip() if estado_idx < len(row) else ""
        db_status = status_map.get(ot_number)
        if db_status is None:
            continue
        text = monthly_status_text(db_status)
        if not current or args.force:
            updates.append((i, ot_number, current, text))

    print(f"  {len(updates)} celdas ESTADO a actualizar")
    for row_no, ot, current, text in updates:
        print(f"    Fila {row_no}: {ot}: '{current}' -> '{text}'")

    if not updates:
        print("  Nada que hacer.")
        return

    if not settings.google_write_enabled:
        print("ERROR: Escribir requiere OAuth (google_write_enabled=False).")
        return

    # Single-cell updates for each ESTADO cell.
    data = [
        {"range": f"{sheet_title}!{estado_letter}{row_no}", "values": [[text]]}
        for row_no, _ot, _current, text in updates
    ]
    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=monthly_id, body={"valueInputOption": "RAW", "data": data}
    ).execute()
    print(f"  OK: {len(updates)} celdas ESTADO llenadas en {sheet_title}.")


if __name__ == "__main__":
    main()