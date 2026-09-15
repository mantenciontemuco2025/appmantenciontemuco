"""LOTO/Bloqueo/AST selection rules shared by API and integrations."""

from collections.abc import Iterable


LOTO_CONTROL_OPTIONS = (
    "LOTO_BLOQUEO",
    "AST",
    "TARJETA_ROJA",
    "CHECKLIST_HERRAMIENTAS",
    "NOT_APPLICABLE",
)
LOTO_CONTROL_SET = frozenset(LOTO_CONTROL_OPTIONS)


def normalize_loto_controls(values: Iterable[str] | None) -> list[str] | None:
    """Normalize and validate the multi-select LOTO controls.

    ``None`` means that the caller did not send the new field (legacy client).
    An empty list is normalized to ``NOT_APPLICABLE``.  That option is
    intentionally exclusive with every other control.
    """
    if values is None:
        return None

    normalized: list[str] = []
    for value in values:
        item = str(value).strip().upper()
        if item not in LOTO_CONTROL_SET:
            allowed = ", ".join(LOTO_CONTROL_OPTIONS)
            raise ValueError(f"Opcion LOTO invalida. Use: {allowed}")
        if item not in normalized:
            normalized.append(item)

    if not normalized:
        return ["NOT_APPLICABLE"]
    if "NOT_APPLICABLE" in normalized and len(normalized) > 1:
        raise ValueError("No aplica no se puede combinar con otras opciones LOTO")
    return normalized


def controls_from_legacy_status(status: str | None) -> list[str]:
    """Provide a sensible display value for OTs created before multi-select."""
    value = (status or "NOT_APPLICABLE").upper()
    if value == "YES":
        return ["LOTO_BLOQUEO"]
    if value == "NOT_APPLICABLE":
        return ["NOT_APPLICABLE"]
    # Legacy NO remains visible through loto_status, but has no new control.
    return []


def legacy_status_from_controls(values: list[str] | None, fallback: str = "NOT_APPLICABLE") -> str:
    """Keep the old YES/NO/NOT_APPLICABLE field synchronized."""
    if values is None:
        return fallback
    if values == ["NOT_APPLICABLE"]:
        return "NOT_APPLICABLE"
    return "YES" if values else "NO"
