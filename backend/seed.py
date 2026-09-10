"""Development seed script.

Run from the backend directory:
    python seed.py

Creates:
- 1 ADMIN, 1 SUPERVISOR, and 10 WORKERs (the plant personnel)
- Real area/equipment catalog from the plant
- One example maintenance record

NOTE: Development-only credentials. Do NOT use in production.
"""

import asyncio

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import async_session
from app.models.user import User, UserRole
from app.models.area import Area
from app.models.equipment import Equipment
from app.models.maintenance import MaintenanceRecord, MaintenanceType, SyncStatus
from app.services.maintenance_service import calculate_duration

from datetime import date


# Development credentials (documented in README)
DEV_USERS = [
    {"full_name": "Administrador", "email": "admin@mantencion.com", "role": UserRole.ADMIN, "password": "Admin123!"},
    {"full_name": "Supervisor", "email": "supervisor@mantencion.com", "role": UserRole.SUPERVISOR, "password": "Super123!"},
    {"full_name": "Ortiz", "email": "ortiz@mantencion.com", "role": UserRole.WORKER, "password": "Worker123!"},
    {"full_name": "Valdés", "email": "valdes@mantencion.com", "role": UserRole.WORKER, "password": "Worker123!"},
    {"full_name": "Fabres", "email": "fabres@mantencion.com", "role": UserRole.WORKER, "password": "Worker123!"},
    {"full_name": "Jara", "email": "jara@mantencion.com", "role": UserRole.WORKER, "password": "Worker123!"},
    {"full_name": "Salazar", "email": "salazar@mantencion.com", "role": UserRole.WORKER, "password": "Worker123!"},
    {"full_name": "Millar", "email": "millar@mantencion.com", "role": UserRole.WORKER, "password": "Worker123!"},
    {"full_name": "Juan Silva", "email": "juansilva@mantencion.com", "role": UserRole.WORKER, "password": "Worker123!"},
    {"full_name": "Inostroza", "email": "inostroza@mantencion.com", "role": UserRole.WORKER, "password": "Worker123!"},
    {"full_name": "Caniullán", "email": "caniullan@mantencion.com", "role": UserRole.WORKER, "password": "Worker123!"},
    {"full_name": "Contreras", "email": "contreras@mantencion.com", "role": UserRole.WORKER, "password": "Worker123!"},
]

# Real plant catalog: Area -> [equipment types]
PLANT_CATALOG: dict[str, list[str]] = {
    "GERMINACIÓN": [
        "MÁQUINA DE CARGA GERMINACIÓN",
        "TINA DE GERMINACIÓN",
        "CORREA TRANSPORTADORA",
        "TORNILLO DE CARGA",
    ],
    "CEBADORA": [
        "MÁQUINA DE CARGA CEBADORA",
        "TINA DE CEBADO",
    ],
    "MOLINO": [
        "MOLINO",
        "ALARMA VIBRACIÓN",
    ],
    "HEROPEN": [
        "TINA DE HEROPEN",
    ],
    "SECADO": [
        "TAMIZ VIBRATORIO",
        "SECADOR",
    ],
    "MOLDEADORA": [
        "MÁQUINA DE CARGA HORNO",
        "MOLDEADORA",
        "MESA VIBRATORIA",
        "TRANSPORTADOR DE MOLDES",
    ],
    "HORNO": [
        "MÁQUINA DE CARGA HORNO",
        "QUEMADOR WEISHAUP",
        "EXTRACTOR",
        "MOTOR PUERTA",
        "TERMOPAR",
        "RESISTENCIA",
    ],
    "ENVASE": [
        "TRANSPORTADOR",
        "SENSOR",
        "MÁQUINA DE EMBALAR",
        "SELLO",
        "MÁQUINA DE ETIQUETAR",
    ],
    "LABORATORIO": [
        "MAQUINAS Y EQUIPOS",
        "INSUMOS",
        "TERMOSTATO",
        "BAÑO MARÍA",
        "BALANZA",
        "HORNO",
        "AGITADOR",
        "GRADILLA",
        "CRIOSTATO",
    ],
    "REFRIGERACIÓN": [
        "COMPRESOR",
        "ENFRIADOR",
        "COOLING",
        "AIRE ACONDICIONADO",
        "VENTILADOR",
    ],
    "CALEFACCIÓN": [
        "BOMBA DE CIRCULACIÓN",
        "AIRE CALIENTE",
        "VENTILACIÓN",
    ],
    "COMPRESORES": [
        "COMPRESOR",
        "TANQUE PULMÓN",
    ],
    "ELECTRICIDAD": [
        "TABLERO",
        "TRANSFORMADOR",
        "GENERADOR",
        "UPS",
    ],
    "AIRE/AZÚCAR": [
        "AIRE COMPRESO",
        "TANQUE DE AZÚCAR",
        "COMPRESOR",
    ],
    "AGUA": [
        "BOMBA DE AGUA",
        "TANQUE DE AGUA",
        "FILTRACIÓN",
    ],
    "LUBRICACIÓN": [
        "BOMBA DE ACEITE",
        "FILTRACIÓN",
        "DOSIFICADOR",
    ],
    "DIRIGIDAS": [
        "BANDA TRANSPORTADORA",
        "TORNILLO",
        "TINA",
    ],
    "ÁREAS COMUNES": [
        "PUERTA",
        "LUMINARIA",
        "VENTILACIÓN",
    ],
    "HIERro": [
        "TINA",
        "TRANSPORTADOR",
    ],
}


