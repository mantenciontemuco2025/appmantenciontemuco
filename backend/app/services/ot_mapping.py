"""Centralized mapping between Work Order fields and Google Sheets cells.

ALL cell coordinates live here. Other modules import from this file —
no coordinates are scattered in google_drive.py, google_sheets.py, or routes.

Source of truth: the PLANTILLA_OT tab of the OT template spreadsheet
(GOOGLE_OT_TEMPLATE_FILE_ID), verified via live audit on 2026-09-09.

Rules:
- For merged cells, write to the TOP-LEFT cell of the merge.
- Never insert/delete rows or columns.
- Never change formatting, colors, or borders, except the dedicated
  authorization blocks when a handwritten signature must be rendered.
- Checkbox fields in this template are SEPARATE un-merged cells (one option
  per cell): write "[X] Label" into the selected option's cell and
  "[ ] Label" into every other option's cell.
"""

# ──────────────────────────────────────────────────────────────────────
# OT Template: text field → cell (top-left of merged range / value cell)
# ──────────────────────────────────────────────────────────────────────
# Current layout (live audit on 2026-09-09). Sección now has its own row, so
# every field below it moved down one row. Value cells are the blank cells
# right of / under the label.
OT_FIELD_MAP: dict[str, str] = {
    "ot_number":          "G2",       # G2:G4 merged — N° OT
    "area":               "C6",       # C6:D6 merged — Área (label B6)
    "section":            "C7",       # C7:G7 merged — Sección (label B7)
    "equipment":          "C8",       # C8:G8 merged — Equipo intervenido (label B8)
    "folio":              "G10",      # value next to "Folio:" label (F10)
    "description":        "B12",      # B12:G14 merged — Descripción del trabajo (label B11)
    "participants":       "C15",      # C15:G15 merged — Responsable(s)
    "responsible":        "C15",      # alias: Responsable(s) same cell as participants
    "estimated_time":     "C16",      # C16:G16 merged — Tiempo estimado (label B16)
    "execution_date":     "F17",      # F17:G17 merged — Fecha ejecución (label E17)
    "request_date":       "C17",      # C17:D17 merged — Fecha Solicitud (label B17)
    "resources_required": "B19",      # B19:G20 merged — value block under "RECURSOS..." (B18)
    "voucher_number":     "C21",      # value next to "N° de vale:" label (B21)
    "risks":              "B23",      # B23:G24 merged — value block under "RIESGOS..." (B22)
    "observations":       "B27",      # B27:G28 merged — value block under "OBSERVACIONES" (B26)
    "requested_by":       "B31",      # B31:D33 — "SOLICITADO POR:..." (label+firma built by app)
    "approved_by":        "E31",      # E31:G33 — "REALIZADO POR:..." (label+firma built by app)
    "performed_by":       "E31",      # alias of approved_by (REALIZADO POR) — E31:G33
}

# ── Autorización cell text (requested_by / realized_by) ────────────────────────
# The new template puts the label + "Firma digital" line inside the merged cell
# (B31:D33 / E31:G33). To show who requested/completed WITHOUT destroying the
# label, the app writes the full text: "SOLICITADO POR: <nombre>\n\nFirma digital: ____".
REQUESTED_BY_LABEL = "SOLICITADO POR:"
REALIZADO_BY_LABEL = "REALIZADO POR:"
FIRMA_DIGITAL_LINE = "Firma digital: ________________________"

# Alias for backwards compatibility (legacy code may reference APPROVED_BY_LABEL)
APPROVED_BY_LABEL = REALIZADO_BY_LABEL


def build_authorization_text(role_label: str, name: str) -> str:
    """Build the full autorización cell text (label + name + firma line).

    Example: build_authorization_text("SOLICITADO POR:", "Juan") ->
      "SOLICITADO POR: Juan\n\nFirma digital: ________________________"
    """
    name = (name or "").strip()
    if not name:
        return f"{role_label}\n\n{FIRMA_DIGITAL_LINE}"
    return f"{role_label} {name}\n\n{FIRMA_DIGITAL_LINE}"

