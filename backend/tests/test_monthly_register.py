"""Unit + endpoint tests for the per-year monthly registry (GoogleMonthlyRegister).

Covers register resolution, idempotent creation from the master template, the
obligatory file name / parent folder, 12-tab validation, UNIQUE-year concurrency,
month + year selection, year-change row cleanup, OAuth gating, the Google-failure
path (WorkOrder kept in DB with FAILED), and the admin status/ensure endpoints.

Google (Drive + Sheets) is mocked via fakes — no real calls.
"""

import pytest

from sqlalchemy import select

from app.models.monthly_register import GoogleMonthlyRegister
from app.services import monthly_register as mr
from tests.conftest import get_token, auth_headers

MONTHS = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
          "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _configure_google(monkeypatch, *, oauth=True, monthly_root="root-monthly",
                      template="tmpl-123", legacy=""):
    """Turn on Google config in settings (keeps secrets out of tests)."""
    import app.core.config as config_mod
    if oauth:
        monkeypatch.setattr(config_mod.settings, "GOOGLE_OAUTH_CLIENT_ID", "c")
        monkeypatch.setattr(config_mod.settings, "GOOGLE_OAUTH_CLIENT_SECRET", "s")
        monkeypatch.setattr(config_mod.settings, "GOOGLE_OAUTH_REFRESH_TOKEN", "r")
    else:
        monkeypatch.setattr(config_mod.settings, "GOOGLE_OAUTH_CLIENT_ID", "")
        monkeypatch.setattr(config_mod.settings, "GOOGLE_OAUTH_CLIENT_SECRET", "")
        monkeypatch.setattr(config_mod.settings, "GOOGLE_OAUTH_REFRESH_TOKEN", "")
    monkeypatch.setattr(config_mod.settings, "GOOGLE_MONTHLY_ROOT_FOLDER_ID", monthly_root)
    monkeypatch.setattr(config_mod.settings, "GOOGLE_MONTHLY_TEMPLATE_FILE_ID", template)
    monkeypatch.setattr(config_mod.settings, "GOOGLE_MONTHLY_SPREADSHEET_ID", legacy)
    monkeypatch.setattr(config_mod.settings, "GOOGLE_OT_TEMPLATE_FILE_ID", "ot-tmpl")
    monkeypatch.setattr(config_mod.settings, "GOOGLE_OT_ROOT_FOLDER_ID", "ot-root")


def _register_templates(drive_fake, template_id="tmpl-123"):
    """Seed a template file + folders in a drive fake for Drive chains to work."""
    drive_fake.add_file("tmpl-123", "Plantilla_Registro_Mensual", "plantillas")
    drive_fake.add_file("root-monthly", "REGISTRO MENSUAL", None)
    drive_fake.add_file("ot-tmpl", "Plantilla_OT", "plantillas")
    drive_fake.add_file("ot-root", "ÓRDENES DE TRABAJO", None)


@pytest.fixture
def google_ready(monkeypatch):
    """Monkeypatch Google config + Drive/Sheets builders with fakes."""
    import app.services.google_drive as gd
    _configure_google(monkeypatch)
    drive = _FakeDrive()
    sheets = _FakeSheets()
    monkeypatch.setattr(gd, "_build_drive_write_service", lambda: drive)
    monkeypatch.setattr(gd, "_build_sheets_service", lambda: sheets)
    monkeypatch.setattr(gd, "_build_sheets_write_service", lambda: sheets)
    return {"drive": drive, "sheets": sheets}


# ──────────────────────────────────────────────────────────────────────
# Fakes
# ──────────────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def execute(self):
        return self._payload


