"""Google Sheets mapper tests (no real calls to Google)."""

from datetime import date

from app.services import google_sheets
from app.models.maintenance import MaintenanceType


class FakeArea:
    name = "Malta"


class FakeEquipment:
    name = "Filtro"


class FakeParticipant:
    def __init__(self, name):
        self.full_name = name


class FakeRecord:
    """Duck-typed record exposing just the fields build_sheet_row needs."""

    def __init__(
        self,
        participant_names,
        maintenance_type=MaintenanceType.PREVENTIVE,
        duration=210,
        section_name="Germinación",
    ):
        self.date = date(2026, 9, 1)
        self.description = "Lubricación"
        self.maintenance_type = maintenance_type
        self.duration_minutes = duration
        self.area = FakeArea()
        self.section_name = section_name
        self.equipment = FakeEquipment()
        self.participants = [FakeParticipant(n) for n in participant_names]


# Mapping layout (18 cols): FECHA AREA SECCION EQUIPO TRABAJO | 10 workers | PREVENTIVO CORRECTIVO HORAS
#   0      1    2       3      4        | 5..14                | 15           16          17
# Workers: 5=ORTIZ 6=VALDES 7=FABRES 8=JARA 9=SALAZAR 10=MILLAR 11=JUAN SILVA 12=INOSTROZA 13=CANIULLAN 14=CONTRERAS


async def test_build_sheet_row_preventive_ortiz_valdes():
    row = google_sheets.build_sheet_row(FakeRecord(["Ortiz", "Valdés"]))
    assert row[0] == "2026-09-01"
    assert row[1] == "Malta"
    assert row[2] == "Germinación"
    assert row[3] == "Filtro"
    assert row[4] == "Lubricación"
    assert row[5] == "X"  # ORTIZ
    assert row[6] == "X"  # VALDES
    assert row[7] == ""   # FABRES
    assert row[8] == ""   # JARA
    assert row[15] == "X"  # PREVENTIVO
    assert row[16] == ""   # CORRECTIVO


async def test_build_sheet_row_corrective_no_participant_mapping():
    row = google_sheets.build_sheet_row(
        FakeRecord(["Ortiz", "Juan Silva"], maintenance_type=MaintenanceType.CORRECTIVE)
    )
    assert row[5] == "X"  # ORTIZ
    assert row[15] == ""     # PREVENTIVO
    assert row[16] == "X"    # CORRECTIVO
    assert row[11] == "X"    # JUAN SILVA


async def test_hours_format():
    # 210 minutes = 3.5 hours (numeric, not string)
    row = google_sheets.build_sheet_row(FakeRecord(["Ortiz"], duration=210))
    assert row[17] == 3.5

    # 120 minutes = 2.0
    row2 = google_sheets.build_sheet_row(FakeRecord(["Ortiz"], duration=120))
    assert row2[17] == 2.0


async def test_unknown_participant_not_flagged():
    # A participant not in the sheet mapping should not create extra columns
    row = google_sheets.build_sheet_row(FakeRecord(["Alguien no mapeado"]))
    # PREVENTIVE + no mapped participant -> only PREVENTIVO is X (1 X total)
    assert sum(1 for v in row if v == "X") == 1


async def test_section_name_free_text():
    """section_name is passed through as-is (free text, not a lookup)."""
    row = google_sheets.build_sheet_row(
        FakeRecord(["Ortiz"], section_name="HORNO 3")
    )
    assert row[2] == "HORNO 3"