# ──────────────────────────────────────────────────────────────────────
# OT Template: maintenance type checkboxes (row 9)
#
# In this template the options are SEPARATE un-merged cells (C9:G9 are not
# merged; C6:G6 / C7:G7 / C8:G8 above are merged). Each
# option lives in its own cell. To mark one, write "[X] Label" to that
# option's cell and "[ ] Label" to every other option cell.
# ──────────────────────────────────────────────────────────────────────
MAINTENANCE_TYPE_CELLS: dict[str, str] = {
    "PREVENTIVE": "C9",
    "CORRECTIVE": "D9",
    "PREDICTIVE": "E9",
    "PROYECTO":   "F9",
    "MONTAJE":    "G9",
}

# Cells that hold stale maintenance-type text and must be cleared when we
# rewrite the type row (all 5 option cells).
MAINTENANCE_TYPE_CLEAR_CELLS = list(MAINTENANCE_TYPE_CELLS.values())

# Backwards-compatible alias: the anchor/maintenance cell (used by tests/tools).
MAINTENANCE_TYPE_CELL = "C9"

_MAINTENANCE_LABELS = {
    "PREVENTIVE": "Preventivo",
    "CORRECTIVE": "Correctivo",
    "PREDICTIVE": "Predictivo",
    "PROYECTO":   "Proyecto",
    "MONTAJE":    "Montaje",
}

_MAINTENANCE_ORDER = ["PREVENTIVE", "CORRECTIVE", "PREDICTIVE", "PROYECTO", "MONTAJE"]


def build_maintenance_type_text(selected: str) -> str:
    """Build the full combined checkbox text (old merged-cell contract).

    Example: build_maintenance_type_text("CORRECTIVE") returns:
    "[ ] Preventivo  [X] Correctivo  [ ] Predictivo  [ ] Proyecto  [ ] Montaje"
    """
    sel = selected.upper()
    parts = []
    for key in _MAINTENANCE_ORDER:
        label = _MAINTENANCE_LABELS[key]
        mark = "X" if key == sel else " "
        parts.append(f"[{mark}] {label}")
    return "  ".join(parts)


def build_maintenance_cell_texts(selected: str) -> dict[str, str]:
    """Return {A1 cell: text} for EACH maintenance-type option cell.

    This template keeps each option in its own un-merged cell, so each cell
    gets its OWN label with [X] only on the selected option, [ ] elsewhere.

    Example: build_maintenance_cell_texts("CORRECTIVE") ->
      {"C9": "[ ] Preventivo", "D9": "[X] Correctivo", "E9": "[ ] Predictivo",
       "F9": "[ ] Proyecto", "G9": "[ ] Montaje"}
    """
    sel = selected.upper()
    return {
        cell: f"[{mark}] {_MAINTENANCE_LABELS[key]}"
        for key, cell in MAINTENANCE_TYPE_CELLS.items()
        for mark in ["X" if key == sel else " "]
    }


# ──────────────────────────────────────────────────────────────────────
# OT Template: LOTO checkboxes (row 10)
#
# Same per-cell pattern as maintenance type: C10:E10 are separate cells.
# ──────────────────────────────────────────────────────────────────────
LOTO_CELLS: dict[str, str] = {
    "YES":            "C10",
    "NO":             "D10",
    "NOT_APPLICABLE": "E10",
}

# Cells that hold stale LOTO text and must be cleared when rewritten.
LOTO_CLEAR_CELLS = list(LOTO_CELLS.values())

# Backwards-compatible alias.
LOTO_CELL = "C10"

_LOTO_LABELS = {
    "YES":            "Sí",
    "NO":             "No",
    "NOT_APPLICABLE": "No aplica",
}

_LOTO_ORDER = ["YES", "NO", "NOT_APPLICABLE"]


