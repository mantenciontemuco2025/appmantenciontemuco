"""Verify a Google Sheets outage does not lose the local maintenance record."""

from tests.conftest import get_token, auth_headers


async def test_google_failure_keeps_record(client, seed_data, monkeypatch):
    # Simulate Google Sheets being down (sync call, as the router invokes it)
    def boom(*args, **kwargs):
        raise RuntimeError("Google Sheets API timeout")

    monkeypatch.setattr(
        "app.api.routes.maintenance.sheets_service.append_row_to_sheet", boom
    )

    token = await get_token(client, "ortiz@test.com")
    resp = await client.post(
        "/api/maintenance",
        json={
            "date": "2026-09-01",
            "area_id": seed_data["area"].id,
            "section_name": "Germinación",
            "equipment_id": seed_data["equipment"].id,
            "description": "Mantención con Google caído",
            "maintenance_type": "PREVENTIVE",
            "start_time": "09:00",
            "end_time": "10:00",
            "participant_ids": [seed_data["worker"].id],
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 201
    data = resp.json()
    # Record was created locally even though Google failed
    assert data["sheet_sync_status"] == "FAILED"
    assert "Google Sheets API timeout" in data["sheet_sync_error"]

    # The record is still retrievable
    rec_id = data["id"]
    token2 = await get_token(client, "supervisor@test.com")
    fetch = await client.get(
        f"/api/maintenance/{rec_id}", headers=auth_headers(token2)
    )
    assert fetch.status_code == 200
    assert fetch.json()["description"] == "Mantención con Google caído"
