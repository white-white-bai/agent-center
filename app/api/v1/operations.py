from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import AdminContext, CurrentTenant, DbSession, ModelRouterDep
from app.core import metrics as app_metrics
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


@router.get("/chat/sessions/{session_id}/stream")
async def stream_session_events(
    session_id: int,
    session: DbSession,
    ctx: CurrentTenant,
    lastEventId: str | None = None,
    timeoutSeconds: float | None = None,
    heartbeatSeconds: float | None = None,
    pollSeconds: float = 1.0,
):
    """会话级长连接：心跳保活，按 Last-Event-ID 续传已落库事件。

    当前事件在 Run 结束后落库，本接口用于长连接保活与断线补偿；
    实时 token 流仍使用单 Run 的消息接口。
    """
    import asyncio
    import time

    from fastapi.responses import StreamingResponse
    from sqlalchemy import select as sa_select

    from app.core.config import get_settings
    from app.domain.session import event_service, service
    from app.domain.session.events import RunEvent
    from app.domain.session.models import Run

    await service.get_conversation(session, ctx, session_id)
    settings = get_settings()
    heartbeat = heartbeatSeconds or settings.sse_heartbeat_seconds
    poll = max(pollSeconds, 0.2)
    timeout = timeoutSeconds
    run_id, _, seq_text = (lastEventId or "").rpartition(":")
    after_id = 0
    if run_id and seq_text.isdigit():
        row = await session.execute(
            sa_select(RunEvent.id)
            .join(Run, Run.id == RunEvent.run_id)
            .where(
                RunEvent.tenant_id == ctx.tenant_id,
                Run.conversation_id == session_id,
                RunEvent.run_id == run_id,
                RunEvent.seq == int(seq_text),
            )
        )
        after_id = row.scalar_one_or_none() or 0
    await session.rollback()

    async def _generate():
        nonlocal after_id
        started = time.monotonic()
        last_beat = started
        disconnected = False
        app_metrics.sse_opened("session")
        try:
            yield event_service.format_sse(
                {"id": "session:ready", "event": "stream.ready", "data": {"sessionId": session_id}}
            )
            while True:
                if timeout is not None and time.monotonic() - started >= timeout:
                    yield event_service.format_sse(
                        {"id": "session:end", "event": "stream.end", "data": {"reason": "timeout"}}
                    )
                    return
                rows = await session.execute(
                    sa_select(RunEvent)
                    .join(Run, Run.id == RunEvent.run_id)
                    .where(
                        RunEvent.tenant_id == ctx.tenant_id,
                        Run.conversation_id == session_id,
                        RunEvent.id > after_id,
                    )
                    .order_by(RunEvent.id.asc())
                    .limit(200)
                )
                rows = list(rows.scalars().all())
                event_ids = [event.id for event in rows]
                serialized = [event_service.serialize_event(event) for event in rows]
                await session.rollback()
                for event_id, event in zip(event_ids, serialized):
                    after_id = event_id
                    yield event_service.format_sse(event)
                now = time.monotonic()
                if heartbeat > 0 and now - last_beat >= heartbeat:
                    yield event_service.format_sse(
                        {
                            "id": f"session:heartbeat:{int(now * 1000)}",
                            "event": "heartbeat",
                            "data": {"ts": datetime.utcnow().isoformat()},
                        }
                    )
                    last_beat = now
                await asyncio.sleep(poll)
        except (asyncio.CancelledError, GeneratorExit):
            disconnected = True
            raise
        finally:
            app_metrics.sse_closed("session", disconnected=disconnected)

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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

    await service.get_conversation(session, ctx, session_id)
    await run_service.get_run(session, ctx, run_id, conversation_id=session_id)
    events = await event_service.load_events(
        session,
        ctx,
        run_id,
        after_seq=event_service.parse_last_event_id(lastEventId),
        limit=limit,
    )
    return ok(events)