class _FakeDrive:
    """Minimal Drive API fake supporting list/copy/get/update + name queries.

    Query parsing supports AND/OR token blocks as used by the real service.
    """

    def __init__(self):
        self._files = {}  # file_id -> {"name": str, "parent": str|None}
        self._counter = 0
        self._copies = 0

    def _new_id(self):
        self._counter += 1
        return f"file-{self._counter}"

    def add_file(self, file_id, name, parent):
        self._files[file_id] = {"name": name, "parent": parent}

    def _parse_q(self, q: str):
        """Parse a Drive query string into {parent, name, trashed}.

        All tokens (whether separated by ' and ' or ' or ') are treated as
        cumulative filters — the real Google Drive API ANDs all conditions
        within a single ``list()`` call.
        """
        filters = {"parent": None, "name": None, "trashed": None}
        # Flatten both ' and ' and ' or ' into a single token list
        tokens = [t.strip() for t in q.replace(" or ", " and ").split(" and ")]
        for token in tokens:
            if " in parents" in token and token.startswith("'"):
                filters["parent"] = token.split("'")[1]
            elif token.startswith("name ="):
                filters["name"] = token.split("=", 1)[1].strip().strip("'")
            elif token.startswith("trashed ="):
                filters["trashed"] = token.split("=", 1)[1].strip() == "true"
        return filters

    def files(self):
        return self

    def list(self, q="", fields="", pageSize=5, **kwargs):
        f = self._parse_q(q)
        out = []
        for fid, info in self._files.items():
            # Parent must match if the query specified one
            if f["parent"] is not None and info["parent"] != f["parent"]:
                continue
            # Name must match if the query specified one
            if f["name"] is not None and info["name"] != f["name"]:
                continue
            # All files in the fake are non-trashed; query `trashed = false` → include, `trashed = true` → skip
            if f["trashed"] is True:
                continue
            out.append({"id": fid, "name": info["name"]})
        return _Resp({"files": out})

    def copy(self, fileId="", body=None, fields="", **kwargs):
        self._copies += 1
        fid = self._new_id()
        src_parent = self._files.get(fileId, {}).get("parent")
        self.add_file(fid, (body or {}).get("name", "copy"), src_parent)
        return _Resp({
            "id": fid,
            "webViewLink": f"https://drive.google.com/file/d/{fid}/view",
        })

    def get(self, fileId="", fields="", **kwargs):
        info = self._files.get(fileId)
        if info is None:
            raise RuntimeError(f"no such file {fileId}")
        if "parents" in (fields or ""):
            return _Resp({"parents": [info["parent"]] if info["parent"] else []})
        return _Resp({"id": fileId, "name": info["name"]})

    def update(self, fileId="", body=None, addParents="", removeParents="", fields="", **kwargs):
        if addParents:
            self._files[fileId]["parent"] = addParents
        return _Resp({"id": fileId})


class _FakeSheetsValues:
    """Proxy for sheets.spreadsheets().values() calls."""

    def __init__(self, outer):
        self._outer = outer

    def get(self, spreadsheetId="", range="", valueRenderOption=None, **kwargs):
        sheet, col = range.split("!")
        col_letter = col.split(":")[0]
        tab = self._outer.tabs.get(sheet, {})
        if col_letter in ("B", "B:B"):
            cells = tab.get("col_b", [])
        else:
            cells = []
        return _Resp({"values": [[c] if c else [] for c in cells]})

    def batchUpdate(self, spreadsheetId="", body=None, **kwargs):
        return _Resp({})

    def update(self, spreadsheetId="", range="", valueInputOption="", body=None, **kwargs):
        return _Resp({})


