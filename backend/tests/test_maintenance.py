"""Maintenance record creation, validation and duration tests."""

from tests.conftest import get_token, auth_headers


def valid_payload(data, **overrides):
    payload = {
        "date": "2026-09-01",
        "area_id": data["area"].id,
        "section_name": "Germinación",
        "equipment_id": data["equipment"].id,
        "description": "Lubricación de filtro",
        "maintenance_type": "PREVENTIVE",
        "start_time": "08:30",
        "end_time": "12:00",
        "participant_ids": [data["worker"].id],
    }
    payload.update(overrides)
    return payload


async def test_create_maintenance_success(client, seed_data):
    token = await get_token(client, "ortiz@test.com")
    resp = await client.post(
        "/api/maintenance",
        json=valid_payload(seed_data),
        headers=auth_headers(token),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["duration_minutes"] == 210
    assert data["maintenance_type"] == "PREVENTIVE"
    assert data["section_name"] == "Germinación"
    assert data["created_by"]["full_name"] == "Ortiz"
    # Google is unconfigured in tests; write ops require OAuth and therefore
    # fail clearly (record still created, marked FAILED — never silently skipped).
    assert data["sheet_sync_status"] == "FAILED"


async def test_area_equipment_mismatch(client, seed_data):
    """Equipment ID that doesn't belong to the selected area -> 400."""
    token = await get_token(client, "ortiz@test.com")
    resp = await client.post(
        "/api/maintenance",
        json=valid_payload(seed_data, equipment_id=9999),
        headers=auth_headers(token),
    )
    assert resp.status_code == 400


async def test_invalid_area(client, seed_data):
    """Non-existent area_id -> 400."""
    token = await get_token(client, "ortiz@test.com")
    resp = await client.post(
        "/api/maintenance",
        json=valid_payload(seed_data, area_id=9999),
        headers=auth_headers(token),
    )
    assert resp.status_code == 400


async def test_empty_section_name_rejected(client, seed_data):
    """section_name must not be blank."""
    token = await get_token(client, "ortiz@test.com")
    resp = await client.post(
        "/api/maintenance",
        json=valid_payload(seed_data, section_name="   "),
        headers=auth_headers(token),
    )
    assert resp.status_code == 422  # pydantic validation


async def test_invalid_participant(client, seed_data):
    token = await get_token(client, "ortiz@test.com")
    resp = await client.post(
        "/api/maintenance",
        json=valid_payload(seed_data, participant_ids=[9999]),
        headers=auth_headers(token),
    )
    assert resp.status_code == 400


async def test_empty_description_rejected(client, seed_data):
    token = await get_token(client, "ortiz@test.com")
    resp = await client.post(
        "/api/maintenance",
        json=valid_payload(seed_data, description="   "),
        headers=auth_headers(token),
    )
    assert resp.status_code == 422  # pydantic validation


async def test_end_before_start_rejected(client, seed_data):
    token = await get_token(client, "ortiz@test.com")
    resp = await client.post(
        "/api/maintenance",
        json=valid_payload(seed_data, start_time="12:00", end_time="08:30"),
        headers=auth_headers(token),
    )
    assert resp.status_code == 400


async def test_duration_calculation(client, seed_data):
    token = await get_token(client, "ortiz@test.com")
    resp = await client.post(
        "/api/maintenance",
        json=valid_payload(seed_data, start_time="08:30", end_time="12:00"),
        headers=auth_headers(token),
    )
    assert resp.json()["duration_minutes"] == 210


async def test_corrective_type(client, seed_data):
    token = await get_token(client, "ortiz@test.com")
    resp = await client.post(
        "/api/maintenance",
        json=valid_payload(seed_data, maintenance_type="CORRECTIVE"),
        headers=auth_headers(token),
    )
    assert resp.status_code == 201
    assert resp.json()["maintenance_type"] == "CORRECTIVE"


async def test_audit_log_created(client, seed_data):
    token = await get_token(client, "ortiz@test.com")
    resp = await client.post(
        "/api/maintenance",
        json=valid_payload(seed_data),
        headers=auth_headers(token),
    )
    rec_id = resp.json()["id"]

    # Supervisor reads audit and finds CREATE for this record
    token2 = await get_token(client, "supervisor@test.com")
    audit = await client.get(
        f"/api/audit?entity_type=MaintenanceRecord&entity_id={rec_id}",
        headers=auth_headers(token2),
    )
    assert audit.status_code == 200
    logs = audit.json()
    assert any(l["action"] == "CREATE" for l in logs)
    assert any(l["entity_type"] == "MaintenanceRecord" for l in logs)


async def test_worker_edit_forbidden(client, seed_data):
    token = await get_token(client, "ortiz@test.com")
    resp = await client.post(
        "/api/maintenance",
        json=valid_payload(seed_data),
        headers=auth_headers(token),
    )
    rec_id = resp.json()["id"]
    update = await client.patch(
        f"/api/maintenance/{rec_id}",
        json={"description": "editado"},
        headers=auth_headers(token),
    )
    assert update.status_code == 403


async def test_supervisor_can_edit(client, seed_data):
    token = await get_token(client, "ortiz@test.com")
    resp = await client.post(
        "/api/maintenance",
        json=valid_payload(seed_data),
        headers=auth_headers(token),
    )
    rec_id = resp.json()["id"]

    token2 = await get_token(client, "supervisor@test.com")
    update = await client.patch(
        f"/api/maintenance/{rec_id}",
        json={"description": "Editado por supervisor"},
        headers=auth_headers(token2),
    )
    assert update.status_code == 200
    assert update.json()["description"] == "Editado por supervisor"
