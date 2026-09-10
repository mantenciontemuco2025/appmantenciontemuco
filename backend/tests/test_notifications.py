"""API-level tests for in-app notifications.

Verifies the notifications model/endpoints (list, unread-count, mark read,
read-all) and that the Work Order lifecycle creates the expected notifications
for the right recipients.
"""

import pytest

from tests.conftest import get_token, auth_headers
from tests.test_wo_workflow import _mock_google, _create_ot, _to_pending, _to_completed


# ── Endpoints ───────────────────────────────────────────────────────────────

async def test_notifications_start_empty(client, seed_data):
    worker = await get_token(client, "ortiz@test.com")
    resp = await client.get("/api/notifications", headers=auth_headers(worker))
    assert resp.status_code == 200
    assert resp.json() == []

    count = await client.get("/api/notifications/unread-count", headers=auth_headers(worker))
    assert count.status_code == 200
    assert count.json() == {"count": 0}


async def test_issue_creates_notification_for_participants(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    responsible = seed_data["worker"].id
    resp = await _create_ot(
        client, seed_data, monkeypatch, token=admin, emit=False,
        responsible_user_id=responsible,
        participant_user_ids=[responsible, seed_data["valdes"].id],
    )
    wo_id = resp.json()["id"]
    await client.post(f"/api/work-orders/{wo_id}/issue", headers=auth_headers(admin))

    # The responsible (worker) should get an OT_ASIGNADA notification.
    worker = await get_token(client, "ortiz@test.com")
    resp = await client.get("/api/notifications", headers=auth_headers(worker))
    notifs = resp.json()
    assert any(n["type"] == "OT_ASIGNADA" and n["is_read"] is False for n in notifs)

    # And the participant (Valdés) too.
    participant = await get_token(client, "valdes@test.com")
    resp2 = await client.get("/api/notifications", headers=auth_headers(participant))
    assert any(n["type"] == "OT_ASIGNADA" for n in resp2.json())


async def test_direct_emit_creates_notification_for_participants(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    await _create_ot(
        client,
        seed_data,
        monkeypatch,
        token=admin,
        emit=True,
        responsible_user_id=seed_data["worker"].id,
        participant_user_ids=[seed_data["worker"].id, seed_data["valdes"].id],
    )

    worker = await get_token(client, "ortiz@test.com")
    notifications = (
        await client.get("/api/notifications", headers=auth_headers(worker))
    ).json()
    assert any(n["type"] == "OT_ASIGNADA" for n in notifications)


async def test_complete_notifies_creator(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    wo_id = await _to_completed(client, seed_data, monkeypatch, admin)

    # The creator (admin) is notified that the OT is complete & awaiting approval.
    notifs = (await client.get("/api/notifications", headers=auth_headers(admin))).json()
    assert any(n["type"] == "OT_COMPLETADA" for n in notifs)


async def test_complete_does_not_notify_unrelated_supervisor(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    wo_id = await _to_completed(client, seed_data, monkeypatch, admin)

    supervisor = await get_token(client, "supervisor@test.com")
    notifs = (
        await client.get("/api/notifications", headers=auth_headers(supervisor))
    ).json()
    assert not any(n["type"] == "OT_COMPLETADA" for n in notifs)


async def test_approve_notifies_responsible(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    wo_id = await _to_completed(client, seed_data, monkeypatch, admin)
    await client.post(f"/api/work-orders/{wo_id}/approve", json={}, headers=auth_headers(admin))

    worker = await get_token(client, "ortiz@test.com")
    notifs = (await client.get("/api/notifications", headers=auth_headers(worker))).json()
    assert any(n["type"] == "OT_APROBADA" for n in notifs)


async def test_return_notifies_responsible(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    wo_id = await _to_completed(client, seed_data, monkeypatch, admin)
    await client.post(
        f"/api/work-orders/{wo_id}/return",
        json={"return_reason": "Necesita ajustes"},
        headers=auth_headers(admin),
    )

    worker = await get_token(client, "ortiz@test.com")
    notifs = (await client.get("/api/notifications", headers=auth_headers(worker))).json()
    match = [n for n in notifs if n["type"] == "OT_DEVUELTA"]
    assert match and "ajustes" in match[-1]["message"]


async def test_mark_read_and_unread_count(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    responsible = seed_data["worker"].id
    resp = await _create_ot(
        client, seed_data, monkeypatch, token=admin, emit=False,
        responsible_user_id=responsible, participant_user_ids=[responsible],
    )
    wo_id = resp.json()["id"]
    await client.post(f"/api/work-orders/{wo_id}/issue", headers=auth_headers(admin))

    worker = await get_token(client, "ortiz@test.com")
    count0 = (await client.get("/api/notifications/unread-count", headers=auth_headers(worker))).json()["count"]
    assert count0 >= 1

    notifs = (await client.get("/api/notifications", headers=auth_headers(worker))).json()
    nid = next(n["id"] for n in notifs if n["type"] == "OT_ASIGNADA")
    marked = await client.post(f"/api/notifications/{nid}/read", headers=auth_headers(worker))
    assert marked.status_code == 200
    assert marked.json()["is_read"] is True

    count1 = (await client.get("/api/notifications/unread-count", headers=auth_headers(worker))).json()["count"]
    assert count1 == count0 - 1


async def test_mark_all_read_and_cannot_read_others(client, seed_data, monkeypatch):
    admin = await get_token(client, "admin@test.com")
    responsible = seed_data["worker"].id
    resp = await _create_ot(
        client, seed_data, monkeypatch, token=admin, emit=False,
        responsible_user_id=responsible, participant_user_ids=[responsible],
    )
    wo_id = resp.json()["id"]
    await client.post(f"/api/work-orders/{wo_id}/issue", headers=auth_headers(admin))

    worker = await get_token(client, "ortiz@test.com")
    notifs = (await client.get("/api/notifications", headers=auth_headers(worker))).json()
    some_id = notifs[0]["id"]
    await client.post("/api/notifications/read-all", headers=auth_headers(worker))
    count = (await client.get("/api/notifications/unread-count", headers=auth_headers(worker))).json()["count"]
    assert count == 0

    # A different user cannot read the worker's notification (404).
    other = await get_token(client, "valdes@test.com")
    resp_other = await client.post(f"/api/notifications/{some_id}/read", headers=auth_headers(other))
    assert resp_other.status_code == 404
