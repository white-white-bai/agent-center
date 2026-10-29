from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.deps import CurrentTenant, DbSession, ModelRouterDep, ToolExecutorDep
from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.core.responses import ok
from app.domain.session import chat_service, service
from app.domain.session.models import Run
from app.domain.tool import confirmation
from app.runtime.registry import run_registry

router = APIRouter(prefix="/chat/sessions", tags=["chat"])


class CreateSessionRequest(BaseModel):
    channel: str = Field(min_length=1, max_length=32)
    agent_group_code: str | None = Field(default=None, max_length=100)
    metadata: dict = Field(default_factory=dict)


@router.post("")
async def create_session(
    payload: CreateSessionRequest,
    session: DbSession,
    ctx: CurrentTenant,
) -> dict:
    conversation = await service.create_conversation(
        session,
        ctx,
        channel=payload.channel,
        agent_group_code=payload.agent_group_code,
        metadata=payload.metadata,
    )
    return ok(service.serialize_conversation(conversation))


@router.get("/{session_id}")
async def get_session(session_id: int, session: DbSession, ctx: CurrentTenant) -> dict:
    conversation = await service.get_conversation(session, ctx, session_id)
    return ok(service.serialize_conversation(conversation))


class SendMessageRequest(BaseModel):
    message: str = Field(min_length=1)
    attachments: list[dict] = Field(default_factory=list)
    clientMessageId: str | None = Field(default=None, max_length=100)
    agentCode: str | None = Field(default=None, max_length=100)


@router.post("/{session_id}/messages")
async def send_message(
    session_id: int,
    payload: SendMessageRequest,
    session: DbSession,
    ctx: CurrentTenant,
    router: ModelRouterDep,
    tool_executor: ToolExecutorDep,
) -> StreamingResponse:
    conversation = await service.get_conversation(session, ctx, session_id)
    duplicate = await chat_service.find_duplicate_reply(
        session, ctx, conversation, payload.clientMessageId
    )
    try:
        agent, version = await chat_service.resolve_agent(
            session, ctx, conversation, payload.agentCode, payload.message, router=router
        )
    except AppError as exc:
        if exc.code != "AC.ROUTE.NEED_CLARIFICATION":
            raise
        import json

        message = exc.message

        def _route_clarify():
            yield (
                "id: route:1\nevent: message.delta\n"
                f"data: {json.dumps({'runId': None, 'seq': 1, 'content': message}, ensure_ascii=False)}\n\n"
            )
            yield (
                "id: route:2\nevent: message.end\n"
                f"data: {json.dumps({'runId': None, 'finishReason': 'waiting_user'}, ensure_ascii=False)}\n\n"
            )

        return StreamingResponse(
            _route_clarify(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    stream = chat_service.stream_message(
        session,
        ctx,
        conversation=conversation,
        text=payload.message,
        client_message_id=payload.clientMessageId,
        agent=agent,
        version=version,
        router=router,
        tool_executor=tool_executor,
        duplicate=duplicate,
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{session_id}/runs/{run_id}/resume")
async def resume_run(
    session_id: int,
    run_id: str,
    session: DbSession,
    ctx: CurrentTenant,
    router: ModelRouterDep,
    tool_executor: ToolExecutorDep,
) -> dict:
    from app.domain.session import resume, run_service

    conversation = await service.get_conversation(session, ctx, session_id)
    old_run = await run_service.get_run(session, ctx, run_id, conversation_id=session_id)
    result = await resume.resume_run(
        session,
        ctx,
        conversation,
        old_run,
        router=router,
        tool_executor=tool_executor,
    )
    return ok(result)


class InterruptRequest(BaseModel):
    runId: str = Field(min_length=1, max_length=64)
    reason: str = Field(default="user_interrupt", max_length=100)


@router.post("/{session_id}/interrupt")
async def interrupt_run(
    session_id: int, payload: InterruptRequest, session: DbSession, ctx: CurrentTenant
) -> dict:
    await service.get_conversation(session, ctx, session_id)
    run = await session.get(Run, payload.runId)
    if run is None or run.tenant_id != ctx.tenant_id or run.conversation_id != session_id:
        raise NotFoundError("Run 不存在或无权访问")
    if run.status in {"COMPLETED", "FAILED", "INTERRUPTED"}:
        return ok({"accepted": False, "runId": run.id, "status": run.status})
    accepted = run_registry.request_interrupt(run.id)
    if not accepted:
        run.status = "INTERRUPTED"
        await session.commit()
    return ok({"accepted": True, "runId": run.id, "status": run.status})


class ConfirmationRequest(BaseModel):
    decision: str = Field(pattern="^(confirm|reject)$")
    arguments: dict | None = None


@router.post("/{session_id}/confirmations/{confirmation_id}")
async def decide_confirmation(
    session_id: int,
    confirmation_id: str,
    payload: ConfirmationRequest,
    session: DbSession,
    ctx: CurrentTenant,
) -> dict:
    conversation = await service.get_conversation(session, ctx, session_id)
    record, executable = await confirmation.decide(
        session,
        ctx,
        confirmation_id=confirmation_id,
        decision=payload.decision,
        arguments=payload.arguments,
    )
    execution = None
    if executable:
        from app.domain.tool.executor import ToolContext, function_tool_executor
        from app.domain.tool.service import invoke_tool

        tool_result = await invoke_tool(
            session,
            ctx,
            function_tool_executor,
            tool_code=record.tool_code,
            arguments=record.arguments_json,
            tool_context=ToolContext(
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
                conversation_id=session_id,
                run_id=record.run_id,
            ),
            allow_write=True,
        )
        execution = {
            "status": tool_result.status,
            "output": tool_result.output,
            "errorCode": tool_result.error_code,
            "cached": tool_result.cached,
        }
        conversation.status = "ACTIVE"
        await session.commit()
    return ok(
        {
            "confirmationId": record.confirmation_id,
            "status": record.status,
            "executable": executable,
            "toolCode": record.tool_code,
            "execution": execution,
        }
    )
