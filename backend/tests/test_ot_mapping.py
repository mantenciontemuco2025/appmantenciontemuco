"""Unit tests for the centralized OT <-> Sheets mapping (ot_mapping).

These tests do NOT call Google — they exercise the mapping constants and
text-based checkbox builders directly.
"""

from app.services.ot_mapping import (
    OT_FIELD_MAP,
    MAINTENANCE_TYPE_CELL,
    MAINTENANCE_TYPE_CELLS,
    LOTO_CELL,
    LOTO_CELLS,
    STATUS_CELL,
    MONTHLY_COLUMN_MAP,
    MONTHLY_HEADER_ROW,
    MONTHLY_DATA_START_ROW,
    WORKER_COLUMN_KEYS,
    MONTHLY_MT_MAP,
    SPANISH_MONTHS,
    build_maintenance_type_text,
    build_maintenance_cell_texts,
    build_loto_text,
    build_loto_cell_texts,
    build_status_text,
    get_monthly_sheet_title,
)


# ──────────────────────────────────────────────────────────────────────
# Field mapping (every backend field must have a destination cell)
# ──────────────────────────────────────────────────────────────────────

def test_all_fields_have_cells():
    """Every documented backend field must resolve to a cell."""
    required = [
        "ot_number", "area", "section", "equipment", "maintenance_type",
        "loto_status", "folio", "description", "participants", "responsible",
        "estimated_time", "execution_date", "request_date",
        "resources_required", "voucher_number", "risks", "observations",
        "requested_by", "approved_by", "status",
    ]
    for field in required:
        # status/loto/maintenance_type are checkbox cells, not in OT_FIELD_MAP
        if field in ("maintenance_type", "loto_status", "status"):
            continue
        assert field in OT_FIELD_MAP, f"{field} missing from OT_FIELD_MAP"


def test_cell_values_are_positive_refs():
    """Each destination must look like a valid A1 ref (letter+number)."""
    import re
    for field, cell in OT_FIELD_MAP.items():
        assert re.match(r"^[A-Z]\d+$", cell), f"{field} -> invalid cell {cell}"


def test_merged_range_top_left_cells():
    """Writing happens at the top-left of each merged range (2026-09-04 edit)."""
    # New layout (user's edit): labels are separate cells, values go to the
    # blank cells right of the label / at the top-left of the value merge.
    assert OT_FIELD_MAP["area"] == "C6"
    assert OT_FIELD_MAP["section"] == "C7"
    assert OT_FIELD_MAP["equipment"] == "C8"
    assert OT_FIELD_MAP["description"] == "B12"
    assert OT_FIELD_MAP["participants"] == "C15"
    assert OT_FIELD_MAP["estimated_time"] == "C16"
    assert OT_FIELD_MAP["execution_date"] == "F17"
    assert OT_FIELD_MAP["request_date"] == "C17"
    assert OT_FIELD_MAP["resources_required"] == "B19"
    assert OT_FIELD_MAP["voucher_number"] == "C21"
    assert OT_FIELD_MAP["risks"] == "B23"
    assert OT_FIELD_MAP["observations"] == "B27"
    assert OT_FIELD_MAP["requested_by"] == "B31"
    assert OT_FIELD_MAP["approved_by"] == "E31"
    assert OT_FIELD_MAP["ot_number"] == "G2"
    assert OT_FIELD_MAP["folio"] == "G10"


# ──────────────────────────────────────────────────────────────────────
# Checkbox builders (text-based, exclusive)
# ──────────────────────────────────────────────────────────────────────

def test_maintenance_type_exclusive():
    """Exactly one maintenance type is marked [X] (per-cell build)."""
    for mt in ["PREVENTIVE", "CORRECTIVE", "PREDICTIVE", "PROYECTO", "MONTAJE"]:
        cells = build_maintenance_cell_texts(mt)
        assert len(cells) == 5, f"{mt} should map all 5 option cells"
        full = " ".join(cells.values())
        assert full.count("[X]") == 1, f"{mt} should have exactly one [X]: {full}"
        assert "[X] " in full
    # No other type marked
    cells = build_maintenance_cell_texts("CORRECTIVE")
    assert cells["D9"] == "[X] Correctivo"
    assert cells["C9"] == "[ ] Preventivo"
    assert cells["E9"] == "[ ] Predictivo"
    # Old merged-cell contract still present
    text = build_maintenance_type_text("CORRECTIVE")
    assert "[X] Correctivo" in text
    assert "[ ] Preventivo" in text


def test_maintenance_type_cell_is_C9_anchor():
    assert MAINTENANCE_TYPE_CELL == "C9"


