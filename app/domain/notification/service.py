from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.tenant import TenantContext
from app.domain.notification.models import Notification


async def schedule(
    session: AsyncSession,
    ctx: TenantContext,
    *,
    notification_type: str,
    title: str,
    content: str = "",
    payload: dict | None = None,
    scheduled_at: datetime | None = None,
) -> Notification:
    notification = Notification(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        notification_type=notification_type,
        title=title,
        content=content,
        payload_json=payload or {},
        scheduled_at=scheduled_at or datetime.utcnow(),
        status="PENDING",
    )
    session.add(notification)
    await session.commit()
    await session.refresh(notification)
    return notification


async def list_user_notifications(
    session: AsyncSession, ctx: TenantContext, *, limit: int = 20
) -> list[Notification]:
    result = await session.execute(
        select(Notification)
        .where(
            Notification.tenant_id == ctx.tenant_id,
            Notification.user_id == ctx.user_id,
            Notification.status != "CANCELLED",
        )
        .order_by(Notification.id.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def cancel(session: AsyncSession, ctx: TenantContext, notification_id: int) -> Notification:
    result = await session.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.tenant_id == ctx.tenant_id,
            Notification.user_id == ctx.user_id,
        )
    )
    notification = result.scalar_one_or_none()
    if notification is None:
        raise NotFoundError("通知不存在")
    if notification.status == "PENDING":
        notification.status = "CANCELLED"
        await session.commit()
    return notification


async def dispatch_due(
    session: AsyncSession, ctx: TenantContext, *, now: datetime | None = None, limit: int = 100
) -> list[Notification]:
    """派发到期提醒：PENDING → SENT，失败的记录由调用方重试。"""
    current = now or datetime.utcnow()
    result = await session.execute(
        select(Notification)
        .where(
            Notification.tenant_id == ctx.tenant_id,
            Notification.status == "PENDING",
            Notification.scheduled_at <= current,
        )
        .order_by(Notification.scheduled_at.asc())
        .limit(limit)
    )
    due = list(result.scalars().all())
    for notification in due:
        notification.status = "SENT"
        notification.sent_at = current
    if due:
        await session.commit()
    return due


def serialize(notification: Notification) -> dict:
    return {
        "id": notification.id,
        "type": notification.notification_type,
        "title": notification.title,
        "content": notification.content,
        "payload": notification.payload_json,
        "scheduledAt": notification.scheduled_at.isoformat() if notification.scheduled_at else None,
        "status": notification.status,
        "sentAt": notification.sent_at.isoformat() if notification.sent_at else None,
    }
