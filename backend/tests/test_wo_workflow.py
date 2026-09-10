"""API-level integration tests for the full Work Order lifecycle.

Covers: create (DRAFT/emit), issue, start, complete, return, approve, cancel,
the /my worker view, and monthly-sync behavior across transitions.
"""

import pytest

from sqlalchemy import insert, select, update

from tests.conftest import get_token, auth_headers
from app.models.supervisor_area import supervisor_areas
from app.models.user import User


async def _mock_google(client, monkeypatch, create_ok=True):
    """Mock Google Drive services so tests never hit real Google."""
    def _noop(*a, **k):
        return None
    if create_ok:
        def _mocker(*a, **k):
            return {"file_id": "fake", "url": "http://fake"}
    else:
        def _mocker(*a, **k):
            raise RuntimeError("mock")
    monkeypatch.setattr(
        "app.api.routes.work_orders.drive_service.create_ot_file", _mocker
    )
    monkeypatch.setattr(
        "app.api.routes.work_orders.drive_service.populate_ot_fields", _noop
    )
    monkeypatch.setattr(
        "app.api.routes.work_orders.drive_service.sync_to_monthly_sheet", _noop
    )
    monkeypatch.setattr(
        "app.api.routes.work_orders.drive_service.update_ot_status", _noop
    )


async def _create_ot(
    client, seed_data, monkeypatch, *, token, emit=True,
    responsible_user_id=None, participant_user_ids=None, extra=None,
):
    await _mock_google(client, monkeypatch)
    body = {
        "title": "OT workflow test",
        "area_id": seed_data["area"].id,
        "equipment_id": seed_data["equipment"].id,
        "maintenance_type": "PREVENTIVE",
        "description": "Trabajo de prueba",
        "execution_date": "2026-09-15",
        "request_date": "2026-09-04",
        "emit": emit,
    }
    if responsible_user_id:
        body["responsible_user_id"] = responsible_user_id
    if participant_user_ids:
        body["participant_user_ids"] = participant_user_ids
    if extra:
        body.update(extra)
    resp = await client.post("/api/work-orders", json=body, headers=auth_headers(token))
    return resp


# ── Creation ────────────────────────────────────────────────────────────────

