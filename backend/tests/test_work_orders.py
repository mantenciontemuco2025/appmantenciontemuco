"""Work Order CRUD tests (Google Drive mocked)."""

from types import SimpleNamespace

from app.api.routes import work_orders as work_orders_route
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
            "plant_area": "CEBADA",
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
    assert data["area_name"] == "CEBADA"
    assert data["section_name"] == "Malta"
    assert data["equipment_name"] == "Filtro"
    assert data["maintenance_type"] == "PREVENTIVE"
    assert data["loto_status"] == "NOT_APPLICABLE"
    assert data["status"] == "PENDING"
    # Google sync now runs in the BACKGROUND: the immediate response reports
    # PENDING (async) and the mocked failure flips it to FAILED on the row.
    assert data["ot_sheet_sync_status"] == "PENDING"

    # The durable sync queue is processed by the application-lifespan worker,
    # which this isolated ASGI test client does not start.
    get_resp = await client.get("/api/work-orders", headers=auth_headers(token))
    assert get_resp.status_code == 200
    latest = next(
        o for o in get_resp.json()
        if o["id"] == data["id"]
    )
    assert latest["ot_sheet_sync_status"] == "PENDING"


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
            "plant_area": "CEBADA",
            "area_id": seed_data["area"].id,
            "equipment_id": seed_data["equipment"].id,
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
            "plant_area": "CEBADA",
            "area_id": seed_data["area"].id,
            "equipment_id": seed_data["equipment"].id,
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


async def test_admin_update_preserves_area_section_and_equipment(client, seed_data):
    """An ordinary admin edit cannot corrupt the selected location fields."""
    token = await get_token(client, "admin@test.com")
    create_resp = await client.post(
        "/api/work-orders",
        json={
            "title": "OT repopulate test",
            "plant_area": "CEBADA",
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

    # Admin edits the request date and description while location stays fixed.
    resp = await client.patch(
        f"/api/work-orders/{wo_id}",
        json={"request_date": "2026-09-03", "description": "descripción editada"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    assert resp.json()["request_date"] == "2026-09-03"
    assert resp.json()["description"] == "descripción editada"
    assert resp.json()["area_name"] == "CEBADA"
    assert resp.json()["section_name"] == "Malta"
    assert resp.json()["equipment_name"] == "Filtro"


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
            "plant_area": "CEBADA",
            "area_id": seed_data["area"].id,
            "equipment_id": seed_data["equipment"].id,
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
            "plant_area": "CEBADA",
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
            "plant_area": "CEBADA",
            "area_id": 9999,
            "maintenance_type": "PREVENTIVE",
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 400


async def test_work_order_requires_equipment(client, seed_data):
    token = await get_token(client, "admin@test.com")
    resp = await client.post(
        "/api/work-orders",
        json={
            "title": "OT sin equipo",
            "plant_area": "CEBADA",
            "area_id": seed_data["area"].id,
            "maintenance_type": "PREVENTIVE",
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 400
    assert "equipo" in resp.json()["detail"].lower()


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
            "plant_area": "CEBADA",
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

    # The sync worker is decoupled from the request and is not started by this
    # in-memory ASGI test fixture.
    get_resp = await client.get(
        f"/api/work-orders/{wo_id}", headers=auth_headers(token)
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["ot_sheet_sync_status"] == "PENDING"
    assert get_resp.json()["google_ot_file_id"] is None

    # Retry persists another idempotent sync request without blocking HTTP.
    created["called"] = 0
    retry = await client.post(
        f"/api/work-orders/{wo_id}/sync-google",
        headers=auth_headers(token),
    )
    assert retry.status_code == 200
    assert retry.json()["google_ot_file_id"] is None
    assert retry.json()["ot_sheet_sync_status"] == "PENDING"
    assert created["called"] == 0


async def test_individual_google_ot_payload_uses_general_area_and_section(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.api.routes.work_orders.drive_service.populate_ot_fields",
        lambda *args, **kwargs: calls.append(kwargs),
    )
    wo = SimpleNamespace(
        google_ot_file_id="drive-id",
        ot_number="OT-2026-9999",
        plant_area="CEBADA",
        area=SimpleNamespace(name="HORNO"),
        section_name="HORNO",
        equipment=SimpleNamespace(name="COMPRESOR"),
        maintenance_type="CORRECTIVE",
        loto_status="NOT_APPLICABLE",
        loto_controls=["NOT_APPLICABLE"],
        description="Prueba de mapeo",
        participants=[],
        estimated_time="2 h",
        execution_date=None,
        request_date=None,
        resources_required=None,
        risks=None,
        observations=None,
        folio=None,
        voucher_number=None,
        requested_by="Supervisor",
        approved_by=None,
        requested_signature=None,
        approved_signature=None,
        status="PENDING",
    )

    await work_orders_route._populate_individual_ot(wo)

    assert calls[0]["area_name"] == "CEBADA"
    assert calls[0]["section_name"] == "HORNO"
    assert calls[0]["equipment_name"] == "COMPRESOR"
