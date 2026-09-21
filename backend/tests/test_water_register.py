from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.core.water_register import WATER_METERS
from app.models.user import User
from app.models.water_register import WaterMeterReading, WaterRegisterBaseline, WaterRegisterRecord
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


async def test_admin_and_supervisor_can_write_but_worker_is_read_only(
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
    readable = await client.get("/api/water-register", headers=worker)
    assert readable.status_code == 200
    assert len(readable.json()["records"]) == 1


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
