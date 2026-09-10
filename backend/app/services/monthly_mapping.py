"""Centralized mapping for the monthly maintenance registry sheet.

THIS FILE is the single source of truth for the monthly registry's structure:
header names, column positions, status mapping, maintenance-type mapping,
and the HORAS rule.

It re-exports the base column constants from ot_mapping.py (the existing
operational mapping) and ADDS the registry-only concepts: ESTADO column,
status mapping, header normalization, and HORAS rule helpers.

Rules (preserved):
- NEVER insert/delete rows or columns.
- NEVER change formatting, colors, or borders.
- NEVER delete tabs or existing data.
- Idempotency key: N° OT (column B) is unique.
"""

import unicodedata
from dataclasses import dataclass, field

from app.services.ot_mapping import (
    MONTHLY_COLUMN_MAP,
    MONTHLY_DATA_START_ROW,
    MONTHLY_MT_MAP,
    MONTHLY_HEADER_ROW,
    WORKER_COLUMN_KEYS,
    SPANISH_MONTHS,
    get_monthly_sheet_title,
)

__all__ = [
    "MONTHLY_COLUMN_MAP",
    "MONTHLY_MT_MAP",
    "WORKER_COLUMN_KEYS",
    "MONTHLY_DATA_START_ROW",
    "MONTHLY_HEADER_ROW",
    "MONTHLY_STATUS_MAP",
    "MONTHLY_STATUS_ORDER",
    "SPANISH_MONTHS",
    "get_monthly_sheet_title",
    # helpers
    "normalize_header",
    "resolve_monthly_columns",
    "monthly_status_text",
    "is_eligible_for_monthly",
    "compute_horas",
    "MONTHLY_LAST_COLUMN",
]

# ──────────────────────────────────────────────────────────────────────
# Status: WorkOrder.status → monthly sheet text (approved 2026-09-03)
#
#     DRAFT      ->  no sync to monthly
#     PENDING    ->  PENDIENTE
#     IN_PROGRESS->  EN PROCESO
#     COMPLETED  ->  FINALIZADO
#     CANCELLED  ->  CANCELADA
# ──────────────────────────────────────────────────────────────────────
MONTHLY_STATUS_MAP: dict[str, str] = {
    "PENDING":     "PENDIENTE",
    "IN_PROGRESS": "EN PROCESO",
    "COMPLETED":   "FINALIZADO",
    "APPROVED":    "APROBADA",
    "CANCELLED":   "CANCELADA",
}

MONTHLY_STATUS_ORDER = ["PENDIENTE", "EN PROCESO", "FINALIZADO", "APROBADA", "CANCELADA"]

# Column keys that are safe to place in the standard layout. ESTADO is a NEW
# header appended after HORAS — its letter is not in the static map, so it is
# resolved dynamically by header name. We keep the header string here.
ESTADO_HEADER = "ESTADO"
RESPONSABLE_HEADER = "RESPONSABLE"  # reserved for future responsible_user_id

# Last column currently in the standard layout (HORAS). ESTADO will be appended
# via the dynamic header resolution; this constant is used only for sizing.
MONTHLY_LAST_COLUMN = "V"  # HORAS

# ──────────────────────────────────────────────────────────────────────
# Header normalization: uppercase, strip accents, spaces, dots.
# Used to locate columns by their REAL header text (never by magic index).
# ──────────────────────────────────────────────────────────────────────
def normalize_header(text: str) -> str:
    """Normalize a header/value for comparison.

    Uppercase, drop accents AND the "°" degree symbol used in "N° OT".
    e.g. "N° OT" -> "N OT", "Juan Silva" -> "JUAN SILVA", "Sección" -> "SECCION".
    """
    nfkd = unicodedata.normalize("NFKD", str(text))
    ascii_only = "".join(c for c in nfkd if not unicodedata.combining(c))
    clean = ascii_only.strip().upper().replace(".", "").replace("°", "")
    return clean


def _expected_header(logical_key: str) -> str:
    """Return the normalized, expected real header text for a logical key."""
    expected_headers = {
        "FECHA": "FECHA", "N_O_T": "N OT", "AREA": "AREA", "SECCION": "SECCION",
        "EQUIPO": "EQUIPO", "TRABAJO": "TRABAJO",
        "ORTIZ": "ORTIZ", "VALDES": "VALDES", "FABRES": "FABRES",
        "JARA": "JARA", "SALAZAR": "SALAZAR", "MILLAR": "MILLAR",
        "JUAN_SILVA": "JUAN SILVA", "INOSTROZA": "INOSTROZA",
        "CANIULLAN": "CANIULLAN", "CONTRERAS": "CONTRERAS",
        "PREVENTIVO": "PREVENTIVO", "CORRECTIVO": "CORRECTIVO",
        "PREDICTIVO": "PREDICTIVO", "PROYECTO": "PROYECTO",
        "MONTAJE": "MONTAJE", "HORAS": "HORAS",
        "ESTADO": "ESTADO", "RESPONSABLE": "RESPONSABLE",
    }
    return normalize_header(expected_headers.get(logical_key, logical_key))


