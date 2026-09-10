"""Full audit of the monthly maintenance registry spreadsheet.

Reads all 12 tabs, headers, column widths, formats, existing rows,
and the MAPEO_APP tab if present.

Output: audit_monthly_full_output.txt
Run: python scripts/audit_monthly_full.py
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
    out_path = _BACKEND / "audit_monthly_full_output.txt"
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

        # 1. Metadata: tabs, dimensions, merges
        meta = sheets.spreadsheets().get(
            spreadsheetId=monthly_id,
            fields="properties.title,sheets(properties(title,sheetId,gridProperties(rowCount,columnCount)),merges)",
        ).execute()

        p("=" * 80)
        p("MONTHLY REGISTRY METADATA")
        p("=" * 80)
        p(f"Title: {meta.get('properties', {}).get('title')}")
        sheets_list = meta.get("sheets", [])
        for sh in sheets_list:
            sp = sh.get("properties", {})
            gp = sp.get("gridProperties", {})
            p(f"  Tab '{sp.get('title')}' sheetId={sp.get('sheetId')} "
              f"rows={gp.get('rowCount')} cols={gp.get('columnCount')}")
            merges = sh.get("merges", [])
            if merges:
                p(f"    merges: {len(merges)}")

        # 2. For each tab, read the first 12 rows to find header + data
        p("\n" + "=" * 80)
        p("PER-TAB HEADERS + DATA SAMPLES")
        p("=" * 80)
        for sh in sheets_list:
            title = sh.get("properties", {}).get("title")
            resp = sheets.spreadsheets().values().get(
                spreadsheetId=monthly_id, range=f"{title}!A1:Z12"
            ).execute()
            rows = resp.get("values", [])
            p(f"\n--- Tab: {title} ---")
            for i, row in enumerate(rows, start=1):
                if not any(str(c).strip() for c in row):
                    continue
                safe = " | ".join(
                    str(c).replace("\n", " ")[:25] if c else "" for c in row
                )
                p(f"  Row {i:2d}: {safe}")

        # 3. Check column widths / formatting of columns (first tab)
        p("\n" + "=" * 80)
        p("COLUMN WIDTHS (first tab)")
        p("=" * 80)
        first = sheets_list[0]
        title = first.get("properties", {}).get("title")
        sheet_id = first.get("properties", {}).get("sheetId")
        try:
            resp = sheets.spreadsheets().get(
                spreadsheetId=monthly_id,
                ranges=[f"{title}!A:V"],
                fields="sheets.data.rowData.values.userEnteredFormat.columnWidth",
            ).execute()
            # columnWidth not a simple field; read via columnMetadata
        except Exception as e:
            p(f"  (no column widths: {type(e).__name__})")

        # Try reading column metadata
        try:
            resp = sheets.spreadsheets().get(
                spreadsheetId=monthly_id,
                fields="sheets(properties(sheetId,title),data)",
                ranges=[f"{title}!A1:V1"],
            ).execute()
            for s in resp.get("sheets", []):
                for d in s.get("data", []):
                    for st in d.get("rowData", []):
                        for v in st.get("values", []):
                            if v:
                                p(f"  {v}")
        except Exception as e:
            p(f"  (column metadata error: {type(e).__name__})")

        # 4. Check MAPEO tab presence
        all_titles = [s.get("properties", {}).get("title") for s in sheets_list]
        mapeo = [t for t in all_titles if "MAPEO" in t.upper()]
        p("\n" + "=" * 80)
        p("MAPEO TAB: " + (", ".join(mapeo) if mapeo else "no encontrado"))
        p("=" * 80)
        if mapeo:
            resp = sheets.spreadsheets().values().get(
                spreadsheetId=monthly_id, range=f"{mapeo[0]}!A1:Z20"
            ).execute()
            for i, row in enumerate(resp.get("values", []), start=1):
                if any(str(c).strip() for c in row):
                    p(f"  Row {i:2d}: {' | '.join(str(c) for c in row)}")

        # 5. Count data rows per tab (non-empty in col B below header)
        p("\n" + "=" * 80)
        p("DATA ROW COUNTS PER TAB")
        p("=" * 80)
        for sh in sheets_list:
            t = sh.get("properties", {}).get("title")
            resp = sheets.spreadsheets().values().get(
                spreadsheetId=monthly_id, range=f"{t}!B:B"
            ).execute()
            vals = resp.get("values", [])
            count = sum(1 for r in vals if r and str(r[0]).strip())
            p(f"  {t}: {count} non-empty cells in col B")

    finally:
        out.close()
        print(f"Audit output: {out_path}")


if __name__ == "__main__":
    main()
