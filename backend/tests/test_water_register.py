from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.core.water_register import WATER_METERS
from app.models.user import User
from app.models.water_register import WaterDqoSample, WaterMeterReading, WaterRegisterBaseline, WaterRegisterRecord
from tests.conftest import auth_headers, get_token


async def _seed_baselines(db_session_factory, user_id):
    async with db_session_factory() as db:
        for meter in WATER_METERS:
            db.add(WaterRegisterBaseline(
                meter_key=meter.key,
                final_reading=Decimal("1000.000"),
                reading_date=date(2026, 9, 14),
                source_row=381,
                initialized_by_user_id=user_id,
            ))
        await db.commit()


async def test_admin_and_supervisor_can_write_but_worker_without_access_is_blocked(
    client, seed_data, db_session_factory
):
    await _seed_baselines(db_session_factory, seed_data["admin"].id)
    payload = {
        "record_date": "2026-09-17",
        "discharge_flow_m3": "2.5",
        "meter_final_readings": {"riles_aa": "1012.5"},
    }
    admin = auth_headers(await get_token(client, "admin@test.com"))
    created = await client.post("/api/water-register", json=payload, headers=admin)
    assert created.status_code == 201, created.text
    item = created.json()
    assert item["sync_status"] == "PENDING"
    assert item["meter_readings"][0]["initial_reading"] == "1000.000"
    assert item["meter_readings"][0]["final_reading"] == "1012.500"
    assert item["meter_readings"][0]["volume_m3"] == "12.500"

    worker = auth_headers(await get_token(client, "ortiz@test.com"))
    forbidden = await client.post("/api/water-register", json={**payload, "record_date": "2026-09-18"}, headers=worker)
    assert forbidden.status_code == 403
    unreadable = await client.get("/api/water-register", headers=worker)
    assert unreadable.status_code == 403


