"""READ-ONLY audit: what exists in Google Drive + DB that a cleanup would remove.

Lists the generated OT documents (copies made from the OT template, i.e. the
files under GOOGLE_OT_ROOT_FOLDER_ID), and counts WorkOrders in the DB. It does
NOT delete anything — it only prints, so the user can confirm the exact scope
before a real cleanup script runs.

Usage:
    cd backend && python -m scripts.audit_cleanup_scope
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import google_drive
from app.core.config import settings


def _drive():
    return google_drive._build_drive_write_service()


def list_drive_children(parent_id: str) -> list[dict]:
    """List immediate children of a Drive folder (id + name + type)."""
    drive = _drive()
    out = []
    q = f"'{parent_id}' in parents and trashed = false"
    page_token = None
    while True:
        body = {"q": q, "fields": "files(id, name, mimeType), nextPageToken", "pageSize": 500}
        if page_token:
            body["pageToken"] = page_token
        resp = drive.files().list(**body).execute()
        out.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return out


def walk(root_id: str, depth: int = 0, max_depth: int = 5) -> None:
    if depth > max_depth:
        return
    for f in list_drive_children(root_id):
        indent = "  " * depth
        is_folder = f["mimeType"] == "application/vnd.google-apps.folder"
        print(f"{indent}{'[DIR]' if is_folder else '[FILE]'} {f['name']}  ({f['id']})")
        if is_folder:
            walk(f["id"], depth + 1, max_depth)


def main() -> None:
    from app.db.session import async_session
    from sqlalchemy import text
    import asyncio

    async def _read_all():
        async with async_session() as s:
            r = await s.execute(
                text("SELECT COUNT(*) AS total, COUNT(google_ot_file_id) AS with_drive FROM work_orders")
            )
            cnt = r.mappings().first()
            r2 = await s.execute(
                text("SELECT MIN(created_at) AS first, MAX(created_at) AS last FROM work_orders")
            )
            rng = r2.mappings().first()
            r3 = await s.execute(
                text(
                    "SELECT ot_number, status, google_ot_file_id, google_ot_url, "
                    "execution_date FROM work_orders ORDER BY ot_number"
                )
            )
            orders = r3.mappings().all()
            r4 = await s.execute(
                text("SELECT year, spreadsheet_id, spreadsheet_url FROM google_monthly_registers ORDER BY year")
            )
            regs = r4.mappings().all()
            return cnt, rng, orders, regs

    cnt, rng, orders, regs = asyncio.run(_read_all())

    print("=== DB: WorkOrders (Postgres) ===")
    print(f"  total OTs: {cnt['total']}")
    print(f"  con google_ot_file_id: {cnt['with_drive']}")
    print(f"  rango created_at: {rng['first']} a {rng['last']}")

    print("\n  OTs con su estado de drive:")
    for o in orders:
        fid = o["google_ot_file_id"] or "-"
        print(f"    {o['ot_number']:<14} {o['status']:<12} exec={o['execution_date']}  drive={fid}")

    print("\n=== DB: google_monthly_registers ===")
    for r_ in regs:
        print(f"  {r_['year']}: {r_['spreadsheet_id']}  url={r_['spreadsheet_url']}")
    if not regs:
        print("  (ninguno)")

    print("\n=== Google Drive: OT root folder tree ===")
    root = settings.GOOGLE_OT_ROOT_FOLDER_ID
    print(f"  OT root: {root}")
    walk(root)


if __name__ == "__main__":
    main()