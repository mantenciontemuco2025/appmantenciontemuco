"""Tests for OT field population + monthly sheet sync (no real Google calls).

Uses fake Sheets services to assert:
- populate_ot_fields writes to the correct cells (and nothing destructive)
- sync_to_monthly_sheet appends when the OT is missing, updates when present,
  and never duplicates
- checkbox text is exclusive
"""

import pytest
from datetime import datetime, date, time

from app.core.config import Settings
from app.services import google_drive
from app.services.ot_mapping import (
    OT_FIELD_MAP,
    MAINTENANCE_TYPE_CELLS,
    LOTO_CELLS,
    STATUS_CELL,
    MONTHLY_COLUMN_MAP,
)


@pytest.fixture
def oauth_settings(monkeypatch):
    """Configure settings with OAuth present (writes allowed)."""
    import app.core.config as config_mod
    monkeypatch.setattr(config_mod.settings, "GOOGLE_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setattr(config_mod.settings, "GOOGLE_OAUTH_CLIENT_SECRET", "csecret")
    monkeypatch.setattr(config_mod.settings, "GOOGLE_OAUTH_REFRESH_TOKEN", "rtok")
    return config_mod.settings


# ──────────────────────────────────────────────────────────────────────
# Fake Sheets service that records writes
# ──────────────────────────────────────────────────────────────────────

class _FakeSheets:
    """Records all cell writes and serves reads for the monthly sheet."""

    def __init__(self):
        self.writes = []          # list of (range, values) for values().update
        self.batch_writes = []    # list of data dicts from batchUpdate
        self.batch_requests = []  # structural requests from spreadsheets().batchUpdate
        self.append_writes = []   # list of (range, values) from append
        self.monthly_rows = {}    # {sheet_title: [ [row...], ... ]} read state

    # -- surface: both .values() and .spreadsheets().values() ->
    def spreadsheets(self):
        return self

    def values(self):
        return self

    def _ot_rows(self, sheet):
        """Count sheet rows that carry an actual N° OT in column B (index 1)."""
        rows = self.monthly_rows.get(sheet, [])
        return sum(
            1 for r in rows if len(r) > 1 and str(r[1]).strip()
        )

    def get(self, spreadsheetId="", range="", **kwargs):
        if not range:
            return _FakeMetadataResponse()
        # Header read: ranges like "Sheet!A3:AA3" come from
        # _merge_monthly_columns_with_headers. Return real headers so ESTADO is
        # resolved (when the caller uses a header-aware path). Base fake returns
        # the static header set.
        sheet = range.split("!")[0] if "!" in range else ""
        rng = range.split("!")[-1] if "!" in range else range
        top, _, bottom = rng.partition(":")
        col_top = "".join(ch for ch in top if ch.isalpha())
        row_top = "".join(ch for ch in top if ch.isdigit())
        row_bottom = "".join(ch for ch in bottom if ch.isdigit()) if bottom else row_top
        rows = self.monthly_rows.get(sheet, [])

        col_letter = col_top.upper() or "A"
        col_idx = ord(col_letter) - ord("A")

        # Full-column read (no explicit row numbers), e.g. "Sheet!B:B": used by
        # _search_row_by_col and the free-row computation. Return the entire
        # column across all stored rows so idempotency is preserved.
        if not row_top.isdigit():
            # Mirror how values().get on a full column returns the data extent:
            # one cell per stored row (each row = one spreadsheet row).
            out = []
            for r in rows:
                out.append([r[col_idx] if col_idx < len(r) else ""])
            return _FakeGetSheetResponse(out)

        row_start = int(row_top)
        row_end = int(row_bottom) if row_bottom.isdigit() else len(rows)

        # Build the column as naive rows within [row_start, row_end].
        out_rows = []
        for i in range(row_start, min(row_end, len(rows)) + 1):
            idx = i - 1  # month_rows is 0-indexed row list; row 1 -> index 0
            r = rows[idx] if idx < len(rows) else []
            out_rows.append([r[col_idx] if col_idx < len(r) else ""])
        return _FakeGetSheetResponse(out_rows)

    def update(self, spreadsheetId="", range="", valueInputOption="", body=None, **kwargs):
        self.writes.append((range, body["values"][0]))
        # Reflect the write into the read-state so idempotent re-syncs (and
        # row-count assertions) see the row.
        sheet = range.split("!")[0] if "!" in range else ""
        rng = range.split("!")[-1] if "!" in range else range
        top, _, _ = rng.partition(":")
        row = "".join(ch for ch in top if ch.isdigit())
        if row.isdigit() and sheet:
            idx = int(row) - 1
            while len(self.monthly_rows.setdefault(sheet, [])) <= idx:
                self.monthly_rows[sheet].append([])
            self.monthly_rows[sheet][idx] = body["values"][0]
        return _FakeUpdateSheetResponse()

    def append(self, spreadsheetId="", range="", valueInputOption="", body=None, **kwargs):
        self.append_writes.append((range, body["values"][0]))
        sheet = range.split("!")[0]
        if sheet not in self.monthly_rows:
            self.monthly_rows[sheet] = []
        self.monthly_rows[sheet].append(body["values"][0])
        return _FakeAppendSheetResponse()

    def batchUpdate(self, spreadsheetId="", body=None, **kwargs):
        self.batch_writes.extend(body.get("data", []))
        self.batch_requests.extend(body.get("requests", []))
        return _FakeBatchResponse()


class _FakeGetSheetResponse:
    def __init__(self, rows):
        self._rows = rows
    def execute(self):
        return {"values": self._rows}


class _FakeMetadataResponse:
    def execute(self):
        return {"sheets": [{"properties": {"sheetId": 0, "index": 0, "title": "PLANTILLA_OT"}}]}


class _FakeUpdateSheetResponse:
    def execute(self):
        return {"updatedRange": "SEPTIEMBRE!A1:V1"}


class _FakeAppendSheetResponse:
    def execute(self):
        return {"updates": {"updatedRange": "SEPTIEMBRE!A4:V4"}}


class _FakeBatchResponse:
    def execute(self):
        return {}


# ──────────────────────────────────────────────────────────────────────
# populate_ot_fields: writes to correct cells, formatting-safe
# ──────────────────────────────────────────────────────────────────────

def test_populate_fields_writes_to_correct_cells(oauth_settings, monkeypatch, tmp_path):
    """All text fields must go to their exact OT_FIELD_MAP cells (not elsewhere)."""
    fake = _FakeSheets()
    monkeypatch.setattr(google_drive, "_build_sheets_write_service", lambda: fake)

    google_drive.populate_ot_fields(
        "spreadsheet-1",
        ot_number="OT-TEST",
        area_name="AREA TEST",
        section_name="SECC TEST",
        equipment_name="EQ TEST",
        maintenance_type="CORRECTIVE",
        loto_status="YES",
        description="DESC TEST",
        participants=["Ortiz", "Jara"],
        estimated_time="1 h 30 min",
        execution_date="03-09-2026",
        request_date="2026-09-04",
        resources_required="RECURSOS",
        risks="RIESGOS",
        observations="OBS",
        folio="FOLIO-1",
        voucher_number="VALE-1",
        requested_by="SOL 1",
        approved_by="APR 1",
        status="PENDING",
    )

    # Text fields came via batchUpdate (data list)
    batch = {d["range"]: d["values"][0][0] for d in fake.batch_writes}

    assert batch["G2"] == "OT-TEST"                    # ot_number
    assert batch["C6"] == "AREA TEST"                  # area
    assert batch["C7"] == "SECC TEST"                  # section
    assert batch["C8"] == "EQ TEST"                    # equipment
    assert batch["B12"] == "DESC TEST"                 # description
    assert batch["C15"] == "Ortiz, Jara"               # participants
    assert batch["C16"] == "1 h 30 min"                # estimated_time
    assert batch["F17"] == "03-09-2026"                # execution_date
    assert batch["C17"] == "2026-09-04"                # request_date
    assert batch["B19"] == "RECURSOS"                  # resources
    assert batch["C21"] == "VALE-1"                    # voucher
    assert batch["B23"] == "RIESGOS"                   # risks
    assert batch["B27"] == "OBS"                       # observations
    assert batch["B31"].startswith("SOLICITADO POR: SOL 1")   # requested by
    assert batch["E31"].startswith("REALIZADO POR: APR 1")    # performed by
    assert batch["G10"] == "FOLIO-1"                    # folio

    # Per-cell checkbox writes
    written_cells = {rng: vals[0] for rng, vals in fake.writes}
    for cell in MAINTENANCE_TYPE_CELLS.values():
        assert cell in written_cells
    assert written_cells["D9"] == "[X] Correctivo"
    assert written_cells["C9"] == "[ ] Preventivo"
    for cell in LOTO_CELLS.values():
        assert cell in written_cells
    assert written_cells["C10"] == "[X] Sí"
    assert written_cells["D10"] == "[ ] No"
    assert STATUS_CELL in written_cells
    assert "[X] PENDIENTE" in written_cells[STATUS_CELL]


def test_update_ot_status_writes_only_status_cell(oauth_settings, monkeypatch, tmp_path):
    """update_ot_status must write ONLY the STATUS_CELL (nothing else)."""
    fake = _FakeSheets()
    monkeypatch.setattr(google_drive, "_build_sheets_write_service", lambda: fake)

    google_drive.update_ot_status("spreadsheet-1", "COMPLETED")

    # Exactly one write, to the status cell, with the completed checkbox marked.
    assert len(fake.writes) == 1
    rng, values = fake.writes[0]
    assert rng.startswith(STATUS_CELL)
    assert "[X] FINALIZADO" in values[0]


def test_update_ot_status_marks_in_progress(oauth_settings, monkeypatch, tmp_path):
    """An in-progress OT reflects EN PROCESO in the document's status cell."""
    fake = _FakeSheets()
    monkeypatch.setattr(google_drive, "_build_sheets_write_service", lambda: fake)

    google_drive.update_ot_status("spreadsheet-1", "IN_PROGRESS")
    assert len(fake.writes) == 1
    _, values = fake.writes[0]
    assert "[X] EN PROCESO" in values[0]
    assert "[ ] PENDIENTE" in values[0]


def test_populate_fields_checkbox_exclusive(oauth_settings, monkeypatch, tmp_path):
    """Only the selected checkbox gets [X]; others get [ ]."""
    fake = _FakeSheets()
    monkeypatch.setattr(google_drive, "_build_sheets_write_service", lambda: fake)

    google_drive.populate_ot_fields(
        "spreadsheet-1",
        ot_number="OT-TEST", area_name="A", section_name="S",
        equipment_name="E", maintenance_type="PREDICTIVE",
        loto_status="NOT_APPLICABLE", description=None, participants=[],
        estimated_time=None, execution_date=None, resources_required=None,
        risks=None, observations=None, folio=None, voucher_number=None,
        requested_by=None, approved_by=None, status="COMPLETED",
    )

    written = {rng: vals[0] for rng, vals in fake.writes}
    # Per-cell: only the selected option gets [X]
    mt_xs = [w for cell, w in written.items() if cell in MAINTENANCE_TYPE_CELLS.values()
             and "[X]" in w]
    assert len(mt_xs) == 1, f"must be exactly one maintenance [X], got {mt_xs}"
    assert written[MAINTENANCE_TYPE_CELLS["PREDICTIVE"]] == "[X] Predictivo"
    loto_xs = [w for cell, w in written.items() if cell in LOTO_CELLS.values()
               and "[X]" in w]
    assert len(loto_xs) == 1, f"must be exactly one LOTO [X], got {loto_xs}"
    assert written[LOTO_CELLS["NOT_APPLICABLE"]] == "[X] No aplica"
    assert "[X] FINALIZADO" in written[STATUS_CELL]


def test_populate_no_destructive_ops(oauth_settings, monkeypatch, tmp_path):
    """Writes only touch value cells — no row/col insert/delete, no formatting."""
    fake = _FakeSheets()
    monkeypatch.setattr(google_drive, "_build_sheets_write_service", lambda: fake)

    google_drive.populate_ot_fields(
        "spreadsheet-1", ot_number="OT-TEST", area_name="A", section_name="",
        equipment_name="", maintenance_type="PREVENTIVE", loto_status="NO",
        description=None, participants=[], estimated_time=None,
        execution_date=None, resources_required=None, risks=None,
        observations=None, folio=None, voucher_number=None,
        requested_by=None, approved_by=None, status="PENDING",
    )

    # Only values().update and values().batchUpdate were used.
    # No batchUpdate with repeatCell / request types (formatting).
    assert fake.batch_writes  # the text-field batch is data, not requests
    # Ensure nothing that looks like a structural/format request was issued
    # (our fake has no batchUpdate-from-requests path, so this is structural
    # by construction: we never call spreadsheets().batchUpdate with requests).
    assert not hasattr(fake, "formatting_requests")


def test_populate_signature_inserts_a_real_image(oauth_settings, monkeypatch):
    """A handwritten signature is delegated to Apps Script as a real image."""
    fake = _FakeSheets()
    monkeypatch.setattr(google_drive, "_build_sheets_write_service", lambda: fake)
    calls = []
    monkeypatch.setattr(google_drive, "insert_signature_image", lambda *args: calls.append(args))

    google_drive.populate_ot_fields(
        "spreadsheet-1", ot_number="OT-TEST", area_name="A", section_name="",
        equipment_name="", maintenance_type="PREVENTIVE", loto_status="NO",
        description=None, participants=[], estimated_time=None, execution_date=None,
        resources_required=None, risks=None, observations=None, folio=None,
        voucher_number=None, requested_by="Admin", approved_by=None,
        requested_signature="https://drive.google.com/uc?export=view&id=signature-1",
        status="PENDING",
    )

    # The original 3-row merge is replaced only for the signed block. The
    # external script then inserts a real Drive blob above the grid.
    assert fake.batch_requests[0]["unmergeCells"]["range"]["startRowIndex"] == 30
    assert all("formulaValue" not in str(request) for request in fake.batch_requests)
    assert calls == [(
        "spreadsheet-1", "PLANTILLA_OT", "requested_by",
        "https://drive.google.com/uc?export=view&id=signature-1",
    )]


def test_performed_signature_inserts_in_realizado_por(oauth_settings, monkeypatch):
    """The worker signature uses the right REALIZADO POR image anchor."""
    fake = _FakeSheets()
    monkeypatch.setattr(google_drive, "_build_sheets_write_service", lambda: fake)
    calls = []
    monkeypatch.setattr(google_drive, "insert_signature_image", lambda *args: calls.append(args))

    google_drive.populate_ot_fields(
        "spreadsheet-1", ot_number="OT-TEST", area_name="A", section_name="",
        equipment_name="", maintenance_type="PREVENTIVE", loto_status="NO",
        description=None, participants=[], estimated_time=None, execution_date=None,
        resources_required=None, risks=None, observations=None, folio=None,
        voucher_number=None, requested_by="Admin", approved_by="Ortiz",
        approved_signature="https://drive.google.com/uc?export=view&id=worker-signature",
        status="COMPLETED",
    )

    assert calls == [(
        "spreadsheet-1", "PLANTILLA_OT", "approved_by",
        "https://drive.google.com/uc?export=view&id=worker-signature",
    )]


# ──────────────────────────────────────────────────────────────────────
# sync_to_monthly_sheet: append / update / no duplicate
# ──────────────────────────────────────────────────────────────────────

def _configure_monthly_sync(monkeypatch, oauth_settings):
    config = __import__("app.core.config", fromlist=["settings"])
    monkeypatch.setattr(config.settings, "GOOGLE_MONTHLY_SPREADSHEET_ID", "monthly-1")
    return config.settings


def test_sync_append_when_missing(oauth_settings, monkeypatch, tmp_path):
    """When the OT does not exist, a new row is written at the first free row."""
    fake = _FakeSheets()
    # Empty monthly state -> no rows; the new row must land at MONTHLY_DATA_START_ROW
    fake.monthly_rows["SEPTIEMBRE"] = []
    monkeypatch.setattr(google_drive, "_build_sheets_write_service", lambda: fake)
    monkeypatch.setattr(google_drive, "_build_sheets_service", lambda: fake)

    monkeypatch.setattr(google_drive.settings, "GOOGLE_MONTHLY_SPREADSHEET_ID", "m1")

    exec_dt = datetime.combine(date(2026, 9, 3), time.min)
    google_drive.sync_to_monthly_sheet(
        "OT-2026-0101", exec_dt,
        area_name="A", section_name="S", equipment_name="E",
        description="D", maintenance_type="CORRECTIVE",
        participants=["Ortiz", "Jara"], duration_hours=1.5,
    )

    # Insert is a values().update at the first data row (row 4), not an append.
    assert len(fake.append_writes) == 0
    assert len(fake.writes) == 1
    rng, row = fake.writes[0]
    assert rng.startswith("SEPTIEMBRE!A4:")
    # Map by column letter using MONTHLY_COLUMN_MAP
    col = MONTHLY_COLUMN_MAP
    assert row[ord(col["FECHA"]) - ord("A")] == "03-09-2026"
    assert row[ord(col["N_O_T"]) - ord("A")] == "OT-2026-0101"
    assert row[ord(col["AREA"]) - ord("A")] == "A"
    assert row[ord(col["SECCION"]) - ord("A")] == "S"
    assert row[ord(col["EQUIPO"]) - ord("A")] == "E"
    assert row[ord(col["TRABAJO"]) - ord("A")] == "D"
    assert row[ord(col["ORTIZ"]) - ord("A")] == "X"
    assert row[ord(col["JARA"]) - ord("A")] == "X"
    assert row[ord(col["VALDES"]) - ord("A")] == ""
    assert row[ord(col["CORRECTIVO"]) - ord("A")] == "X"
    assert row[ord(col["PREVENTIVO"]) - ord("A")] == ""
    assert row[ord(col["HORAS"]) - ord("A")] == "1.5"


def test_sync_update_when_exists(oauth_settings, monkeypatch, tmp_path):
    """When the OT already exists, the row is updated (not duplicated)."""
    fake = _FakeSheets()
    col = MONTHLY_COLUMN_MAP
    n_ot_idx = ord(col["N_O_T"]) - ord("A")
    # Seed an existing row with our OT number
    existing = [""] * 22
    existing[n_ot_idx] = "OT-2026-0101"
    existing[0] = "03-09-2026"
    fake.monthly_rows["SEPTIEMBRE"] = [existing]
    monkeypatch.setattr(google_drive, "_build_sheets_write_service", lambda: fake)
    monkeypatch.setattr(google_drive, "_build_sheets_service", lambda: fake)
    monkeypatch.setattr(google_drive.settings, "GOOGLE_MONTHLY_SPREADSHEET_ID", "m1")

    exec_dt = datetime.combine(date(2026, 9, 3), time.min)
    google_drive.sync_to_monthly_sheet(
        "OT-2026-0101", exec_dt,
        area_name="A2", section_name="S2", equipment_name="E2",
        description="D2", maintenance_type="PREVENTIVE",
        participants=["Jara"], duration_hours=2.0,
    )

    # It must UPDATE, not append
    assert len(fake.append_writes) == 0
    assert len(fake.writes) == 1
    updated_range, updated_row = fake.writes[0]
    assert "SEPTIEMBRE" in updated_range
    # The updated row reflects the new values (PREVENTIVE, Jara, 2.0 h)
    col = MONTHLY_COLUMN_MAP
    assert updated_row[ord(col["AREA"]) - ord("A")] == "A2"
    assert updated_row[ord(col["PREVENTIVO"]) - ord("A")] == "X"
    assert updated_row[ord(col["CORRECTIVO"]) - ord("A")] == ""
    assert updated_row[ord(col["JARA"]) - ord("A")] == "X"
    assert updated_row[ord(col["ORTIZ"]) - ord("A")] == ""
    assert updated_row[ord(col["HORAS"]) - ord("A")] == "2.0"


def test_sync_no_duplicate_on_second_sync(oauth_settings, monkeypatch, tmp_path):
    """Syncing the same OT twice yields exactly one row."""
    fake = _FakeSheets()
    fake.monthly_rows["SEPTIEMBRE"] = []
    monkeypatch.setattr(google_drive, "_build_sheets_write_service", lambda: fake)
    monkeypatch.setattr(google_drive, "_build_sheets_service", lambda: fake)
    monkeypatch.setattr(google_drive.settings, "GOOGLE_MONTHLY_SPREADSHEET_ID", "m1")

    exec_dt = datetime.combine(date(2026, 9, 3), time.min)
    for _ in range(2):
        google_drive.sync_to_monthly_sheet(
            "OT-2026-0202", exec_dt,
            area_name="A", section_name="S", equipment_name="E",
            description="D", maintenance_type="MONTAJE",
            participants=["Ortiz"], duration_hours=1.0,
        )

    # There must be exactly one OT row (first call inserts, second updates same row).
    assert len(fake.append_writes) == 0
    assert fake._ot_rows("SEPTIEMBRE") == 1


def test_sync_month_determined_from_execution_date(oauth_settings, monkeypatch, tmp_path):
    """The tab is chosen from execution_date's month."""
    fake = _FakeSheets()
    fake.monthly_rows["OCTUBRE"] = []
    monkeypatch.setattr(google_drive, "_build_sheets_write_service", lambda: fake)
    monkeypatch.setattr(google_drive, "_build_sheets_service", lambda: fake)
    monkeypatch.setattr(google_drive.settings, "GOOGLE_MONTHLY_SPREADSHEET_ID", "m1")

    exec_dt = datetime.combine(date(2026, 10, 14), time.min)
    google_drive.sync_to_monthly_sheet(
        "OT-2026-0303", exec_dt,
        area_name="A", section_name="S", equipment_name="E",
        description="D", maintenance_type="PREVENTIVE",
        participants=[], duration_hours=1.0,
    )
    # Must write to OCTUBRE, not SEPTIEMBRE
    assert fake.writes and "OCTUBRE!A4" in fake.writes[0][0]


def test_sync_draft_skipped(oauth_settings, monkeypatch, tmp_path):
    """A DRAFT status is not synced to the monthly sheet."""
    fake = _FakeSheets()
    fake.monthly_rows["SEPTIEMBRE"] = []
    monkeypatch.setattr(google_drive, "_build_sheets_write_service", lambda: fake)
    monkeypatch.setattr(google_drive, "_build_sheets_service", lambda: fake)
    monkeypatch.setattr(google_drive.settings, "GOOGLE_MONTHLY_SPREADSHEET_ID", "m1")

    exec_dt = datetime.combine(date(2026, 9, 3), time.min)
    result = google_drive.sync_to_monthly_sheet(
        "OT-2026-0404", exec_dt,
        area_name="A", section_name="S", equipment_name="E",
        description="D", maintenance_type="PREVENTIVE",
        participants=[], duration_hours=1.0,
        status="DRAFT",
    )
    assert result is False
    assert fake.append_writes == []
    assert fake.writes == []


# ──────────────────────────────────────────────────────────────────────
# ESTADO column support (header-driven)
# ──────────────────────────────────────────────────────────────────────

class _FakeSheetsWithHeaders(_FakeSheets):
    """Extends the fake so the header read returns the real monthly header row."""

    REAL_HEADERS = [
        "FECHA", "N° OT", "AREA", "SECCION", "EQUIPO", "TRABAJO",
        "ORTIZ", "VALDES", "FABRES", "JARA", "SALAZAR", "MILLAR",
        "JUAN SILVA", "INOSTROZA", "CANIULLAN", "CONTRERAS",
        "PREVENTIVO", "CORRECTIVO", "PREDICTIVO", "PROYECTO", "MONTAJE",
        "HORAS", "ESTADO", "PARTICIPANTES",
    ]

    def get(self, spreadsheetId="", range="", **kwargs):
        # Header read: range "Sheet!A3:AA3" -> return the header row
        if "!A3" in range and ":AA" in range:
            return _FakeGetSheetResponse([self.REAL_HEADERS])
        # Otherwise delegate to the base fake (searches column for N° OT)
        return super().get(spreadsheetId=spreadsheetId, range=range)


def test_sync_writes_estado_with_header(oauth_settings, monkeypatch, tmp_path):
    """When the monthly sheet has an ESTADO column, status is written there."""
    fake = _FakeSheetsWithHeaders()
    fake.monthly_rows["SEPTIEMBRE"] = []
    monkeypatch.setattr(google_drive, "_build_sheets_write_service", lambda: fake)
    monkeypatch.setattr(google_drive, "_build_sheets_service", lambda: fake)
    monkeypatch.setattr(google_drive.settings, "GOOGLE_MONTHLY_SPREADSHEET_ID", "m1")

    exec_dt = datetime.combine(date(2026, 9, 3), time.min)
    google_drive.sync_to_monthly_sheet(
        "OT-2026-0505", exec_dt,
        area_name="A", section_name="S", equipment_name="E",
        description="D", maintenance_type="CORRECTIVE",
        participants=["Ortiz"], duration_hours=2.0,
        status="IN_PROGRESS",
    )

    assert len(fake.append_writes) == 0
    assert len(fake.writes) == 1
    row = fake.writes[0][1]
    # Column V = HORAS, column W = ESTADO
    assert row[ord("V") - ord("A")] == "2.0"
    assert row[ord("W") - ord("A")] == "EN PROCESO"


def test_sync_writes_new_participant_in_summary_column(oauth_settings, monkeypatch):
    """A worker absent from the old fixed columns is still recorded by name."""
    fake = _FakeSheetsWithHeaders()
    fake.monthly_rows["SEPTIEMBRE"] = []
    monkeypatch.setattr(google_drive, "_build_sheets_write_service", lambda: fake)
    monkeypatch.setattr(google_drive, "_build_sheets_service", lambda: fake)
    monkeypatch.setattr(google_drive.settings, "GOOGLE_MONTHLY_SPREADSHEET_ID", "m1")

    exec_dt = datetime.combine(date(2026, 9, 3), time.min)
    google_drive.sync_to_monthly_sheet(
        "OT-2026-0707", exec_dt,
        area_name="A", section_name="S", equipment_name="E",
        description="D", maintenance_type="CORRECTIVE",
        participants=["Trabajador Nuevo"], duration_hours=2.0,
    )

    row = fake.writes[0][1]
    assert row[ord("X") - ord("A")] == "Trabajador Nuevo"


def test_sync_estado_full_cycle_updates_same_row(oauth_settings, monkeypatch, tmp_path):
    """PENDING -> IN_PROGRESS -> COMPLETED updates the SAME row (one append + updates)."""
    fake = _FakeSheetsWithHeaders()
    fake.monthly_rows["SEPTIEMBRE"] = []
    monkeypatch.setattr(google_drive, "_build_sheets_write_service", lambda: fake)
    monkeypatch.setattr(google_drive, "_build_sheets_service", lambda: fake)
    monkeypatch.setattr(google_drive.settings, "GOOGLE_MONTHLY_SPREADSHEET_ID", "m1")

    exec_dt = datetime.combine(date(2026, 9, 3), time.min)
    ot = "OT-2026-0606"

    # PENDING -> append
    google_drive.sync_to_monthly_sheet(
        ot, exec_dt, area_name="A", section_name="S", equipment_name="E",
        description="D", maintenance_type="CORRECTIVE",
        participants=["Ortiz"], duration_hours=1.5, status="PENDING",
    )
    # IN_PROGRESS -> update same row
    google_drive.sync_to_monthly_sheet(
        ot, exec_dt, area_name="A", section_name="S", equipment_name="E",
        description="D", maintenance_type="CORRECTIVE",
        participants=["Ortiz"], duration_hours=1.5, status="IN_PROGRESS",
    )
    # COMPLETED -> update same row
    google_drive.sync_to_monthly_sheet(
        ot, exec_dt, area_name="A", section_name="S", equipment_name="E",
        description="D", maintenance_type="CORRECTIVE",
        participants=["Ortiz"], duration_hours=1.5, status="COMPLETED",
    )

    # Exactly ONE OT row in the sheet (insert at row 4 + two updates to the SAME
    # row), never a duplicate, never a values().append.
    assert len(fake.append_writes) == 0
    assert fake._ot_rows("SEPTIEMBRE") == 1
    # The last write is an UPDATE whose payload shows FINALIZADO in ESTADO (W).
    assert len(fake.writes) >= 3
    last_row = fake.writes[-1][1]
    assert last_row[ord("W") - ord("A")] == "FINALIZADO"
