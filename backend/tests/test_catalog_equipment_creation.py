"""Authorization and duplicate protection for inline equipment creation."""

from app.models.area import Area
from app.models.user import User
from tests.conftest import auth_headers, get_token


async def test_admin_can_create_equipment_and_duplicate_is_rejected(client, seed_data):
    token = await get_token(client, "admin@test.com")
    headers = auth_headers(token)
    payload = {"name": "Bomba de prueba", "area_id": seed_data["area"].id}

    created = await client.post("/api/catalogs/equipment", json=payload, headers=headers)
    assert created.status_code == 201
    assert created.json()["name"] == payload["name"]
    assert created.json()["area_id"] == payload["area_id"]

    duplicate = await client.post("/api/catalogs/equipment", json=payload, headers=headers)
    assert duplicate.status_code == 409


async def test_supervisor_can_only_add_equipment_to_assigned_section(
    client, seed_data, db_session_factory
):
    async with db_session_factory() as db:
        supervisor = await db.get(User, seed_data["supervisor"].id)
        assigned_area = await db.get(Area, seed_data["area"].id)
        other_area = Area(name="Otra sección")
        db.add(other_area)
        supervisor.supervised_areas.append(assigned_area)
        await db.flush()
        other_area_id = other_area.id
        await db.commit()

    token = await get_token(client, "supervisor@test.com")
    headers = auth_headers(token)

    allowed = await client.post(
        "/api/catalogs/equipment",
        json={"name": "Equipo del supervisor", "area_id": seed_data["area"].id},
        headers=headers,
    )
    assert allowed.status_code == 201

    forbidden = await client.post(
        "/api/catalogs/equipment",
        json={"name": "Equipo fuera de alcance", "area_id": other_area_id},
        headers=headers,
    )
    assert forbidden.status_code == 403


async def test_worker_cannot_create_equipment(client, seed_data):
    token = await get_token(client, "ortiz@test.com")
    response = await client.post(
        "/api/catalogs/equipment",
        json={"name": "No autorizado", "area_id": seed_data["area"].id},
        headers=auth_headers(token),
    )
    assert response.status_code == 403
