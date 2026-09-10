"""Signature profile API tests (Drive is mocked; no external files are used)."""

from tests.conftest import auth_headers, get_token


async def test_upload_signature_validates_the_actual_file_type(client, seed_data):
    token = await get_token(client, "admin@test.com")
    response = await client.post(
        "/api/users/me/signature",
        files={"file": ("not-a-signature.png", b"not an image", "image/png")},
        headers=auth_headers(token),
    )
    assert response.status_code == 415


async def test_upload_signature_updates_my_profile(client, seed_data, monkeypatch):
    token = await get_token(client, "admin@test.com")
    expected_url = "https://drive.google.com/uc?export=view&id=signature-new"
    monkeypatch.setattr(
        "app.api.routes.users.upload_signature",
        lambda user_id, contents, mime: expected_url,
    )
    monkeypatch.setattr("app.api.routes.users.delete_signature", lambda signature_url: None)

    png = b"\x89PNG\r\n\x1a\n" + b"image bytes"
    response = await client.post(
        "/api/users/me/signature",
        files={"file": ("firma.png", png, "image/png")},
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    assert response.json() == {"url": expected_url}

    me = await client.get("/api/auth/me", headers=auth_headers(token))
    assert me.status_code == 200
    assert me.json()["signature"] == expected_url


async def test_signature_image_is_served_from_the_application_origin(client, seed_data, monkeypatch):
    png = b"\x89PNG\r\n\x1a\nproxied-image"
    monkeypatch.setattr(
        "app.api.routes.users.get_signature_image",
        lambda file_id: (png, "image/png"),
    )

    response = await client.get("/api/users/signature-image/admin-signature")

    assert response.status_code == 200
    assert response.content == png
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "public, max-age=3600"


async def test_signature_image_rejects_unknown_file_id(client, seed_data, monkeypatch):
    monkeypatch.setattr(
        "app.api.routes.users.get_signature_image",
        lambda file_id: (_ for _ in ()).throw(AssertionError("must not fetch Drive")),
    )

    response = await client.get("/api/users/signature-image/not-a-signature")

    assert response.status_code == 404
