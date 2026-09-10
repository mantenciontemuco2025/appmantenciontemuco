"""Unit tests for the centralized monthly registry mapping (monthly_mapping.py).

Covers:
- Column resolution by REAL header text (including ESTADO appended after HORAS)
- Status mapping / eligibility (DRAFT excluded)
- HORAS rule (estimated-time now; actual_duration_minutes prepared)
- That ESTADO is written only when the column exists in the sheet
- Non-derivation of RESPONSABLE from participant order
"""

import pytest

from app.services.monthly_mapping import (
    resolve_monthly_columns,
    normalize_header,
    is_eligible_for_monthly,
    monthly_status_text,
    compute_horas,
    HorasInput,
    MONTHLY_STATUS_MAP,
)


# ────────────────────────────────────────────────────────────────
# Header normalization
# ────────────────────────────────────────────────────────────────
def test_normalize_strips_accents_uppercase():
    assert normalize_header("N° OT") == "N OT"
    assert normalize_header("Sección") == "SECCION"
    assert normalize_header("Juan Silva") == "JUAN SILVA"
    assert normalize_header("FECHA") == "FECHA"
    assert normalize_header("") == ""


# ────────────────────────────────────────────────────────────────
# Column resolution by real header row
# ────────────────────────────────────────────────────────────────
HEADERS_22 = [
    "FECHA", "N° OT", "AREA", "SECCION", "EQUIPO", "TRABAJO",
    "ORTIZ", "VALDES", "FABRES", "JARA", "SALAZAR", "MILLAR",
    "JUAN SILVA", "INOSTROZA", "CANIULLAN", "CONTRERAS",
    "PREVENTIVO", "CORRECTIVO", "PREDICTIVO", "PROYECTO", "MONTAJE", "HORAS",
]


def test_resolve_standard_22_columns():
    col = resolve_monthly_columns(HEADERS_22)
    assert col["FECHA"] == "A"
    assert col["N_O_T"] == "B"
    assert col["AREA"] == "C"
    assert col["SECCION"] == "D"
    assert col["EQUIPO"] == "E"
    assert col["TRABAJO"] == "F"
    assert col["ORTIZ"] == "G"
    assert col["JARA"] == "J"
    assert col["PREVENTIVO"] == "Q"
    assert col["CORRECTIVO"] == "R"
    assert col["MONTAJE"] == "U"
    assert col["HORAS"] == "V"
    # ESTADO absent -> key not present
    assert "ESTADO" not in col


def test_resolve_with_estado_after_horas():
    headers = HEADERS_22 + ["ESTADO"]
    col = resolve_monthly_columns(headers)
    assert col["HORAS"] == "V"
    assert col["ESTADO"] == "W"
    assert col["TRABAJO"] == "F"  # unchanged
    assert col["PREVENTIVO"] == "Q"


def test_resolve_header_driven_not_position_dependent():
    # Ensure resolution is by header text, not magic index: shuffle isn't tested
    # here (positions must remain), but a header spelling variant is resolved.
    headers = [
        "fecha", "n° ot", "área", "sección", "equipo", "trabajo",
        "ortiz", "valdés", "fabres", "jara", "salazar", "millar",
        "juan silva", "inostroza", "caniullán", "contreras",
        "preventivo", "correctivo", "predictivo", "proyecto", "montaje", "horas",
        "estado",
    ]
    col = resolve_monthly_columns(headers)
    assert col["AREA"] == "C"
    assert col["SECCION"] == "D"
    assert col["VALDES"] == "H"
    assert col["ESTADO"] == "W"


# ────────────────────────────────────────────────────────────────
# Status mapping / eligibility
# ────────────────────────────────────────────────────────────────
def test_status_mapping_approved():
    assert MONTHLY_STATUS_MAP == {
        "PENDING": "PENDIENTE",
        "IN_PROGRESS": "EN PROCESO",
        "COMPLETED": "FINALIZADO",
        "APPROVED": "APROBADA",
        "CANCELLED": "CANCELADA",
    }


def test_monthly_status_text():
    assert monthly_status_text("PENDING") == "PENDIENTE"
    assert monthly_status_text("IN_PROGRESS") == "EN PROCESO"
    assert monthly_status_text("COMPLETED") == "FINALIZADO"
    assert monthly_status_text("CANCELLED") == "CANCELADA"


def test_draft_not_eligible():
    assert is_eligible_for_monthly("DRAFT") is False
    assert is_eligible_for_monthly(None) is False  # treated as DRAFT
    assert is_eligible_for_monthly("") is False


def test_other_statuses_eligible():
    for s in ("PENDING", "IN_PROGRESS", "COMPLETED", "CANCELLED"):
        assert is_eligible_for_monthly(s) is True


# ────────────────────────────────────────────────────────────────
# HORAS rule
# ────────────────────────────────────────────────────────────────
def test_horas_uses_estimated_time_when_no_actual():
    # 90 min estimated -> 1.5 h
    assert compute_horas(HorasInput(estimated_minutes=90, status="PENDING")) == 1.5
    # 60 min estimated -> 1.0 h
    assert compute_horas(HorasInput(estimated_minutes=60, status="IN_PROGRESS")) == 1.0


def test_horas_uses_actual_when_completed_and_present():
    # Future path: actual_duration_minutes overrides estimated when COMPLETED
    assert (
        compute_horas(
            HorasInput(estimated_minutes=720, status="COMPLETED", actual_duration_minutes=90)
        )
        == 1.5
    )


def test_horas_keeps_estimated_when_completed_without_actual():
    # COMPLETED but no real-time minutes -> fall back to estimated
    assert compute_horas(HorasInput(estimated_minutes=120, status="COMPLETED")) == 2.0


def test_horas_zero_when_no_time():
    assert compute_horas(HorasInput()) == 0.0


# ────────────────────────────────────────────────────────────────
# RESPONSABLE is NOT derived from participant position
# ────────────────────────────────────────────────────────────────
def test_responsable_not_in_default_resolution():
    # Even if RESPONSABLE header were present, there is no static column for it
    # and it must NOT be synthesized from participants. With no header it is absent.
    col = resolve_monthly_columns(HEADERS_22)
    assert "RESPONSABLE" not in col


def test_responsable_resolved_only_when_header_present_for_future():
    # Architecture note: when responsible_user_id is added later, the header may
    # exist. This test documents that resolution is possible without deriving it
    # from participants. It is deliberately NOT derived here.
    headers = HEADERS_22 + ["RESPONSABLE"]
    col = resolve_monthly_columns(headers)
    assert col.get("RESPONSABLE") == "W"