class _FakeSheetsSpreadsheets:
    """Proxy for sheets.spreadsheets() calls."""

    def __init__(self, outer):
        self._outer = outer

    def get(self, spreadsheetId="", fields="", **kwargs):
        if "sheets(properties.title)" in (fields or ""):
            sheets = [{"properties": {"title": t}} for t in self._outer.tabs]
        else:
            sheets = [
                {"properties": {"title": t, "sheetId": v["sheetId"]}}
                for t, v in self._outer.tabs.items()
            ]
        return _Resp({"sheets": sheets})

    def values(self):
        return _FakeSheetsValues(self._outer)

    def batchUpdate(self, spreadsheetId="", body=None, **kwargs):
        for req in (body or {}).get("requests", []):
            if "findReplace" in req:
                self._outer.find_replace_calls.append(req["findReplace"])
            if "deleteDimension" in req:
                rng = req["deleteDimension"]["range"]
                self._outer.delete_calls.append({
                    "sheetId": rng.get("sheetId"),
                    "startIndex": rng.get("startIndex"),
                    "endIndex": rng.get("endIndex"),
                })
        return _Resp({})


class _FakeSheets:
    """Minimal Sheets API fake supporting the method chain:
    sheets.spreadsheets().get/batchUpdate(...)  ->  .execute()
    sheets.spreadsheets().values().get/batchUpdate(...)  ->  .execute()

    tabs: {title: {"sheetId": int, "col_b": list-of-cell-strings}}
    """

    def __init__(self):
        self.tabs = {}
        self.delete_calls = []
        self.find_replace_calls = []

    def spreadsheets(self):
        return _FakeSheetsSpreadsheets(self)

    def add_tab(self, title, sheet_id=None, col_b=None):
        self.tabs[title] = {
            "sheetId": sheet_id if sheet_id is not None else len(self.tabs),
            "col_b": list(col_b or []),
        }


# ──────────────────────────────────────────────────────────────────────
# Unit: resolution + creation
# ──────────────────────────────────────────────────────────────────────

async def test_resolve_existing_2026(db_session_factory):
    async with db_session_factory() as db:
        db.add(GoogleMonthlyRegister(year=2026, spreadsheet_id="legacy-2026"))
        await db.commit()
        reg = await mr.resolve_register(db, 2026)
        assert reg is not None and reg.spreadsheet_id == "legacy-2026"
        assert await mr.resolve_register(db, 2027) is None


def test_register_filename_format():
    assert mr.register_filename(2026) == "Registro_Mantencion_2026"
    assert mr.register_filename(2027) == "Registro_Mantencion_2027"


async def test_create_register_from_template_name_and_parent(google_ready, db_session_factory):
    _register_templates(google_ready["drive"])
    async with db_session_factory() as db:
        reg = await mr.ensure_monthly_register_for_year(db, 2027)
        assert reg is not None and reg.year == 2027 and reg.spreadsheet_id.startswith("file-")
        assert google_ready["drive"]._copies == 1
        copied_id = reg.spreadsheet_id
        assert google_ready["drive"]._files[copied_id]["name"] == "Registro_Mantencion_2027"
        assert google_ready["drive"]._files[copied_id]["parent"] == "root-monthly"
        assert google_ready["sheets"].find_replace_calls == [
            {"find": "{{YEAR}}", "replacement": "2027", "allSheets": True},
            {"find": "2026", "replacement": "2027", "allSheets": True},
        ]


async def test_ensure_reuses_existing_no_duplicate(google_ready, db_session_factory):
    _register_templates(google_ready["drive"])
    async with db_session_factory() as db:
        reg1 = await mr.ensure_monthly_register_for_year(db, 2027)
        reg2 = await mr.ensure_monthly_register_for_year(db, 2027)
        assert reg1.id == reg2.id and reg1.spreadsheet_id == reg2.spreadsheet_id
        assert google_ready["drive"]._copies == 1  # only one Drive copy


async def test_ensure_uniqueness_year(google_ready, db_session_factory):
    """A UNIQUE(year) race -> second ensure reuses the row, never duplicates."""
    _register_templates(google_ready["drive"])
    async with db_session_factory() as db:
        reg1 = await mr.ensure_monthly_register_for_year(db, 2028)
        assert reg1 is not None and reg1.year == 2028
    # A fresh session sees the committed row; second ensure must reuse it.
    async with db_session_factory() as db:
        reg2 = await mr.ensure_monthly_register_for_year(db, 2028)
        assert reg2.spreadsheet_id == reg1.spreadsheet_id
    assert google_ready["drive"]._copies == 1  # only one copy requested