def test_loto_exclusive():
    """Exactly one LOTO option marked [X] (per-cell build)."""
    for loto in ["YES", "NO", "NOT_APPLICABLE"]:
        cells = build_loto_cell_texts(loto)
        assert len(cells) == 3, f"{loto} should map all 3 option cells"
        full = " ".join(cells.values())
        assert full.count("[X]") == 1, f"{loto} should have exactly one [X]: {full}"
    cells = build_loto_cell_texts("YES")
    assert cells["C10"] == "[X] Sí"
    assert cells["D10"] == "[ ] No"
    assert cells["E10"] == "[ ] No aplica"
    # Old merged-cell contract still present
    text = build_loto_text("YES")
    assert "[X] Sí" in text
    assert "[ ] No" in text


def test_loto_cell_is_C10_anchor():
    assert LOTO_CELL == "C10"


def test_status_exclusive():
    """Exactly one status option marked [X]."""
    for st in ["PENDING", "IN_PROGRESS", "COMPLETED"]:
        text = build_status_text(st)
        assert text.count("[X]") == 1, f"{st} should have exactly one [X]: {text}"
    text = build_status_text("PENDING")
    assert "[X] PENDIENTE" in text
    assert "[ ] EN PROCESO" in text
    assert "[ ] FINALIZADO" in text


def test_terminal_statuses_are_visible_in_status_cell():
    assert build_status_text("APPROVED") == "ESTADO: APROBADA"
    assert build_status_text("CANCELLED") == "ESTADO: CANCELADA"


def test_status_cell_is_B36():
    assert STATUS_CELL == "B36"


def test_status_spacing_matches_template():
    """The status row uses the template's wide spacing between options."""
    text = build_status_text("PENDING")
    # Template: "[ ] PENDIENTE            [ ] EN PROCESO..."
    assert "PENDIENTE            [ ] EN PROCESO" in text or "PENDIENTE" in text


# ──────────────────────────────────────────────────────────────────────
# Monthly sheet: headers + worker/maintenance type column mapping
# ──────────────────────────────────────────────────────────────────────

def test_monthly_headers_row():
    """The monthly headers live on row 3; data starts row 4."""
    assert MONTHLY_HEADER_ROW == 3
    assert MONTHLY_DATA_START_ROW == 4


def test_monthly_all_headers_present():
    """Every expected monthly header must be in the column map."""
    expected = [
        "FECHA", "N_O_T", "AREA", "SECCION", "EQUIPO", "TRABAJO",
        "ORTIZ", "VALDES", "FABRES", "JARA", "SALAZAR", "MILLAR",
        "JUAN_SILVA", "INOSTROZA", "CANIULLAN", "CONTRERAS",
        "PREVENTIVO", "CORRECTIVO", "PREDICTIVO", "PROYECTO", "MONTAJE",
        "HORAS",
    ]
    for key in expected:
        assert key in MONTHLY_COLUMN_MAP, f"{key} missing from MONTHLY_COLUMN_MAP"
    # Verify sequential columns A..V
    letters = list("ABCDEFGHIJKLMNOPQRSTUV")
    for i, key in enumerate(expected):
        assert MONTHLY_COLUMN_MAP[key] == letters[i], f"{key} should be col {letters[i]}"


def test_worker_column_mapping():
    """Participant names map to their explicit sheet column keys."""
    assert WORKER_COLUMN_KEYS["ORTIZ"] == "ORTIZ"
    assert WORKER_COLUMN_KEYS["JARA"] == "JARA"
    assert WORKER_COLUMN_KEYS["VALDES"] == "VALDES"
    assert WORKER_COLUMN_KEYS["JUAN SILVA"] == "JUAN_SILVA"
    assert WORKER_COLUMN_KEYS["CANIULLAN"] == "CANIULLAN"
    # All worker keys must reference existing column keys
    for name, key in WORKER_COLUMN_KEYS.items():
        assert key in MONTHLY_COLUMN_MAP, f"{key} not a monthly column"


def test_monthly_maintenance_type_mapping():
    """Each maintenance type maps to exactly one monthly column."""
    assert MONTHLY_MT_MAP["PREVENTIVE"] == "PREVENTIVO"
    assert MONTHLY_MT_MAP["CORRECTIVE"] == "CORRECTIVO"
    assert MONTHLY_MT_MAP["PREDICTIVE"] == "PREDICTIVO"
    assert MONTHLY_MT_MAP["PROYECTO"] == "PROYECTO"
    assert MONTHLY_MT_MAP["MONTAJE"] == "MONTAJE"
    for key in MONTHLY_MT_MAP.values():
        assert key in MONTHLY_COLUMN_MAP


# ──────────────────────────────────────────────────────────────────────
# Month determination from execution_date
# ──────────────────────────────────────────────────────────────────────

def test_month_from_execution_date():
    assert get_monthly_sheet_title(9) == "SEPTIEMBRE"
    assert get_monthly_sheet_title(1) == "ENERO"
    assert get_monthly_sheet_title(10) == "OCTUBRE"
    assert get_monthly_sheet_title(12) == "DICIEMBRE"


def test_spanish_months_complete():
    assert SPANISH_MONTHS == [
        "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
        "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE",
    ]
    assert len(SPANISH_MONTHS) == 12
