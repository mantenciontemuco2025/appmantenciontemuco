from app.core.loto import (
    controls_from_legacy_status,
    legacy_status_from_controls,
    normalize_loto_controls,
)
from app.services.ot_mapping import build_loto_control_cell_texts


def test_loto_controls_allow_multiple_options():
    selected = normalize_loto_controls(["ast", "LOTO_BLOQUEO", "AST"])

    assert selected == ["AST", "LOTO_BLOQUEO"]
    assert legacy_status_from_controls(selected) == "YES"


def test_no_aplica_is_exclusive_and_empty_defaults_to_it():
    assert normalize_loto_controls([]) == ["NOT_APPLICABLE"]

    try:
        normalize_loto_controls(["AST", "NOT_APPLICABLE"])
    except ValueError as exc:
        assert "No aplica" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("No aplica debe ser exclusiva")


def test_legacy_loto_status_is_available_to_new_clients():
    assert controls_from_legacy_status("YES") == ["LOTO_BLOQUEO"]
    assert controls_from_legacy_status("NOT_APPLICABLE") == ["NOT_APPLICABLE"]


def test_google_loto_layout_writes_two_lines_without_changing_cells():
    cells = build_loto_control_cell_texts(["LOTO_BLOQUEO", "AST", "TARJETA_ROJA"])

    assert set(cells) == {"C10", "D10", "E10"}
    assert "[X] LOTO / Bloqueo" in cells["C10"]
    assert "[X] AST" in cells["C10"]
    assert "[X] Tarjeta roja" in cells["D10"]
    assert "[ ] Checklist herramientas" in cells["D10"]
    assert cells["E10"] == "[ ] No aplica"
