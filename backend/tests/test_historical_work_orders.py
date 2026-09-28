from sqlalchemy import select

from app.core.security import hash_password
from app.models.user import User, UserRole
from app.models.sync_job import ExternalSyncJob
from tests.conftest import auth_headers, get_token


async def test_admin_registers_historical_ot_and_kpi_counts_it_as_planned(
    client, seed_data, db_session_factory
):
    admin_token = await get_token(client, "admin@test.com")
    payload = {
        "original_ot_number": "OT-LEGACY-0042",
        "title": "Cambio de sello bomba antigua",
        "description": "Trabajo ejecutado antes de utilizar la aplicación.",
        "plant_area": "MALTA",
        "area_id": seed_data["area"].id,
        "equipment_id": seed_data["equipment"].id,
        "maintenance_type": "CORRECTIVE",
        "execution_date": "2025-06-15",
        "worked_duration_minutes": 90,
        "responsible_user_id": seed_data["worker"].id,
        "folio": "F-42",
        "voucher_number": "V-7",
        "material_codes": "SELLO-01-ORING-02",
    }
    response = await client.post(
        "/api/work-orders/historical",
        json=payload,
        headers=auth_headers(admin_token),
    )

    assert response.status_code == 201, response.text
    created = response.json()
    assert created["is_historical"] is True
    assert created["original_ot_number"] == "OT-LEGACY-0042"
    assert created["status"] == "COMPLETED"
    assert created["is_planned"] is True
    assert created["worked_duration_minutes"] == 90
    assert created["ot_sheet_sync_status"] == "NOT_APPLICABLE"
    assert created["monthly_sheet_sync_status"] == "PENDING"

    listed = await client.get(
        "/api/work-orders?search=OT-LEGACY-0042",
        headers=auth_headers(admin_token),
    )
    assert listed.status_code == 200
    assert listed.json()[0]["is_historical"] is True

    kpi = await client.get(
        "/api/kpis?date_from=2025-01-01&date_to=2025-12-31",
        headers=auth_headers(admin_token),
    )
    assert kpi.status_code == 200
    summary = kpi.json()["summary"]
    assert summary["total_ots"] == 1
    assert summary["planned_ots"] == 1
    assert summary["executed_planned_ots"] == 1
    assert summary["total_hours"] == 1.5

    edited = await client.patch(
        f"/api/work-orders/{created['id']}",
        json={"description": "Trabajo antiguo corregido por administración", "worked_duration_minutes": 120},
        headers=auth_headers(admin_token),
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["worked_duration_minutes"] == 120
    assert edited.json()["actual_duration_minutes"] == 120.0

    async with db_session_factory() as db:
        job = await db.scalar(
            select(ExternalSyncJob).where(ExternalSyncJob.work_order_id == created["id"])
        )
        assert job is not None
        assert job.job_type == "MONTHLY"


async def test_worker_cannot_register_historical_ot(client, seed_data):
    worker_token = await get_token(client, "ortiz@test.com")
    response = await client.post(
        "/api/work-orders/historical",
        json={
            "title": "No permitido",
            "description": "Prueba",
            "plant_area": "MALTA",
            "area_id": seed_data["area"].id,
            "maintenance_type": "CORRECTIVE",
            "execution_date": "2025-06-15",
            "worked_duration_minutes": 30,
        },
        headers=auth_headers(worker_token),
    )
    assert response.status_code == 403


async def test_admin_imports_unclassified_historical_rows_and_lists_pending(
    client, seed_data, db_session_factory
):
    async with db_session_factory() as db:
        db.add_all([
            User(
                full_name="Wilson Ortiz",
                email="wilson@test.com",
                password_hash=hash_password("pass123"),
                role=UserRole.WORKER,
            ),
            User(
                full_name="Domingo Contreras",
                email="domingo@test.com",
                password_hash=hash_password("pass123"),
                role=UserRole.WORKER,
            ),
        ])
        await db.commit()

    admin_token = await get_token(client, "admin@test.com")
    response = await client.post(
        "/api/work-orders/historical/import",
        json={
            "items": [
                {
                    "source_row": 2,
                    "original_ot_number": "OT-ANTIGUA-001",
                    "source_responsible": "Wilson / Domingo",
                    "title": "Bomba de alimentación",
                    "description": "Se reemplazó sello y se dejó operativa.",
                    "execution_date": "2025-06-15",
                    "duration_minutes": 90,
                    "duration_text": "1 h 30 min",
                }
            ]
        },
        headers=auth_headers(admin_token),
    )

    assert response.status_code == 201, response.text
    result = response.json()
    assert result["received"] == 1
    assert result["created"] == 1
    assert result["unmatched_responsibles"] == []
    assert result["created_items"][0]["classification_pending"] is True

    pending = await client.get(
        "/api/work-orders/historical/pending-classification",
        headers=auth_headers(admin_token),
    )
    assert pending.status_code == 200, pending.text
    assert len(pending.json()) == 1
    assert pending.json()[0]["classification_pending"] is True
    assert pending.json()[0]["area_name"] is None
    assert pending.json()[0]["responsible_user_name"] == "Wilson Ortiz"

    duplicate = await client.post(
        "/api/work-orders/historical/import",
        json={
            "items": [{
                "source_row": 2,
                "original_ot_number": "OT-ANTIGUA-001",
                "title": "Bomba de alimentación",
                "description": "Duplicado",
                "execution_date": "2025-06-15",
                "duration_minutes": 30,
            }]
        },
        headers=auth_headers(admin_token),
    )
    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json()["created"] == 0
    assert duplicate.json()["skipped"] == 1
