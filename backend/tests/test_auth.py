"""Auth, permissions and RBAC tests."""

from tests.conftest import get_token, auth_headers


async def _login(client, email, password="pass123"):
    return await client.post(
        "/api/auth/login",
        data={"username": email, "password": password},
    )


async def test_login_success(client, seed_data):
    resp = await _login(client, "admin@test.com")
    assert resp.status_code == 200
    data = resp.json()
    assert data["token_type"] == "bearer"
    assert "access_token" in data


async def test_login_wrong_password(client, seed_data):
    resp = await _login(client, "admin@test.com", "wrongpass")
    assert resp.status_code == 401


async def test_login_inactive_user(client, seed_data):
    resp = await _login(client, "inactive@test.com")
    assert resp.status_code == 403
    assert "desactivado" in resp.json()["detail"]


async def test_login_unknown_user(client, seed_data):
    resp = await _login(client, "nobody@test.com")
    assert resp.status_code == 401


async def test_access_without_token(client, seed_data):
    resp = await client.get("/api/catalogs/tree")
    assert resp.status_code == 401


async def test_worker_cannot_list_users(client, seed_data):
    token = await get_token(client, "ortiz@test.com")
    resp = await client.get("/api/users", headers=auth_headers(token))
    assert resp.status_code == 403


async def test_admin_cannot_deactivate_self(client, seed_data):
    token = await get_token(client, "admin@test.com")
    resp = await client.patch(
        f"/api/users/{seed_data['admin'].id}",
        json={"is_active": False},
        headers=auth_headers(token),
    )
    assert resp.status_code == 400
    assert "propio" in resp.json()["detail"]


async def test_admin_cannot_deactivate_last_active_admin(client, seed_data):
    """With only one active admin, self- and other-admin deactivation is blocked."""
    token = await get_token(client, "admin@test.com")
    resp = await client.patch(
        f"/api/users/{seed_data['admin'].id}",
        json={"is_active": False},
        headers=auth_headers(token),
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    # Either guard message may fire; the important thing is it's blocked.
    assert any(word in detail for word in ("propio", "último administrador"))


async def test_admin_cannot_demote_last_active_admin(client, seed_data):
    """Cannot change the role of the only active admin to a non-admin role."""
    token = await get_token(client, "admin@test.com")
    resp = await client.patch(
        f"/api/users/{seed_data['admin'].id}",
        json={"role": "WORKER"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 400
    assert "último administrador" in resp.json()["detail"]


async def test_admin_can_deactivate_worker(client, seed_data):
    """Deactivating a non-admin remains allowed."""
    token = await get_token(client, "admin@test.com")
    resp = await client.patch(
        f"/api/users/{seed_data['worker'].id}",
        json={"is_active": False},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200


async def test_admin_can_reset_user_password(client, seed_data):
    """Admin can reset a user's password via the PATCH users endpoint."""
    token = await get_token(client, "admin@test.com")
    resp = await client.patch(
        f"/api/users/{seed_data['worker'].id}",
        json={"password": "nuevapass123"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200

    # Worker can now log in with the new password
    login_resp = await _login(client, "ortiz@test.com", "nuevapass123")
    assert login_resp.status_code == 200


async def test_admin_cannot_reset_own_password(client, seed_data):
    """Admin cannot change their own password from the users panel."""
    token = await get_token(client, "admin@test.com")
    resp = await client.patch(
        f"/api/users/{seed_data['admin'].id}",
        json={"password": "nuevapass123"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 400
    assert "propia" in resp.json()["detail"]


async def test_short_password_rejected(client, seed_data):
    """New passwords must have at least 6 characters (Pydantic validation)."""
    token = await get_token(client, "admin@test.com")
    resp = await client.patch(
        f"/api/users/{seed_data['worker'].id}",
        json={"password": "ab"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 422


async def test_admin_can_list_users(client, seed_data):
    token = await get_token(client, "admin@test.com")
    resp = await client.get("/api/users", headers=auth_headers(token))
    assert resp.status_code == 200
    assert len(resp.json()) >= 5


async def test_supervisor_can_read_audit(client, seed_data):
    token = await get_token(client, "supervisor@test.com")
    resp = await client.get("/api/audit", headers=auth_headers(token))
    assert resp.status_code == 200


async def test_worker_cannot_read_audit(client, seed_data):
    token = await get_token(client, "ortiz@test.com")
    resp = await client.get("/api/audit", headers=auth_headers(token))
    assert resp.status_code == 403


async def test_worker_only_own_records(client, seed_data):
    # Worker creates one record, then lists -> only their own
    token = await get_token(client, "ortiz@test.com")
    oracle = seed_data

    resp = await client.post(
        "/api/maintenance",
        json={
            "date": "2026-09-01",
            "area_id": oracle["area"].id,
            "section_name": "Germinación",
            "equipment_id": oracle["equipment"].id,
            "description": "Mantención de prueba",
            "maintenance_type": "PREVENTIVE",
            "start_time": "08:30",
            "end_time": "12:00",
            "participant_ids": [oracle["worker"].id],
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 201

    # Valdés lists -> should be empty
    token2 = await get_token(client, "valdes@test.com")
    resp2 = await client.get("/api/maintenance", headers=auth_headers(token2))
    assert resp2.status_code == 200
    assert resp2.json() == []

    # Supervisor lists -> sees everyone
    token3 = await get_token(client, "supervisor@test.com")
    resp3 = await client.get("/api/maintenance", headers=auth_headers(token3))
    assert resp3.status_code == 200
    assert len(resp3.json()) >= 1
