from app.models.area import Area
from app.models.equipment import Equipment
from app.models.plant_area import PlantArea
from app.models.user import User
from tests.conftest import auth_headers, get_token


async def test_supervisor_hallazgo_catalog_returns_assigned_equipment_only(
    client, seed_data, db_session_factory
):
    async with db_session_factory() as db:
        supervisor = await db.get(User, seed_data["supervisor"].id)

        assigned_plant_area = PlantArea(name="Calderas")
        other_plant_area = PlantArea(name="Paillaco")
        assigned_section = Area(name="Caldera (D)")
        excluded_section = Area(name="Caldera (Auxiliar)")
        other_section = Area(name="Sala de bombas")
        assigned_plant_area.sections.extend([assigned_section, excluded_section])
        other_plant_area.sections.append(other_section)

        db.add_all([assigned_plant_area, other_plant_area])
        await db.flush()
        assigned_equipment = Equipment(
            name="Bomba autorizada",
            area_id=assigned_section.id,
            plant_area_id=assigned_plant_area.id,
        )
        excluded_equipment = Equipment(
            name="Equipo de sección excluida",
            area_id=excluded_section.id,
            plant_area_id=assigned_plant_area.id,
        )
        other_equipment = Equipment(
            name="Equipo de otra área",
            area_id=other_section.id,
            plant_area_id=other_plant_area.id,
        )
        db.add_all([assigned_equipment, excluded_equipment, other_equipment])
        await db.commit()
        ids = {
            "plant_area": assigned_plant_area.id,
            "assigned_section": assigned_section.id,
            "excluded_section": excluded_section.id,
            "other_section": other_section.id,
            "assigned_equipment": assigned_equipment.id,
            "supervisor": supervisor.id,
        }

    supervisor_headers = auth_headers(await get_token(client, "supervisor@test.com"))
    admin_headers = auth_headers(await get_token(client, "admin@test.com"))
    assignment = await client.patch(
        f"/api/users/{ids['supervisor']}",
        json={
            "role": "SUPERVISOR",
            "area_id": None,
            "area_ids": [],
            "plant_area_ids": [ids["plant_area"]],
            "excluded_section_ids": [ids["excluded_section"]],
        },
        headers=admin_headers,
    )
    assert assignment.status_code == 200, assignment.text
    assert assignment.json()["plant_area_ids"] == [ids["plant_area"]]
    assert assignment.json()["area_ids"] == [ids["assigned_section"]]

    admin_catalog = await client.get("/api/catalogs/hierarchy", headers=admin_headers)
    assert admin_catalog.status_code == 200, admin_catalog.text
    assert any(
        equipment["id"] == ids["assigned_equipment"]
        for plant_area in admin_catalog.json()
        for section in plant_area["sections"]
        for equipment in section["equipment"]
    ), admin_catalog.json()
    me = await client.get("/api/auth/me", headers=supervisor_headers)
    assert me.status_code == 200, me.text
    assert me.json()["plant_area_ids"] == [ids["plant_area"]]
    assert me.json()["area_ids"] == [ids["assigned_section"]]
    assert me.json()["excluded_section_ids"] == [ids["excluded_section"]]

    supervisor_hierarchy = await client.get(
        "/api/catalogs/hierarchy", headers=supervisor_headers
    )
    assert supervisor_hierarchy.status_code == 200, supervisor_hierarchy.text
    hierarchy_section = next(
        section
        for section in supervisor_hierarchy.json()[0]["sections"]
        if section["id"] == ids["assigned_section"]
    )
    assert hierarchy_section["equipment"][0]["id"] == ids["assigned_equipment"]

    supervisor_tree = await client.get("/api/catalogs/tree", headers=supervisor_headers)
    assert supervisor_tree.status_code == 200, supervisor_tree.text
    tree_section = next(
        item for item in supervisor_tree.json() if item["id"] == ids["assigned_section"]
    )
    assert tree_section["equipment"][0]["id"] == ids["assigned_equipment"]

    response = await client.get(
        "/api/catalogs/hallazgo-options", headers=supervisor_headers
    )
    assert response.status_code == 200, response.text
    catalog = response.json()
    assert [area["id"] for area in catalog] == [ids["plant_area"]]
    assert [section["id"] for section in catalog[0]["sections"]] == [
        ids["assigned_section"]
    ]
    assert [equipment["id"] for equipment in catalog[0]["sections"][0]["equipment"]] == [
        ids["assigned_equipment"]
    ]


async def test_supervisor_hallazgo_catalog_keeps_assigned_legacy_section(
    client, seed_data, db_session_factory
):
    async with db_session_factory() as db:
        supervisor = await db.get(User, seed_data["supervisor"].id)
        legacy_section = Area(name="Sección histórica sin área")
        legacy_equipment = Equipment(name="Equipo histórico", area=legacy_section)
        db.add_all([legacy_section, legacy_equipment])
        await db.flush()
        supervisor.supervised_areas = [legacy_section]
        await db.commit()
        section_id = legacy_section.id
        equipment_id = legacy_equipment.id

    headers = auth_headers(await get_token(client, "supervisor@test.com"))
    response = await client.get("/api/catalogs/hallazgo-options", headers=headers)
    assert response.status_code == 200, response.text
    catalog = response.json()
    assert len(catalog) == 1
    assert catalog[0]["id"] == -1
    assert catalog[0]["sections"][0]["id"] == section_id
    assert catalog[0]["sections"][0]["equipment"][0]["id"] == equipment_id
