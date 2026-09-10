"""Backfill: register the existing 2026 monthly spreadsheet into PostgreSQL.

Once the GoogleMonthlyRegister table exists (alembic 0006), this registers the
legacy single spreadsheet from settings.GOOGLE_MONTHLY_SPREADSHEET_ID as the
year=2026 annual register so the system resolves 2026 from PostgreSQL instead of
the fixed env var. Idempotent: if a 2026 row already exists it is left untouched
(never duplicates).

Usage:  python scripts/backfill_monthly_registers.py
"""

import asyncio
import io
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from sqlalchemy import select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.session import async_session  # noqa: E402
from app.models.monthly_register import GoogleMonthlyRegister  # noqa: E402


async def run() -> None:
    legacy_id = settings.GOOGLE_MONTHLY_SPREADSHEET_ID.strip()
    if not legacy_id:
        print("GOOGLE_MONTHLY_SPREADSHEET_ID no configurado; no hay 2026 que backfillear.")
        return

    async with async_session() as db:
        existing = (
            await db.execute(
                select(GoogleMonthlyRegister).where(GoogleMonthlyRegister.year == 2026)
            )
        ).scalar_one_or_none()

        if existing is not None:
            print(
                f"2026 ya registrado (spreadsheet_id={existing.spreadsheet_id}); "
                "nada que hacer. No se duplicó."
            )
            return

        reg = GoogleMonthlyRegister(
            year=2026,
            spreadsheet_id=legacy_id,
            spreadsheet_url=f"https://drive.google.com/file/d/{legacy_id}/view",
            is_active=True,
        )
        db.add(reg)
        await db.commit()
        print(f"OK: 2026 registrado con el spreadsheet existente ({legacy_id}).")


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    asyncio.run(run())
