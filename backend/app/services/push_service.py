"""Web Push delivery for durable in-app notifications."""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, or_, select

from app.core.config import settings
from app.db.session import async_session
from app.models.notification import Notification
from app.models.push_subscription import PushSubscription

logger = logging.getLogger(__name__)


def _send(subscription: PushSubscription, payload: dict) -> None:
    import requests
    from pywebpush import webpush

    session = requests.Session()
    session.trust_env = False
    try:
        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
            },
            data=json.dumps(payload),
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={"sub": settings.VAPID_SUBJECT},
            requests_session=session,
            timeout=15,
        )
    finally:
        session.close()


async def _deliver_one(notification: Notification) -> None:
    async with async_session() as db:
        result = await db.execute(
            select(PushSubscription).where(PushSubscription.user_id == notification.user_id)
        )
        subscriptions = list(result.scalars().all())
        if not subscriptions:
            result = await db.execute(
                select(Notification).where(Notification.id == notification.id)
            )
            current = result.scalar_one_or_none()
            if current is not None:
                current.push_sent_at = datetime.now(timezone.utc)
            await db.commit()
            return

        result = await db.execute(
            select(Notification).where(Notification.id == notification.id)
        )
        current = result.scalar_one_or_none()
        if current is None:
            await db.commit()
            return
        current.push_attempts += 1
        await db.commit()

    payload = {
        "title": "Mantención",
        "body": notification.message,
        "url": notification.link or "/dashboard",
        "notification_id": notification.id,
    }
    delivered = 0
    errors: list[str] = []
    stale_endpoints: list[str] = []
    for subscription in subscriptions:
        try:
            await asyncio.to_thread(_send, subscription, payload)
            delivered += 1
        except Exception as exc:  # Web Push libraries expose different exception types by version.
            response = getattr(exc, "response", None)
            status_code = getattr(response, "status_code", None)
            if status_code in (404, 410):
                stale_endpoints.append(subscription.endpoint)
            else:
                errors.append(str(exc)[:500])

    async with async_session() as db:
        if stale_endpoints:
            await db.execute(
                delete(PushSubscription).where(PushSubscription.endpoint.in_(stale_endpoints))
            )
        result = await db.execute(
            select(Notification).where(Notification.id == notification.id)
        )
        current = result.scalar_one_or_none()
        if current is None:
            await db.commit()
            return
        if delivered or not errors:
            current.push_sent_at = datetime.now(timezone.utc)
            current.push_last_error = None
        else:
            current.push_last_error = "; ".join(errors)
            if current.push_attempts < 5:
                current.push_next_attempt_at = datetime.now(timezone.utc) + timedelta(
                    seconds=15 * (2 ** (current.push_attempts - 1))
                )
        await db.commit()


async def process_pending_pushes() -> None:
    if not settings.push_configured:
        return
    now = datetime.now(timezone.utc)
    async with async_session() as db:
        result = await db.execute(
            select(Notification)
            .where(
                Notification.push_sent_at.is_(None),
                Notification.push_attempts < 5,
                or_(
                    Notification.push_next_attempt_at.is_(None),
                    Notification.push_next_attempt_at <= now,
                ),
            )
            .order_by(Notification.created_at.asc())
            .limit(20)
        )
        pending = list(result.scalars().all())
    for notification in pending:
        try:
            await _deliver_one(notification)
        except Exception:
            logger.exception("Error enviando push para la notificación %s", notification.id)


async def worker() -> None:
    while True:
        await process_pending_pushes()
        await asyncio.sleep(5)
