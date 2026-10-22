"""Reconcile hazardous-waste records as integer item counts, not kg/L."""

from datetime import date
from decimal import Decimal
import unicodedata

from alembic import op
import sqlalchemy as sa


revision = "0042_hazwaste_unit_reconcile"
down_revision = "0041_hazwaste_optional_qty"
branch_labels = None
depends_on = None


def _normalize(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in text if not unicodedata.combining(char)).strip().casefold()


# Corrections transcribed from the two photographed pages. The source's
# "Unidad" column is the quantity used here; its separate Kg column is not
# part of this app's stored stock. Empty/unclear fields remain empty, except
# the user's explicit clarification that the third uncertain quantity is 1.
CORRECTIONS = [
    ("2026-07-07", "a1160", "BATERIA", "BODEGA EXTRACTO", "25", "kg", 1),
    ("2026-07-07", "a1", "TONNER", "MANTENCION", "2.500", "kg", 5),
    ("2026-07-07", "a1190", "CHATARRA ELECTRONICA (FOCO)", "MANTENCION", "3.400", "kg", 9),
    ("2026-07-07", "a3140", "DESINFECTANTE", "BODEGA EXTRACTO", "10", "kg", 9),
    ("2026-07-07", "1", "SODA CAUSTICA", "PROD. EXTRACTO", "5", "kg", 10),
    ("2026-07-08", "a1030", "EQUIPOS TUBOS LED", "MANTENCION", "5", "kg", 8),
    ("2026-07-08", "a1180", "TUBO FLUORECENTE", "MANTENCION", "6", "kg", 8),
    ("2026-07-08", "a1180", "CHATARRA ELECTRONICA (FOCO)", "MANTENCION", "14", "kg", 8),
    ("2026-07-08", "a3020", "ACEITE CONTAMINADO", "MANTENCION", "12", "kg", 8),
    ("2026-07-08", "a1180", "CHATARRA ELECTRONICA (FOCO)", "MANTENCION", "2", "kg", 6),
    ("2026-07-08", "1180", "CARGADOR BATERIA", "MANTENCION", "1", "kg", 1),
    ("2026-08-14", "1", "SODA CAUSTICA", "EXTRACTO", "7", "kg", 2),
    ("2026-08-14", "1", "SODA CAUSTICA", "EXTRACTO", "1.2", "kg", 1),
    ("2026-09-18", "1", "SODA CAUSTICA", "EXTRACTO", "3.7", "kg", 1),
    ("2026-08-19", "8", "DETERGENTE", "EXTRACTO", "13", "kg", 1),
    ("2026-08-19", "1", "SODA CAUSTICA", "EXTRACTO", "4.6", "kg", 1),
    ("2026-08-20", "a130", "EQUIPOS LED", "CAJON", "10", "kg", 10),
    ("2026-08-20", "1", "SODA CAUSTICA", "EXTRACTO", "5", "kg", 2),
    ("2026-08-20", "8", "ACEITE CONTAMINADO", "DESPACHO", "50", "l", 1),
    ("2026-08-20", "13", "TUBOS LED", "MANTENCION", "17", "kg", 10),
    ("2026-08-20", "2", "TUBOS LED", "MANTENCION", "10", "kg", 24),
    ("2026-08-20", "a130", "EQUIPOS LED", "MANTENCION", "40", "kg", 17),
    ("2026-08-20", "a130", "EQUIPOS LED", "MANTENCION", "26", "kg", 15),
    ("2026-10-14", "", "RESIDUOS PELIGROSOS", "BODEGA", None, "", 1),
    ("2026-10-21", "1", "ENVASE CONTAMINADO SODA CAUSTICA EN ESCAMAS", "RILES", "15", "kg", 2),
    ("2026-10-21", "", "ENVASE REACTIVO LABORATORIO", "RILES", "20", "kg", 2),
    ("2026-10-21", "", "ACIDO NITRICO", "EXTRACTO", "6", "kg", 4),
    ("2026-10-21", "1", "ENVASE CONTAMINADO SODA CAUSTICA EN ESCAMAS", "EXTRACTO", "20", "kg", 8),
]


def upgrade() -> None:
    bind = op.get_bind()
    records = sa.table(
        "hazardous_waste_records",
        sa.column("id", sa.Integer), sa.column("entry_date", sa.Date),
        sa.column("respel_code", sa.String), sa.column("normalized_code", sa.String),
        sa.column("waste_name", sa.String), sa.column("normalized_name", sa.String),
        sa.column("origin", sa.String), sa.column("quantity", sa.Numeric(16, 3)),
        sa.column("unit", sa.String), sa.column("accumulated_quantity", sa.Numeric(16, 3)),
        sa.column("disposal_date", sa.Date), sa.column("sync_status", sa.String),
        sa.column("sync_version", sa.Integer), sa.column("sync_error", sa.Text),
        sa.column("sync_next_attempt_at", sa.DateTime(timezone=True)),
    )
    rows = [dict(row) for row in bind.execute(sa.select(records)).mappings()]
    changed: set[int] = set()

    for date_text, code, name, origin, old_quantity, old_unit, new_quantity in CORRECTIONS:
        matches = [row for row in rows
                   if row["entry_date"] == date.fromisoformat(date_text)
                   and _normalize(row["normalized_code"]) == code
                   and _normalize(row["normalized_name"]) == _normalize(name)
                   and _normalize(row["origin"]) == _normalize(origin)
                   and (None if row["quantity"] is None else Decimal(row["quantity"]))
                       == (None if old_quantity is None else Decimal(old_quantity))
                   and _normalize(row["unit"]) == old_unit]
        # Do not guess if a database does not contain exactly this photographed
        # source row. Such a row is left untouched for a deliberate manual fix.
        if len(matches) != 1:
            continue
        row = matches[0]
        row["quantity"] = Decimal(new_quantity)
        row["unit"] = ""
        changed.add(row["id"])

    groups: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        code = _normalize(row["respel_code"])
        identity = ("code", code) if code else ("name", _normalize(row["waste_name"]))
        groups.setdefault(identity, []).append(row)
    for group in groups.values():
        group.sort(key=lambda row: (row["entry_date"], row["id"]))
        for row in group:
            active = [item for item in group
                      if item["entry_date"] <= row["entry_date"]
                      and (item["disposal_date"] is None or item["disposal_date"] > row["entry_date"])]
            total = None if any(item["quantity"] is None for item in active) else sum(
                (Decimal(item["quantity"]) for item in active), Decimal("0")
            )
            if row["accumulated_quantity"] != total:
                row["accumulated_quantity"] = total
                changed.add(row["id"])

    for row in rows:
        if row["id"] in changed:
            bind.execute(sa.update(records).where(records.c.id == row["id"]).values(
                quantity=row["quantity"], unit=row["unit"],
                accumulated_quantity=row["accumulated_quantity"],
                sync_status="PENDING", sync_version=row["sync_version"] + 1,
                sync_error=None, sync_next_attempt_at=None,
            ))


def downgrade() -> None:
    # Corrected source values cannot be safely converted back into the old
    # mistaken kg/L values. Keep the repaired data on downgrade.
    pass
