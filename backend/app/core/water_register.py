"""Column and meter definitions for the independent water register."""

from dataclasses import dataclass


@dataclass(frozen=True)
class WaterMeter:
    key: str
    label: str
    initial_column: str
    final_column: str
    volume_column: str


WATER_METERS = (
    WaterMeter("riles_aa", "Descarga RILES AA", "F", "G", "H"),
    WaterMeter("pozo_norte", "Pozo Norte", "I", "J", "K"),
    WaterMeter("pozo_sur", "Pozo Sur", "L", "M", "N"),
    WaterMeter("riles_malta", "RILES Malta", "O", "P", "Q"),
    WaterMeter("riles_extracto", "RILES Extracto", "R", "S", "T"),
    WaterMeter("copa_malta", "Copa Malta", "U", "V", "W"),
    WaterMeter("grifos", "Grifos", "X", "Y", "Z"),
    WaterMeter("copa_extracto", "Copa Extracto", "AA", "AB", "AC"),
)

WATER_METER_BY_KEY = {meter.key: meter for meter in WATER_METERS}

WATER_REGISTER_DATA_START_ROW = 4
WATER_REGISTER_DATE_COLUMN = "A"
WATER_REGISTER_LAST_COLUMN = "AG"

# These anchors are checked before reading/writing. If the template moves, sync
# fails visibly rather than placing values in unrelated cells.
WATER_REGISTER_HEADER_ANCHORS = {
    "A3": "Fecha",
    "F3": "Lect. Inicial",
    "G3": "Lect. Final",
    "H3": "Vol (m3)",
    "I3": "Lect. Inicial",
    "J3": "Lect. Final",
    "AD3": "Fecha",
    "AE3": "Hr muestreo",
    "AF3": "Piscina",
    "AG3": "DQO mg/L",
}
