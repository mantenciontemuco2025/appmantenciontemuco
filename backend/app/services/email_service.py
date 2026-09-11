"""Reliable email delivery for durable in-app notifications."""

import asyncio
import logging
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from sqlalchemy import or_, select

from app.core.config import settings
from app.db.session import async_session
from app.models.notification import Notification
from app.models.user import User

logger = logging.getLogger(__name__)

_SUBJECTS = {
    "OT_ASIGNADA": "Nueva OT asignada",
    "OT_EMITIDA": "OT pendiente de revisión",
    "OT_REASIGNADA": "OT reasignada",
    "OT_COMPLETADA": "OT completada",
    "OT_APROBADA": "OT aprobada",
    "OT_DEVUELTA": "OT devuelta para corrección",
    "OT_CANCELADA": "OT cancelada",
    "OT_REABIERTA": "OT reabierta",
}


def _message_for(notification: Notification, user: User) -> EmailMessage:
    message = EmailMessage()
    message["From"] = settings.SMTP_FROM
    message["To"] = user.email
    message["Subject"] = (
        "Mantención Temuco — "
        f"{_SUBJECTS.get(notification.type, 'Nueva notificación')}"
    )
    if settings.SMTP_REPLY_TO:
        message["Reply-To"] = settings.SMTP_REPLY_TO

    url = notification.link or "/dashboard"
    if url.startswith("/"):
        url = f"{settings.EMAIL_APP_URL.rstrip('/')}{url}"

    message.set_content(
        f"Hola {user.full_name or user.email},\n\n"
        f"{notification.message}\n\n"
        f"Puedes revisar la información aquí:\n{url}\n\n"
        "Este correo fue enviado automáticamente por Mantención Temuco."
    )
    return message


def _send_sync(notification: Notification, user: User) -> None:
    message = _message_for(notification, user)
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as server:
        server.ehlo()
        if settings.SMTP_USE_TLS:
            server.starttls()
            server.ehlo()
        server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        server.send_message(message)


async def _deliver_one(notification_id: int) -> None:
    async with async_session() as db:
        result = await db.execute(
            select(Notification, User)
            .join(User, User.id == Notification.user_id)
            .where(Notification.id == notification_id)
        )
        row = result.one_or_none()
        if row is None:
            return
        notification, user = row
        notification.email_attempts += 1
        attempt = notification.email_attempts
        await db.commit()

    try:
        await asyncio.to_thread(_send_sync, notification, user)
    except Exception as exc:
        async with async_session() as db:
            current = await db.get(Notification, notification_id)
            if current is not None:
                current.email_last_error = str(exc)[:1000]
                if attempt < 5:
                    current.email_next_attempt_at = datetime.now(timezone.utc) + timedelta(
                        seconds=15 * (2 ** (attempt - 1))
                    )
                await db.commit()
        logger.exception("Error enviando email para la notificación %s", notification_id)
        return

    async with async_session() as db:
        current = await db.get(Notification, notification_id)
        if current is not None:
            current.email_sent_at = datetime.now(timezone.utc)
            current.email_last_error = None
            current.email_next_attempt_at = None
            await db.commit()


async def process_pending_emails() -> None:
    if not settings.email_configured:
        return

    now = datetime.now(timezone.utc)
    async with async_session() as db:
        result = await db.execute(
            select(Notification.id)
            .join(User, User.id == Notification.user_id)
            .where(
                User.is_active.is_(True),
                Notification.email_sent_at.is_(None),
                Notification.email_attempts < 5,
                or_(
                    Notification.email_next_attempt_at.is_(None),
                    Notification.email_next_attempt_at <= now,
                ),
            )
            .order_by(Notification.created_at.asc())
            .limit(20)
        )
        notification_ids = [row[0] for row in result.all()]

    for notification_id in notification_ids:
        await _deliver_one(notification_id)


async def worker() -> None:
    while True:
        await process_pending_emails()
        await asyncio.sleep(10)