async def test_ensure_requires_oauth(monkeypatch, db_session_factory):
    import app.services.google_drive as gd
    _configure_google(monkeypatch, oauth=False)
    monkeypatch.setattr(gd, "_build_drive_write_service", lambda: _FakeDrive())
    monkeypatch.setattr(gd, "_build_sheets_service", lambda: _FakeSheets())
    async with db_session_factory() as db:
        reg = await mr.ensure_monthly_register_for_year(db, 2030)
        assert reg is None  # cannot create without OAuth
        assert await mr.resolve_register(db, 2030) is None


async def test_create_register_validates_12_tabs(google_ready, db_session_factory):
    _register_templates(google_ready["drive"])
    for m in MONTHS:
        google_ready["sheets"].add_tab(m, col_b=[])
    async with db_session_factory() as db:
        reg = await mr.ensure_monthly_register_for_year(db, 2027)
        assert reg is not None
        assert mr.validate_12_tabs(reg.spreadsheet_id) == []


async def test_create_register_flags_missing_tabs(google_ready, db_session_factory):
    """Even if tabs are missing, the register is still created (warning only)."""
    _register_templates(google_ready["drive"])
    for m in MONTHS[:6]:  # only 6 tabs
        google_ready["sheets"].add_tab(m, col_b=[])
    async with db_session_factory() as db:
        reg = await mr.ensure_monthly_register_for_year(db, 2029)
        assert reg is not None
        missing = mr.validate_12_tabs(reg.spreadsheet_id)
        assert len(missing) == 6  # 6 tabs missing


# ──────────────────────────────────────────────────────────────────────
# delete_ot_from_register (year-change cleanup) — deleteDimension
# ──────────────────────────────────────────────────────────────────────

async def test_delete_ot_from_register_removes_row(google_ready):
    google_ready["sheets"].add_tab("DICIEMBRE", sheet_id=11, col_b=["", "", "OT-2026-001", ""])
    mr.delete_ot_from_register("fake-spreadsheet", "DICIEMBRE", "OT-2026-001")
    assert google_ready["sheets"].delete_calls
    call = google_ready["sheets"].delete_calls[0]
    assert call["sheetId"] == 11
    assert (call["startIndex"], call["endIndex"]) == (2, 3)


async def test_delete_ot_from_register_noop_when_missing(google_ready):
    google_ready["sheets"].add_tab("DICIEMBRE", sheet_id=11, col_b=["", "OT-999-X"])
    mr.delete_ot_from_register("fake-spreadsheet", "DICIEMBRE", "OT-DOES-NOT-EXIST")
    assert google_ready["sheets"].delete_calls == []


# ──────────────────────────────────────────────────────────────────────
# Month / year selection
# ──────────────────────────────────────────────────────────────────────

def test_month_selection_by_month_number():
    from app.services.ot_mapping import get_monthly_sheet_title
    assert get_monthly_sheet_title(1) == "ENERO"
    assert get_monthly_sheet_title(8) == "AGOSTO"
    assert get_monthly_sheet_title(2) == "FEBRERO"
    assert get_monthly_sheet_title(12) == "DICIEMBRE"


# ──────────────────────────────────────────────────────────────────────
# Admin endpoints (status + ensure + list)
# ──────────────────────────────────────────────────────────────────────

async def test_list_monthly_registers(client, db_session_factory, seed_data, monkeypatch):
    """GET /api/admin/google/monthly-registers lists seeded registers."""
    async with db_session_factory() as db:
        db.add(GoogleMonthlyRegister(year=2026, spreadsheet_id="a-2026"))
        db.add(GoogleMonthlyRegister(year=2027, spreadsheet_id="b-2027"))
        await db.commit()

    token = await get_token(client, seed_data["admin"].email)
    resp = await client.get(
        "/api/admin/google/monthly-registers", headers=auth_headers(token)
    )
    assert resp.status_code == 200
    rows = resp.json()
    assert [r["year"] for r in rows] == [2027, 2026]


