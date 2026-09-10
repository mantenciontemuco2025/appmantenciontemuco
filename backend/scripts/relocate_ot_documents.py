"""Re-locate OT documents that landed in the wrong Drive folder (PLANTILLAS).

Context: before the 2026-09-04 fix, `_copy_template` passed addParents/removeParents
in the body of `files().update()` instead of as query params, so every OT copy
stayed in PLANTILLAS. This script fixes existing OTs.

Approach (idempotent, safe):
- Reads the DATABASE as source of truth: every WorkOrder with a
  google_ot_file_id and an execution_date.
- For each, resolves its CURRENT parent folder on Drive.
- If the parent is NOT the year/month folder (and not already correct), moves
  the file into the correct  ORDENES DE TRABAJO/<AÑO>/<MES>/  folder.
- Nothing is deleted; only addParents/removeParents on the file.

Usage (from backend/):
    python scripts/relocate_ot_documents.py --dry-run      # preview only
    python scripts/relocate_ot_documents.py                # apply

Requires OAuth (write) — the Service Account is never used for writes.
"""

import argparse
import asyncio
import sys
from datetime import date as _date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.session import async_session  # noqa: E402
from app.models.work_order import WorkOrder  # noqa: E402
from app.services.google_drive import (  # noqa: E402
    _build_drive_write_service,
    _ensure_month_folder,
    _get_file_parent,
)
from app.services.ot_mapping import SPANISH_MONTHS  # noqa: E402


def _folder_name_of(drive, folder_id: str | None) -> str:
    if not folder_id:
        return "?"
    try:
        return drive.files().get(fileId=folder_id, fields="name").execute().get("name", "?")
    except Exception as exc:  # noqa: BLE001 - best-effort
        return f"<{type(exc).__name__}>"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="preview only, no changes")
    args = parser.parse_args()

    drive = _build_drive_write_service()

    # Collect OTs with a Google file and an execution date
    async with async_session() as db:
        result = await db.execute(
            select(WorkOrder)
            .where(
                WorkOrder.google_ot_file_id.isnot(None),
                WorkOrder.execution_date.isnot(None),
            )
            .order_by(WorkOrder.ot_number)
        )
        wos = result.scalars().all()

    if not wos:
        print("No hay OTs con documento de Google + fecha de ejecución.")
        return

    moved = 0
    already_ok = 0
    skipped = 0

    for wo in wos:
        file_id = wo.google_ot_file_id
        exec_dt = wo.execution_date
        if isinstance(exec_dt, _date):
            year, month = exec_dt.year, exec_dt.month
            month_name = SPANISH_MONTHS[month - 1]
        else:
            skipped += 1
            print(f"  [SKIP] {wo.ot_number}: fecha de ejecución inválida")
            continue

        # Resolve current parent
        current_parent = _get_file_parent(drive, file_id)
        current_name = _folder_name_of(drive, current_parent)
        target_id = _ensure_month_folder(year, month)
        target_name = _folder_name_of(drive, target_id)

        if current_parent == target_id:
            already_ok += 1
            print(f"  [OK]   {wo.ot_number}: ya en {target_name}")
            continue

        print(
            f"  [MOV]  {wo.ot_number}: {current_name} -> {target_name}"
            f"  (file_id={file_id})"
        )
        if args.dry_run:
            continue

        drive.files().update(
            fileId=file_id, addParents=target_id, removeParents=current_parent
        ).execute()
        moved += 1

    print(
        f"\nResumen: movidos={moved}, ya-correctos={already_ok}, "
        f"omitidos={skipped}  ({'DRY-RUN, sin cambios' if args.dry_run else 'aplicado'})"
    )


if __name__ == "__main__":
    asyncio.run(main())