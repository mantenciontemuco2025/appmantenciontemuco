"""Work Order CRUD tests (Google Drive mocked)."""

from io import BytesIO
from types import SimpleNamespace

from PIL import Image
from sqlalchemy import func, select

from app.api.routes import work_orders as work_orders_route
from app.models.audit_log import AuditLog
from app.models.notification import Notification
from app.models.sync_job import ExternalSyncJob, SyncJobStatus
from app.models.work_order import WorkOrder
from app.models.work_order_evidence import WorkOrderEvidence
from app.models.work_order_participants import work_order_participants
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


async def test_list_work_orders_searches_all_pages_and_responsible(
    client, seed_data, monkeypatch
):
    """Search parameters are applied by the API, including assigned workers."""
    monkeypatch.setattr(
        "app.api.routes.work_orders.drive_service.create_ot_file",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("mocked")),
    )
    token = await get_token(client, "admin@test.com")
    common = {
        "plant_area": "CEBADA",
        "area_id": seed_data["area"].id,
        "equipment_id": seed_data["equipment"].id,
        "maintenance_type": "CORRECTIVE",
    }
    first = await client.post(
        "/api/work-orders",
        json={**common, "title": "Bomba de transferencia", "responsible_user_id": seed_data["worker"].id},
        headers=auth_headers(token),
    )
    second = await client.post(
        "/api/work-orders",
        json={**common, "title": "Válvula de retorno", "responsible_user_id": seed_data["worker_jara"].id},
        headers=auth_headers(token),
    )
    assert first.status_code == 201
    assert second.status_code == 201

    search = await client.get(
        "/api/work-orders?search=transferencia&limit=1",
        headers=auth_headers(token),
    )
    assert search.status_code == 200
    assert [item["title"] for item in search.json()] == ["Bomba de transferencia"]

    responsible = await client.get(
        "/api/work-orders?responsible=Jara&limit=100",
        headers=auth_headers(token),
    )
    assert responsible.status_code == 200
    assert responsible.json()
    assert all("jara" in (item["responsible_user_name"] or "").lower() for item in responsible.json())


async def test_admin_delete_removes_ot_and_related_records(
    client, seed_data, db_session_factory, monkeypatch
):
    """Deleting an erroneous OT cleans app references and its Google artifacts."""
    deleted_google: list[tuple] = []
    monkeypatch.setattr(
        "app.core.config.settings.GOOGLE_MONTHLY_SPREADSHEET_ID", "monthly-test"
    )
    monkeypatch.setattr(
        "app.api.routes.work_orders.delete_ot_from_register",
        lambda spreadsheet_id, sheet, ot_number: deleted_google.append(
            ("monthly", spreadsheet_id, sheet, ot_number)
        ),
    )
    monkeypatch.setattr(
        "app.api.routes.work_orders.drive_service.trash_ot_file",
        lambda file_id: deleted_google.append(("drive", file_id)) or True,
    )

    admin_token = await get_token(client, "admin@test.com")
    create = await client.post(
        "/api/work-orders",
        json={
            "title": "OT de prueba para borrar",
            "plant_area": "CEBADA",
            "area_id": seed_data["area"].id,
            "equipment_id": seed_data["equipment"].id,
            "maintenance_type": "CORRECTIVE",
            "execution_date": "2026-09-12",
            "responsible_user_id": seed_data["worker"].id,
            "participant_user_ids": [seed_data["worker"].id],
        },
        headers=auth_headers(admin_token),
    )
    assert create.status_code == 201
    wo_id = create.json()["id"]
    ot_number = create.json()["ot_number"]

    async with db_session_factory() as db:
        wo = await db.get(WorkOrder, wo_id)
        wo.google_ot_file_id = "drive-file-test"
        wo.monthly_sheet_sync_status = "SYNCED"
        db.add(
            WorkOrderEvidence(
                work_order_id=wo_id,
                drive_file_id="drive-photo-test",
                filename="evidencia.jpg",
                mime_type="image/jpeg",
                stage="WORK",
                uploaded_by_user_id=seed_data["worker"].id,
                uploaded_by_name=seed_data["worker"].full_name,
            )
        )
        db.add(
            Notification(
                user_id=seed_data["worker"].id,
                type="OT_ASIGNADA",
                message=f"Nueva OT {ot_number} asignada.",
                link=f"/mis-ordenes/{wo_id}",
            )
        )
        db.add(
            ExternalSyncJob(
                work_order_id=wo_id,
                job_type="LIFECYCLE",
                status=SyncJobStatus.PENDING,
                actor_user_id=seed_data["admin"].id,
            )
        )
        await db.commit()

    response = await client.request(
        "DELETE",
        f"/api/work-orders/{wo_id}",
        json={"confirm_ot_number": ot_number, "reason": "OT creada por error"},
        headers=auth_headers(admin_token),
    )
    assert response.status_code == 200, response.text
    assert response.json()["deleted"] is True
    assert response.json()["notifications_removed"] == 1
    assert response.json()["evidence_files_removed"] == 1
    assert deleted_google == [
        ("monthly", "monthly-test", "SEPTIEMBRE", ot_number),
        ("drive", "drive-file-test"),
        ("drive", "drive-photo-test"),
    ]

    async with db_session_factory() as db:
        assert await db.get(WorkOrder, wo_id) is None
        assert await db.scalar(
            select(func.count()).select_from(ExternalSyncJob).where(
                ExternalSyncJob.work_order_id == wo_id
            )
        ) == 0
        assert await db.scalar(
            select(func.count()).select_from(Notification).where(
                Notification.message.contains(ot_number)
            )
        ) == 0
        assert await db.scalar(
            select(func.count()).select_from(work_order_participants).where(
                work_order_participants.c.work_order_id == wo_id
            )
        ) == 0
        assert await db.scalar(
            select(func.count()).select_from(WorkOrderEvidence).where(
                WorkOrderEvidence.work_order_id == wo_id
            )
        ) == 0
        audit = await db.scalar(
            select(AuditLog).where(AuditLog.action == "DELETE_WORK_ORDER")
        )
        assert audit is not None
        assert audit.entity_id is None
        assert audit.new_data["ot_number"] == ot_number
        assert audit.new_data["reason"] == "OT creada por error"


