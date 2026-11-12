"""Notify active administrators about preventive maintenance dates."""

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.models.equipment import Equipment
from app.models.notification import Notification
from app.models.preventive import PreventiveAlertSettings, PreventivePlan
from app.models.user import User, UserRole
from app.services.notification_service import create_notification

logger = logging.getLogger(__name__)
DEFAULT_ALERT_DAYS = 30
CHECK_INTERVAL_SECONDS = 6 * 60 * 60
NOTIFICATION_TYPES = ("PREVENTIVO_PROXIMO", "PREVENTIVO_VENCIDO")


def _today():
    return datetime.now(ZoneInfo("America/Santiago")).date()


def _is_configured(plan: PreventivePlan) -> bool:
    if plan.periodicity == "CUSTOM":
        return bool(plan.interval_months and plan.interval_months > 0)
    return plan.periodicity in {"MONTHLY", "QUARTERLY", "SEMIANNUAL", "ANNUAL"}


async def create_due_alerts(db: AsyncSession, *, today=None) -> int:
    """Create one deduplicated summary alert for each populated due-date group."""
    today = today or _today()
    settings_row = await db.get(PreventiveAlertSettings, 1)
    alert_days = settings_row.alert_days if settings_row is not None else DEFAULT_ALERT_DAYS
    admin_ids = set((await db.execute(
        select(User.id).where(User.is_active.is_(True), User.role == UserRole.ADMIN)
    )).scalars().all())
    if not admin_ids:
        return 0

    plans = (await db.execute(
        select(PreventivePlan, Equipment)
        .join(Equipment, Equipment.id == PreventivePlan.equipment_id)
        .where(
            PreventivePlan.active.is_(True),
            PreventivePlan.next_due_date.is_not(None),
            PreventivePlan.next_due_date <= today + timedelta(days=alert_days),
        )
        .order_by(PreventivePlan.next_due_date, PreventivePlan.id)
    )).all()

    groups = {"PREVENTIVO_PROXIMO": [], "PREVENTIVO_VENCIDO": []}
    for plan, equipment in plans:
        if not _is_configured(plan):
            continue
        notification_type = "PREVENTIVO_VENCIDO" if plan.next_due_date < today else "PREVENTIVO_PROXIMO"
        groups[notification_type].append((plan, equipment))
    groups = {notification_type: items for notification_type, items in groups.items() if items}
    if not groups:
        return 0

    candidates = []
    for notification_type, items in groups.items():
        signature_source = f"days:{alert_days}|" + "|".join(
            f"{plan.id}:{plan.next_due_date.isoformat()}" for plan, _equipment in items
        )
        signature = hashlib.sha256(signature_source.encode("utf-8")).hexdigest()[:16]
        status = "OVERDUE" if notification_type == "PREVENTIVO_VENCIDO" else "DUE_SOON"
        link = f"/preventivo?status={status}&alert_signature={signature}"
        count = len(items)
        if status == "OVERDUE":
            label = "mantenimientos preventivos vencidos"
            detail = "Revisa los equipos vencidos en el módulo Preventivo."
        else:
            label = f"mantenimientos preventivos próximos a vencer (dentro de {alert_days} días)"
            detail = "Revisa los próximos vencimientos en el módulo Preventivo."
        names = ", ".join(equipment.name for _plan, equipment in items[:3])
        if count > 3:
            names += f" y {count - 3} más"
        message = f"Hay {count} {label}. {detail} Equipos: {names}."
        candidates.append((notification_type, message, link))

    candidate_links = {candidate[2] for candidate in candidates}
    existing = (await db.execute(
        select(Notification.user_id, Notification.type, Notification.link)
        .where(
            Notification.user_id.in_(admin_ids),
            Notification.type.in_(NOTIFICATION_TYPES),
            Notification.link.in_(candidate_links),
        )
    )).all()
    sent_keys = {(row.user_id, row.type, row.link) for row in existing}

    created = 0
    for notification_type, message, link in candidates:
        for admin_id in admin_ids:
            key = (admin_id, notification_type, link)
            if key in sent_keys:
                continue
            await create_notification(
                db,
                user_id=admin_id,
                type=notification_type,
                message=message,
                link=link,
            )
            sent_keys.add(key)
            created += 1
    if created:
        await db.commit()
    return created


async def worker() -> None:
    while True:
        try:
            async with async_session() as db:
                created = await create_due_alerts(db)
            if created:
                logger.info("Se crearon %s alertas de mantenimiento preventivo", created)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Error generando alertas de mantenimiento preventivo")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
