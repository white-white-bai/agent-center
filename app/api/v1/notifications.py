from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import AdminContext, CurrentTenant, DbSession
from app.core.responses import ok
from app.domain.notification import service

router = APIRouter(tags=["notification"])


class ScheduleNotificationRequest(BaseModel):
    type: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=1, max_length=200)
    content: str = ""
    payload: dict = Field(default_factory=dict)
    scheduledAt: datetime | None = None


@router.post("/notifications")
async def schedule_notification(
    payload: ScheduleNotificationRequest, session: DbSession, ctx: CurrentTenant
) -> dict:
    notification = await service.schedule(
        session,
        ctx,
        notification_type=payload.type,
        title=payload.title,
        content=payload.content,
        payload=payload.payload,
        scheduled_at=payload.scheduledAt,
    )
    return ok(service.serialize(notification))


@router.get("/notifications")
async def list_notifications(session: DbSession, ctx: CurrentTenant) -> dict:
    items = await service.list_user_notifications(session, ctx)
    return ok([service.serialize(item) for item in items])


@router.delete("/notifications/{notification_id}")
async def cancel_notification(notification_id: int, session: DbSession, ctx: CurrentTenant) -> dict:
    notification = await service.cancel(session, ctx, notification_id)
    return ok({"id": notification.id, "status": notification.status})


@router.post("/admin/notifications/dispatch-due")
async def dispatch_due(session: DbSession, ctx: AdminContext) -> dict:
    items = await service.dispatch_due(session, ctx)
    from app.domain.evaluation import audit

    await audit.record_audit(
        session,
        ctx,
        action="notification.dispatch",
        resource_type="notification",
        detail={"dispatched": len(items), "ids": [item.id for item in items]},
    )
    return ok({"dispatched": len(items), "ids": [item.id for item in items]})
