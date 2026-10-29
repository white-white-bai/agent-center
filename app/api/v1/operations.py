from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import AdminContext, CurrentTenant, DbSession
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
async def get_run_admin(run_id: str, session: DbSession, ctx: AdminContext) -> dict:
    run = await run_service.get_run(session, ctx, run_id)
    steps = await run_service.list_steps(session, ctx, run_id)
    return ok({"run": run_service.serialize_run(run), "steps": [run_service.serialize_step(s) for s in steps]})


@router.get("/chat/sessions/{session_id}/runs/{run_id}/events")
async def replay_run_events(
    session_id: int,
    run_id: str,
    session: DbSession,
    ctx: CurrentTenant,
    lastEventId: str | None = None,
    limit: int = 500,
) -> dict:
    from app.domain.session import event_service
    from app.infrastructure.redis.event_stream import read_events, serialize_stream_event

    await service.get_conversation(session, ctx, session_id)
    await run_service.get_run(session, ctx, run_id, conversation_id=session_id)
    after_seq = event_service.parse_last_event_id(lastEventId)
    stream_events = await read_events(ctx.tenant_id, run_id, after_seq=after_seq, limit=limit)
    if stream_events:
        return ok([serialize_stream_event(event) for event in stream_events])
    events = await event_service.list_events(
        session, ctx, run_id, after_seq=after_seq, limit=limit
    )
    return ok([event_service.serialize_event(event) for event in events])


class PurgeTraceRequest(BaseModel):
    days: int | None = Field(default=None, ge=1, le=3650)


@router.post("/admin/maintenance/purge-trace")
async def purge_trace(payload: PurgeTraceRequest, session: DbSession, ctx: AdminContext) -> dict:
    from app.workers.retention import purge_trace as purge

    return ok(await purge(session, ctx, days=payload.days))


@router.get("/admin/metrics/overview")
async def metrics_overview(session: DbSession, ctx: AdminContext) -> dict:
    from app.domain.evaluation import metrics

    return ok(await metrics.overview(session, ctx))


class ConvertBadcaseRequest(BaseModel):
    datasetId: int
    question: str = Field(min_length=1)
    expectedAnswer: str | None = None


@router.get("/admin/badcases")
async def list_badcases(session: DbSession, ctx: AdminContext, status: str | None = None) -> dict:
    from app.domain.evaluation import badcase

    items = await badcase.list_badcases(session, ctx, status=status)
    return ok(
        [
            {
                "id": item.id,
                "runId": item.run_id,
                "status": item.status,
                "description": item.description,
                "evalCaseId": item.eval_case_id,
            }
            for item in items
        ]
    )


@router.post("/admin/badcases/{badcase_id}/convert")
async def convert_badcase(
    badcase_id: int, payload: ConvertBadcaseRequest, session: DbSession, ctx: AdminContext
) -> dict:
    from app.domain.evaluation import audit, badcase

    item = await badcase.convert_to_eval_case(
        session,
        ctx,
        badcase_id,
        dataset_id=payload.datasetId,
        question=payload.question,
        expected_answer=payload.expectedAnswer,
    )
    await audit.record_audit(
        session, ctx, action="badcase.convert", resource_type="badcase", resource_id=item.id
    )
    return ok({"id": item.id, "status": item.status, "evalCaseId": item.eval_case_id})


@router.get("/admin/audit-logs")
async def list_audit_logs(
    session: DbSession,
    ctx: AdminContext,
    action: str | None = None,
    resourceType: str | None = None,
    limit: int = 100,
) -> dict:
    from app.domain.evaluation import audit

    entries = await audit.list_audit_logs(
        session, ctx, action=action, resource_type=resourceType, limit=limit
    )
    return ok([audit.serialize_audit(entry) for entry in entries])


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
