async def get_token(client, email: str) -> str:
    response = await client.post(
        "/api/auth/login", data={"username": email, "password": "pass123"}
    )
    return response.json()["access_token"]


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_equipment_inventory_admin_edits_and_worker_sees_no_initial_value(
    client, seed_data
):
    equipment_id = seed_data["equipment"].id
    admin_token = await get_token(client, "admin@test.com")
    worker_token = await get_token(client, "ortiz@test.com")
    other_worker_token = await get_token(client, "valdes@test.com")

    assigned = await client.patch(
        f"/api/users/{seed_data['worker'].id}",
        headers=auth_headers(admin_token),
        json={"can_manage_equipment_inventory": True},
    )
    assert assigned.status_code == 200
    assert assigned.json()["can_manage_equipment_inventory"] is True

    response = await client.patch(
        f"/api/catalogs/equipment/{equipment_id}/inventory",
        headers=auth_headers(admin_token),
        json={
            "model": "MX-100",
            "weight": 12.5,
            "unit": "KG",
            "initial_value": 125000,
            "custom_attributes": [{"label": "Tipo de sello", "value": "Mecánico"}],
        },
    )
    assert response.status_code == 200
    assert response.json()["model"] == "MX-100"
    assert response.json()["initial_value"] == "125000"

    worker_list = await client.get(
        "/api/catalogs/equipment-inventory", headers=auth_headers(worker_token)
    )
    assert worker_list.status_code == 200
    worker_item = next(item for item in worker_list.json() if item["id"] == equipment_id)
    assert worker_item["model"] == "MX-100"
    assert worker_item["initial_value"] is None
    assert worker_item["custom_attributes"] == [{"label": "Tipo de sello", "value": "Mecánico"}]

    edited_by_worker = await client.patch(
        f"/api/catalogs/equipment/{equipment_id}/inventory",
        headers=auth_headers(worker_token),
        json={"model": "MX-101"},
    )
    assert edited_by_worker.status_code == 200
    assert edited_by_worker.json()["initial_value"] is None

    forbidden_price_edit = await client.patch(
        f"/api/catalogs/equipment/{equipment_id}/inventory",
        headers=auth_headers(worker_token),
        json={"initial_value": 1},
    )
    assert forbidden_price_edit.status_code == 403

    not_assigned = await client.patch(
        f"/api/catalogs/equipment/{equipment_id}/inventory",
        headers=auth_headers(other_worker_token),
        json={"model": "No autorizado"},
    )
    assert not_assigned.status_code == 403

    transferred = await client.patch(
        f"/api/users/{seed_data['valdes'].id}",
        headers=auth_headers(admin_token),
        json={"can_manage_equipment_inventory": True},
    )
    assert transferred.status_code == 200
    previous_holder = await client.get("/api/auth/me", headers=auth_headers(worker_token))
    assert previous_holder.json()["can_manage_equipment_inventory"] is False
    new_holder = await client.get("/api/auth/me", headers=auth_headers(other_worker_token))
    assert new_holder.json()["can_manage_equipment_inventory"] is True


async def test_equipment_inventory_rejects_duplicate_custom_attribute_labels(client, seed_data):
    admin_token = await get_token(client, "admin@test.com")
    response = await client.patch(
        f"/api/catalogs/equipment/{seed_data['equipment'].id}/inventory",
        headers=auth_headers(admin_token),
        json={
            "custom_attributes": [
                {"label": "Sello", "value": "A"},
                {"label": "sello", "value": "B"},
            ]
        },
    )
    assert response.status_code == 422
