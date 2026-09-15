from datetime import date, datetime, timezone

from app.api.routes.kpis import _duration_minutes, _parse_estimated_minutes
from app.models.work_order import WorkOrder
from tests.conftest import auth_headers, get_token


def test_parse_estimated_minutes_supports_hours_and_minutes():
    assert _parse_estimated_minutes("2 horas 30 minutos") == 150
    assert _parse_estimated_minutes("2 h 10 min") == 130
    assert _parse_estimated_minutes("90 minutos") == 90
    assert _parse_estimated_minutes("1.5") == 90


def test_completed_kpi_duration_prefers_worker_declared_time():
    order = WorkOrder(
        status="COMPLETED",
        worked_duration_minutes=150,
        actual_duration_minutes=30,
        estimated_time="1 hora",
        created_at=datetime.now(timezone.utc),
    )
    assert _duration_minutes(order) == 150


async def test_admin_can_read_empty_kpi_report(client, seed_data):
    token = await get_token(client, "admin@test.com")
    response = await client.get("/api/kpis", headers=auth_headers(token))

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["total_ots"] == 0
    assert payload["summary"]["compliance_percent"] is None
    assert payload["by_worker"] == []


async def test_worker_cannot_read_kpi_report(client, seed_data):
    token = await get_token(client, "ortiz@test.com")
    response = await client.get("/api/kpis", headers=auth_headers(token))

    assert response.status_code == 403


async def test_kpi_report_counts_each_participant_with_full_ot_duration(
    client, seed_data, db_session_factory
):
    async with db_session_factory() as db:
        completed = WorkOrder(
            ot_number="OT-KPI-0001",
            title="Preventivo molino",
            area_id=seed_data["area"].id,
            maintenance_type="PREVENTIVE",
            section_name="Cebada",
            execution_date=date.today(),
            status="COMPLETED",
            is_planned=True,
            worked_duration_minutes=150,
            created_by_user_id=seed_data["admin"].id,
            participants=[seed_data["worker"], seed_data["valdes"]],
        )
        pending = WorkOrder(
            ot_number="OT-KPI-0002",
            title="Correctivo filtro",
            area_id=seed_data["area"].id,
            maintenance_type="CORRECTIVE",
            section_name="Cebada",
            execution_date=date.today(),
            status="PENDING",
            is_planned=True,
            estimated_time="2 horas",
            created_by_user_id=seed_data["admin"].id,
            participants=[seed_data["worker"]],
        )
        db.add_all([completed, pending])
        await db.commit()

    token = await get_token(client, "admin@test.com")
    response = await client.get(
        "/api/kpis?date_from=2020-01-01&date_to=2099-12-31",
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["total_ots"] == 2
    assert payload["summary"]["planned_ots"] == 2
    assert payload["summary"]["executed_planned_ots"] == 1
    assert payload["summary"]["compliance_percent"] == 50.0
    assert payload["summary"]["total_hours"] == 4.5
    workers = {row["worker_name"]: row for row in payload["by_worker"]}
    assert workers["Ortiz"]["total_hours"] == 4.5
    other_worker_hours = [row["total_hours"] for name, row in workers.items() if name != "Ortiz"]
    assert other_worker_hours == [2.5]
    current_month = next(row for row in payload["by_month"] if row["month"] == date.today().strftime("%Y-%m"))
    assert current_month["total_ots"] == 2
    assert current_month["planned_ots"] == 2
    assert current_month["executed_planned_ots"] == 1
    assert current_month["compliance_percent"] == 50.0
