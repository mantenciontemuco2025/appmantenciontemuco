"""Reset the database: drop all tables, recreate via Alembic, then seed.

Run from backend/:
    python reset_db.py
"""

import subprocess
import sys

from sqlalchemy import text
from app.db.session import async_session
import asyncio


async def reset():
    print("1/4  Dropping all tables...")
    async with async_session() as session:
        result = await session.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
        tables = [row[0] for row in result.fetchall()]

        if tables:
            await session.execute(text("SET session_replication_role = 'replica'"))
            for t in tables:
                await session.execute(text(f"DROP TABLE IF EXISTS {t} CASCADE"))
            await session.execute(text("SET session_replication_role = 'origin'"))
            for enum_name in ["syncstatus", "maintenancetype", "userrole"]:
                await session.execute(text(f"DROP TYPE IF EXISTS {enum_name} CASCADE"))

        await session.commit()
    print(f"    Dropped {len(tables)} tables.")


def migrate():
    print("2/4  Running Alembic migrations...")
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=".",
        check=True,
    )
    print("    Migrations applied.")


def seed():
    print("3/4  Running seed...")
    subprocess.run(
        [sys.executable, "seed.py"],
        cwd=".",
        check=True,
    )
    print("    Seed complete.")


def verify():
    print("4/4  Verifying tables...")
    result = subprocess.run(
        [
            "docker", "exec", "maintenance_postgres",
            "psql", "-U", "maintenance_user", "-d", "maintenance_db",
            "-c", "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        ],
        capture_output=True, text=True
    )
    print(result.stdout)


if __name__ == "__main__":
    asyncio.run(reset())
    migrate()
    seed()
    verify()
    print("Done! Database reset, migrated, and seeded.")