async def test_create_draft_by_default(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    resp = await _create_ot(client, seed_data, monkeypatch, token=admin, emit=False)
    assert resp.status_code == 201
    assert resp.json()["status"] == "DRAFT"
    # DRAFT should not reach monthly sheet
    assert resp.json()["ot_sheet_sync_status"] == "PENDING"


async def test_emit_param_creates_pending(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    resp = await _create_ot(
        client, seed_data, monkeypatch, token=admin, emit=True,
        responsible_user_id=seed_data["worker"].id,
        participant_user_ids=[seed_data["worker"].id],
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "PENDING"
    assert resp.json()["responsible_user_name"] == "Ortiz"


async def test_emit_requires_creator_signature(client, seed_data, monkeypatch):
    supervisor = await get_token(client, "supervisor@test.com")
    resp = await _create_ot(
        client, seed_data, monkeypatch, token=supervisor, emit=True,
        responsible_user_id=seed_data["worker"].id,
        participant_user_ids=[seed_data["worker"].id],
    )
    assert resp.status_code == 400
    assert "Firma manuscrita" in resp.json()["detail"]


async def test_supervisor_signature_survives_admin_acceptance(
    client, seed_data, db_session_factory, monkeypatch
):
    """Admin acceptance must not replace the supervisor's request signature."""
    async with db_session_factory() as db:
        await db.execute(
            update(User)
            .where(User.id == seed_data["supervisor"].id)
            .values(signature="https://drive.google.com/uc?export=view&id=supervisor-signature")
        )
        await db.execute(
            insert(supervisor_areas).values(
                supervisor_id=seed_data["supervisor"].id,
                area_id=seed_data["area"].id,
            )
        )
        await db.commit()

    supervisor = await get_token(client, "supervisor@test.com")
    submitted = await _create_ot(
        client, seed_data, monkeypatch, token=supervisor, emit=True
    )
    assert submitted.status_code == 201
    assert submitted.json()["submitted_for_review"] is True
    assert submitted.json()["requested_by"] == "Supervisor"
    assert submitted.json()["requested_signature"].endswith("supervisor-signature")

    admin = await get_token(client, "admin@test.com")
    wo_id = submitted.json()["id"]
    reassigned = await client.post(
        f"/api/work-orders/{wo_id}/reassign",
        json={
            "responsible_user_id": seed_data["worker"].id,
            "participant_user_ids": [seed_data["worker"].id],
        },
        headers=auth_headers(admin),
    )
    assert reassigned.status_code == 200

    accepted = await client.post(
        f"/api/work-orders/{wo_id}/issue", headers=auth_headers(admin)
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "PENDING"
    assert accepted.json()["requested_by"] == "Supervisor"
    assert accepted.json()["requested_signature"].endswith("supervisor-signature")


async def test_worker_cannot_create(client, seed_data, monkeypatch):
    worker = await get_token(client, "ortiz@test.com")
    resp = await _create_ot(client, seed_data, monkeypatch, token=worker)
    assert resp.status_code == 403


# ── Fulfill (responsible completes remaining details) ───────────────────────

async def test_responsible_can_fulfill_details(client, seed_data, monkeypatch):
    """Admin sets base fields + participants; responsible fills execution details."""
    admin = await get_token(client, "admin@test.com")
    # Admin creates with responsible + participants + request date.
    resp = await _create_ot(
        client, seed_data, monkeypatch, token=admin, emit=False,
        responsible_user_id=seed_data["worker"].id,
        participant_user_ids=[seed_data["worker"].id, seed_data["valdes"].id],
    )
    assert resp.status_code == 201
    assert resp.json()["request_date"] == "2026-09-04"
    wo_id = resp.json()["id"]

    worker = await get_token(client, "ortiz@test.com")
    fulfill = await client.patch(
        f"/api/work-orders/{wo_id}/fulfill",
        json={
            "maintenance_type": "CORRECTIVE",
            "loto_status": "YES",
            "execution_date": "2026-09-15",
            "section_name": "Sala de bombas",
            "estimated_time": "1 h 30 min",
            "resources_required": "Sello SKF, llave 24mm",
            "risks": "Desenergizar",
            "observations": "Cambio de sello",
        },
        headers=auth_headers(worker),
    )
    assert fulfill.status_code == 200, fulfill.text
    data = fulfill.json()
    assert data["maintenance_type"] == "CORRECTIVE"
    assert data["loto_status"] == "YES"
    assert data["execution_date"] == "2026-09-15"
    assert data["section_name"] == "Sala de bombas"
    assert data["estimated_time"] == "1 h 30 min"
    assert data["resources_required"] == "Sello SKF, llave 24mm"
    # Participants were chosen by the ADMIN and remain unchanged by the worker
    assert seed_data["worker"].id in data["participant_user_ids"]
    assert seed_data["valdes"].id in data["participant_user_ids"]


async def test_other_worker_cannot_fulfill(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    resp = await _create_ot(
        client, seed_data, monkeypatch, token=admin, emit=False,
        responsible_user_id=seed_data["worker"].id,
    )
    assert resp.status_code == 201
    wo_id = resp.json()["id"]

    other = await get_token(client, "valdes@test.com")
    fulfill = await client.patch(
        f"/api/work-orders/{wo_id}/fulfill",
        json={"maintenance_type": "CORRECTIVE"},
        headers=auth_headers(other),
    )
    # Other worker is not the responsible → 403
    assert fulfill.status_code == 403


# ── Issue (DRAFT → PENDING) ────────────────────────────────────────────────

async def test_issue_validates_required_fields(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    # Create DRAFT with no responsible / participants. Both are required at issue.
    resp = await _create_ot(client, seed_data, monkeypatch, token=admin, emit=False)
    assert resp.status_code == 201
    wo_id = resp.json()["id"]

    issue = await client.post(f"/api/work-orders/{wo_id}/issue", headers=auth_headers(admin))
    assert issue.status_code == 400
    detail = issue.json()["detail"]
    assert "Responsable" in detail
    # Participants ARE required at issue time again (admin chooses who enters the OT)
    assert "participante" in detail.lower()


async def test_issue_transitions_to_pending(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    responsible = seed_data["worker"].id
    resp = await _create_ot(
        client, seed_data, monkeypatch, token=admin, emit=False,
        responsible_user_id=responsible,
        participant_user_ids=[responsible],
        extra={"estimated_time": "2 h 30 min"},
    )
    wo_id = resp.json()["id"]
    assert resp.json()["status"] == "DRAFT"

    issue = await client.post(f"/api/work-orders/{wo_id}/issue", headers=auth_headers(admin))
    assert issue.status_code == 200
    assert issue.json()["status"] == "PENDING"
    # Emitting responds instantly (Google sync runs in the background), so the
    # sync statuses start PENDING and the document is created asynchronously.
    assert issue.json()["ot_sheet_sync_status"] == "PENDING"
    assert issue.json()["monthly_sheet_sync_status"] == "PENDING"


async def test_issue_from_pending_rejected(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    responsible = seed_data["worker"].id
    resp = await _create_ot(
        client, seed_data, monkeypatch, token=admin, emit=True,
        responsible_user_id=responsible,
        participant_user_ids=[responsible],
    )
    wo_id = resp.json()["id"]
    issue = await client.post(f"/api/work-orders/{wo_id}/issue", headers=auth_headers(admin))
    assert issue.status_code == 400


# ── Start / Complete ────────────────────────────────────────────────────────

async def _to_pending(client, seed_data, monkeypatch, admin):
    responsible = seed_data["worker"].id
    resp = await _create_ot(
        client, seed_data, monkeypatch, token=admin, emit=False,
        responsible_user_id=responsible,
        participant_user_ids=[responsible],
        extra={"estimated_time": "1 h"},
    )
    wo_id = resp.json()["id"]
    await client.post(f"/api/work-orders/{wo_id}/issue", headers=auth_headers(admin))
    return wo_id


async def test_responsible_can_start(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    wo_id = await _to_pending(client, seed_data, monkeypatch, admin)

    worker = await get_token(client, "ortiz@test.com")
    resp = await client.post(f"/api/work-orders/{wo_id}/start", headers=auth_headers(worker))
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "IN_PROGRESS"
    assert data["started_at"] is not None
    assert data["started_by_user_id"] == seed_data["worker"].id


async def test_other_worker_cannot_start(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    wo_id = await _to_pending(client, seed_data, monkeypatch, admin)

    other = await get_token(client, "valdes@test.com")
    resp = await client.post(f"/api/work-orders/{wo_id}/start", headers=auth_headers(other))
    assert resp.status_code == 403


async def test_complete_sets_actual_duration(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    wo_id = await _to_pending(client, seed_data, monkeypatch, admin)

    worker = await get_token(client, "ortiz@test.com")
    await client.post(f"/api/work-orders/{wo_id}/start", headers=auth_headers(worker))
    resp = await client.patch(
        f"/api/work-orders/{wo_id}/complete",
        json={"completion_notes": "Listo"},
        headers=auth_headers(worker),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "COMPLETED"
    assert data["completed_at"] is not None
    assert data["completion_notes"] == "Listo"
    assert isinstance(data["actual_duration_minutes"], float)
    assert data["approved_by"] == "Ortiz"
    assert data["approved_signature"] == seed_data["worker"].signature


async def test_complete_requires_in_progress(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    wo_id = await _to_pending(client, seed_data, monkeypatch, admin)

    worker = await get_token(client, "ortiz@test.com")
    # Try to complete before starting
    resp = await client.patch(
        f"/api/work-orders/{wo_id}/complete", json={}, headers=auth_headers(worker)
    )
    assert resp.status_code == 400


# ── Return ──────────────────────────────────────────────────────────────────

async def _to_completed(client, seed_data, monkeypatch, admin):
    wo_id = await _to_pending(client, seed_data, monkeypatch, admin)
    worker = await get_token(client, "ortiz@test.com")
    await client.post(f"/api/work-orders/{wo_id}/start", headers=auth_headers(worker))
    await client.patch(f"/api/work-orders/{wo_id}/complete", json={}, headers=auth_headers(worker))
    return wo_id


async def test_return_sends_back_to_worker(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    wo_id = await _to_completed(client, seed_data, monkeypatch, admin)

    resp = await client.post(
        f"/api/work-orders/{wo_id}/return",
        json={"return_reason": "Mal realizado"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "IN_PROGRESS"
    assert data["return_reason"] == "Mal realizado"
    # Completion snapshot cleared (event preserved in audit log)
    assert data["completed_at"] is None
    assert data["actual_duration_minutes"] is None


async def test_worker_cannot_return(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    wo_id = await _to_completed(client, seed_data, monkeypatch, admin)

    worker = await get_token(client, "ortiz@test.com")
    resp = await client.post(
        f"/api/work-orders/{wo_id}/return",
        json={"return_reason": "no"},
        headers=auth_headers(worker),
    )
    assert resp.status_code == 403


# ── Approve ─────────────────────────────────────────────────────────────────

async def test_approve_with_signature(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    wo_id = await _to_completed(client, seed_data, monkeypatch, admin)

    resp = await client.post(
        f"/api/work-orders/{wo_id}/approve",
        json={"approved_signature": "Admin Firma"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "APPROVED"
    assert data["approved_at"] is not None
    assert data["approved_by_user_id"] == seed_data["admin"].id
    assert data["approved_by_user_name"] == "Admin"
    # Approval is attributed to the administrator, while REALIZADO POR keeps
    # the worker who actually completed the OT and their signature.
    assert data["approved_by"] == "Ortiz"
    assert data["approved_signature"] == seed_data["worker"].signature


async def test_worker_cannot_approve(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    wo_id = await _to_completed(client, seed_data, monkeypatch, admin)

    worker = await get_token(client, "ortiz@test.com")
    resp = await client.post(
        f"/api/work-orders/{wo_id}/approve", json={}, headers=auth_headers(worker)
    )
    assert resp.status_code == 403


async def test_approved_ot_is_readonly(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    wo_id = await _to_completed(client, seed_data, monkeypatch, admin)
    await client.post(f"/api/work-orders/{wo_id}/approve", json={}, headers=auth_headers(admin))

    resp = await client.patch(
        f"/api/work-orders/{wo_id}", json={"title": "hack"}, headers=auth_headers(admin)
    )
    assert resp.status_code == 403


# ── Cancel ──────────────────────────────────────────────────────────────────

async def test_cancel_requires_reason(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    wo_id = await _to_pending(client, seed_data, monkeypatch, admin)

    resp = await client.post(f"/api/work-orders/{wo_id}/cancel", json={}, headers=auth_headers(admin))
    assert resp.status_code == 422  # cancellation_reason required


async def test_cancel_transitions(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    wo_id = await _to_pending(client, seed_data, monkeypatch, admin)

    resp = await client.post(
        f"/api/work-orders/{wo_id}/cancel",
        json={"cancellation_reason": "Ya no necesario"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "CANCELLED"
    assert resp.json()["cancellation_reason"] == "Ya no necesario"


# ── /my worker view ─────────────────────────────────────────────────────────

async def test_my_orders_shows_assigned(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    wo_id = await _to_pending(client, seed_data, monkeypatch, admin)

    worker = await get_token(client, "ortiz@test.com")
    resp = await client.get("/api/work-orders/my", headers=auth_headers(worker))
    assert resp.status_code == 200
    ids = [o["id"] for o in resp.json()]
    assert wo_id in ids


async def test_my_orders_excludes_unassigned(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    await _to_pending(client, seed_data, monkeypatch, admin)

    # Valdés is not responsible for this OT
    other = await get_token(client, "valdes@test.com")
    resp = await client.get("/api/work-orders/my", headers=auth_headers(other))
    assert resp.json() == []


async def test_my_orders_filters_by_status(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    await _to_pending(client, seed_data, monkeypatch, admin)

    worker = await get_token(client, "ortiz@test.com")
    resp = await client.get(
        "/api/work-orders/my?status=IN_PROGRESS", headers=auth_headers(worker)
    )
    assert resp.json() == []


# ── Monthly sync across statuses ────────────────────────────────────────────

async def test_completed_syncs_monthly_horas(client, seed_data, monkeypatch):
    """HORAS uses actual_duration_minutes when available on COMPLETED."""
    from app.services.monthly_mapping import compute_horas, HorasInput
    # Unit-level: the rule is tested in isolation (the API-level monthly sync
    # is mocked out in these tests).
    horas = compute_horas(
        HorasInput(
            estimated_minutes=120,   # estimated 2h
            status="COMPLETED",
            actual_duration_minutes=90.0,  # real 1.5h
        )
    )
    assert horas == 1.5


async def test_approved_status_maps_aprobada(client, seed_data, monkeypatch):
    from app.services.monthly_mapping import monthly_status_text
    assert monthly_status_text("APPROVED") == "APROBADA"


# ── Reopen (admin reopens a closed OT) ──────────────────────────────────────

async def test_reopen_approved_returns_to_in_progress(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    wo_id = await _to_completed(client, seed_data, monkeypatch, admin)
    await client.post(f"/api/work-orders/{wo_id}/approve", json={}, headers=auth_headers(admin))

    resp = await client.post(
        f"/api/work-orders/{wo_id}/reopen",
        json={"reopen_reason": "Cliente pidió ajustes después de aprobar"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "IN_PROGRESS"
    assert data["return_reason"] == "Cliente pidió ajustes después de aprobar"
    assert data["returned_at"] is not None


async def test_reopen_cancelled_returns_to_draft(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    wo_id = await _to_pending(client, seed_data, monkeypatch, admin)
    await client.post(
        f"/api/work-orders/{wo_id}/cancel",
        json={"cancellation_reason": "Fue un error"},
        headers=auth_headers(admin),
    )

    resp = await client.post(
        f"/api/work-orders/{wo_id}/reopen",
        json={"reopen_reason": "Se reanuda el trabajo"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "DRAFT"


async def test_reopen_requires_reason(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    wo_id = await _to_pending(client, seed_data, monkeypatch, admin)
    await client.post(
        f"/api/work-orders/{wo_id}/cancel",
        json={"cancellation_reason": "x"},
        headers=auth_headers(admin),
    )
    resp = await client.post(f"/api/work-orders/{wo_id}/reopen", json={}, headers=auth_headers(admin))
    assert resp.status_code == 422  # reopen_reason required


async def test_worker_cannot_reopen(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    wo_id = await _to_pending(client, seed_data, monkeypatch, admin)
    await client.post(
        f"/api/work-orders/{wo_id}/cancel",
        json={"cancellation_reason": "x"},
        headers=auth_headers(admin),
    )
    worker = await get_token(client, "ortiz@test.com")
    resp = await client.post(
        f"/api/work-orders/{wo_id}/reopen",
        json={"reopen_reason": "nope"},
        headers=auth_headers(worker),
    )
    assert resp.status_code == 403


# ── Counter (admin-only) ────────────────────────────────────────────────────

async def test_counter_returns_counts(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    # Create one emitted OT (execution_date 2026-09-15) → counts
    await _create_ot(
        client, seed_data, monkeypatch, token=admin, emit=True,
        responsible_user_id=seed_data["worker"].id,
        participant_user_ids=[seed_data["worker"].id],
        extra={"execution_date": "2026-09-15"},
    )
    resp = await client.get("/api/work-orders/counter", headers=auth_headers(admin))
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_all"] >= 1
    assert data["current_year"] >= 2026
    # September (index 8) of the current year should have ≥1 (JSON keys are strings)
    assert data["per_month"].get("8", 0) >= 1
    assert data["next_ot_number"].startswith("OT-")


async def test_counter_admin_only(client, seed_data, monkeypatch):
    worker = await get_token(client, "ortiz@test.com")
    resp = await client.get("/api/work-orders/counter", headers=auth_headers(worker))
    assert resp.status_code == 403


# ── Batch issue (multiple DRAFT → PENDING at once) ──────────────────────────

async def test_batch_issue_admin_only(client, seed_data):
    supervisor = await get_token(client, "supervisor@test.com")
    resp = await client.post(
        "/api/work-orders/batch-issue", json={"ids": []}, headers=auth_headers(supervisor)
    )
    assert resp.status_code == 403


async def test_batch_issue_emits_multiple(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    ids = []
    for _ in range(2):
        resp = await _create_ot(
            client, seed_data, monkeypatch, token=admin, emit=False,
            responsible_user_id=seed_data["worker"].id,
            participant_user_ids=[seed_data["worker"].id],
        )
        ids.append(resp.json()["id"])

    resp = await client.post(
        "/api/work-orders/batch-issue", json={"ids": ids}, headers=auth_headers(admin)
    )
    assert resp.status_code == 200
    assert set(resp.json()["issued"]) == set(ids)
    assert resp.json()["failures"] == []

    # Both are now PENDING. (Sync status is set to SYNCED by the background task,
    # which runs synchronously under the ASGITransport test client.)
    for wo_id in ids:
        detail = await client.get(f"/api/work-orders/{wo_id}", headers=auth_headers(admin))
        assert detail.json()["status"] == "PENDING"


async def test_batch_issue_reports_failures(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    # One valid DRAFT and one missing id.
    resp = await _create_ot(
        client, seed_data, monkeypatch, token=admin, emit=False,
        responsible_user_id=seed_data["worker"].id,
        participant_user_ids=[seed_data["worker"].id],
    )
    valid_id = resp.json()["id"]

    resp = await client.post(
        "/api/work-orders/batch-issue",
        json={"ids": [valid_id, 999999]},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    assert resp.json()["issued"] == [valid_id]
    assert any(f["id"] == 999999 for f in resp.json()["failures"])


async def test_batch_issue_rejects_invalid_draft(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    # DRAFT without responsible/participants → fails validation.
    resp = await _create_ot(client, seed_data, monkeypatch, token=admin, emit=False)
    invalid_id = resp.json()["id"]

    resp = await client.post(
        "/api/work-orders/batch-issue", json={"ids": [invalid_id]}, headers=auth_headers(admin)
    )
    assert resp.status_code == 200
    assert resp.json()["issued"] == []
    assert any(f["id"] == invalid_id for f in resp.json()["failures"])


# ── Reassign responsibility ─────────────────────────────────────────────────

async def test_reassign_updates_responsible_and_participants(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    resp = await _create_ot(
        client, seed_data, monkeypatch, token=admin, emit=False,
        responsible_user_id=seed_data["worker"].id,
        participant_user_ids=[seed_data["worker"].id],
    )
    wo_id = resp.json()["id"]

    # Reassign to Valdés, keeping Ortiz as participant.
    reassign = await client.post(
        f"/api/work-orders/{wo_id}/reassign",
        json={
            "responsible_user_id": seed_data["valdes"].id,
            "participant_user_ids": [seed_data["valdes"].id, seed_data["worker"].id],
        },
        headers=auth_headers(admin),
    )
    assert reassign.status_code == 200, reassign.text
    data = reassign.json()
    assert data["responsible_user_id"] == seed_data["valdes"].id
    assert seed_data["valdes"].id in data["participant_user_ids"]
    assert seed_data["worker"].id in data["participant_user_ids"]


async def test_reassign_blocked_on_approved(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    wo_id = await _to_completed(client, seed_data, monkeypatch, admin)
    await client.post(f"/api/work-orders/{wo_id}/approve", json={}, headers=auth_headers(admin))

    resp = await client.post(
        f"/api/work-orders/{wo_id}/reassign",
        json={"responsible_user_id": seed_data["valdes"].id},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 403


async def test_worker_cannot_reassign(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    resp = await _create_ot(
        client, seed_data, monkeypatch, token=admin, emit=False,
        responsible_user_id=seed_data["worker"].id,
        participant_user_ids=[seed_data["worker"].id],
    )
    wo_id = resp.json()["id"]

    worker = await get_token(client, "ortiz@test.com")
    resp = await client.post(
        f"/api/work-orders/{wo_id}/reassign",
        json={"responsible_user_id": seed_data["valdes"].id},
        headers=auth_headers(worker),
    )
    assert resp.status_code == 403


# ── Overdue list filter ─────────────────────────────────────────────────────

async def test_overdue_list_filter(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    # OT with a past due date, PENDING → should appear as overdue.
    resp = await _create_ot(
        client, seed_data, monkeypatch, token=admin, emit=False,
        responsible_user_id=seed_data["worker"].id,
        participant_user_ids=[seed_data["worker"].id],
        extra={"due_date": "2020-01-01"},
    )
    overdue_id = resp.json()["id"]
    await client.post(f"/api/work-orders/{overdue_id}/issue", headers=auth_headers(admin))

    # OT with a future due date → should NOT appear.
    resp2 = await _create_ot(
        client, seed_data, monkeypatch, token=admin, emit=False,
        responsible_user_id=seed_data["worker"].id,
        participant_user_ids=[seed_data["worker"].id],
        extra={"due_date": "2099-12-31"},
    )
    future_id = resp2.json()["id"]
    await client.post(f"/api/work-orders/{future_id}/issue", headers=auth_headers(admin))

    resp = await client.get("/api/work-orders?overdue=true", headers=auth_headers(admin))
    assert resp.status_code == 200
    ids = [o["id"] for o in resp.json()]
    assert overdue_id in ids
    assert future_id not in ids


async def test_overdue_excludes_approved(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    # Build an OT through COMPLETED, keeping its overdue due date.
    resp = await _create_ot(
        client, seed_data, monkeypatch, token=admin, emit=False,
        responsible_user_id=seed_data["worker"].id,
        participant_user_ids=[seed_data["worker"].id],
        extra={"due_date": "2020-01-01"},
    )
    wo_id = resp.json()["id"]
    await client.post(f"/api/work-orders/{wo_id}/issue", headers=auth_headers(admin))
    worker = await get_token(client, "ortiz@test.com")
    await client.post(f"/api/work-orders/{wo_id}/start", headers=auth_headers(worker))
    await client.patch(f"/api/work-orders/{wo_id}/complete", json={}, headers=auth_headers(worker))
    await client.post(f"/api/work-orders/{wo_id}/approve", json={}, headers=auth_headers(admin))

    resp = await client.get("/api/work-orders?overdue=true", headers=auth_headers(admin))
    ids = [o["id"] for o in resp.json()]
    assert wo_id not in ids
