"""End-to-end tests for the provisional hallazgo workflow.

These tests use the existing isolated SQLite fixture. Google Drive is not
called; acceptance is verified up to the persisted external-sync job, which is
the boundary consumed by the real background synchronizer.
"""

from sqlalchemy import select

from app.models.sync_job import ExternalSyncJob, SyncJobStatus
from app.models.work_order import WorkOrderStatus

from .conftest import auth_headers, get_token


def hallazgo_payload(seed_data, **overrides):
    payload = {
        "title": "Reparación detectada en terreno",
        "description": "Se reparó el equipo y quedó operativo.",
        "area_id": seed_data["area"].id,
        "plant_area": "MANTENCION",
        "equipment_id": None,
        "report_kind": "COMPLETED",
        "priority": "NORMAL",
        "report_date": "2026-09-23",
        "work_time_mode": "RANGE",
        "work_start_time": "08:00",
        "work_end_time": "10:30",
        "folio": "FOL-123",
        "voucher_number": "VAL-456",
        "participant_user_ids": [seed_data["valdes"].id],
        "risks": "Aislamiento eléctrico realizado.",
        "observations": "Equipo probado y operativo.",
    }
    payload.update(overrides)
    return payload


async def test_completed_hallazgo_converts_with_duration_equipment_and_admin_fields(
    client, db_session_factory, seed_data
):
    worker_token = await get_token(client, "ortiz@test.com")
    admin_token = await get_token(client, "admin@test.com")

    created = await client.post(
        "/api/work-orders/hallazgos",
        json=hallazgo_payload(seed_data),
        headers=auth_headers(worker_token),
    )
    assert created.status_code == 201, created.text
    provisional = created.json()
    assert provisional["hallazgo_status"] == "PENDING_REVIEW"
    assert provisional["equipment_id"] is None
    assert provisional["folio"] == "FOL-123"
    assert provisional["voucher_number"] == "VAL-456"

    accepted = await client.post(
        f"/api/work-orders/{provisional['id']}/hallazgo-review",
        json={
            "action": "ACCEPT",
            "equipment_id": seed_data["equipment"].id,
            "folio": "FOL-ADMIN",
            "voucher_number": "VAL-ADMIN",
        },
        headers=auth_headers(admin_token),
    )
    assert accepted.status_code == 200, accepted.text
    data = accepted.json()
    assert data["hallazgo_status"] == "CONVERTED"
    assert data["status"] == WorkOrderStatus.APPROVED.value
    assert data["is_planned"] is True
    assert data["equipment_id"] == seed_data["equipment"].id
    assert data["equipment_name"] == "Filtro"
    assert data["folio"] == "FOL-ADMIN"
    assert data["voucher_number"] == "VAL-ADMIN"
    assert data["worked_duration_minutes"] == 150
    assert data["estimated_time"] == "2 horas 30 minutos"
    assert data["responsible_user_id"] == seed_data["worker"].id
    assert data["participant_user_ids"] == [seed_data["worker"].id, seed_data["valdes"].id]

    async with db_session_factory() as db:
        jobs = (
            await db.execute(
                select(ExternalSyncJob).where(
                    ExternalSyncJob.work_order_id == provisional["id"]
                )
            )
        ).scalars().all()
        assert any(job.job_type == "FULL_CREATE" for job in jobs)
        assert all(job.status in (SyncJobStatus.PENDING, SyncJobStatus.PROCESSING) for job in jobs)


