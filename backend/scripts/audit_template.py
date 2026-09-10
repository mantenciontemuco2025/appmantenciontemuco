"""Audit the real OT template Google Sheet.

Reads all cell values, merged cells, and sheet dimensions.
Output is written to audit_template_output.txt (ASCII-safe for cp1252 consoles).

Run: python scripts/audit_template.py
"""

import sys
import io
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from app.core.config import settings


def col_letter(idx: int) -> str:
    """0-based column index -> letter: 0='A', 1='B', ..."""
    return chr(ord("A") + idx)


def main():
    out_path = _BACKEND / "audit_template_output.txt"
    out = io.open(out_path, "w", encoding="utf-8")

    def p(msg=""):
        out.write(msg + "\n")

    try:
        from googleapiclient.discovery import build

        creds = settings.get_google_credentials()
        if creds is None:
            p("ERROR: No Google credentials configured.")
            return

        sheets = build("sheets", "v4", credentials=creds)
        template_id = settings.GOOGLE_OT_TEMPLATE_FILE_ID

        # 1. Sheet metadata
        meta = sheets.spreadsheets().get(
            spreadsheetId=template_id,
            fields="properties.title,sheets(properties(title,sheetId,gridProperties(rowCount,columnCount)))"
        ).execute()

        p("=" * 70)
        p("TEMPLATE METADATA")
        p("=" * 70)
        p(f"Title: {meta.get('properties', {}).get('title')}")

        sheets_list = meta.get("sheets", [])
        for sh in sheets_list:
            props = sh.get("properties", {})
            gp = props.get("gridProperties", {})
            p(f"  Tab: '{props.get('title')}' (sheetId={props.get('sheetId')}, "
              f"rows={gp.get('rowCount')}, cols={gp.get('columnCount')})")

        if not sheets_list:
            p("ERROR: No sheets found.")
            return

        first_sheet = sheets_list[0]
        sheet_title = first_sheet["properties"]["title"]
        grid = first_sheet["properties"].get("gridProperties", {})
        max_rows = min(grid.get("rowCount", 100), 80)
        max_cols = min(grid.get("columnCount", 26), 26)

        # 2. Read all values
        end_col = chr(ord("A") + max_cols - 1)
        range_name = f"{sheet_title}!A1:{end_col}{max_rows}"
        p(f"\nReading range: {range_name}")

        resp = sheets.spreadsheets().values().get(
            spreadsheetId=template_id,
            range=range_name,
        ).execute()
        values = resp.get("values", [])

        p("\n" + "=" * 70)
        p("CELL VALUES (row by row)")
        p("=" * 70)
        for i, row in enumerate(values, start=1):
            row_str = " | ".join(str(cell) if cell else "" for cell in row)
            p(f"Row {i:2d}: {row_str}")

        # 3. Merged cells
        p("\n" + "=" * 70)
        p("MERGED CELLS")
        p("=" * 70)

        full_meta = sheets.spreadsheets().get(
            spreadsheetId=template_id,
            fields="sheets(merges)"
        ).execute()

        for sh in full_meta.get("sheets", []):
            merges = sh.get("merges", [])
            if merges:
                for m in merges:
                    start_r = m.get("startRowIndex", 0) + 1
                    end_r = m.get("endRowIndex", 0)
                    start_c = m.get("startColumnIndex", 0)
                    end_c = m.get("endColumnIndex", 0)
                    start_cell = f"{col_letter(start_c)}{start_r}"
                    end_cell = f"{col_letter(end_c - 1)}{end_r}"
                    p(f"  Merged: {start_cell}:{end_cell} "
                      f"(rows {start_r}-{end_r}, cols {col_letter(start_c)}-{col_letter(end_c - 1)})")

        # 4. Visual grid: non-empty cells
        p("\n" + "=" * 70)
        p("VISUAL GRID (non-empty cells)")
        p("=" * 70)

        for i, row in enumerate(values):
            for j, cell in enumerate(row):
                if cell:
                    cell_ref = f"{col_letter(j)}{i + 1}"
                    # Replace problematic unicode for safe output
                    safe = str(cell).replace("☐", "[ ]").replace("☑", "[X]").replace("☒", "[X]")
                    p(f"  {cell_ref:6s} = {safe}")

        # 5. Label detection
        p("\n" + "=" * 70)
        p("LABEL DETECTION (looking for field labels)")
        p("=" * 70)

        keywords = [
            "OT", "NUMERO", "NÚMERO", "AREA", "ÁREA", "SECCION", "SECCIÓN",
            "EQUIPO", "MANTENIMIENTO", "TIPO", "LOTO", "FOLIO", "DESCRIPCION",
            "DESCRIPCIÓN", "PARTICIPANTE", "RESPONSABLE", "TIEMPO", "ESTIMADO",
            "FECHA", "EJECUCION", "EJECUCIÓN", "RECURSO", "MATERIAL", "VALE",
            "RIESGO", "PELIGRO", "OBSERVACION", "OBSERVACIÓN", "SOLICITADO",
            "APROBADO", "PENDIENTE", "ESTADO", "PROCESO", "FINALIZADO",
            "PREVENTIVO", "CORRECTIVO", "PREDICTIVO", "PROYECTO", "MONTAJE",
            "SI", "SÍ", "NO ", "APLICA", "HORAS", "DURACION",
        ]

        for i, row in enumerate(values):
            for j, cell in enumerate(row):
                cell_upper = str(cell).upper()
                for kw in keywords:
                    if kw in cell_upper:
                        cell_ref = f"{col_letter(j)}{i + 1}"
                        safe = str(cell).replace("☐", "[ ]").replace("☑", "[X]").replace("☒", "[X]")
                        p(f"  {cell_ref:6s} = {safe}  (matches: {kw})")
                        break

        p("\n" + "=" * 70)
        p("DONE - audit_template_output.txt")
        p("=" * 70)

    finally:
        out.close()
        print(f"Audit written to: {out_path}")


if __name__ == "__main__":
    main()