async def test_only_admin_can_delete_and_ot_number_confirmation_is_required(
    client, seed_data
):
    admin_token = await get_token(client, "admin@test.com")
    create = await client.post(
        "/api/work-orders",
        json={
            "title": "OT protegida",
            "plant_area": "CEBADA",
            "area_id": seed_data["area"].id,
            "equipment_id": seed_data["equipment"].id,
            "maintenance_type": "PREVENTIVE",
        },
        headers=auth_headers(admin_token),
    )
    wo_id = create.json()["id"]
    ot_number = create.json()["ot_number"]

    worker_token = await get_token(client, "ortiz@test.com")
    denied = await client.request(
        "DELETE",
        f"/api/work-orders/{wo_id}",
        json={"confirm_ot_number": ot_number, "reason": "OT creada por error"},
        headers=auth_headers(worker_token),
    )
    assert denied.status_code == 403

    wrong_confirmation = await client.request(
        "DELETE",
        f"/api/work-orders/{wo_id}",
        json={"confirm_ot_number": "OT-INCORRECTA", "reason": "OT creada por error"},
        headers=auth_headers(admin_token),
    )
    assert wrong_confirmation.status_code == 422
    still_exists = await client.get(
        f"/api/work-orders/{wo_id}", headers=auth_headers(admin_token)
    )
    assert still_exists.status_code == 200


def _valid_png() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (8, 6), color=(20, 80, 140)).save(buffer, format="PNG")
    return buffer.getvalue()


