"""Create one controlled Google test OT for the multi-select LOTO layout.

This intentionally leaves the OT and its monthly-register row in the local
test Google account so they can be inspected manually. It never touches the
production environment unless the local .env points there.
"""

from datetime import date, datetime, time
from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from googleapiclient.discovery import build

from app.core.config import settings
from app.services.google_drive import create_ot_file, populate_ot_fields, sync_to_monthly_sheet
from app.services.ot_mapping import get_monthly_sheet_title


def main() -> None:
    if not settings.google_write_enabled:
        raise RuntimeError("Google OAuth de escritura no está configurado en backend/.env")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    ot_number = f"OT-TEST-LOTO-{stamp}"
    execution_date = date.today()
    execution_dt = datetime.combine(execution_date, time.min)
    controls = ["LOTO_BLOQUEO", "AST", "TARJETA_ROJA"]

    created = create_ot_file(ot_number, execution_dt)
    file_id = created["file_id"]

    populate_ot_fields(
        file_id,
        ot_number=ot_number,
        area_name="AREA TEST LOTO",
        section_name="SECCION TEST",
        equipment_name="EQUIPO TEST",
        maintenance_type="CORRECTIVE",
        loto_status="YES",
        loto_controls=controls,
        description="Prueba controlada de selección múltiple LOTO / AST",
        participants=["Ortiz", "Jara"],
        estimated_time="2 h 30 min",
        execution_date=execution_date.isoformat(),
        request_date=execution_date.isoformat(),
        resources_required="RECURSOS TEST",
        risks="RIESGOS TEST",
        observations="PRUEBA DE INTEGRACION",
        folio="FOLIO-TEST",
        voucher_number="VALE-TEST",
        requested_by="USUARIO TEST",
        approved_by=None,
        status="PENDING",
    )

    sync_to_monthly_sheet(
        ot_number,
        execution_dt,
        area_name="AREA TEST LOTO",
        section_name="SECCION TEST",
        equipment_name="EQUIPO TEST",
        description="Prueba controlada de selección múltiple LOTO / AST",
        maintenance_type="CORRECTIVE",
        participants=["Ortiz", "Jara"],
        duration_hours=2.5,
        status="PENDING",
        spreadsheet_id=settings.GOOGLE_MONTHLY_SPREADSHEET_ID,
    )

    sheets = build("sheets", "v4", credentials=settings.get_google_credentials())
    ot_values = sheets.spreadsheets().values().get(
        spreadsheetId=file_id,
        range="PLANTILLA_OT!C10:E10",
    ).execute().get("values", [[]])
    monthly_values = sheets.spreadsheets().values().get(
        spreadsheetId=settings.GOOGLE_MONTHLY_SPREADSHEET_ID,
        range=f"{get_monthly_sheet_title(execution_date.month)}!A:W",
    ).execute().get("values", [])
    monthly_row = next(
        (row for row in monthly_values if len(row) > 1 and str(row[1]).strip() == ot_number),
        None,
    )

    if not ot_values or len(ot_values[0]) < 3:
        raise RuntimeError("No se pudo leer C10:E10 de la OT creada")
    if "[X] LOTO / Bloqueo" not in ot_values[0][0] or "[X] AST" not in ot_values[0][0]:
        raise RuntimeError(f"C10 no contiene los controles esperados: {ot_values[0][0]!r}")
    if "[X] Tarjeta roja" not in ot_values[0][1]:
        raise RuntimeError(f"D10 no contiene Tarjeta roja: {ot_values[0][1]!r}")
    if monthly_row is None:
        raise RuntimeError("No se encontró la OT de prueba en el registro mensual")

    output = BACKEND / "test_loto_integration_output.txt"
    output.write_text(
        "RESULTADO: OK\n"
        f"OT: {ot_number}\n"
        f"Google OT: https://docs.google.com/spreadsheets/d/{file_id}/edit\n"
        f"Plantilla usada: {settings.GOOGLE_OT_TEMPLATE_FILE_ID}\n"
        f"Controles: {', '.join(controls)}\n"
        f"C10: {ot_values[0][0]!r}\n"
        f"D10: {ot_values[0][1]!r}\n"
        f"E10: {ot_values[0][2]!r}\n"
        f"Registro mensual: {settings.GOOGLE_MONTHLY_SPREADSHEET_ID}\n",
        encoding="utf-8",
    )
    print(output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
