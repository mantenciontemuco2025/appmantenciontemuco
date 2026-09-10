"""Work Order CRUD tests (Google Drive mocked)."""

from tests.conftest import get_token, auth_headers


async def test_create_work_order(client, seed_data, monkeypatch):
    """Create a Work Order — Google Drive is mocked, so OT file creation is skipped."""
    # Mock Google Drive so no real calls are made
    def mock_create_ot(*args, **kwargs):
        raise RuntimeError("Google Drive not configured in tests")

    monkeypatch.setattr(
        "app.api.routes.work_orders.drive_service.create_ot_file", mock_create_ot
    )

    # Admin creates with emit=True (PENDING, like old behavior)
    token = await get_token(client, "admin@test.com")
    resp = await client.post(
        "/api/work-orders",
        json={
            "title": "Mantenimiento preventivo Horno 1",
            "area_id": seed_data["area"].id,
            "equipment_id": seed_data["equipment"].id,
            "section_name": "Sección norte",
            "maintenance_type": "PREVENTIVE",
            "loto_status": "NOT_APPLICABLE",
            "description": "Revisión general del horno",
            "execution_date": "2026-09-15",
            "request_date": "2026-09-04",
            "requested_by": "Supervisor",
            "responsible_user_id": seed_data["worker"].id,
            "participant_user_ids": [seed_data["worker"].id, seed_data["worker_jara"].id],
            "participant_names": ["Ortiz", "Jara"],
            "emit": True,
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["ot_number"].startswith("OT-2026-")
    assert data["title"] == "Mantenimiento preventivo Horno 1"
    assert data["section_name"] == "Sección norte"
    assert data["maintenance_type"] == "PREVENTIVE"
    assert data["loto_status"] == "NOT_APPLICABLE"
    assert data["status"] == "PENDING"
    # Google sync now runs in the BACKGROUND: the immediate response reports
    # PENDING (async) and the mocked failure flips it to FAILED on the row.
    assert data["ot_sheet_sync_status"] == "PENDING"

    # With httpx ASGITransport the background task completes before the client
    # call returns, so a follow-up read already sees the mocked FAILED state.
    get_resp = await client.get("/api/work-orders", headers=auth_headers(token))
    assert get_resp.status_code == 200
    latest = next(
        o for o in get_resp.json()
        if o["id"] == data["id"]
    )
    assert latest["ot_sheet_sync_status"] == "FAILED"


async def test_list_work_orders(client, seed_data, monkeypatch):
    """List Work Orders — admin sees all."""
    monkeypatch.setattr(
        "app.api.routes.work_orders.drive_service.create_ot_file",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("mocked")),
    )

    # Admin creates (can_create requires ADMIN or SUPERVISOR)
    admin_token = await get_token(client, "admin@test.com")
    await client.post(
        "/api/work-orders",
        json={
            "title": "OT test list",
            "area_id": seed_data["area"].id,
            "maintenance_type": "CORRECTIVE",
        },
        headers=auth_headers(admin_token),
    )

    resp = await client.get("/api/work-orders", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    orders = resp.json()
    assert len(orders) >= 1
    assert orders[0]["ot_number"].startswith("OT-")


async def test_update_work_order(client, seed_data, monkeypatch):
    """Supervisor can update a Work Order."""
    monkeypatch.setattr(
        "app.api.routes.work_orders.drive_service.create_ot_file",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("mocked")),
    )

    # Create as admin (can_create requires ADMIN or SUPERVISOR)
    token = await get_token(client, "admin@test.com")
    create_resp = await client.post(
        "/api/work-orders",
        json={
            "title": "OT to update",
            "area_id": seed_data["area"].id,
            "maintenance_type": "PREVENTIVE",
        },
        headers=auth_headers(token),
    )
    wo_id = create_resp.json()["id"]

    # Update as supervisor (title only — status changes go through /issue, /start, etc.)
    token2 = await get_token(client, "supervisor@test.com")
    resp = await client.patch(
        f"/api/work-orders/{wo_id}",
        json={"title": "OT updated"},
        headers=auth_headers(token2),
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "OT updated"


async def test_admin_update_repopulates_ot_document(
    client, seed_data, monkeypatch
):
    """Admin edits to OT fields (e.g. fecha solicitud) re-populate the Google OT doc."""
    calls = []

    def _fake_create(*a, **k):
        return {"file_id": "fake-ot-id", "url": "http://fake"}

    def _noop(*a, **k):
        return None

    def _record_populate(*a, **k):
        calls.append(k)

    monkeypatch.setattr(
        "app.api.routes.work_orders.drive_service.create_ot_file", _fake_create
    )
    monkeypatch.setattr(
        "app.api.routes.work_orders.drive_service.populate_ot_fields",
        _record_populate,
    )
    monkeypatch.setattr(
        "app.api.routes.work_orders.drive_service.sync_to_monthly_sheet", _noop
    )
    monkeypatch.setattr(
        "app.api.routes.work_orders.drive_service.update_ot_status", _noop
    )

    token = await get_token(client, "admin@test.com")
    create_resp = await client.post(
        "/api/work-orders",
        json={
            "title": "OT repopulate test",
            "area_id": seed_data["area"].id,
            "equipment_id": seed_data["equipment"].id,
            "maintenance_type": "PREVENTIVE",
            "description": "trabajo",
            "request_date": "2026-09-01",
            "responsible_user_id": seed_data["worker"].id,
            "participant_user_ids": [seed_data["worker"].id],
            "emit": True,
        },
        headers=auth_headers(token),
    )
    assert create_resp.status_code == 201
    wo_id = create_resp.json()["id"]

    # Issue flow calls populate once (with the original request_date via _sync_ot_and_monthly)
    assert any(
        c.get("request_date") == "2026-09-01" for c in calls
    ), "issue populate should carry the initial request_date"

    # Admin edits the fecha de solicitud (and description) on the emitted OT
    calls.clear()
    resp = await client.patch(
        f"/api/work-orders/{wo_id}",
        json={"request_date": "2026-09-03", "description": "descripción editada"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    assert resp.json()["request_date"] == "2026-09-03"
    assert resp.json()["description"] == "descripción editada"

    # The OT document was re-populated with the NEW request_date
    assert calls, "admin edit should re-populate the OT document"
    last = calls[-1]
    assert last["request_date"] == "2026-09-03"
    assert last["description"] == "descripción editada"


async def test_worker_cannot_update_work_order(client, seed_data, monkeypatch):
    """Worker cannot update someone else's Work Order."""
    monkeypatch.setattr(
        "app.api.routes.work_orders.drive_service.create_ot_file",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("mocked")),
    )

    # Create as admin (can_create requires ADMIN or SUPERVISOR)
    token = await get_token(client, "admin@test.com")
    create_resp = await client.post(
        "/api/work-orders",
        json={
            "title": "OT worker cannot edit others",
            "area_id": seed_data["area"].id,
            "maintenance_type": "PREVENTIVE",
        },
        headers=auth_headers(token),
    )
    wo_id = create_resp.json()["id"]

    # Valdés (different worker) tries to update
    token2 = await get_token(client, "valdes@test.com")
    resp = await client.patch(
        f"/api/work-orders/{wo_id}",
        json={"title": "hacked"},
        headers=auth_headers(token2),
    )
    assert resp.status_code == 403


async def test_invalid_maintenance_type(client, seed_data, monkeypatch):
    """Invalid maintenance_type is rejected."""
    monkeypatch.setattr(
        "app.api.routes.work_orders.drive_service.create_ot_file",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("mocked")),
    )

    # Admin creates (can_create requires ADMIN or SUPERVISOR)
    token = await get_token(client, "admin@test.com")
    resp = await client.post(
        "/api/work-orders",
        json={
            "title": "OT bad type",
            "area_id": seed_data["area"].id,
            "maintenance_type": "INVALID_TYPE",
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 422


async def test_invalid_area_rejected(client, seed_data, monkeypatch):
    """Non-existent area -> 400."""
    monkeypatch.setattr(
        "app.api.routes.work_orders.drive_service.create_ot_file",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("mocked")),
    )

    # Admin creates (can_create requires ADMIN or SUPERVISOR)
    token = await get_token(client, "admin@test.com")
    resp = await client.post(
        "/api/work-orders",
        json={
            "title": "OT bad area",
            "area_id": 9999,
            "maintenance_type": "PREVENTIVE",
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 400


async def test_sync_google_creates_ot_and_marks_synced(
    client, seed_data, monkeypatch
):
    """POST /{wo_id}/sync-google re-runs the full Google sync (doc + monthly)."""
    created = {"called": 0}

    def _fake_create(*a, **k):
        created["called"] += 1
        return {"file_id": "ot-retry-1", "url": "http://fake/retry"}

    monkeypatch.setattr(
        "app.api.routes.work_orders.drive_service.create_ot_file", _fake_create
    )
    monkeypatch.setattr(
        "app.api.routes.work_orders.drive_service.populate_ot_fields",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "app.api.routes.work_orders.drive_service.sync_to_monthly_sheet",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "app.api.routes.work_orders.drive_service.update_ot_status",
        lambda *a, **k: None,
    )

    token = await get_token(client, "admin@test.com")
    create_resp = await client.post(
        "/api/work-orders",
        json={
            "title": "OT retry test",
            "area_id": seed_data["area"].id,
            "equipment_id": seed_data["equipment"].id,
            "maintenance_type": "PREVENTIVE",
            "description": "trabajo",
            "responsible_user_id": seed_data["worker"].id,
            "participant_user_ids": [seed_data["worker"].id],
            "emit": True,
        },
        headers=auth_headers(token),
    )
    assert create_resp.status_code == 201
    wo_id = create_resp.json()["id"]
    assert create_resp.json()["ot_sheet_sync_status"] == "PENDING"

    # Background sync completes before the client call returns (ASGITransport),
    # so a follow-up read already shows SYNCED with the doc id.
    get_resp = await client.get(
        f"/api/work-orders/{wo_id}", headers=auth_headers(token)
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["ot_sheet_sync_status"] == "SYNCED"
    assert get_resp.json()["google_ot_file_id"] == "ot-retry-1"

    # Retry: reuses the existing doc (idempotent), does NOT create a 2nd file.
    created["called"] = 0
    retry = await client.post(
        f"/api/work-orders/{wo_id}/sync-google",
        headers=auth_headers(token),
    )
    assert retry.status_code == 200
    assert retry.json()["google_ot_file_id"] == "ot-retry-1"
    assert retry.json()["ot_sheet_sync_status"] == "SYNCED"
    assert created["called"] == 0, \
        "retry must reuse the existing doc, not create a duplicate"
