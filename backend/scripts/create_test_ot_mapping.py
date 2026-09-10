"""Controlled test for OT <-> Google Sheets field mapping.

Creates OT-TEST-MAPPING with clearly-distinguishable test data, then reads
back each expected cell/range to verify the mapping.

This is a READ+WRITE test against the REAL Google environment. It does NOT
touch PostgreSQL — DRIVE (Google) is write-only here, PostgreSQL stays the
source of truth in production.

Run: python scripts/create_test_ot_mapping.py
"""

import sys
import io
import json
from datetime import datetime, date, time
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from app.core.config import settings
from app.services.google_drive import (
    create_ot_file,
    sync_to_monthly_sheet,
)
from app.services.ot_mapping import (
    OT_FIELD_MAP,
    MAINTENANCE_TYPE_CELLS,
    LOTO_CELLS,
    STATUS_CELL,
    MONTHLY_COLUMN_MAP,
    get_monthly_sheet_title,
    build_maintenance_cell_texts,
    build_loto_cell_texts,
    build_status_text,
)

TEST = {
    "area":               "AREA TEST",
    "section":            "SECCION TEST",
    "equipment":          "EQUIPO TEST",
    "maintenance_type":   "CORRECTIVE",
    "loto_status":        "YES",
    "folio":              "FOLIO-TEST-123",
    "description":        "DESCRIPCION TEST UBICACION",
    "participants":       ["Ortiz", "Jara"],
    "estimated_time":     "1 h 30 min",
    "execution_date":     "03-09-2026",
    "request_date":       "04-09-2026",
    "resources_required": "RECURSOS TEST UBICACION",
    "voucher_number":     "VALE-TEST-999",
    "risks":              "RIESGOS TEST UBICACION",
    "observations":       "OBSERVACIONES TEST UBICACION",
    "requested_by":       "SOLICITANTE TEST",
    "approved_by":        "APROBADOR TEST",
    "status":             "PENDING",
    "ot_number":          "OT-TEST-MAPPING",
}


