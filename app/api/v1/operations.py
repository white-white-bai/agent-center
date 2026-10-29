from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import CurrentTenant, DbSession
from app.core.responses import ok
from app.domain.session import run_service, service

router = APIRouter(tags=["operations"])


@router.get("/chat/sessions/{session_id}/runs/{run_id}")
async def get_session_run(session_id: int, run_id: str, session: DbSession, ctx: CurrentTenant) -> dict:
    await service.get_conversation(session, ctx, session_id)
    run = await run_service.get_run(session, ctx, run_id, conversation_id=session_id)
    steps = await run_service.list_steps(session, ctx, run_id)
    return ok({"run": run_service.serialize_run(run), "steps": [run_service.serialize_step(s) for s in steps]})


@router.get("/admin/runs/{run_id}")
async def get_run_admin(run_id: str, session: DbSession, ctx: CurrentTenant) -> dict:
    run = await run_service.get_run(session, ctx, run_id)
    steps = await run_service.list_steps(session, ctx, run_id)
    return ok({"run": run_service.serialize_run(run), "steps": [run_service.serialize_step(s) for s in steps]})


class FeedbackRequest(BaseModel):
    conversationId: int | None = None
    messageId: int | None = None
    runId: str | None = None
    rating: str = Field(pattern="^(up|down)$")
    reason: str | None = Field(default=None, max_length=100)
    comment: str | None = Field(default=None, max_length=2000)


@router.post("/feedback")
async def submit_feedback(payload: FeedbackRequest, session: DbSession, ctx: CurrentTenant) -> dict:
    feedback = await run_service.submit_feedback(
        session,
        ctx,
        rating=payload.rating,
        conversation_id=payload.conversationId,
        message_id=payload.messageId,
        run_id=payload.runId,
        reason=payload.reason,
        comment=payload.comment,
    )
    return ok(run_service.serialize_feedback(feedback))
