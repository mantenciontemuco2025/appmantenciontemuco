"""Create and inspect local-only KPI demo work orders.

This script never calls Google services. It is intentionally identifiable by
the KPI-DEMO- prefix so the rows can be removed with --remove.
"""

import argparse
import asyncio
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.api.routes.kpis import get_kpis
from app.db.session import async_session
from app.models.area import Area
from app.models.user import User, UserRole
from app.models.work_order import WorkOrder
from app.models.work_order_participants import work_order_participants


PREFIX = "KPI-DEMO-"


def build_orders(admin: User, workers: list[User], areas: list[Area]) -> list[WorkOrder]:
    today = date.today()
    dates = [
        today,
        today - timedelta(days=2),
        today - timedelta(days=8),
        today - timedelta(days=31),
        today - timedelta(days=45),
        today - timedelta(days=60),
        today - timedelta(days=75),
        today - timedelta(days=90),
    ]
    types = ["PREVENTIVE", "CORRECTIVE", "PREDICTIVE", "PROYECTO", "MONTAJE", "CORRECTIVE", "PREVENTIVE", "CORRECTIVE"]
    statuses = ["COMPLETED", "PENDING", "IN_PROGRESS", "APPROVED", "CANCELLED", "COMPLETED", "COMPLETED", "PENDING"]
    sections = ["Cebada", "Cebada", "Malta", "Planta Extracto", "Planta CO2", "Malta", "Cebada", "Planta CO2"]
    durations = [150, 120, 90, 240, 30, 45, 90, 180]
    planned = [True, True, True, True, True, False, True, False]
    participant_indexes = [(0, 1), (0,), (1, 2), (0, 1, 2), (2,), (0, 1), (1,), ()]
    orders = []
    for index, (report_date, maintenance_type, status, section, minutes, is_planned, indexes) in enumerate(
        zip(dates, types, statuses, sections, durations, planned, participant_indexes), start=1
    ):
        selected = [workers[i % len(workers)] for i in indexes]
        estimated = f"{minutes // 60} horas" if minutes >= 60 and minutes % 60 == 0 else f"{minutes} minutos"
        order = WorkOrder(
            ot_number=f"{PREFIX}{today.year}-{index:02d}",
            title=f"Demostracion KPI {index} - {maintenance_type.title()}",
            description="Registro local de prueba para validar indicadores.",
            area_id=areas[(index - 1) % len(areas)].id,
            maintenance_type=maintenance_type,
            section_name=section,
            estimated_time=estimated,
            execution_date=report_date,
            scheduled_date=report_date,
            due_date=report_date,
            status=status,
            is_planned=is_planned,
            worked_duration_minutes=minutes if status in {"COMPLETED", "APPROVED"} else None,
            actual_duration_minutes=minutes if status in {"COMPLETED", "APPROVED"} else None,
            responsible_user_id=(selected[0].id if selected else workers[0].id),
            created_by_user_id=admin.id,
            created_at=datetime.combine(report_date, datetime.min.time(), tzinfo=timezone.utc),
            participants=selected,
        )
        orders.append(order)
    return orders


async def main(remove: bool) -> None:
    async with async_session() as db:
        if remove:
            result = await db.execute(select(WorkOrder).where(WorkOrder.ot_number.like(f"{PREFIX}%")))
            orders = result.scalars().all()
            for order in orders:
                await db.execute(delete(work_order_participants).where(work_order_participants.c.work_order_id == order.id))
            await db.execute(delete(WorkOrder).where(WorkOrder.ot_number.like(f"{PREFIX}%")))
            await db.commit()
            print(f"Eliminadas OTs KPI-DEMO: {len(orders)}")
            return

        existing = await db.execute(select(WorkOrder).where(WorkOrder.ot_number.like(f"{PREFIX}%")))
        old_orders = existing.scalars().all()
        if old_orders:
            print(f"Ya existen {len(old_orders)} OTs KPI-DEMO. Usa --remove antes de regenerar.")
            return

        admin = (await db.execute(select(User).where(User.role == UserRole.ADMIN, User.is_active.is_(True)).order_by(User.id))).scalars().first()
        workers = (await db.execute(select(User).where(User.role == UserRole.WORKER, User.is_active.is_(True)).order_by(User.id))).scalars().all()
        areas = (await db.execute(select(Area).order_by(Area.id))).scalars().all()
        if not admin or len(workers) < 3 or not areas:
            raise RuntimeError("Se necesitan un administrador, tres trabajadores activos y al menos un area local.")

        orders = build_orders(admin, list(workers[:3]), list(areas[:4] or areas))
        db.add_all(orders)
        await db.commit()

        # Run the same aggregation used by GET /api/kpis against the local DB.
        result = await get_kpis(
            date_from=date(date.today().year, 1, 1),
            date_to=date.today(),
            area_id=None,
            section_name=None,
            maintenance_type=None,
            current_user=admin,
            db=db,
        )
        print(f"Creadas OTs KPI-DEMO: {len(orders)}")
        print(f"Resumen: {result.summary.model_dump()}")
        print("Por tipo:", [row.model_dump() for row in result.by_maintenance_type])
        print("Por trabajador:", [row.model_dump() for row in result.by_worker])
        print("Por seccion:", [row.model_dump() for row in result.by_section])
        print("Por mes:", [row.model_dump() for row in result.by_month])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--remove", action="store_true", help="remove only KPI-DEMO rows")
    args = parser.parse_args()
    asyncio.run(main(args.remove))