def main():
    out_path = _BACKEND / "test_ot_mapping_output.txt"
    out = io.open(out_path, "w", encoding="utf-8")

    def p(msg=""):
        out.write(msg + "\n")

    def col_letter(idx):
        return chr(ord("A") + idx)

    try:
        from googleapiclient.discovery import build

        if not settings.google_write_enabled:
            p("ERROR: OAuth no configurado — se requieren credenciales de escritura.")
            return

        p("=" * 70)
        p("PRUEBA CONTROLADA OT-TEST-MAPPING")
        p("=" * 70)

        # 1. Create the OT file (Drive copy) into the SEPTIEMBRE folder
        exec_dt = datetime.combine(date(2026, 9, 3), time.min)
        ot_result = create_ot_file(TEST["ot_number"], exec_dt)
        file_id = ot_result["file_id"]
        url = ot_result["url"]
        p(f"\nOT file creado: file_id={file_id}")
        p(f"OT URL: {url}")
        p(f"OT_TEMPLATE_FILE_ID (fuente de template): {settings.GOOGLE_OT_TEMPLATE_FILE_ID}")

        # 2. Populate the OT fields
        from app.services.google_drive import populate_ot_fields
        populate_ot_fields(
            file_id,
            ot_number=TEST["ot_number"],
            area_name=TEST["area"],
            section_name=TEST["section"],
            equipment_name=TEST["equipment"],
            maintenance_type=TEST["maintenance_type"],
            loto_status=TEST["loto_status"],
            description=TEST["description"],
            participants=TEST["participants"],
            estimated_time=TEST["estimated_time"],
            execution_date=TEST["execution_date"],
            request_date=TEST["request_date"],
            resources_required=TEST["resources_required"],
            risks=TEST["risks"],
            observations=TEST["observations"],
            folio=TEST["folio"],
            voucher_number=TEST["voucher_number"],
            requested_by=TEST["requested_by"],
            approved_by=TEST["approved_by"],
            status=TEST["status"],
        )
        p("\nOT poblada correctamente.")

        # 3. Sync to monthly sheet (SEPTIEMBRE)
        sync_ok = sync_to_monthly_sheet(
            TEST["ot_number"],
            exec_dt,
            area_name=TEST["area"],
            section_name=TEST["section"],
            equipment_name=TEST["equipment"],
            description=TEST["description"],
            maintenance_type=TEST["maintenance_type"],
            participants=TEST["participants"],
            duration_hours=1.5,  # 1 h 30 min
        )
        p(f"\nSync mensual OK: {sync_ok}")

        # 4. READ BACK each OT field to verify
        sheets = build("sheets", "v4", credentials=settings.get_google_credentials())

        p("\n" + "=" * 70)
        p("VERIFICACION — LECTURA DE VUELTA DEL OT")
        p("=" * 70)
        p(f"{'CAMPO':<18} {'DESTINO':<10} {'ESPERADO <-> LEIDO'}")
        p("-" * 70)

        # Build expected mapping
        expected = {
            "ot_number":          TEST["ot_number"],
            "area":               TEST["area"],
            "section":            TEST["section"],
            "equipment":          TEST["equipment"],
            "participants":       ", ".join(TEST["participants"]),
            "estimated_time":     TEST["estimated_time"],
            "execution_date":     TEST["execution_date"],
            "request_date":       TEST["request_date"],
            "resources_required": TEST["resources_required"],
            "voucher_number":     TEST["voucher_number"],
            "risks":              TEST["risks"],
            "observations":       TEST["observations"],
            "requested_by":       TEST["requested_by"],
            "approved_by":        TEST["approved_by"],
            "folio":              TEST["folio"],
        }

        fields = ["ot_number", "area", "section", "equipment",
                  "estimated_time", "execution_date", "request_date",
                  "resources_required", "voucher_number", "risks",
                  "observations", "requested_by", "approved_by",
                  "description", "folio"]

        for field in fields:
            target = OT_FIELD_MAP[field]
            resp = sheets.spreadsheets().values().get(
                spreadsheetId=file_id, range=f"PLANTILLA_OT!{target}"
            ).execute()
            values = resp.get("values", [[]])
            actual = values[0][0] if values and values[0] else ""
            exp = expected.get(field, TEST.get(field, ""))
            status = "OK" if str(actual).strip() == str(exp).strip() else "MISMATCH"
            p(f"{field:<18} {target:<10} '{str(actual)}'  [{status}]")

        # 5. Verify checkboxes
        p("\n" + "=" * 70)
        p("VERIFICACION CHECKBOXES")
        p("=" * 70)

        from app.services.ot_mapping import build_status_text
        expected_mt = build_maintenance_cell_texts(TEST["maintenance_type"])
        expected_loto = build_loto_cell_texts(TEST["loto_status"])
        expected_status = build_status_text(TEST["status"])

        # Per-cell checkboxes: verify each option cell holds its own [X]/[ ] text
        p("MAINTENANCE TYPE (per-cell):")
        for cell, exp in expected_mt.items():
            resp = sheets.spreadsheets().values().get(
                spreadsheetId=file_id, range=f"PLANTILLA_OT!{cell}"
            ).execute()
            values = resp.get("values", [[]])
            actual = values[0][0] if values and values[0] else ""
            status = "OK" if str(actual).strip() == str(exp).strip() else "MISMATCH"
            p(f"  {cell:<6} '{actual}'  [{status}]  (esperado: {exp})")

        p("LOTO (per-cell):")
        for cell, exp in expected_loto.items():
            resp = sheets.spreadsheets().values().get(
                spreadsheetId=file_id, range=f"PLANTILLA_OT!{cell}"
            ).execute()
            values = resp.get("values", [[]])
            actual = values[0][0] if values and values[0] else ""
            status = "OK" if str(actual).strip() == str(exp).strip() else "MISMATCH"
            p(f"  {cell:<6} '{actual}'  [{status}]  (esperado: {exp})")

        p(f"STATUS ({STATUS_CELL}):")
        resp = sheets.spreadsheets().values().get(
            spreadsheetId=file_id, range=f"PLANTILLA_OT!{STATUS_CELL}"
        ).execute()
        values = resp.get("values", [[]])
        actual = values[0][0] if values and values[0] else ""
        status = "OK" if str(actual).strip() == str(expected_status).strip() else "MISMATCH"
        p(f"  {STATUS_CELL:<6} '{actual}'  [{status}]")

        # 6. Verify monthly row
        p("\n" + "=" * 70)
        p("VERIFICACION REGISTRO MENSUAL (SEPTIEMBRE)")
        p("=" * 70)
        monthly_id = settings.GOOGLE_MONTHLY_SPREADSHEET_ID
        sheet_title = get_monthly_sheet_title(9)
        # Find OT-TEST-MAPPING row by scanning N° OT column (B)
        resp = sheets.spreadsheets().values().get(
            spreadsheetId=monthly_id, range=f"{sheet_title}!A:V"
        ).execute()
        all_rows = resp.get("values", [])
        header_row = None
        data_rows = []
        for i, row in enumerate(all_rows, start=1):
            if header_row is None and len(row) > 1 and str(row[1]).strip().upper() == "N° OT":
                header_row = i
                norm_headers = [str(h).strip() for h in row]
                continue
            # data rows
            if row and str(row[0]).strip():
                data_rows.append((i, row))

        p(f"Header row index: {header_row}")
        if header_row is not None:
            p("Headers: " + " | ".join(norm_headers))

        # Find the row with our OT number
        ot_row = None
        for i, row in data_rows:
            if len(row) > 1 and str(row[1]).strip().upper() == TEST["ot_number"].upper():
                ot_row = (i, row)
                break

        if ot_row is None:
            p(f"\nERROR: No se encontro fila con {TEST['ot_number']} en {sheet_title}.")
        else:
            row_idx, row = ot_row
            p(f"\nFila encontrada: {row_idx}")
            p(f"Filas de datos en total: {len(data_rows)}")
            for j, h in enumerate(norm_headers):
                val = row[j] if j < len(row) else ""
                p(f"  Col {col_letter(j)} ({h}): '{val}'")

        # 7. Check for duplicates of the same OT number
        dup_count = sum(1 for _, r in data_rows
                        if len(r) > 1 and str(r[1]).strip().upper() == TEST["ot_number"].upper())
        p(f"\nDuplicados de {TEST['ot_number']}: {dup_count} (debe ser 1)")

        p("\n" + "=" * 70)
        p("URL OT: " + url)
        p("=" * 70)

    finally:
        out.close()
        print(f"Output written to: {out_path}")


if __name__ == "__main__":
    main()
