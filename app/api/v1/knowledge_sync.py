from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import CurrentTenant, DbSession
from app.core.responses import ok
from app.core.tenant import require_admin
from app.domain.knowledge import service, sync

router = APIRouter(prefix="/admin/knowledge-sync-tasks", tags=["knowledge"], dependencies=[Depends(require_admin)])


class CreateSyncTaskRequest(BaseModel):
    spaceId: int
    sourceType: str = Field(default="UPLOAD", max_length=20)
    sourceRef: str | None = None
    documents: list[dict] | None = None


@router.post("")
async def create_sync_task(payload: CreateSyncTaskRequest, session: DbSession, ctx: CurrentTenant) -> dict:
    await service.get_space(session, ctx, payload.spaceId)
    task = await sync.create_sync_task(
        session,
        ctx,
        space_id=payload.spaceId,
        source_type=payload.sourceType,
        source_ref=payload.sourceRef,
    )
    if payload.documents is not None:
        task = await sync.run_sync_task(session, ctx, task, documents=payload.documents)
    from app.domain.evaluation import audit

    await audit.record_audit(
        session,
        ctx,
        action="knowledge.sync.create",
        resource_type="knowledge_sync_task",
        resource_id=task.id,
        detail={"spaceId": payload.spaceId, "sourceType": payload.sourceType, "status": task.status},
    )
    return ok(
        {
            "id": task.id,
            "status": task.status,
            "retryCount": task.retry_count,
            "checkpoint": task.checkpoint_json,
            "errorMessage": task.error_message,
        }
    )


@router.post("/{task_id}/run")
async def run_sync_task(task_id: int, session: DbSession, ctx: CurrentTenant) -> dict:
    task = await sync.get_task(session, ctx, task_id)
    task = await sync.run_sync_task(session, ctx, task)
    from app.domain.evaluation import audit

    await audit.record_audit(
        session,
        ctx,
        action="knowledge.sync.run",
        resource_type="knowledge_sync_task",
        resource_id=task.id,
        detail={"sourceType": task.source_type, "status": task.status},
    )
    return ok(
        {
            "id": task.id,
            "status": task.status,
            "retryCount": task.retry_count,
            "checkpoint": task.checkpoint_json,
            "errorMessage": task.error_message,
        }
    )


@router.get("/{task_id}")
async def get_sync_task(task_id: int, session: DbSession, ctx: CurrentTenant) -> dict:
    task = await sync.get_task(session, ctx, task_id)
    return ok(
        {
            "id": task.id,
            "status": task.status,
            "retryCount": task.retry_count,
            "checkpoint": task.checkpoint_json,
            "errorMessage": task.error_message,
        }
    )
