"""Cleanup of all testing data (OTs + their Google files), keeping templates and accounts.

What it REMOVES (dry-run by default, single async transaction):
  1. All WorkOrder rows in Postgres + their M2M participants rows + the
     work-order-related audit_logs (entity_type='WorkOrder').
  2. The individual OT documents in Google Drive — EXACTLY those referenced by
     the  `google_ot_file_id` of the OTs being removed. No blind folder sweep.
  3. The OT test rows written into the per-year register spreadsheet: the DATA
     cells of every month tab are cleared via values.clear. The spreadsheet
     itself, its headers, tabs, formats and the master templates are KEPT.

What it NEVER touches (by design):
  - users, roles, areas, equipment, work_order participants / M2M of users.
  - GOOGLE_OT_TEMPLATE_FILE_ID, GOOGLE_MONTHLY_TEMPLATE_FILE_ID (master templates).
  - The monthly register spreadsheet(s) themselves (only their data cells).

Usage:
    cd backend
    python -m scripts.cleanup_test_ot        # dry-run: only prints what WOULD happen
    python -m scripts.cleanup_test_ot --yes   # actually performs the deletion
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.db.session import async_session
from app.services import google_drive
from app.services.ot_mapping import SPANISH_MONTHS
from app.core.config import settings


def _drive():
    return google_drive._build_drive_write_service()


async def main() -> None:
    dry = "--yes" not in sys.argv
    print("=" * 70)
    print("LIMPIEZA DE OTs DE PRUEBA")
    print(("DRY-RUN (no borra nada). Para ejecutar: python -m scripts.cleanup_test_ot --yes")
          if dry else "EJECUTANDO BORRADO REAL")
    print("=" * 70)

    async with async_session() as db:
        # ── Read scope (single DB session, one event loop) ────────────────
        r = await db.execute(text(
            "SELECT ot_number, google_ot_file_id FROM work_orders ORDER BY ot_number"
        ))
        orders = r.mappings().all()
        r2 = await db.execute(text(
            "SELECT spreadsheet_id FROM google_monthly_registers"
        ))
        regs = r2.mappings().all()

    targets = [o["google_ot_file_id"] for o in orders if o["google_ot_file_id"]]
    targets = [fid for fid in targets if fid not in (
        settings.GOOGLE_OT_TEMPLATE_FILE_ID,
        settings.GOOGLE_MONTHLY_TEMPLATE_FILE_ID,
        settings.GOOGLE_MONTHLY_SPREADSHEET_ID,
    )]

    print(f"\n  OTs en BD a borrar: {len(orders)}")
    print(f"  Archivos Drive referenciados (a borrar): {len(targets)}")

    # 1) Drive: individual OT documents (exactly those the test OTs reference)
    print("\n[1] Borrar documentos OT en Drive (solo los referenciados):")
    for fid in targets:
        print(f"    x {fid}")
        if not dry:
            try:
                _drive().files().delete(fileId=fid).execute()
            except Exception as e:
                # Already deleted (not found) is fine — idempotent cleanup.
                if "404" in str(e) or "notFound" in str(e) or "File not found" in str(e):
                    print("        (ya no existe — ok)")
                else:
                    raise

    # 2) BD: audit logs + participants + work orders (same session, one loop)
    print("\n[2] Borrar OTs en BD (audit_logs + M2M + work_orders):")
    if not dry:
        async with async_session() as db:
            await db.execute(text(
                "DELETE FROM audit_logs WHERE entity_type='WorkOrder' "
                "AND entity_id IN (SELECT id FROM work_orders)"
            ))
            await db.execute(text("DELETE FROM work_order_participants"))
            await db.execute(text("DELETE FROM work_orders"))
            await db.commit()
    print(f"    {len(orders)} work_orders + participantes + audit de OTs")

    # 3) Monthly register: clear the DATA cells of every month tab, keeping
    #    the spreadsheet + headers + tabs + formats intact.
    print("\n[3] Vaciar filas de datos del registro mensual (conservando el spreadsheet):")
    register_ids = set(r_["spreadsheet_id"] for r_ in regs)
    if not register_ids and settings.GOOGLE_MONTHLY_SPREADSHEET_ID:
        register_ids = {settings.GOOGLE_MONTHLY_SPREADSHEET_ID}

    for sid in register_ids:
        sheets = google_drive._build_sheets_write_service()
        print(f"  spreadsheet {sid}:")
        for tab_title in SPANISH_MONTHS:
            rng = f"{tab_title}!A4:Z1000"  # MONTHLY_DATA_START_ROW=4 → data onwards
            print(f"    x limpiar valores en '{tab_title}'")
            if not dry:
                try:
                    sheets.spreadsheets().values().clear(
                        spreadsheetId=sid,
                        range=rng,
                        body={},
                    ).execute()
                except Exception as e:
                    print(f"        (aviso: {e})")

    print("\n" + "=" * 70)
    if dry:
        print("DRY-RUN completado. Nada fue borrado.")
        print("Para ejecutar: python -m scripts.cleanup_test_ot --yes")
    else:
        print("Limpieza completada.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())