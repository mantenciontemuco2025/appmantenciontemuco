from datetime import date, time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class WaterDqoInput(BaseModel):
    id: int | None = None
    date: date
    time: time
    pool: str = Field(min_length=1, max_length=120)
    mg_l: Decimal = Field(ge=0, max_digits=14, decimal_places=3)


class WaterRegisterInput(BaseModel):
    record_date: date
    discharge_flow_m3: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=3)
    ph_plc: Decimal | None = Field(default=None, ge=0, le=14, max_digits=5, decimal_places=2)
    ph_discharge: Decimal | None = Field(default=None, ge=0, le=14, max_digits=5, decimal_places=2)
    discharge_temp_c: Decimal | None = Field(default=None, max_digits=8, decimal_places=2)
    meter_final_readings: dict[str, Decimal | None] = Field(default_factory=dict)
    dqo: WaterDqoInput | None = None
    dqo_samples: list[WaterDqoInput] = Field(default_factory=list, max_length=100)

    @field_validator("meter_final_readings")
    @classmethod
    def validate_meter_readings(cls, values):
        # The database column is NUMERIC(16, 3): at most 13 integer digits
        # and 3 decimal places. Validate here so the user receives a useful
        # 422 message instead of a PostgreSQL 500 numeric overflow.
        for meter_key, value in values.items():
            if value is None:
                continue
            if value < 0:
                raise ValueError(f"La lectura final de '{meter_key}' no puede ser negativa.")
            if value >= Decimal("10000000000000"):
                raise ValueError(
                    f"La lectura final de '{meter_key}' es demasiado grande. "
                    "Debe ser menor que 9.999.999.999.999,999."
                )
            if abs(value.as_tuple().exponent) > 3:
                raise ValueError(
                    f"La lectura final de '{meter_key}' puede tener como máximo 3 decimales."
                )
        return values

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_dqo_field(cls, values):
        if isinstance(values, dict) and values.get("dqo") and not values.get("dqo_samples"):
            values = {**values, "dqo_samples": [values["dqo"]]}
        return values

    @model_validator(mode="after")
    def has_something_to_record(self):
        has_general = any((
            self.discharge_flow_m3 is not None,
            self.ph_plc is not None,
            self.ph_discharge is not None,
            self.discharge_temp_c is not None,
            bool(self.dqo_samples),
        ))
        has_meter = any(value is not None for value in self.meter_final_readings.values())
        if not has_general and not has_meter:
            raise ValueError("Ingresa al menos una lectura o un dato del registro.")
        return self


class WaterMeterReadingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    meter_key: str
    initial_reading: Decimal
    final_reading: Decimal
    volume_m3: Decimal


class WaterDqoSampleResponse(BaseModel):
    id: int
    sample_date: date = Field(serialization_alias="date")
    sample_time: str | None = Field(serialization_alias="time")
    pool: str | None
    mg_l: Decimal
    sheet_row: int | None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class WaterRegisterRecordResponse(BaseModel):
    id: int
    record_date: date
    discharge_flow_m3: Decimal | None
    ph_plc: Decimal | None
    ph_discharge: Decimal | None
    discharge_temp_c: Decimal | None
    dqo_date: date | None
    dqo_time: str | None
    dqo_pool: str | None
    dqo_mg_l: Decimal | None
    dqo_samples: list[WaterDqoSampleResponse]
    sync_status: str
    sync_error: str | None
    sheet_row: int | None
    meter_readings: list[WaterMeterReadingResponse]

    model_config = ConfigDict(from_attributes=True)


class WaterRegisterResponse(BaseModel):
    records: list[WaterRegisterRecordResponse]
    baselines: list[dict]
    meters: list[dict]
    latest_readings: dict[str, str]
    latest_reading_dates: dict[str, date]


class WaterHistoricalMeterResponse(BaseModel):
    meter_key: str
    label: str
    initial_reading: Decimal | None
    final_reading: Decimal | None
    volume_m3: Decimal | None


class WaterHistoricalDqoResponse(BaseModel):
    date: date
    time: str | None
    pool: str | None
    mg_l: Decimal | None


class WaterHistoricalRowResponse(BaseModel):
    sheet_row: int
    record_date: date
    discharge_flow_m3: Decimal | None
    ph_plc: Decimal | None
    ph_discharge: Decimal | None
    discharge_temp_c: Decimal | None
    meters: list[WaterHistoricalMeterResponse]
    dqo: WaterHistoricalDqoResponse | None


class WaterHistoricalResponse(BaseModel):
    from_date: date
    to_date: date
    rows: list[WaterHistoricalRowResponse]
