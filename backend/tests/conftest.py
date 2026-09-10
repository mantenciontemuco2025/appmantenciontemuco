"""Shared test fixtures.

Uses an in-memory SQLite database (aiosqlite) so tests need no Postgres.
Google Sheets is mocked.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.db.base import Base
from app.main import app as fastapi_app
from app.core.security import hash_password
from app.models.user import User, UserRole
from app.models.area import Area
from app.models.equipment import Equipment

import app.models  # noqa: F401 - register models


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session_factory(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def client(db_session_factory, monkeypatch):
    from app.db import session as session_module

    async def override_get_db():
        async with db_session_factory() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    # Ensure Google is NOT configured -> sync skipped gracefully.
    # Clear BOTH Service Account and OAuth credentials so no real calls leak
    # from the developer's .env into the isolated test env.
    monkeypatch.setattr(
        "app.core.config.settings.GOOGLE_SERVICE_ACCOUNT_JSON", ""
    )
    monkeypatch.setattr(
        "app.core.config.settings.GOOGLE_SERVICE_ACCOUNT_FILE", ""
    )
    monkeypatch.setattr(
        "app.core.config.settings.GOOGLE_OAUTH_CLIENT_ID", ""
    )
    monkeypatch.setattr(
        "app.core.config.settings.GOOGLE_OAUTH_CLIENT_SECRET", ""
    )
    monkeypatch.setattr(
        "app.core.config.settings.GOOGLE_OAUTH_REFRESH_TOKEN", ""
    )

    fastapi_app.dependency_overrides[session_module.get_db] = override_get_db
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    fastapi_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def seed_data(db_session_factory):
    """Create users (admin, supervisor, workers), area, equipment (no section)."""
    async with db_session_factory() as db:
        admin = User(
            full_name="Admin",
            email="admin@test.com",
            password_hash=hash_password("pass123"),
            role=UserRole.ADMIN,
            signature="https://drive.google.com/uc?export=view&id=admin-signature",
        )
        supervisor = User(
            full_name="Supervisor",
            email="supervisor@test.com",
            password_hash=hash_password("pass123"),
            role=UserRole.SUPERVISOR,
        )
        worker = User(
            full_name="Ortiz",
            email="ortiz@test.com",
            password_hash=hash_password("pass123"),
            role=UserRole.WORKER,
            signature="https://drive.google.com/uc?export=view&id=ortiz-signature",
        )
        inactive = User(
            full_name="Inactivo",
            email="inactive@test.com",
            password_hash=hash_password("pass123"),
            role=UserRole.WORKER,
            is_active=False,
        )
        valdes = User(
            full_name="Valdés",
            email="valdes@test.com",
            password_hash=hash_password("pass123"),
            role=UserRole.WORKER,
        )
        worker_jara = User(
            full_name="Jara",
            email="jara@test.com",
            password_hash=hash_password("pass123"),
            role=UserRole.WORKER,
        )
        db.add_all([admin, supervisor, worker, inactive, valdes, worker_jara])
        await db.flush()

        area = Area(name="Malta")
        db.add(area)
        await db.flush()

        equipment = Equipment(name="Filtro", area_id=area.id)
        db.add(equipment)
        await db.flush()

        await db.commit()

        return {
            "admin": admin,
            "supervisor": supervisor,
            "worker": worker,
            "inactive": inactive,
            "valdes": valdes,
            "worker_jara": worker_jara,
            "area": area,
            "equipment": equipment,
        }


async def get_token(client, email, password="pass123"):
    resp = await client.post(
        "/api/auth/login",
        data={"username": email, "password": password},
    )
    return resp.json()["access_token"]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
