"""Audit the real monthly tracking Google Sheet.

Reads headers from the SEPTIEMBRE tab and checks the full OT template (rows 30-60).
Output: audit_monthly_output.txt

Run: python scripts/audit_monthly.py
"""

import sys
import io
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from app.core.config import settings


def col_letter(idx: int) -> str:
    return chr(ord("A") + idx)


def main():
    out_path = _BACKEND / "audit_monthly_output.txt"
    out = io.open(out_path, "w", encoding="utf-8")

    def p(msg=""):
        out.write(msg + "\n")

    try:
        from googleapiclient.discovery import build

        creds = settings.get_google_credentials()
        if creds is None:
            p("ERROR: No Google credentials configured.")
            return

        # ── PART 1: Monthly sheet headers ──
        sheets = build("sheets", "v4", credentials=creds)
        monthly_id = settings.GOOGLE_MONTHLY_SPREADSHEET_ID

        p("=" * 70)
        p("MONTHLY SHEET - SEPTIEMBRE TAB HEADERS")
        p("=" * 70)

        # Read row 1 (headers) and a few data rows
        resp = sheets.spreadsheets().values().get(
            spreadsheetId=monthly_id,
            range="SEPTIEMBRE!A1:Z5",
        ).execute()
        values = resp.get("values", [])

        for i, row in enumerate(values, start=1):
            row_str = " | ".join(str(cell) if cell else "" for cell in row)
            p(f"Row {i:2d}: {row_str}")

        p("\nHeader mapping (row 1):")
        if values:
            headers = values[0]
            for j, h in enumerate(headers):
                p(f"  {col_letter(j)}1 = {h}")

        # ── PART 2: OT template rows 30-60 ──
        p("\n" + "=" * 70)
        p("OT TEMPLATE - ROWS 30-60 (checking for more content)")
        p("=" * 70)

        template_id = settings.GOOGLE_OT_TEMPLATE_FILE_ID
        resp2 = sheets.spreadsheets().values().get(
            spreadsheetId=template_id,
            range="PLANTILLA_OT!A30:Z60",
        ).execute()
        values2 = resp2.get("values", [])

        for i, row in enumerate(values2, start=30):
            row_str = " | ".join(str(cell) if cell else "" for cell in row)
            if row_str.strip(" |"):
                safe = row_str.replace("☐", "[ ]").replace("☑", "[X]").replace("☒", "[X]")
                p(f"Row {i:2d}: {safe}")

        # ── PART 3: Check MAPEO_APP tab ──
        p("\n" + "=" * 70)
        p("OT TEMPLATE - MAPEO_APP TAB")
        p("=" * 70)

        resp3 = sheets.spreadsheets().values().get(
            spreadsheetId=template_id,
            range="MAPEO_APP!A1:Z20",
        ).execute()
        values3 = resp3.get("values", [])

        for i, row in enumerate(values3, start=1):
            row_str = " | ".join(str(cell) if cell else "" for cell in row)
            if row_str.strip(" |"):
                p(f"Row {i:2d}: {row_str}")

        # ── PART 4: Status checkbox row detail ──
        p("\n" + "=" * 70)
        p("STATUS CHECKBOXES - DETAILED (row 33)")
        p("=" * 70)

        resp4 = sheets.spreadsheets().values().get(
            spreadsheetId=template_id,
            range="PLANTILLA_OT!A33:G33",
        ).execute()
        vals4 = resp4.get("values", [[]])
        if vals4:
            row = vals4[0]
            for j, cell in enumerate(row):
                safe = str(cell).replace("☐", "[ ]").replace("☑", "[X]").replace("☒", "[X]")
                p(f"  {col_letter(j)}33 = '{safe}'")

        # Also get the raw unmerged cell value
        resp5 = sheets.spreadsheets().values().get(
            spreadsheetId=template_id,
            range="PLANTILLA_OT!B33:B33",
        ).execute()
        vals5 = resp5.get("values", [[]])
        if vals5:
            raw = str(vals5[0][0]).replace("☐", "[ ]").replace("☑", "[X]").replace("☒", "[X]")
            p(f"\n  Raw B33 value: '{raw}'")

        p("\n" + "=" * 70)
        p("DONE")
        p("=" * 70)

    finally:
        out.close()
        print(f"Audit written to: {out_path}")


if __name__ == "__main__":
    main()
