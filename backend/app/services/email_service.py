"""Reliable email delivery for durable in-app notifications."""

import asyncio
import html
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
    subject_label = _SUBJECTS.get(notification.type, "Nueva notificación")
    message = EmailMessage()
    message["From"] = settings.SMTP_FROM
    message["To"] = user.email
    message["Subject"] = f"Mantención Temuco — {subject_label}"
    if settings.SMTP_REPLY_TO:
        message["Reply-To"] = settings.SMTP_REPLY_TO

    url = notification.link or "/dashboard"
    if url.startswith("/"):
        url = f"{settings.EMAIL_APP_URL.rstrip('/')}{url}"

    recipient_name = user.full_name or user.email
    safe_name = html.escape(recipient_name)
    safe_message = html.escape(notification.message).replace("\n", "<br>")
    safe_url = html.escape(url, quote=True)
    safe_label = html.escape(subject_label)

    message.set_content(
        f"Hola {recipient_name},\n\n"
        f"{notification.message}\n\n"
        f"Puedes revisar la información aquí:\n{url}\n\n"
        "Este correo fue enviado automáticamente por Mantención Temuco."
    )
    message.add_alternative(
        f"""\
<!doctype html>
<html lang="es">
  <body style="margin:0;background:#f3f6fb;font-family:Arial,Helvetica,sans-serif;color:#172033;">
    <div style="padding:32px 12px;">
      <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="max-width:600px;margin:0 auto;background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 18px rgba(23,32,51,.10);">
        <tr>
          <td style="background:#253b80;padding:26px 32px;color:#ffffff;">
            <div style="font-size:13px;letter-spacing:1.4px;text-transform:uppercase;opacity:.82;">Mantención Temuco</div>
            <div style="font-size:25px;font-weight:700;margin-top:8px;">{safe_label}</div>
          </td>
        </tr>
        <tr>
          <td style="padding:32px;">
            <p style="font-size:17px;margin:0 0 18px;">Hola <strong>{safe_name}</strong>,</p>
            <div style="background:#f0f5ff;border-left:4px solid #2f6fed;border-radius:8px;padding:18px 20px;font-size:16px;line-height:1.55;">
              {safe_message}
            </div>
            <p style="margin:28px 0;text-align:center;">
              <a href="{safe_url}" style="display:inline-block;background:#1769e0;color:#ffffff;text-decoration:none;font-weight:700;padding:13px 24px;border-radius:8px;">Ver información</a>
            </p>
            <p style="font-size:13px;line-height:1.5;color:#667085;margin:0;">
              Si el botón no funciona, copia este enlace en tu navegador:<br>
              <a href="{safe_url}" style="color:#1769e0;word-break:break-all;">{safe_url}</a>
            </p>
          </td>
        </tr>
        <tr>
          <td style="border-top:1px solid #e5e7eb;padding:18px 32px;color:#667085;font-size:12px;line-height:1.5;">
            Este correo fue enviado automáticamente por Mantención Temuco. No respondas si no necesitas contactar al equipo.
          </td>
        </tr>
      </table>
    </div>
  </body>
</html>
""",
        subtype="html",
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