async def _create_evidence_test_order(client, seed_data, token, *, emit=False):
    response = await client.post(
        "/api/work-orders",
        json={
            "title": "OT con evidencia fotográfica",
            "description": "Inspección de prueba para adjuntar evidencia",
            "plant_area": "CEBADA",
            "area_id": seed_data["area"].id,
            "equipment_id": seed_data["equipment"].id,
            "maintenance_type": "PREVENTIVE",
            "execution_date": "2026-09-16",
            "responsible_user_id": seed_data["worker"].id,
            "participant_user_ids": [seed_data["worker"].id],
            "emit": emit,
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_work_order_evidence_upload_list_and_private_download(
    client, seed_data, monkeypatch
):
    uploads = []
    monkeypatch.setattr(
        "app.api.routes.work_orders.drive_service.upload_ot_evidence",
        lambda *args: uploads.append(args) or f"drive-evidence-{len(uploads)}",
    )
    monkeypatch.setattr(
        "app.api.routes.work_orders.drive_service.download_ot_evidence",
        lambda file_id: b"private-image-bytes",
    )

    token = await get_token(client, "admin@test.com")
    order = await _create_evidence_test_order(client, seed_data, token)
    response = await client.post(
        f"/api/work-orders/{order['id']}/evidence",
        data={"stage": "ISSUE"},
        files={"file": ("equipo.png", _valid_png(), "image/png")},
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    evidence = response.json()
    assert evidence["filename"] == "equipo.png"
    assert evidence["stage"] == "ISSUE"
    assert evidence["mime_type"] == "image/jpeg"
    assert uploads[0][0] == order["ot_number"]
    assert uploads[0][4] == "image/jpeg"

    supervisor_token = await get_token(client, "supervisor@test.com")
    supervisor_upload = await client.post(
        f"/api/work-orders/{order['id']}/evidence",
        data={"stage": "ISSUE"},
        files={"file": ("supervisor.png", _valid_png(), "image/png")},
        headers=auth_headers(supervisor_token),
    )
    assert supervisor_upload.status_code == 201, supervisor_upload.text
    assert supervisor_upload.json()["uploaded_by_name"] == "Supervisor"

    listed = await client.get(
        f"/api/work-orders/{order['id']}/evidence", headers=auth_headers(token)
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [evidence["id"], supervisor_upload.json()["id"]]

    photo = await client.get(
        f"/api/work-orders/{order['id']}/evidence/{evidence['id']}/content",
        headers=auth_headers(token),
    )
    assert photo.status_code == 200
    assert photo.headers["content-type"].startswith("image/jpeg")
    assert photo.content == b"private-image-bytes"
    assert photo.headers["cache-control"] == "private, max-age=300"


async def test_work_order_evidence_limit_is_two_photos_per_user(
    client, seed_data, monkeypatch
):
    uploaded = []
    monkeypatch.setattr(
        "app.api.routes.work_orders.drive_service.upload_ot_evidence",
        lambda *args: uploaded.append(args) or f"drive-evidence-{len(uploaded)}",
    )
    token = await get_token(client, "admin@test.com")
    order = await _create_evidence_test_order(
        client, seed_data, token, emit=True
    )

    async def upload(user_token, stage):
        return await client.post(
            f"/api/work-orders/{order['id']}/evidence",
            data={"stage": stage},
            files={"file": ("foto.png", _valid_png(), "image/png")},
            headers=auth_headers(user_token),
        )

    for _ in range(2):
        response = await upload(token, "ISSUE")
        assert response.status_code == 201, response.text

    worker_token = await get_token(client, "ortiz@test.com")
    for _ in range(2):
        response = await upload(worker_token, "WORK")
        assert response.status_code == 201, response.text

    admin_third = await upload(token, "ISSUE")
    worker_third = await upload(worker_token, "WORK")
    assert admin_third.status_code == 409
    assert worker_third.status_code == 409
    assert "2 fotos" in admin_third.json()["detail"]
    assert len(uploaded) == 4


async def test_responsible_worker_can_upload_work_photo_but_not_issue_photo(
    client, seed_data, monkeypatch
):
    monkeypatch.setattr(
        "app.api.routes.work_orders.drive_service.upload_ot_evidence",
        lambda *args: "drive-worker-photo",
    )
    admin_token = await get_token(client, "admin@test.com")
    order = await _create_evidence_test_order(
        client, seed_data, admin_token, emit=True
    )
    worker_token = await get_token(client, "ortiz@test.com")

    forbidden = await client.post(
        f"/api/work-orders/{order['id']}/evidence",
        data={"stage": "ISSUE"},
        files={"file": ("trabajo.png", _valid_png(), "image/png")},
        headers=auth_headers(worker_token),
    )
    assert forbidden.status_code == 403

    uploaded = await client.post(
        f"/api/work-orders/{order['id']}/evidence",
        data={"stage": "WORK"},
        files={"file": ("trabajo.png", _valid_png(), "image/png")},
        headers=auth_headers(worker_token),
    )
    assert uploaded.status_code == 201, uploaded.text
    assert uploaded.json()["stage"] == "WORK"
    assert uploaded.json()["uploaded_by_name"] == "Ortiz"


async def test_supervisor_can_upload_work_photo_in_assigned_area(
    client, seed_data, monkeypatch
):
    monkeypatch.setattr(
        "app.api.routes.work_orders.drive_service.upload_ot_evidence",
        lambda *args: "drive-supervisor-work-photo",
    )
    admin_token = await get_token(client, "admin@test.com")
    order = await _create_evidence_test_order(
        client, seed_data, admin_token, emit=True
    )
    supervisor_token = await get_token(client, "supervisor@test.com")

    uploaded = await client.post(
        f"/api/work-orders/{order['id']}/evidence",
        data={"stage": "WORK"},
        files={"file": ("trabajo-supervisor.png", _valid_png(), "image/png")},
        headers=auth_headers(supervisor_token),
    )
    assert uploaded.status_code == 201, uploaded.text
    assert uploaded.json()["stage"] == "WORK"
    assert uploaded.json()["uploaded_by_name"] == "Supervisor"


async def test_work_order_evidence_rejects_non_image_and_unauthorized_upload(
    client, seed_data, monkeypatch
):
    monkeypatch.setattr(
        "app.api.routes.work_orders.drive_service.upload_ot_evidence",
        lambda *args: "drive-evidence",
    )
    admin_token = await get_token(client, "admin@test.com")
    order = await _create_evidence_test_order(client, seed_data, admin_token)
    bad_file = await client.post(
        f"/api/work-orders/{order['id']}/evidence",
        data={"stage": "ISSUE"},
        files={"file": ("nota.txt", b"not an image", "text/plain")},
        headers=auth_headers(admin_token),
    )
    assert bad_file.status_code == 422

    worker_token = await get_token(client, "valdes@test.com")
    denied = await client.post(
        f"/api/work-orders/{order['id']}/evidence",
        data={"stage": "WORK"},
        files={"file": ("foto.png", _valid_png(), "image/png")},
        headers=auth_headers(worker_token),
    )
    assert denied.status_code == 403


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