def build_loto_text(selected: str) -> str:
    """Build the full combined LOTO text (old merged-cell contract).

    Example: build_loto_text("YES") returns:
    "[X] Sí  [ ] No  [ ] No aplica"
    """
    sel = selected.upper()
    parts = []
    for key in _LOTO_ORDER:
        label = _LOTO_LABELS[key]
        mark = "X" if key == sel else " "
        parts.append(f"[{mark}] {label}")
    return "  ".join(parts)


def build_loto_cell_texts(selected: str) -> dict[str, str]:
    """Return {A1 cell: text} for EACH LOTO option cell (per-cell template).

    Example: build_loto_cell_texts("YES") ->
      {"C10": "[X] Sí", "D10": "[ ] No", "E10": "[ ] No aplica"}
    """
    sel = selected.upper()
    return {
        cell: f"[{mark}] {_LOTO_LABELS[key]}"
        for key, cell in LOTO_CELLS.items()
        for mark in ["X" if key == sel else " "]
    }


# ──────────────────────────────────────────────────────────────────────
# OT Template: status checkboxes (row 36)
#
# The status row is B36:G36. In this template the option text lives in B36
# (single cell, wide spacing between options) — matching the old merged-cell
# contract (one string with [ ] PENDIENTE... [ ] EN PROCESO... [ ] FINALIZADO).
# ──────────────────────────────────────────────────────────────────────
STATUS_CELL = "B36"

_STATUS_LABELS = {
    "PENDING":     "PENDIENTE",
    "IN_PROGRESS": "EN PROCESO",
    "COMPLETED":   "FINALIZADO",
}

_STATUS_ORDER = ["PENDING", "IN_PROGRESS", "COMPLETED"]


def build_status_text(selected: str) -> str:
    """Build the full checkbox text for the status row.

    Matches the template's spacing: 12 spaces between options.
    Example: build_status_text("PENDING") returns:
    "[X] PENDIENTE            [ ] EN PROCESO            [ ] FINALIZADO"
    """
    sel = (selected or "").upper()
    # The individual OT template has checkboxes for the three operational
    # states above. Approved and cancelled are terminal workflow states and do
    # not have a checkbox in the current master template; keep them visible
    # instead of leaving every checkbox apparently unselected.
    if sel == "APPROVED":
        return "ESTADO: APROBADA"
    if sel == "CANCELLED":
        return "ESTADO: CANCELADA"

    parts = []
    for key in _STATUS_ORDER:
        label = _STATUS_LABELS[key]
        mark = "X" if key == sel else " "
        parts.append(f"[{mark}] {label}")
    return "            ".join(parts)


# ──────────────────────────────────────────────────────────────────────
# Monthly tracking sheet: column letter → header text
#
# Source: row 3 of the SEPTIEMBRE tab, read from the real sheet.
# Columns are identified by HEADER TEXT, not by magic index.
# ──────────────────────────────────────────────────────────────────────
MONTHLY_HEADER_ROW = 3  # Row containing column headers
MONTHLY_DATA_START_ROW = 4  # First data row (header row + 1)

MONTHLY_COLUMN_MAP: dict[str, str] = {
    "FECHA":        "A",
    "N_O_T":        "B",
    "AREA":         "C",
    "SECCION":      "D",
    "EQUIPO":       "E",
    "TRABAJO":      "F",
    "ORTIZ":        "G",
    "VALDES":       "H",
    "FABRES":       "I",
    "JARA":         "J",
    "SALAZAR":      "K",
    "MILLAR":       "L",
    "JUAN_SILVA":   "M",
    "INOSTROZA":    "N",
    "CANIULLAN":    "O",
    "CONTRERAS":    "P",
    "PREVENTIVO":   "Q",
    "CORRECTIVO":   "R",
    "PREDICTIVO":   "S",
    "PROYECTO":     "T",
    "MONTAJE":      "U",
    "HORAS":        "V",
}