async def test_attention_hallazgo_admin_assigns_equipment_responsible_and_plan(
    client, seed_data
):
    worker_token = await get_token(client, "ortiz@test.com")
    admin_token = await get_token(client, "admin@test.com")

    created = await client.post(
        "/api/work-orders/hallazgos",
        json=hallazgo_payload(
            seed_data,
            report_kind="REQUIRES_ATTENTION",
            description="Bomba con ruido anormal; requiere revisión.",
            work_time_mode=None,
            work_start_time=None,
            work_end_time=None,
            folio=None,
            voucher_number=None,
        ),
        headers=auth_headers(worker_token),
    )
    assert created.status_code == 201, created.text
    provisional = created.json()
    assert provisional["equipment_id"] is None
    assert provisional["responsible_user_id"] is None

    accepted = await client.post(
        f"/api/work-orders/{provisional['id']}/hallazgo-review",
        json={
            "action": "ACCEPT",
            "equipment_id": seed_data["equipment"].id,
            "responsible_user_id": seed_data["worker_jara"].id,
            "participant_user_ids": [seed_data["valdes"].id],
            "maintenance_type": "CORRECTIVE",
            "estimated_time": "1 hora 15 minutos",
            "scheduled_date": "2026-09-24",
            "due_date": "2026-09-25",
            "folio": "FOL-ATT",
            "voucher_number": "VAL-ATT",
        },
        headers=auth_headers(admin_token),
    )
    assert accepted.status_code == 200, accepted.text
    data = accepted.json()
    assert data["hallazgo_status"] == "CONVERTED"
    assert data["status"] == WorkOrderStatus.PENDING.value
    assert data["is_planned"] is True
    assert data["responsible_user_id"] == seed_data["worker_jara"].id
    assert seed_data["worker_jara"].id in data["participant_user_ids"]
    assert seed_data["valdes"].id in data["participant_user_ids"]
    assert data["equipment_id"] == seed_data["equipment"].id
    assert data["estimated_time"] == "1 hora 15 minutos"
    assert data["scheduled_date"] == "2026-09-24"
    assert data["due_date"] == "2026-09-25"
    assert data["folio"] == "FOL-ATT"
    assert data["voucher_number"] == "VAL-ATT"


async def test_returned_hallazgo_can_be_corrected_and_resubmitted(client, seed_data):
    worker_token = await get_token(client, "ortiz@test.com")
    admin_token = await get_token(client, "admin@test.com")

    created = await client.post(
        "/api/work-orders/hallazgos",
        json=hallazgo_payload(seed_data),
        headers=auth_headers(worker_token),
    )
    assert created.status_code == 201, created.text
    wo_id = created.json()["id"]

    returned = await client.post(
        f"/api/work-orders/{wo_id}/hallazgo-review",
        json={"action": "RETURN", "notes": "Agrega el detalle de la prueba final."},
        headers=auth_headers(admin_token),
    )
    assert returned.status_code == 200, returned.text
    assert returned.json()["hallazgo_status"] == "RETURNED"
    assert returned.json()["submitted_for_review"] is False

    corrected = await client.patch(
        f"/api/work-orders/{wo_id}/hallazgo",
        json={
            "description": "Se reparó y se realizó prueba final satisfactoria.",
            "folio": "FOL-CORREGIDO",
            "voucher_number": "VAL-CORREGIDO",
            "resubmit": True,
        },
        headers=auth_headers(worker_token),
    )
    assert corrected.status_code == 200, corrected.text
    data = corrected.json()
    assert data["hallazgo_status"] == "PENDING_REVIEW"
    assert data["submitted_for_review"] is True
    assert data["folio"] == "FOL-CORREGIDO"
    assert data["voucher_number"] == "VAL-CORREGIDO"


async def test_hallazgo_can_be_rejected_without_creating_official_ot(client, seed_data):
    worker_token = await get_token(client, "ortiz@test.com")
    admin_token = await get_token(client, "admin@test.com")

    created = await client.post(
        "/api/work-orders/hallazgos",
        json=hallazgo_payload(seed_data),
        headers=auth_headers(worker_token),
    )
    assert created.status_code == 201, created.text
    provisional = created.json()

    rejected = await client.post(
        f"/api/work-orders/{provisional['id']}/hallazgo-review",
        json={"action": "REJECT", "notes": "No corresponde a mantenimiento."},
        headers=auth_headers(admin_token),
    )
    assert rejected.status_code == 200, rejected.text
    data = rejected.json()
    assert data["hallazgo_status"] == "REJECTED"
    assert data["submitted_for_review"] is False
    assert data["ot_number"] == provisional["ot_number"]
    assert data["is_planned"] is False


async def test_supervisor_cannot_access_or_create_hallazgos(client, seed_data):
    supervisor = auth_headers(await get_token(client, "supervisor@test.com"))
    listed = await client.get("/api/work-orders/hallazgos", headers=supervisor)
    assert listed.status_code == 403

    created = await client.post(
        "/api/work-orders/hallazgos",
        json=hallazgo_payload(seed_data),
        headers=supervisor,
    )
    assert created.status_code == 403
