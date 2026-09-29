"""Authorization and duplicate protection for admin area creation."""

from tests.conftest import auth_headers, get_token
from app.models.work_order import WorkOrder


async def test_admin_can_create_area_and_duplicate_is_rejected(client, seed_data):
    token = await get_token(client, "admin@test.com")
    headers = auth_headers(token)

    created = await client.post(
        "/api/catalogs/areas",
        json={"name": "Planta de Riles"},
        headers=headers,
    )
    assert created.status_code == 201
    assert created.json()["name"] == "Planta de Riles"

    duplicate = await client.post(
        "/api/catalogs/areas",
        json={"name": " planta de riles "},
        headers=headers,
    )
    assert duplicate.status_code == 409


async def test_worker_cannot_create_area(client, seed_data):
    token = await get_token(client, "ortiz@test.com")
    response = await client.post(
        "/api/catalogs/areas",
        json={"name": "Área no autorizada"},
        headers=auth_headers(token),
    )
    assert response.status_code == 403


async def test_admin_can_create_general_plant_area_and_duplicate_is_rejected(client, seed_data):
    token = await get_token(client, "admin@test.com")
    headers = auth_headers(token)

    created = await client.post(
        "/api/catalogs/plant-areas",
        json={"name": "Planta de Riles"},
        headers=headers,
    )
    assert created.status_code == 201
    assert created.json()["name"] == "Planta de Riles"
    plant_area_id = created.json()["id"]

    updated = await client.patch(
        f"/api/catalogs/plant-areas/{plant_area_id}",
        json={"name": "Planta de Riles Nueva"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Planta de Riles Nueva"

    duplicate = await client.post(
        "/api/catalogs/plant-areas",
        json={"name": " planta de riles nueva "},
        headers=headers,
    )
    assert duplicate.status_code == 409

    deleted = await client.delete(
        f"/api/catalogs/plant-areas/{plant_area_id}",
        headers=headers,
    )
    assert deleted.status_code == 204


async def test_worker_cannot_create_general_plant_area(client, seed_data):
    token = await get_token(client, "ortiz@test.com")
    response = await client.post(
        "/api/catalogs/plant-areas",
        json={"name": "Área general no autorizada"},
        headers=auth_headers(token),
    )
    assert response.status_code == 403


async def test_area_with_work_orders_cannot_be_deleted(client, seed_data, db_session_factory):
    token = await get_token(client, "admin@test.com")
    headers = auth_headers(token)
    created = await client.post(
        "/api/catalogs/plant-areas",
        json={"name": "Área protegida por OT"},
        headers=headers,
    )
    assert created.status_code == 201
    plant_area_id = created.json()["id"]

    async with db_session_factory() as db:
        db.add(
            WorkOrder(
                ot_number="OT-TEST-AREA-01",
                title="OT asociada al área",
                description="Prueba de protección del catálogo",
                plant_area="Área protegida por OT",
                maintenance_type="CORRECTIVE",
                created_by_user_id=seed_data["admin"].id,
            )
        )
        await db.commit()

    deleted = await client.delete(
        f"/api/catalogs/plant-areas/{plant_area_id}",
        headers=headers,
    )
    assert deleted.status_code == 409
    assert "OTs" in deleted.json()["detail"]

    related = await client.get(
        f"/api/catalogs/plant-areas/{plant_area_id}/work-orders",
        headers=headers,
    )
    assert related.status_code == 200
    assert related.json()[0]["ot_number"] == "OT-TEST-AREA-01"


async def test_area_without_work_orders_can_be_deleted(client, seed_data, db_session_factory):
    token = await get_token(client, "admin@test.com")
    headers = auth_headers(token)
    created = await client.post(
        "/api/catalogs/plant-areas",
        json={"name": "Área sin OT"},
        headers=headers,
    )
    assert created.status_code == 201

    deleted = await client.delete(
        f"/api/catalogs/plant-areas/{created.json()['id']}",
        headers=headers,
    )
    assert deleted.status_code == 204
