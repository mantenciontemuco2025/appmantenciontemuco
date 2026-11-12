import calendar
from datetime import date


PERIODICITY_MONTHS = {
    "MONTHLY": 1,
    "QUARTERLY": 3,
    "SEMIANNUAL": 6,
    "ANNUAL": 12,
}


def add_months(value: date, months: int) -> date:
    """Add calendar months while keeping the day valid at month ends."""
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def periodicity_from_template(value: str | None) -> tuple[str | None, int | None]:
    if not value:
        return None, None
    normalized = " ".join(value.strip().upper().split())
    mapping = {
        "MENSUAL": ("MONTHLY", 1),
        "TRIMESTRAL": ("QUARTERLY", 3),
        "SEMESTRAL": ("SEMIANNUAL", 6),
        "ANUAL": ("ANNUAL", 12),
        "MONTHLY": ("MONTHLY", 1),
        "QUARTERLY": ("QUARTERLY", 3),
        "SEMIANNUAL": ("SEMIANNUAL", 6),
        "ANNUAL": ("ANNUAL", 12),
    }
    return mapping.get(normalized, (None, None))


def preventive_source_key(source_plan_id: str | None, item: object) -> str:
    """Build a stable idempotency key for template rows, even with blank Id_prev."""
    import hashlib

    if source_plan_id and source_plan_id.strip():
        return f"template:id:{source_plan_id.strip()}"
    equipment_id = getattr(item, "equipment_inventory_id", "").strip()
    frequency = getattr(item, "periodicity", "") or ""
    description = getattr(item, "description", "") or ""
    section = getattr(item, "section_name", "") or ""
    identity = "|".join((equipment_id, frequency.strip().upper(), section.strip().casefold(), description.strip().casefold()))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:40]
    return f"template:hash:{digest}"