# Worker column keys → MONTHLY_COLUMN_MAP key
# Maps participant name (normalized, uppercase, no accents) to column key.
WORKER_COLUMN_KEYS: dict[str, str] = {
    "ORTIZ":       "ORTIZ",
    "VALDES":      "VALDES",
    "FABRES":      "FABRES",
    "JARA":        "JARA",
    "SALAZAR":     "SALAZAR",
    "MILLAR":      "MILLAR",
    "JUAN SILVA":  "JUAN_SILVA",
    "INOSTROZA":   "INOSTROZA",
    "CANIULLAN":   "CANIULLAN",
    "CONTRERAS":   "CONTRERAS",
}

# Maintenance type enum → monthly sheet column key
MONTHLY_MT_MAP: dict[str, str] = {
    "PREVENTIVE":  "PREVENTIVO",
    "CORRECTIVE":  "CORRECTIVO",
    "PREDICTIVE":  "PREDICTIVO",
    "PROYECTO":    "PROYECTO",
    "MONTAJE":     "MONTAJE",
}

# Last column in the monthly sheet (for row sizing)
MONTHLY_LAST_COLUMN = "V"  # HORAS


# ──────────────────────────────────────────────────────────────────────
# Spanish month names (for sheet tab titles)
# ──────────────────────────────────────────────────────────────────────
SPANISH_MONTHS = [
    "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
    "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE",
]


def get_monthly_sheet_title(month_index: int) -> str:
    """Return the tab name for a given month (1=ENERO, 12=DICIEMBRE)."""
    return SPANISH_MONTHS[month_index - 1]


# ──────────────────────────────────────────────────────────────────────
# Legacy signature anchors retained temporarily for older imports.
# ──────────────────────────────────────────────────────────────────────
# Each anchor defines the cell where the signature image will be overlaid,
# its zero-based row/col indices, and default image dimensions in pixels.
# These can be adjusted per-template without changing google_drive logic.
SIGNATURE_ANCHORS: dict[str, dict] = {
    "requested_by": {
        "cell": "B31",
        "row": 30,      # zero-based (B31 is row 31 -> index 30)
        "col": 1,       # zero-based (B is column 2 -> index 1)
        "width_px": 200,
        "height_px": 80,
        "offset_y_px": 40,  # push down so text ("SOLICITADO POR: ...") stays visible above
    },
    "realized_by": {
        "cell": "E31",
        "row": 30,      # E31 is row 31 -> index 30
        "col": 4,       # E is column 5 -> index 4
        "width_px": 200,
        "height_px": 80,
        "offset_y_px": 40,
    },
}


def get_signature_anchor(field: str) -> dict:
    """Return the anchor config for a signature field ('requested_by' or 'realized_by')."""
    return SIGNATURE_ANCHORS.get(field, {})


# Sheets REST cannot create a floating image from a URL. These ranges split an
# authorization block into a one-row title and a two-row =IMAGE() area. Grid
# indexes are zero-based.
SIGNATURE_BLOCKS: dict[str, dict[str, dict[str, int]]] = {
    "requested_by": {
        "whole": {"start_row": 30, "end_row": 33, "start_col": 1, "end_col": 4},
        "label": {"start_row": 30, "end_row": 31, "start_col": 1, "end_col": 4},
        "image": {"start_row": 31, "end_row": 33, "start_col": 1, "end_col": 4},
    },
    "performed_by": {
        "whole": {"start_row": 30, "end_row": 33, "start_col": 4, "end_col": 7},
        "label": {"start_row": 30, "end_row": 31, "start_col": 4, "end_col": 7},
        "image": {"start_row": 31, "end_row": 33, "start_col": 4, "end_col": 7},
    },
    # Legacy wire name used by the already deployed Apps Script. The visual
    # block is still REALIZADO POR and is only filled on worker completion.
    "approved_by": {
        "whole": {"start_row": 30, "end_row": 33, "start_col": 4, "end_col": 7},
        "label": {"start_row": 30, "end_row": 31, "start_col": 4, "end_col": 7},
        "image": {"start_row": 31, "end_row": 33, "start_col": 4, "end_col": 7},
    },
}


def get_signature_block(field: str) -> dict[str, dict[str, int]]:
    return SIGNATURE_BLOCKS.get(field, {})