def resolve_monthly_columns(headers: list[str]) -> dict[str, str]:
    """Map logical keys -> column letter by reading the REAL header row.

    Reads the actual header cell text at each position. If a header matches a
    known logical key, that column letter is used. Otherwise falls back to the
    static MONTHLY_COLUMN_MAP position. Header-driven first, static fallback.

    `headers` is the list of header cell values from the read (any length);
    unknown trailing columns beyond the static map are still resolved if their
    header matches a known key (e.g. ESTADO appended after HORAS).
    """
    col_by_header: dict[str, str] = {}
    for idx, header in enumerate(headers):
        h_text = normalize_header(header)
        if h_text:
            col_by_header[h_text] = chr(ord("A") + idx)

    # Known logical keys we care about, in a canonical order.
    all_keys = list(MONTHLY_COLUMN_MAP.keys()) + ["ESTADO", "RESPONSABLE"]

    resolved: dict[str, str] = {}
    for logical in all_keys:
        exp = _expected_header(logical)
        matched = col_by_header.get(exp)
        if matched:
            resolved[logical] = matched
        elif logical in MONTHLY_COLUMN_MAP:
            # Static fallback for the standard layout columns.
            resolved[logical] = MONTHLY_COLUMN_MAP[logical]
        # ESTADO / RESPONSABLE have no static position (they sit after HORAS);
        # if not found by header, they are simply absent from `resolved`.
    return resolved


# ──────────────────────────────────────────────────────────────────────
# Eligibility: which WorkOrder.status values can be synced to the monthly sheet.
# DRAFT is intentionally excluded.
# ──────────────────────────────────────────────────────────────────────
def is_eligible_for_monthly(status: str | None) -> bool:
    """Return True if a WorkOrder status should produce/update a monthly row.

    DRAFT -> False (never sync a draft). All others -> True (Pending maps too).
    """
    return (status or "DRAFT").upper() in MONTHLY_STATUS_MAP


def monthly_status_text(status: str | None) -> str:
    """Map a WorkOrder status to its monthly-sheet text.

    DRAFT -> "DRAFT" (should not be reached; guarded by is_eligible_for_monthly).
    Unknown values -> the raw status string, uppercased.
    """
    s = (status or "PENDING").upper()
    return MONTHLY_STATUS_MAP.get(s, s)


# ──────────────────────────────────────────────────────────────────────
# HORAS rule (approved 2026-09-03)
#
# Current data model has only `estimated_time` (text). We show:
#   HORAS = estimated_time parsed to numeric hours.
#
# Architecture is PREPARED for future real-time tracking:
#   started_at, completed_at, actual_duration_minutes, completed_by_user_id.
# When actual_duration_minutes exists:
#   - if status is COMPLETED and actual_duration_minutes is set:
#       HORAS = actual_duration_minutes / 60
#   - otherwise:
#       HORAS = estimated_time parsed.
#
# The `compute_horas` helper reads both sources so the future switch is a
# one-line change once the fields exist. No real-time tracking is implemented
# in this phase.
# ──────────────────────────────────────────────────────────────────────
@dataclass
class HorasInput:
    """Input for the HORAS rule. Fields for future real-time tracking are
    optional placeholders — they are not populated by the current sync."""
    estimated_minutes: float = 0.0            # parsed from estimated_time
    status: str = "PENDING"
    actual_duration_minutes: float | None = None  # future field


def compute_horas(data: HorasInput) -> float:
    """Compute the numeric HORAS value for a monthly row.

    Rules:
      1. If status == COMPLETED and actual_duration_minutes is set
         (the future real-time path): HORAS = actual_duration_minutes / 60.
      2. Otherwise (current): HORAS = estimated_time parsed to hours.
    """
    if data.status.upper() == "COMPLETED" and data.actual_duration_minutes is not None:
        return round(data.actual_duration_minutes / 60, 2)
    # Current path: estimated time.
    minutes = data.estimated_minutes or 0.0
    return round(minutes / 60, 2) if minutes else 0.0