async def seed():
    async with async_session() as session:
        # --- Users ---
        created_users = {}
        for spec in DEV_USERS:
            existing = await session.execute(
                select(User).where(User.email == spec["email"])
            )
            user = existing.scalar_one_or_none()
            if user is None:
                user = User(
                    full_name=spec["full_name"],
                    email=spec["email"],
                    password_hash=hash_password(spec["password"]),
                    role=spec["role"],
                    is_active=True,
                )
                session.add(user)
                await session.flush()
            created_users[user.full_name] = user

        # --- Area + Equipment (skip if area already exists) ---
        for area_name, equipment_names in PLANT_CATALOG.items():
            existing_area = await session.execute(
                select(Area).where(Area.name == area_name)
            )
            area = existing_area.scalar_one_or_none()
            if area is None:
                area = Area(name=area_name)
                session.add(area)
                await session.flush()

            for eq_name in equipment_names:
                existing_eq = await session.execute(
                    select(Equipment).where(
                        Equipment.name == eq_name,
                        Equipment.area_id == area.id,
                    )
                )
                if existing_eq.scalar_one_or_none() is None:
                    session.add(Equipment(name=eq_name, area_id=area.id))

        await session.flush()

        # --- Example maintenance record (skip if exists) ---
        ortiz = created_users.get("Ortiz")
        valdes = created_users.get("Valdés")
        if ortiz and valdes:
            rec = await session.execute(
                select(MaintenanceRecord).where(MaintenanceRecord.id == 1)
            )
            if rec.scalar_one_or_none() is None:
                # Pick the first area and its first equipment
                first_area = (await session.execute(
                    select(Area).order_by(Area.name)
                )).scalars().first()
                first_eq = (await session.execute(
                    select(Equipment).where(Equipment.area_id == first_area.id).limit(1)
                )).scalars().first()

                if first_area and first_eq:
                    record = MaintenanceRecord(
                        date=date.today(),
                        area_id=first_area.id,
                        section_name="Sección de prueba",
                        equipment_id=first_eq.id,
                        description="Lubricación de rodamientos — ejemplo de desarrollo.",
                        maintenance_type=MaintenanceType.PREVENTIVE,
                        start_time="08:30",
                        end_time="12:00",
                        duration_minutes=calculate_duration("08:30", "12:00"),
                        created_by_user_id=ortiz.id,
                        sheet_sync_status=SyncStatus.PENDING,
                    )
                    session.add(record)
                    record.participants = [ortiz, valdes]
                    await session.flush()

        await session.commit()

    print("Seed completado.")
    print("Credenciales de desarrollo:")
    for u in DEV_USERS:
        print(f"  {u['role'].value:10s} {u['email']} / {u['password']}")


if __name__ == "__main__":
    asyncio.run(seed())
