from tests.conftest import auth_headers, get_token


async def test_admin_can_import_and_manage_material_catalog(client, seed_data):
    admin_token = await get_token(client, "admin@test.com")
    worker_token = await get_token(client, "ortiz@test.com")
    admin_headers = auth_headers(admin_token)

    imported = await client.post(
        "/api/admin/materials/import",
        json={
            "items": [
                {"code": "B4320001", "description": "Abrazadera doble", "family": "Material eléctrico"},
                {"code": "B4340001", "description": "Perno hexagonal", "family": "Pernos"},
            ]
        },
        headers=admin_headers,
    )
    assert imported.status_code == 200
    assert imported.json()["created"] == 2

    # Interactive OT search must not return the entire catalog on an empty
    # query, and exact-code lookups preserve labels for codes already saved.
    empty_search = await client.get("/api/materials", headers=auth_headers(worker_token))
    assert empty_search.status_code == 200
    assert empty_search.json() == []

    selected_codes = await client.get(
        "/api/materials?codes=B4320001&codes=B4340001&limit=50",
        headers=auth_headers(worker_token),
    )
    assert selected_codes.status_code == 200
    assert {item["code"] for item in selected_codes.json()} == {"B4320001", "B4340001"}

    too_many_results = await client.get(
        "/api/materials?query=B&limit=5000",
        headers=auth_headers(worker_token),
    )
    assert too_many_results.status_code == 422

    visible = await client.get(
        "/api/materials?query=abrazadera",
        headers=auth_headers(worker_token),
    )
    assert visible.status_code == 200
    assert [item["code"] for item in visible.json()] == ["B4320001"]

    listed = await client.get("/api/admin/materials", headers=admin_headers)
    assert listed.status_code == 200
    assert listed.json()["total"] == 2

    material_id = next(item["id"] for item in listed.json()["items"] if item["code"] == "B4320001")
    edited = await client.patch(
        f"/api/admin/materials/{material_id}",
        json={"active": False},
        headers=admin_headers,
    )
    assert edited.status_code == 200
    assert edited.json()["active"] is False

    hidden = await client.get("/api/materials?query=B4320001", headers=auth_headers(worker_token))
    assert hidden.status_code == 200
    assert hidden.json() == []

    forbidden = await client.post(
        "/api/admin/materials",
        json={"code": "B4700001", "description": "Golilla", "family": "Tuercas"},
        headers=auth_headers(worker_token),
    )
    assert forbidden.status_code == 403
