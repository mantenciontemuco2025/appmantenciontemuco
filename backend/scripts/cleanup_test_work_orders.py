"""Remove the explicitly listed test work orders and their external artifacts.

Default mode is a dry run. Use --confirm only after reviewing the report.
This script never deletes templates, root folders, users, or monthly-register
spreadsheets; it only clears rows whose exact OT number is in TEST_OT_NUMBERS.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Iterable

from sqlalchemy import delete, or_, select

from app.db.session import async_session
from app.models.monthly_register import GoogleMonthlyRegister
from app.models.notification import Notification
from app.models.sync_job import ExternalSyncJob
from app.models.work_order import WorkOrder
from app.models.work_order_participants import work_order_participants
from app.services.google_drive import _build_drive_write_service, _build_sheets_write_service
from app.services.monthly_mapping import SPANISH_MONTHS, get_monthly_sheet_title
from app.core.config import settings


TEST_OT_NUMBERS = tuple(f"OT-2026-{number:04d}" for number in range(1, 6))


def _drive_files_by_name(names: Iterable[str]) -> list[dict]:
    drive = _build_drive_write_service()
    files: list[dict] = []
    for name in names:
        response = (
            drive.files()
            .list(
                q=f"name = '{name}' and trashed = false",
                fields="files(id,name,parents,webViewLink)",
                pageSize=100,
            )
            .execute()
        )
        files.extend(response.get("files", []))
    return files


def _monthly_spreadsheet_ids(registers: list[GoogleMonthlyRegister]) -> list[str]:
    ids = [register.spreadsheet_id for register in registers]
    if settings.GOOGLE_MONTHLY_SPREADSHEET_ID:
        ids.append(settings.GOOGLE_MONTHLY_SPREADSHEET_ID)
    return list(dict.fromkeys(ids))


def _monthly_rows(spreadsheet_ids: Iterable[str], names: set[str]) -> list[tuple[str, str, int]]:
    sheets = _build_sheets_write_service()
    matches: list[tuple[str, str, int]] = []
    for spreadsheet_id in spreadsheet_ids:
        for month in SPANISH_MONTHS:
            title = get_monthly_sheet_title(SPANISH_MONTHS.index(month) + 1)
            response = (
                sheets.spreadsheets()
                .values()
                .get(spreadsheetId=spreadsheet_id, range=f"{title}!A:Z")
                .execute()
            )
            for row_number, row in enumerate(response.get("values", []), start=1):
                if any(str(cell).strip() in names for cell in row):
                    matches.append((spreadsheet_id, title, row_number))
    return matches


async def _load_data():
    async with async_session() as db:
        result = await db.execute(
            select(WorkOrder).where(WorkOrder.ot_number.in_(TEST_OT_NUMBERS))
        )
        work_orders = list(result.scalars().all())
        registers = list((await db.execute(select(GoogleMonthlyRegister))).scalars().all())
        notification_filters = [
            condition
            for ot_number in TEST_OT_NUMBERS
            for condition in (
                Notification.message.contains(ot_number),
                Notification.link.contains(ot_number),
            )
        ]
        notifications = list(
            (
                await db.execute(
                    select(Notification).where(or_(*notification_filters))
                )
            )
            .scalars()
            .all()
        )
        return work_orders, registers, notifications


async def _delete_database_rows(
    work_order_ids: list[int], notification_ids: list[int]
) -> None:
    if not work_order_ids and not notification_ids:
        return
    async with async_session() as db:
        if notification_ids:
            await db.execute(
                delete(Notification).where(Notification.id.in_(notification_ids))
            )
        if work_order_ids:
            await db.execute(
                delete(ExternalSyncJob).where(
                    ExternalSyncJob.work_order_id.in_(work_order_ids)
                )
            )
            await db.execute(
                delete(work_order_participants).where(
                    work_order_participants.c.work_order_id.in_(work_order_ids)
                )
            )
            await db.execute(delete(WorkOrder).where(WorkOrder.id.in_(work_order_ids)))
        await db.commit()


async def _run(args: argparse.Namespace) -> None:
    work_orders, registers, notifications = await _load_data()
    names = set(TEST_OT_NUMBERS)
    drive_files = _drive_files_by_name(names)
    monthly_rows = _monthly_rows(_monthly_spreadsheet_ids(registers), names)

    print("OTs objetivo:", ", ".join(TEST_OT_NUMBERS))
    print("\nBase de datos:")
    for work_order in work_orders:
        print(
            f"  id={work_order.id} {work_order.ot_number} "
            f"drive={work_order.google_ot_file_id or '(sin archivo)'}"
        )
    print("\nNotificaciones asociadas:")
    for notification in notifications:
        print(
            f"  id={notification.id} user={notification.user_id} "
            f"type={notification.type} message={notification.message}"
        )
    print("\nArchivos de Google Drive que coinciden exactamente:")
    for file in drive_files:
        print(f"  {file.get('name')}  id={file.get('id')}")
    print("\nFilas del registro mensual:")
    for spreadsheet_id, title, row_number in monthly_rows:
        print(f"  spreadsheet={spreadsheet_id} hoja={title} fila={row_number}")

    if not args.confirm:
        print("\nSIMULACION: no se borro nada.")
        print("Si la lista es correcta, vuelve a ejecutar agregando --confirm.")
        return

    sheets = _build_sheets_write_service()
    for spreadsheet_id, title, row_number in monthly_rows:
        sheets.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id,
            range=f"{title}!A{row_number}:Z{row_number}",
            body={},
        ).execute()

    drive = _build_drive_write_service()
    for file in drive_files:
        drive.files().delete(fileId=file["id"]).execute()

    await _delete_database_rows(
        [work_order.id for work_order in work_orders],
        [notification.id for notification in notifications],
    )
    print("\nLimpieza completada.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="perform the deletion after displaying the exact targets",
    )
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