@router.get("/chat/sessions/{session_id}/runs/{run_id}/stream")
async def stream_run_events(
    session_id: int,
    run_id: str,
    session: DbSession,
    ctx: CurrentTenant,
    lastEventId: str | None = None,
    limit: int = 500,
):
    """按 Last-Event-ID 直接续流，客户端无需轮询重放接口。"""
    from fastapi.responses import StreamingResponse

    from app.domain.session import event_service

    await service.get_conversation(session, ctx, session_id)
    await run_service.get_run(session, ctx, run_id, conversation_id=session_id)
    events = await event_service.load_events(
        session,
        ctx,
        run_id,
        after_seq=event_service.parse_last_event_id(lastEventId),
        limit=limit,
    )

    async def _generate():
        for event in events:
            yield event_service.format_sse(event)
        yield event_service.format_sse(
            {"id": f"{run_id}:end", "event": "stream.end", "data": {"runId": run_id}}
        )

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class PurgeTraceRequest(BaseModel):
    days: int | None = Field(default=None, ge=1, le=3650)


@router.post("/admin/maintenance/purge-trace")
async def purge_trace(payload: PurgeTraceRequest, session: DbSession, ctx: AdminContext) -> dict:
    from app.workers.retention import purge_trace as purge
    from app.domain.evaluation import audit

    result = await purge(session, ctx, days=payload.days)
    await audit.record_audit(
        session,
        ctx,
        action="maintenance.purge_trace",
        resource_type="trace",
        detail=result,
    )
    return ok(result)


@router.get("/admin/sessions")
async def list_sessions(
    session: DbSession,
    ctx: AdminContext,
    userId: str | None = None,
    status: str | None = None,
    startAt: datetime | None = None,
    endAt: datetime | None = None,
    page: int = 1,
    pageSize: int = 20,
) -> dict:
    page = max(page, 1)
    page_size = min(max(pageSize, 1), 100)
    items, total = await service.list_conversations(
        session,
        ctx,
        user_id=userId,
        status=status,
        start_at=startAt,
        end_at=endAt,
        page=page,
        page_size=page_size,
    )
    return ok(
        {
            "items": [service.serialize_conversation(item) for item in items],
            "total": total,
            "page": page,
            "pageSize": page_size,
        }
    )


@router.get("/admin/model/health")
async def model_health(session: DbSession, ctx: AdminContext, model_router: ModelRouterDep) -> dict:
    """实际调用一次模型，验证密钥、地址与模型是否可用。"""
    import time

    from app.core.config import get_settings
    from app.integrations.llm.client import ChatMessage, LLMRequest

    settings = get_settings()
    if not settings.llm_api_key:
        return ok(
            {
                "configured": False,
                "ok": False,
                "message": "未配置 AC_LLM_API_KEY，当前使用桩模型",
            }
        )

    started = time.perf_counter()
    try:
        response = await model_router.complete(
            session,
            ctx,
            LLMRequest(
                messages=[ChatMessage(role="user", content="只回复两个字：正常")],
                model=settings.llm_model,
                timeout_ms=15000,
            ),
            primary_model=settings.llm_model,
            fallback_model=settings.llm_fallback_model,
            max_retries=0,
        )
    except Exception as exc:  # noqa: BLE001 - 健康检查返回原因而不是抛错
        return ok(
            {
                "configured": True,
                "ok": False,
                "model": settings.llm_model,
                "latencyMs": int((time.perf_counter() - started) * 1000),
                "message": str(exc)[:300],
                "hint": "401 通常表示密钥失效或被轮换，请到 Command Code Studio 重新生成 API Key",
            }
        )

    return ok(
        {
            "configured": True,
            "ok": True,
            "model": response.model,
            "latencyMs": int((time.perf_counter() - started) * 1000),
            "finishReason": response.finish_reason,
            "content": response.content[:100],
            "tokens": {"input": response.token_input, "output": response.token_output},
        }
    )


@router.get("/admin/metrics/prometheus")
async def prometheus_metrics(session: DbSession, ctx: AdminContext):
    from fastapi.responses import PlainTextResponse

    from app.domain.evaluation import alerts, metrics

    data = await metrics.overview(session, ctx)
    return PlainTextResponse(
        alerts.render_prometheus(data),
        media_type=alerts.prometheus_content_type(),
    )


@router.post("/admin/alerts/check")
async def check_alerts(session: DbSession, ctx: AdminContext) -> dict:
    from app.domain.evaluation import alerts

    found = await alerts.evaluate_alerts(session, ctx)
    notified = await alerts.notify_alerts(found)
    return ok({"alerts": [alert.to_dict() for alert in found], "notified": notified})


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