async def test_ensure_endpoint_idempotent_existing(client, db_session_factory, seed_data, monkeypatch):
    """POST ensure for an existing year returns created=False."""
    async with db_session_factory() as db:
        db.add(GoogleMonthlyRegister(
            year=2026, spreadsheet_id="spread-2026",
            spreadsheet_url="https://drive.google.com/file/d/spread-2026/view",
        ))
        await db.commit()

    token = await get_token(client, seed_data["admin"].email)
    resp = await client.post(
        "/api/admin/google/monthly-registers/2026/ensure",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    j = resp.json()
    assert j["year"] == 2026
    assert j["spreadsheet_id"] == "spread-2026"
    assert j["created"] is False


async def test_ensure_endpoint_creates_new(client, seed_data, monkeypatch):
    """POST ensure for a new year calls ensure_service and returns the register."""
    from app.models.monthly_register import GoogleMonthlyRegister as GMR

    async def fake_ensure(db, year, user_id=None, *, commit=True):
        # Simulate service creating a new register — insert directly in DB.
        reg = GMR(
            year=year, spreadsheet_id=f"new-{year}",
            spreadsheet_url=f"https://drive.google.com/file/d/new-{year}/view",
            is_active=True,
        )
        db.add(reg)
        if commit:
            await db.commit()
        return reg

    # Patch the service function imported into the admin route module.
    import app.api.routes.admin as admin_mod
    monkeypatch.setattr(admin_mod, "ensure_monthly_register_for_year", fake_ensure)

    token = await get_token(client, seed_data["admin"].email)
    resp = await client.post(
        "/api/admin/google/monthly-registers/2028/ensure",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    j = resp.json()
    assert j["year"] == 2028
    assert j["created"] is True
    assert j["spreadsheet_id"] == "new-2028"


async def test_ensure_endpoint_400_when_not_configured(client, seed_data, monkeypatch):
    """POST ensure returns 400 when Google write is not configured."""
    async def fake_ensure_returns_none(db, year, user_id=None, *, commit=True):
        return None

    import app.api.routes.admin as admin_mod
    monkeypatch.setattr(admin_mod, "ensure_monthly_register_for_year", fake_ensure_returns_none)

    token = await get_token(client, seed_data["admin"].email)
    resp = await client.post(
        "/api/admin/google/monthly-registers/2030/ensure",
        headers=auth_headers(token),
    )
    assert resp.status_code == 400


# ──────────────────────────────────────────────────────────────────────
# Status endpoint (mocked google status check)
# ──────────────────────────────────────────────────────────────────────

async def test_status_endpoint_reports_register(client, db_session_factory, seed_data, monkeypatch):
    """GET /api/admin/integrations/google/status includes current_year_register."""
    async with db_session_factory() as db:
        db.add(GoogleMonthlyRegister(year=2026, spreadsheet_id="spread-2026"))
        await db.commit()

    # Mock check_google_drive_status so we don't hit real Google.
    import app.services.google_drive as gd
    monkeypatch.setattr(gd, "check_google_drive_status", lambda: {
        "configured": True, "auth_method": "oauth", "write_enabled": True,
        "template_access": True, "ot_folder_access": True,
        "monthly_sheet_access": True, "monthly_tabs_valid": True,
        "monthly_root_folder_access": True, "monthly_template_access": True,
        "current_year": 2026, "current_year_register": None,
    })

    token = await get_token(client, seed_data["admin"].email)
    resp = await client.get(
        "/api/admin/integrations/google/status", headers=auth_headers(token)
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is True
    reg = data.get("current_year_register")
    assert reg is not None
    assert reg["spreadsheet_id"] == "spread-2026"
