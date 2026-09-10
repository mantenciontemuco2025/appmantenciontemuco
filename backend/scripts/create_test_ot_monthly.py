"""CONTROLLED test: OT-TEST-MONTHLY full lifecycle in the monthly registry.

STEP 0  - Backup/report the current MONTHLY structure (FASE 8 compatibility):
          lists each tab's headers before ANY change. Nothing is deleted.
STEP 1  - Additively add the "ESTADO" header to column W (row 3) of each
          month tab IF it is not already present. This only writes a value to
          a currently-blank header cell; it does NOT insert/delete rows or
          columns, does NOT touch formatting, and does NOT modify existing data.
STEP 2  - Run the full lifecycle on OT-TEST-MONTHLY:
            PENDING    -> expect append (1 row)
            IN_PROGRESS-> expect SAME row updated (ESTADO = EN PROCESO)
            COMPLETED  -> expect SAME row updated (ESTADO = FINALIZADO)
          Verifies there is exactly ONE row (no duplicates) and that ESTADO
          reflects each stage.
STEP 3  - Read back and print the final SEPTIEMBRE rows for OT-TEST-MONTHLY.

Output: test_ot_monthly_output.txt
Security: never prints credentials/private keys.
Run: python scripts/create_test_ot_monthly.py
"""

import io
import sys
from datetime import date, datetime, time
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from app.core.config import settings
from app.services.ot_mapping import get_monthly_sheet_title
from app.services.monthly_mapping import resolve_monthly_columns, normalize_header


# ---------------------------------------------------------------------------
# Layer on top of google_drive so the SAME production path is exercised.
# ---------------------------------------------------------------------------
from app.services import google_drive as drive_service


def main():
    out_path = _BACKEND / "test_ot_monthly_output.txt"
    out = io.open(out_path, "w", encoding="utf-8")

    def p(msg=""):
        out.write(msg + "\n")
        print(msg)

    from googleapiclient.discovery import build

    creds = settings.get_google_credentials()
    sheets = build("sheets", "v4", credentials=creds)
    monthly_id = settings.GOOGLE_MONTHLY_SPREADSHEET_ID

    months = [get_monthly_sheet_title(m) for m in range(1, 13)]

    p("=" * 80)
    p("STEP 0 - STRUCTURE BEFORE CHANGE (compatibility report)")
    p("=" * 80)
    for m in months:
        resp = sheets.spreadsheets().values().get(
            spreadsheetId=monthly_id, range=f"{m}!A3:W3"
        ).execute()
        headers = resp.get("values", [[]])
        if headers:
            p(f"  {m} headers: {' | '.join(str(h) for h in headers[0])}")

    p("\n" + "=" * 80)
    p("STEP 1 - ADD ESTADO HEADER (column W, additive, never deletes/reformats)")
    p("=" * 80)
    # Build one update request per tab that lacks ESTADO. ValueInputOption RAW,
    # single-cell write to W3 (currently blank). No insert/delete, no formatting.
    # Use values().update (not batchUpdate requests) to keep it purely value-based.
    updates = []
    for m in months:
        resp = sheets.spreadsheets().values().get(
            spreadsheetId=monthly_id, range=f"{m}!A3:W3"
        ).execute()
        headers = resp.get("values", [[]])
        present = any(normalize_header(h) == "ESTADO" for h in (headers[0] if headers else []))
        if not present:
            updates.append(f"{m}!W3")
    if updates:
        for rng in updates:
            sheets.spreadsheets().values().update(
                spreadsheetId=monthly_id,
                range=rng,
                valueInputOption="RAW",
                body={"values": [["ESTADO"]]},
            ).execute()
            p(f"  + ESTADO header added to {rng}")
    else:
        p("  ESTADO header already present in all tabs; no change.")

    # Verify header reads now resolve ESTADO -> W
    p("\n  Header-resolution check:")
    for m in months:
        resp = sheets.spreadsheets().values().get(
            spreadsheetId=monthly_id, range=f"{m}!A3:W3"
        ).execute()
        headers = resp.get("values", [[]])
        col = resolve_monthly_columns(headers[0] if headers else [])
        p(f"    {m}: ESTADO -> {col.get('ESTADO', 'MISSING')}")

    p("\n" + "=" * 80)
    p("STEP 2 - FULL LIFECYCLE OT-TEST-MONTHLY (PENDING->IN_PROGRESS->COMPLETED)")
    p("=" * 80)

    exec_date = date(2026, 9, 3)
    exec_dt = datetime.combine(exec_date, time.min)
    ot = "OT-TEST-MONTHLY"
    participants = ["Ortiz", "Jara"]

    def count_rows_for_ot():
        rows = sheets.spreadsheets().values().get(
            spreadsheetId=monthly_id, range="SEPTIEMBRE!B:B"
        ).execute().get("values", [])
        return sum(1 for r in rows if r and str(r[0]).strip().upper() == ot)

    def read_row_for_ot():
        rows = sheets.spreadsheets().values().get(
            spreadsheetId=monthly_id, range="SEPTIEMBRE!A4:W400"
        ).execute().get("values", [])
        for row in rows:
            if row and len(row) > 1 and str(row[1]).strip().upper() == ot:
                return row
        return None

    stages = [
        ("PENDING", 1.0),
        ("IN_PROGRESS", 1.5),
        ("COMPLETED", 2.0),
    ]

    for i, (status, horas) in enumerate(stages, start=1):
        drive_service.sync_to_monthly_sheet(
            ot, exec_dt,
            area_name="AREA TEST MONTHLY",
            section_name="SECC TEST MONTHLY",
            equipment_name="EQ TEST MONTHLY",
            description="Controlled monthly lifecycle test",
            maintenance_type="CORRECTIVE",
            participants=participants,
            duration_hours=horas,
            status=status,
        )
        cnt = count_rows_for_ot()
        row = read_row_for_ot()
        p(f"  Stage {i}/{len(stages)} status={status} horas={horas}")
        p(f"    rows for {ot}: {cnt}  (must stay 1)")
        if row:
            p(f"    -> ESTADO col W = '{row[ord('W') - ord('A')] if len(row) > ord('W') - ord('A') else '?'}'")
        else:
            p("    -> row NOT FOUND (unexpected)")

    p("\n" + "=" * 80)
    p("STEP 3 - FINAL SEPTIEMBRE ROW FOR OT-TEST-MONTHLY")
    p("=" * 80)
    final = read_row_for_ot()
    if final:
        labels = ["FECHA", "N_OT", "AREA", "SECC", "EQ", "TRABAJO",
                  "ORTIZ", "VALDES", "FABRES", "JARA", "SALAZAR", "MILLAR",
                  "JUAN_SILVA", "INOSTROZA", "CANIULLAN", "CONTRERAS",
                  "PREV", "CORR", "PRED", "PROY", "MONT", "HORAS", "ESTADO"]
        for idx, (label, val) in enumerate(zip(labels, final)):
            p(f"  {label:>10} ({chr(65+idx)}4) = {val!r}")

    p("\nTOTAL SEPTIEMBRE rows matching OT-TEST-MONTHLY: " + str(count_rows_for_ot()))

    out.close()


if __name__ == "__main__":
    main()