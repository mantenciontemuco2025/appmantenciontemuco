"""OAuth credential selection tests (no real Google calls)."""

import pytest

from app.core.config import Settings


@pytest.fixture
def base_settings():
    """Settings with everything empty (neither OAuth nor Service Account)."""
    return Settings(_env_file=None)


def _fake_sa_file(tmp_path, filename="sa.json"):
    """Write a minimal service-account JSON file with a real RSA key."""
    import json

    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    sa_data = {
        "type": "service_account",
        "project_id": "test",
        "private_key": pem,
        "client_email": "sa@test.iam.gserviceaccount.com",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    sa_file = tmp_path / filename
    sa_file.write_text(json.dumps(sa_data), encoding="utf-8")
    return sa_file


def test_auth_method_none_configured(base_settings, monkeypatch):
    """With no credentials, google_auth_method is None and no creds built."""
    monkeypatch.setattr(base_settings, "GOOGLE_OAUTH_CLIENT_ID", "")
    monkeypatch.setattr(base_settings, "GOOGLE_OAUTH_CLIENT_SECRET", "")
    monkeypatch.setattr(base_settings, "GOOGLE_OAUTH_REFRESH_TOKEN", "")
    monkeypatch.setattr(base_settings, "GOOGLE_SERVICE_ACCOUNT_FILE", "")
    monkeypatch.setattr(base_settings, "GOOGLE_SERVICE_ACCOUNT_JSON", "")

    assert base_settings.google_auth_method is None
    assert base_settings.get_google_credentials() is None


def test_auth_method_oauth_when_configured(base_settings, monkeypatch):
    """All three OAuth vars set => auth_method 'oauth' and OAuth credentials."""
    monkeypatch.setattr(base_settings, "GOOGLE_OAUTH_CLIENT_ID", "client-id-123")
    monkeypatch.setattr(base_settings, "GOOGLE_OAUTH_CLIENT_SECRET", "client-secret-456")
    monkeypatch.setattr(base_settings, "GOOGLE_OAUTH_REFRESH_TOKEN", "refresh-token-789")

    assert base_settings.google_auth_method == "oauth"

    creds = base_settings.get_google_credentials()
    from google.oauth2.credentials import Credentials

    assert isinstance(creds, Credentials)
    assert creds.token_uri == "https://oauth2.googleapis.com/token"
    assert creds.client_id == "client-id-123"
    assert creds.client_secret == "client-secret-456"
    assert creds.refresh_token == "refresh-token-789"


def test_auth_method_partial_oauth_not_configured(base_settings, monkeypatch):
    """Only ID+secret set (no refresh token) => not considered OAuth."""
    monkeypatch.setattr(base_settings, "GOOGLE_OAUTH_CLIENT_ID", "client-id-123")
    monkeypatch.setattr(base_settings, "GOOGLE_OAUTH_CLIENT_SECRET", "client-secret-456")
    monkeypatch.setattr(base_settings, "GOOGLE_OAUTH_REFRESH_TOKEN", "")
    monkeypatch.setattr(base_settings, "GOOGLE_SERVICE_ACCOUNT_FILE", "")
    monkeypatch.setattr(base_settings, "GOOGLE_SERVICE_ACCOUNT_JSON", "")

    assert base_settings.google_auth_method is None


def test_auth_method_service_account_fallback(base_settings, monkeypatch, tmp_path):
    """Service Account file present (no OAuth) => 'service_account'."""
    sa_file = _fake_sa_file(tmp_path)

    monkeypatch.setattr(base_settings, "GOOGLE_OAUTH_CLIENT_ID", "")
    monkeypatch.setattr(base_settings, "GOOGLE_OAUTH_CLIENT_SECRET", "")
    monkeypatch.setattr(base_settings, "GOOGLE_OAUTH_REFRESH_TOKEN", "")
    monkeypatch.setattr(base_settings, "GOOGLE_SERVICE_ACCOUNT_FILE", str(sa_file))
    monkeypatch.setattr(base_settings, "GOOGLE_SERVICE_ACCOUNT_JSON", "")

    assert base_settings.google_auth_method == "service_account"

    creds = base_settings.get_google_credentials()
    from google.oauth2.service_account import Credentials as SACredentials

    assert isinstance(creds, SACredentials)
    assert creds.service_account_email == "sa@test.iam.gserviceaccount.com"


def test_auth_method_missing_sa_file_does_not_raise(base_settings, monkeypatch, tmp_path):
    """A GOOGLE_SERVICE_ACCOUNT_FILE pointing to a missing file => None, no crash."""
    monkeypatch.setattr(base_settings, "GOOGLE_OAUTH_CLIENT_ID", "")
    monkeypatch.setattr(base_settings, "GOOGLE_OAUTH_CLIENT_SECRET", "")
    monkeypatch.setattr(base_settings, "GOOGLE_OAUTH_REFRESH_TOKEN", "")
    monkeypatch.setattr(
        base_settings, "GOOGLE_SERVICE_ACCOUNT_FILE", str(tmp_path / "no-such-file.json")
    )
    monkeypatch.setattr(base_settings, "GOOGLE_SERVICE_ACCOUNT_JSON", "")

    assert base_settings.google_auth_method is None
    assert base_settings.get_google_credentials() is None


def test_oauth_preferred_over_service_account(base_settings, monkeypatch, tmp_path):
    """Both OAuth and SA configured => OAuth wins."""
    sa_file = _fake_sa_file(tmp_path)

    monkeypatch.setattr(base_settings, "GOOGLE_OAUTH_CLIENT_ID", "client-id-123")
    monkeypatch.setattr(base_settings, "GOOGLE_OAUTH_CLIENT_SECRET", "client-secret-456")
    monkeypatch.setattr(base_settings, "GOOGLE_OAUTH_REFRESH_TOKEN", "refresh-token-789")
    monkeypatch.setattr(base_settings, "GOOGLE_SERVICE_ACCOUNT_FILE", str(sa_file))
    monkeypatch.setattr(base_settings, "GOOGLE_SERVICE_ACCOUNT_JSON", "")

    assert base_settings.google_auth_method == "oauth"

    creds = base_settings.get_google_credentials()
    from google.oauth2.credentials import Credentials

    assert isinstance(creds, Credentials)
    assert creds.token_uri == "https://oauth2.googleapis.com/token"


# ──────────────────────────────────────────────────────────────────────
# Write-gate: OAuth required for writes, NO Service Account fallback
# ──────────────────────────────────────────────────────────────────────

def test_write_requires_oauth(base_settings, monkeypatch, tmp_path):
    """SA configured but OAuth missing => get_google_write_credentials raises."""
    sa_file = _fake_sa_file(tmp_path)

    monkeypatch.setattr(base_settings, "GOOGLE_OAUTH_CLIENT_ID", "")
    monkeypatch.setattr(base_settings, "GOOGLE_OAUTH_CLIENT_SECRET", "")
    monkeypatch.setattr(base_settings, "GOOGLE_OAUTH_REFRESH_TOKEN", "")
    monkeypatch.setattr(base_settings, "GOOGLE_SERVICE_ACCOUNT_FILE", str(sa_file))
    monkeypatch.setattr(base_settings, "GOOGLE_SERVICE_ACCOUNT_JSON", "")

    # Reads still resolve to the Service Account
    assert base_settings.google_auth_method == "service_account"
    assert base_settings.get_google_credentials() is not None

    # Writes MUST NOT fall back to SA
    with pytest.raises(RuntimeError, match="OAuth credentials are required"):
        base_settings.get_google_write_credentials()

    # write_enabled is False when OAuth is missing
    assert base_settings.google_write_enabled is False


def test_write_enabled_only_with_oauth(base_settings, monkeypatch, tmp_path):
    """Both OAuth + SA configured => write_enabled True, writes use OAuth."""
    from google.oauth2.credentials import Credentials

    sa_file = _fake_sa_file(tmp_path)
    monkeypatch.setattr(base_settings, "GOOGLE_OAUTH_CLIENT_ID", "client-id-123")
    monkeypatch.setattr(base_settings, "GOOGLE_OAUTH_CLIENT_SECRET", "client-secret-456")
    monkeypatch.setattr(base_settings, "GOOGLE_OAUTH_REFRESH_TOKEN", "refresh-token-789")
    monkeypatch.setattr(base_settings, "GOOGLE_SERVICE_ACCOUNT_FILE", str(sa_file))
    monkeypatch.setattr(base_settings, "GOOGLE_SERVICE_ACCOUNT_JSON", "")

    assert base_settings.google_write_enabled is True
    creds = base_settings.get_google_write_credentials()
    assert isinstance(creds, Credentials)
    assert creds.token_uri == "https://oauth2.googleapis.com/token"


def test_write_disabled_no_credentials(base_settings, monkeypatch):
    """No credentials at all => write_enabled False and writes raise."""
    monkeypatch.setattr(base_settings, "GOOGLE_OAUTH_CLIENT_ID", "")
    monkeypatch.setattr(base_settings, "GOOGLE_OAUTH_CLIENT_SECRET", "")
    monkeypatch.setattr(base_settings, "GOOGLE_OAUTH_REFRESH_TOKEN", "")
    monkeypatch.setattr(base_settings, "GOOGLE_SERVICE_ACCOUNT_FILE", "")
    monkeypatch.setattr(base_settings, "GOOGLE_SERVICE_ACCOUNT_JSON", "")

    assert base_settings.google_write_enabled is False
    with pytest.raises(RuntimeError, match="OAuth credentials are required"):
        base_settings.get_google_write_credentials()


# ──────────────────────────────────────────────────────────────────────
# Service-level: write builders never hand Service Account creds to build()
# ──────────────────────────────────────────────────────────────────────

def test_drive_write_builder_uses_oauth_not_sa(monkeypatch, tmp_path):
    """Both OAuth + SA configured => drive write builder gets OAuth creds."""
    from google.oauth2.credentials import Credentials as OAuthCredentials
    from google.oauth2.service_account import Credentials as SACredentials
    from app.services import google_drive

    sa_file = _fake_sa_file(tmp_path)
    _configure_both(monkeypatch, sa_file)

    captured = {}

    def fake_build(service_name, version, credentials=None):
        captured["credentials"] = credentials
        return object()  # unused by the builder

    monkeypatch.setattr("googleapiclient.discovery.build", fake_build)

    google_drive._build_drive_write_service()
    assert isinstance(captured["credentials"], OAuthCredentials)
    assert isinstance(captured["credentials"], SACredentials) is False

    google_drive._build_sheets_write_service()
    assert isinstance(captured["credentials"], OAuthCredentials)


def test_drive_write_builder_raises_without_oauth(monkeypatch, tmp_path):
    """SA configured but OAuth missing => drive write builder raises."""
    from app.services import google_drive

    sa_file = _fake_sa_file(tmp_path)
    _configure_sa_only(monkeypatch, sa_file)

    monkeypatch.setattr("googleapiclient.discovery.build", lambda *a, **k: object())

    with pytest.raises(RuntimeError, match="OAuth credentials are required"):
        google_drive._build_drive_write_service()
    with pytest.raises(RuntimeError, match="OAuth credentials are required"):
        google_drive._build_sheets_write_service()


def test_google_sheets_append_requires_oauth(monkeypatch, tmp_path):
    """append_row_to_sheet raises (does NOT silently skip) when OAuth missing."""
    from app.services import google_sheets

    sa_file = _fake_sa_file(tmp_path)
    _configure_sa_only(monkeypatch, sa_file)

    monkeypatch.setattr("googleapiclient.discovery.build", lambda *a, **k: object())

    with pytest.raises(RuntimeError, match="OAuth credentials are required"):
        google_sheets.append_row_to_sheet(["some", "row"])


def _configure_both(monkeypatch, sa_file):
    import app.core.config as config_mod
    monkeypatch.setattr(config_mod.settings, "GOOGLE_OAUTH_CLIENT_ID", "client-id-123")
    monkeypatch.setattr(config_mod.settings, "GOOGLE_OAUTH_CLIENT_SECRET", "client-secret-456")
    monkeypatch.setattr(config_mod.settings, "GOOGLE_OAUTH_REFRESH_TOKEN", "refresh-token-789")
    monkeypatch.setattr(config_mod.settings, "GOOGLE_SERVICE_ACCOUNT_FILE", str(sa_file))
    monkeypatch.setattr(config_mod.settings, "GOOGLE_SERVICE_ACCOUNT_JSON", "")


def _configure_sa_only(monkeypatch, sa_file):
    import app.core.config as config_mod
    monkeypatch.setattr(config_mod.settings, "GOOGLE_OAUTH_CLIENT_ID", "")
    monkeypatch.setattr(config_mod.settings, "GOOGLE_OAUTH_CLIENT_SECRET", "")
    monkeypatch.setattr(config_mod.settings, "GOOGLE_OAUTH_REFRESH_TOKEN", "")
    monkeypatch.setattr(config_mod.settings, "GOOGLE_SERVICE_ACCOUNT_FILE", str(sa_file))
    monkeypatch.setattr(config_mod.settings, "GOOGLE_SERVICE_ACCOUNT_JSON", "")


# ──────────────────────────────────────────────────────────────────────
# Folder hierarchy: year under ÓRDENES DE TRABAJO, month under year, OT under month
# ──────────────────────────────────────────────────────────────────────

def test_month_folder_hierarchy_is_nested(monkeypatch, tmp_path):
    """_ensure_month_folder creates year under OT_ROOT and month under year.

    Uses a fake Drive service that records the parent for each folder it
    creates, and returns existing ones on subsequent lookups.
    """
    from datetime import datetime
    from app.services import google_drive

    sa_file = _fake_sa_file(tmp_path)
    _configure_both(monkeypatch, sa_file)

    OT_ROOT = "root-ot-folder"
    monkeypatch.setattr(google_drive.settings, "GOOGLE_OT_ROOT_FOLDER_ID", OT_ROOT)
    # Ensure the write-builder returns our fake drive
    fake_drive = _FakeDrive(OT_ROOT)
    monkeypatch.setattr(google_drive, "_build_drive_write_service", lambda: fake_drive)

    month_id = google_drive._ensure_month_folder(2026, 9)  # SEPTIEMBRE

    # The month folder must be a child of the year folder, which is a child of OT_ROOT
    year_id = fake_drive._find_by_name(OT_ROOT, "2026")
    month_id_a = fake_drive._find_by_name(year_id, "SEPTIEMBRE")
    assert year_id is not None
    assert month_id_a is not None and month_id_a == month_id
    # No duplicates: scanning OT_ROOT again returns the same year id
    assert fake_drive._find_by_name(OT_ROOT, "2026") == year_id


def test_ensure_month_folder_creates_year_under_ot_root_not_root(monkeypatch, tmp_path):
    """The year folder is created directly under OT_ROOT (ÓRDENES DE TRABAJO)."""
    from datetime import datetime
    from app.services import google_drive

    sa_file = _fake_sa_file(tmp_path)
    _configure_both(monkeypatch, sa_file)

    OT_ROOT = "ot-root"
    monkeypatch.setattr(google_drive.settings, "GOOGLE_OT_ROOT_FOLDER_ID", OT_ROOT)
    fake_drive = _FakeDrive(OT_ROOT)
    monkeypatch.setattr(google_drive, "_build_drive_write_service", lambda: fake_drive)

    google_drive._ensure_month_folder(2026, 9)

    # Directly assert the year folder's creator recorded parent == OT_ROOT
    assert fake_drive._parent_of("2026") == OT_ROOT
    # The month folder's parent is the year folder's ID
    year_id = fake_drive._find_by_name(OT_ROOT, "2026")
    assert fake_drive._parent_of("SEPTIEMBRE") == year_id


def test_copy_template_removes_template_parent_not_ot_root(monkeypatch, tmp_path):
    """_copy_template moves the copy out of the TEMPLATE's folder, not OT_ROOT."""
    from app.services import google_drive

    sa_file = _fake_sa_file(tmp_path)
    _configure_both(monkeypatch, sa_file)

    OT_ROOT = "ot-root"
    PLANTILLAS = "plantillas-folder"
    TEMPLATE_ID = "template-123"
    DEST = "septiembre-folder"

    monkeypatch.setattr(google_drive.settings, "GOOGLE_OT_ROOT_FOLDER_ID", OT_ROOT)
    monkeypatch.setattr(google_drive.settings, "GOOGLE_OT_TEMPLATE_FILE_ID", TEMPLATE_ID)
    fake_drive = _FakeDrive(OT_ROOT, template_parent=PLANTILLAS)
    monkeypatch.setattr(google_drive, "_build_drive_write_service", lambda: fake_drive)

    result = google_drive._copy_template("OT-2026-0009", DEST)

    assert result["file_id"]
    # The move must remove the template's parent (PLANTILLAS), not OT_ROOT
    assert fake_drive._last_remove_parent == PLANTILLAS
    assert fake_drive._last_add_parent == DEST
    assert fake_drive._last_remove_parent != OT_ROOT


def test_copy_template_reuses_existing_ot(monkeypatch, tmp_path):
    """A retry must reuse an existing Drive file with the same OT number."""
    from app.services import google_drive

    sa_file = _fake_sa_file(tmp_path)
    _configure_both(monkeypatch, sa_file)

    destination = "septiembre-folder"
    fake_drive = _FakeDrive("ot-root", template_parent="plantillas-folder")
    fake_drive._created["existing-ot"] = {
        "id": "existing-ot",
        "name": "OT-2026-0010",
        "parent": destination,
    }
    monkeypatch.setattr(google_drive.settings, "GOOGLE_OT_ROOT_FOLDER_ID", "ot-root")
    monkeypatch.setattr(google_drive.settings, "GOOGLE_OT_TEMPLATE_FILE_ID", "template-123")
    monkeypatch.setattr(google_drive, "_build_drive_write_service", lambda: fake_drive)

    result = google_drive._copy_template("OT-2026-0010", destination)

    assert result["file_id"] == "existing-ot"
    assert fake_drive._counter == 0


class _FakeDrive:
    """Minimal fake Drive API service for folder-hierarchy tests.

    Tracks folder creation parents and supports the queries the service uses.
    """

    def __init__(self, ot_root, template_parent=None):
        self._created = {}  # dict: {name: {"id": str, "parent": str}}
        self._last_remove_parent = None
        self._last_add_parent = None
        self._template_parent = template_parent
        self._counter = 0

    def _new_id(self):
        self._counter += 1
        return f"id-{self._counter}"

    def _find_by_name(self, parent_id, name):
        for fid, info in self._created.items():
            if info["name"] == name and info["parent"] == parent_id:
                return fid
        return None

    def _parent_of(self, name):
        for info in self._created.values():
            if info["name"] == name:
                return info["parent"]
        return None

    def files(self):
        return self

    # -- Drive API surface used by the service --
    def list(self, q="", fields="", pageSize=5, **kwargs):
        # query like "'parent' in parents and name = 'X' and trashed = false"
        parent = None
        name = None
        for token in q.split(" and "):
            token = token.strip()
            if token.startswith("'") and " in parents" in token:
                parent = token.split("'")[1]
            elif token.startswith("name ="):
                name = token.split("=", 1)[1].strip().strip("'")
        files = []
        for fid, info in self._created.items():
            matches_parent = parent is None or info["parent"] == parent
            matches_name = name is None or info["name"] == name
            if matches_parent and matches_name:
                files.append({"id": fid, "name": info["name"], "parent": info["parent"]})
        return _FakeListResponse(files, fields)

    def create(self, body=None, fields="", **kwargs):
        name = body["name"]
        parent = (body.get("parents") or [None])[0]
        fid = self._new_id()
        self._created[fid] = {"id": fid, "name": name, "parent": parent}
        return _FakeCreateResponse(fid, fields)

    def copy(self, fileId="", body=None, fields="", **kwargs):
        fid = self._new_id()
        self._created[fid] = {
            "id": fid,
            "name": (body or {}).get("name", "copy"),
            "parent": self._template_parent,
        }
        return _FakeCopyResponse(fid, fields)

    def get(self, fileId="", fields="", **kwargs):
        # _get_file_parent asks for the file's "parents". For the template
        # file id it reports PLANTILLAS as its parent.
        if "parents" in fields and fileId != "ot-root":
            # Treat the template as living in PLANTILLAS
            return _FakeGetResponse([self._template_parent], fields)
        if "name" in fields:
            return _FakeGetResponse({"name": "plantilla"}, fields)
        return _FakeGetResponse([], fields)

    def update(self, fileId="", body=None, addParents="", removeParents="", fields="", **kwargs):
        body = body or {}
        self._last_add_parent = body.get("addParents", addParents)
        self._last_remove_parent = body.get("removeParents", removeParents)
        if self._last_add_parent:
            self._created[fileId]["parent"] = self._last_add_parent
        return _FakeUpdateResponse(fileId, fields)


class _FakeListResponse:
    def __init__(self, files, fields):
        self._files = files

    def execute(self):
        return {"files": self._files}


class _FakeCreateResponse:
    def __init__(self, fid, fields):
        self._fid = fid

    def execute(self):
        return {"id": self._fid}


class _FakeCopyResponse:
    def __init__(self, fid, fields):
        self._fid = fid

    def execute(self):
        return {"id": self._fid, "webViewLink": f"https://drive.google.com/file/d/{self._fid}/view"}


class _FakeUpdateResponse:
    def __init__(self, fid, fields):
        self._fid = fid

    def execute(self):
        return {"id": self._fid, "webViewLink": f"https://drive.google.com/file/d/{self._fid}/view"}


class _FakeGetResponse:
    def __init__(self, result, fields):
        self._result = result

    def execute(self):
        if isinstance(self._result, list):
            return {"parents": self._result}
        return self._result
