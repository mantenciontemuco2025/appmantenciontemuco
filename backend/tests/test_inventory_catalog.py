from tests.conftest import auth_headers, get_token


async def test_inventory_import_preserves_legacy_catalog_and_scopes_equipment(client, seed_data):
    token = await get_token(client, "admin@test.com")
    headers = auth_headers(token)

    imported = await client.post(
        "/api/catalogs/inventory/import",
        json={
            "items": [
                {
                    "inventory_code": "1449",
                    "plant_area": "Planta Cajón",
                    "section": "Recepción y Despacho",
                    "equipment": "Elevador 1 Pavo 2",
                    "category": "Elevador",
                },
                {
                    "inventory_code": "1481",
                    "plant_area": "Planta Paillaco",
                    "section": "Recepción y Despacho",
                    "equipment": "Elevador 1 Pavo 2",
                    "category": "Elevador",
                },
                {
                    "inventory_code": "1449",
                    "plant_area": "Planta Cajón",
                    "section": "Recepción y Despacho",
                    "equipment": "Duplicado",
                },
                {
                    "inventory_code": "2104",
                    "plant_area": "Extracto",
                    "section": "Holding",
                    "equipment": "",
                },
            ]
        },
        headers=headers,
    )
    assert imported.status_code == 200
    data = imported.json()
    assert data["equipment_created"] == 2
    assert data["skipped"] == 2
    assert any("1449" in error for error in data["errors"])
    assert any("2104" in error for error in data["errors"])

    hierarchy = await client.get("/api/catalogs/hierarchy", headers=headers)
    assert hierarchy.status_code == 200
    areas = {item["name"]: item for item in hierarchy.json()}
    cajon = areas["Planta Cajón"]
    paillaco = areas["Planta Paillaco"]
    cajon_section = next(item for item in cajon["sections"] if item["name"] == "Recepción y Despacho")
    paillaco_section = next(item for item in paillaco["sections"] if item["name"] == "Recepción y Despacho")
    assert cajon_section["equipment"][0]["inventory_code"] == "1449"
    assert paillaco_section["equipment"][0]["inventory_code"] == "1481"

    legacy_tree = await client.get("/api/catalogs/tree", headers=headers)
    assert legacy_tree.status_code == 200
    assert any(item["name"] == "Malta" for item in legacy_tree.json())