async def test_admin_can_assign_water_register_to_worker(
    client, seed_data, db_session_factory
):
    await _seed_baselines(db_session_factory, seed_data["admin"].id)
    admin = auth_headers(await get_token(client, "admin@test.com"))
    assigned = await client.patch(
        f"/api/users/{seed_data['worker'].id}",
        json={"can_manage_water_register": True},
        headers=admin,
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["can_manage_water_register"] is True

    worker = auth_headers(await get_token(client, "ortiz@test.com"))
    response = await client.post(
        "/api/water-register",
        json={"record_date": "2026-09-17", "meter_final_readings": {"riles_aa": "1001"}},
        headers=worker,
    )
    assert response.status_code == 201, response.text


async def test_admin_can_assign_view_only_water_register_to_worker(
    client, seed_data, db_session_factory
):
    await _seed_baselines(db_session_factory, seed_data["admin"].id)
    admin = auth_headers(await get_token(client, "admin@test.com"))
    assigned = await client.patch(
        f"/api/users/{seed_data['worker'].id}",
        json={"water_register_access": "VIEW"},
        headers=admin,
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["water_register_access"] == "VIEW"

    worker = auth_headers(await get_token(client, "ortiz@test.com"))
    readable = await client.get("/api/water-register", headers=worker)
    assert readable.status_code == 200
    forbidden = await client.post(
        "/api/water-register",
        json={"record_date": "2026-09-17", "meter_final_readings": {"riles_aa": "1001"}},
        headers=worker,
    )
    assert forbidden.status_code == 403


async def test_unique_daily_record_and_multiple_dqo_samples(
    client, seed_data, db_session_factory
):
    await _seed_baselines(db_session_factory, seed_data["admin"].id)
    token = auth_headers(await get_token(client, "supervisor@test.com"))
    payload = {
        "record_date": "2026-09-17",
        "ph_plc": "6.2",
        "dqo": {"date": "2026-09-17", "time": "10:15", "pool": "Piscina 1", "mg_l": "12"},
    }
    first = await client.post("/api/water-register", json=payload, headers=token)
    assert first.status_code == 201, first.text
    duplicate_day = await client.post("/api/water-register", json=payload, headers=token)
    assert duplicate_day.status_code == 409
    another_day_same_dqo = await client.post(
        "/api/water-register",
        json={**payload, "record_date": "2026-09-18"},
        headers=token,
    )
    assert another_day_same_dqo.status_code == 201

    multiple = await client.put(
        "/api/water-register/2026-09-17",
        json={
            "record_date": "2026-09-17",
            "dqo_samples": [
                {"date": "2026-09-17", "time": "10:15", "pool": "Piscina 1", "mg_l": "12"},
                {"date": "2026-09-17", "time": "14:00", "pool": "Piscina 2", "mg_l": "18.5"},
            ],
        },
        headers=token,
    )
    assert multiple.status_code == 200, multiple.text
    assert len(multiple.json()["dqo_samples"]) == 2


async def test_import_manual_sheet_day_preserves_all_dqo_samples(
    client, seed_data, db_session_factory, monkeypatch
):
    from app.api.routes import water_register

    imported_date = date(2026, 9, 20)
    monkeypatch.setattr(
        water_register,
        "read_historical_range",
        lambda *_: [
            {
                "sheet_row": 400,
                "record_date": imported_date,
                "discharge_flow_m3": Decimal("12.5"),
                "ph_plc": None,
                "ph_discharge": Decimal("6.8"),
                "discharge_temp_c": None,
                "meters": [{
                    "meter_key": "riles_aa",
                    "initial_reading": Decimal("1000"),
                    "final_reading": Decimal("1005"),
                    "volume_m3": Decimal("5"),
                }],
                "dqo": {"date": imported_date, "time": "08:00", "pool": "1", "mg_l": Decimal("100")},
            },
            {
                "sheet_row": 401,
                "record_date": imported_date,
                "discharge_flow_m3": None,
                "ph_plc": None,
                "ph_discharge": None,
                "discharge_temp_c": None,
                "meters": [],
                "dqo": {"date": imported_date, "time": "14:00", "pool": "2", "mg_l": Decimal("200")},
            },
        ],
    )
    supervisor = auth_headers(await get_token(client, "supervisor@test.com"))
    response = await client.post(
        f"/api/water-register/import-day?date={imported_date.isoformat()}",
        json={},
        headers=supervisor,
    )
    assert response.status_code == 201, response.text
    item = response.json()
    assert item["sheet_row"] == 400
    assert Decimal(item["discharge_flow_m3"]) == Decimal("12.5")
    assert len(item["dqo_samples"]) == 2
    assert item["meter_readings"][0]["final_reading"] == "1005.000"

    duplicate = await client.post(
        f"/api/water-register/import-day?date={imported_date.isoformat()}",
        json={},
        headers=supervisor,
    )
    assert duplicate.status_code == 409
    async with db_session_factory() as db:
        samples = (await db.scalars(select(WaterDqoSample))).all()
        assert len(samples) == 2


async def test_volume_matches_sheet_formula_when_final_is_lower(
    client, seed_data, db_session_factory
):
    await _seed_baselines(db_session_factory, seed_data["admin"].id)
    token = auth_headers(await get_token(client, "admin@test.com"))
    response = await client.post(
        "/api/water-register",
        json={"record_date": "2026-09-17", "meter_final_readings": {"riles_aa": "900"}},
        headers=token,
    )
    assert response.status_code == 201, response.text
    assert response.json()["meter_readings"][0]["volume_m3"] == "0"


async def test_invalid_meter_reading_returns_clear_validation_error(
    client, seed_data, db_session_factory
):
    await _seed_baselines(db_session_factory, seed_data["admin"].id)
    token = auth_headers(await get_token(client, "admin@test.com"))
    response = await client.post(
        "/api/water-register",
        json={
            "record_date": "2026-09-19",
            "meter_final_readings": {"riles_aa": "9999999999999000"},
        },
        headers=token,
    )
    assert response.status_code == 422
    assert "demasiado grande" in response.json()["detail"][0]["msg"]


async def test_editing_earlier_day_recalculates_later_meter_opening(
    client, seed_data, db_session_factory
):
    await _seed_baselines(db_session_factory, seed_data["admin"].id)
    token = auth_headers(await get_token(client, "admin@test.com"))
    first_payload = {"record_date": "2026-09-17", "meter_final_readings": {"riles_aa": "1010"}}
    second_payload = {"record_date": "2026-09-18", "meter_final_readings": {"riles_aa": "1020"}}
    first = await client.post("/api/water-register", json=first_payload, headers=token)
    second = await client.post("/api/water-register", json=second_payload, headers=token)
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text

    edited = await client.put(
        "/api/water-register/2026-09-17",
        json={"record_date": "2026-09-17", "meter_final_readings": {"riles_aa": "1015"}},
        headers=token,
    )
    assert edited.status_code == 200, edited.text
    async with db_session_factory() as db:
        later = await db.scalar(
            select(WaterRegisterRecord).where(WaterRegisterRecord.record_date == date(2026, 9, 18))
        )
        reading = await db.scalar(
            select(WaterMeterReading).where(WaterMeterReading.record_id == later.id)
        )
        assert reading.initial_reading == Decimal("1015.000")
        assert later.sync_status == "PENDING"


async def test_admin_initializes_baselines_from_latest_nonzero_sheet_readings(
    client, seed_data, monkeypatch
):
    from app.api.routes import water_register

    monkeypatch.setattr(
        water_register,
        "read_latest_meter_baselines",
        lambda: [
            {
                "meter_key": meter.key,
                "final_reading": Decimal("987.5"),
                "reading_date": date(2026, 9, 14),
                "source_row": 381,
            }
            for meter in WATER_METERS
        ],
    )
    admin = auth_headers(await get_token(client, "admin@test.com"))
    response = await client.post("/api/water-register/initialize-from-sheet", headers=admin)
    assert response.status_code == 200, response.text
    assert response.json()["initialized"] == 8


async def test_edit_user_can_refresh_latest_readings_without_creating_daily_record(
    client, seed_data, db_session_factory, monkeypatch
):
    from app.api.routes import water_register

    await _seed_baselines(db_session_factory, seed_data["admin"].id)
    monkeypatch.setattr(
        water_register,
        "read_latest_meter_baselines",
        lambda: [
            {
                "meter_key": meter.key,
                "final_reading": Decimal("1200.500"),
                "reading_date": date(2026, 9, 22),
                "source_row": 389,
            }
            for meter in WATER_METERS
        ],
    )
    supervisor = auth_headers(await get_token(client, "supervisor@test.com"))
    response = await client.post("/api/water-register/refresh-latest-readings", headers=supervisor)
    assert response.status_code == 200, response.text
    assert response.json()["updated"] == 8

    listing = await client.get("/api/water-register", headers=supervisor)
    assert listing.status_code == 200, listing.text
    assert listing.json()["latest_readings"][WATER_METERS[0].key] == "1200.500"
    assert listing.json()["latest_reading_dates"][WATER_METERS[0].key] == "2026-09-22"
    async with db_session_factory() as db:
        assert await db.scalar(select(WaterRegisterRecord.id)) is None
