from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.maintenance import MaintenanceRecord, SyncStatus
from app.models.audit_log import AuditLog


def calculate_duration(start_time: str, end_time: str) -> int:
    """Calculate duration in minutes from HH:MM strings."""
    sh, sm = map(int, start_time.split(":"))
    eh, em = map(int, end_time.split(":"))
    start_minutes = sh * 60 + sm
    end_minutes = eh * 60 + em
    if end_minutes <= start_minutes:
        raise ValueError("La hora de término debe ser posterior a la hora de inicio")
    return end_minutes - start_minutes


def get_sync_status_description(status: SyncStatus) -> str:
    descriptions = {
        SyncStatus.PENDING: "Pendiente",
        SyncStatus.SYNCED: "Sincronizado",
        SyncStatus.FAILED: "Error",
    }
    return descriptions.get(status, "Desconocido")
