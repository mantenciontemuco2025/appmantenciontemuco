"""One-time migration: fix OT folder hierarchy location.

Problem: GOOGLE_OT_ROOT_FOLDER_ID used to point at the `Mantencion prueba`
root folder, so the `2026` year folder was created at root instead of inside
`ÓRDENES DE TRABAJO/`.

This script moves the misplaced `AÑO` folder(s) (e.g. `2026`) from the Drive
root into `ÓRDENES DE TRABAJO/`. It is idempotent: if the year folder already
lives inside ÓRDENES DE TRABAJO, it does nothing.

Expected final structure:
    Mantencion prueba/
    ├── ÓRDENES DE TRABAJO/
    │   └── 2026/
    │       └── SEPTIEMBRE/
    │           └── OT-2026-000N
    ├── PLANTILLAS/
    └── REGISTRO MENSUAL/

Run from backend/:
    python scripts/migrate_ot_folders.py

Uses the OAuth credentials (write) — the Service Account is never used.
Migrate is a WRITE operation, so OAuth must be configured.
"""

import sys
from pathlib import Path

from googleapiclient.discovery import build

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings  # noqa: E402


def main() -> None:
    creds = settings.get_google_write_credentials()  # raises if no OAuth
    drive = build("drive", "v3", credentials=creds)

    ot_root = settings.GOOGLE_OT_ROOT_FOLDER_ID
    if not ot_root:
        print("ERROR: GOOGLE_OT_ROOT_FOLDER_ID no está definido.")
        sys.exit(1)

    # Sanity: root of the whole Drive tree ("Mantencion prueba")
    ot_root_meta = drive.files().get(fileId=ot_root, fields="id,name,parents").execute()
    root_name = ot_root_meta.get("name")
    root_parent = (ot_root_meta.get("parents") or [None])[0]
    print(f"ÓRDENES DE TRABAJO folder: id={ot_root} name='{root_name}'")

    # Find year folders that are children of the ROOT and not inside OT_ROOT.
    # The tree's top-level root is the parent of ÓRDENES DE TRABAJO.
    if not root_parent:
        print("El folder de OT no reporta parent; no se puede localizar la raíz.")
        sys.exit(1)

    query = f"'{root_parent}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
    top_level = (
        drive.files().list(q=query, fields="files(id,name)", pageSize=500).execute()
    ).get("files", [])

    moved = 0
    for folder in top_level:
        name = folder.get("name", "")
        # Only move year-like folders (4-digit) that are NOT already in OT_ROOT
        if not (name.isdigit() and len(name) == 4):
            continue
        # Check if it's already a child of OT_ROOT
        already = (
            drive.files()
            .list(
                q=f"'{ot_root}' in parents and name='{name}' and trashed=false",
                fields="files(id)",
                pageSize=5,
            )
            .execute()
        ).get("files", [])
        if already:
            print(f"  * Anio '{name}' ya esta dentro de ORDENES DE TRABAJO - OK")
            continue

        drive.files().update(
            fileId=folder["id"], addParents=ot_root, removeParents=root_parent
        ).execute()
        print(f"  [OK] Movido '{name}' ({folder['id']}) -> ORDENES DE TRABAJO/")
        moved += 1

    if moved == 0:
        print("Nada que mover. La jerarquia ya es correcta.")
    else:
        print(f"\nListo. Se movieron {moved} carpeta(s) al interior de ORDENES DE TRABAJO.")


if __name__ == "__main__":
    main()
