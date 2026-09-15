"""Create the Services / General Plant catalog entries.

The script is intentionally idempotent: it creates the area and only the
equipment that is missing from that area.  It does not rename or delete
existing catalog entries.

Usage from ``backend/``::

    python scripts/seed_services_catalog.py          # dry run
    python scripts/seed_services_catalog.py --apply  # write to configured DB

Set ``MAINTENANCE_ENV_FILE`` when the database environment file is outside
``backend/.env``.  This makes the same script usable for local and production
databases without putting credentials in source control.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import func, select

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from app.db.session import async_session  # noqa: E402
from app.models.area import Area  # noqa: E402
from app.models.equipment import Equipment  # noqa: E402


AREA_NAME = "SERVICIOS PLANTA GENERAL / OTRAS AREAS"

EQUIPMENT_NAMES = (
    "COMPRESOR ATLAS COPCO GA15",
    "COMPRESOR ATLAS COPCO GA37",
    "COMPRESOR ATLAS COPCO GA30",
    "BOMBA POZO AGUA SUR",
    "BOMBA POZO AGUA NORTE",
    "ROMANA CAMIONES",
    "GENERADORES PLANTA 500 KVA",
    "SOPLADOR SUB PRODUCTOS",
    "MEDIDOR GAS CALDERA (BOSH)",
    "MEDIDOR GAS HORNO",
    "MEDIDOR GAS CALDERA CHICA (PIEDRA)",
    "MANTENCION BARRERA CRUCE FFCC",
)


def _key(value: str) -> str:
    """Compare catalog names case-insensitively and ignoring extra spaces."""

    return " ".join(value.split()).casefold()


async def seed(*, apply: bool) -> None:
    async with async_session() as db:
        area = (
            await db.execute(
                select(Area).where(func.lower(func.trim(Area.name)) == AREA_NAME.casefold())
            )
        ).scalar_one_or_none()

        area_was_created = area is None
        if area is None:
            area = Area(name=AREA_NAME)
            db.add(area)
            await db.flush()

        existing = (
            await db.execute(select(Equipment).where(Equipment.area_id == area.id))
        ).scalars().all()
        existing_by_key = {_key(item.name): item for item in existing}
        missing = [name for name in EQUIPMENT_NAMES if _key(name) not in existing_by_key]

        print(f"Área: {AREA_NAME} ({'nueva' if area_was_created else 'ya existe'})")
        print(f"Equipos existentes en el área: {len(existing)}")
        if missing:
            print("Equipos que se agregarán:")
            for name in missing:
                print(f"  - {name}")
        else:
            print("No faltan equipos; el catálogo ya está completo.")

        if not apply:
            await db.rollback()
            print("\nSIMULACIÓN: no se modificó la base de datos.")
            print("Para aplicar, vuelve a ejecutar con --apply.")
            return

        for name in missing:
            db.add(Equipment(name=name, area_id=area.id))
        await db.commit()
        print(f"\nOK: área lista con {len(EQUIPMENT_NAMES)} equipos configurados.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="guardar los cambios en la base configurada; sin esto solo simula",
    )
    args = parser.parse_args()
    asyncio.run(seed(apply=args.apply))


if __name__ == "__main__":
    main()
