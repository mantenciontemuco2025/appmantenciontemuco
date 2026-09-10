from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.push_subscription import PushSubscription
from app.models.user import User

router = APIRouter(prefix="/api/push-subscriptions", tags=["push-notifications"])


class PushSubscriptionPayload(BaseModel):
    endpoint: str = Field(min_length=10, max_length=2000)
    p256dh: str = Field(min_length=20, max_length=255)
    auth: str = Field(min_length=10, max_length=255)


class PublicKeyResponse(BaseModel):
    public_key: str


@router.get("/public-key", response_model=PublicKeyResponse)
async def public_key(current_user: User = Depends(get_current_user)):
    del current_user
    if not settings.push_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Las notificaciones push no están configuradas todavía.",
        )
    return PublicKeyResponse(public_key=settings.VAPID_PUBLIC_KEY)


@router.post("", status_code=status.HTTP_204_NO_CONTENT)
async def save_subscription(
    payload: PushSubscriptionPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not settings.push_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Las notificaciones push no están configuradas todavía.",
        )
    result = await db.execute(
        select(PushSubscription).where(PushSubscription.endpoint == payload.endpoint)
    )
    subscription = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if subscription is None:
        subscription = PushSubscription(
            user_id=current_user.id,
            endpoint=payload.endpoint,
            p256dh=payload.p256dh,
            auth=payload.auth,
            created_at=now,
            updated_at=now,
        )
        db.add(subscription)
    else:
        subscription.user_id = current_user.id
        subscription.p256dh = payload.p256dh
        subscription.auth = payload.auth
        subscription.updated_at = now
    await db.flush()


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subscription(
    payload: PushSubscriptionPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await db.execute(
        delete(PushSubscription).where(
            PushSubscription.endpoint == payload.endpoint,
            PushSubscription.user_id == current_user.id,
        )
    )
