"""Debug: read all rows from SEPTIEMBRE tab to see current state.

Output: debug_monthly_output.txt
Run: python scripts/debug_monthly_sheet.py
"""

import sys
import io
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from app.core.config import settings


def col_letter(idx):
    return chr(ord("A") + idx)


def main():
    out_path = _BACKEND / "debug_monthly_output.txt"
    out = io.open(out_path, "w", encoding="utf-8")

    def p(msg=""):
        out.write(msg + "\n")

    try:
        from googleapiclient.discovery import build

        creds = settings.get_google_credentials()
        if creds is None:
            p("ERROR: No Google credentials.")
            return

        sheets = build("sheets", "v4", credentials=creds)
        monthly_id = settings.GOOGLE_MONTHLY_SPREADSHEET_ID

        # Read header row + all data rows
        resp = sheets.spreadsheets().values().get(
            spreadsheetId=monthly_id,
            range="SEPTIEMBRE!A1:Z50",
        ).execute()
        rows = resp.get("values", [])

        p("=" * 90)
        p("SEPTIEMBRE - ALL ROWS")
        p("=" * 90)

        for i, row in enumerate(rows, start=1):
            safe = " | ".join(
                str(cell).replace("\n", " ")[:40] if cell else ""
                for cell in row
            )
            p(f"Row {i:2d}: {safe}")

        # Also check headers specifically
        p("\n" + "=" * 90)
        p("HEADER ROW (row 3) detailed:")
        p("=" * 90)
        if len(rows) >= 3:
            headers = rows[2]  # row 3 (0-indexed = 2)
            for j, h in enumerate(headers):
                p(f"  {col_letter(j)}3 = '{h}'")

        # Also read the OT-TEST-MAPPING file to check its current state
        p("\n" + "=" * 90)
        p("OT-TEST-MAPPING - CURRENT STATE")
        p("=" * 90)
        test_ot_id = "1P1eIr9PiOAAqCd6wbEmoh4IkDD0k6ANhlLJ3y0DRiRU"
        resp2 = sheets.spreadsheets().values().get(
            spreadsheetId=test_ot_id,
            range="PLANTILLA_OT!A1:Z35",
        ).execute()
        ot_rows = resp2.get("values", [])
        for i, row in enumerate(ot_rows, start=1):
            if any(str(c).strip() for c in row):
                safe = " | ".join(
                    str(cell).replace("\n", " ")[:50] if cell else ""
                    for cell in row
                )
                p(f"Row {i:2d}: {safe}")

    finally:
        out.close()
        print(f"Debug output: {out_path}")


if __name__ == "__main__":
    main()
