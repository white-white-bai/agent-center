from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.deps import CurrentTenant, DbSession, ModelRouterDep, ToolExecutorDep
from app.core.exceptions import ConflictError, NotFoundError
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
    agent, version = await chat_service.resolve_agent(session, ctx, conversation, payload.agentCode)
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
    await service.get_conversation(session, ctx, session_id)
    record, executable = await confirmation.decide(
        session,
        ctx,
        confirmation_id=confirmation_id,
        decision=payload.decision,
        arguments=payload.arguments,
    )
    return ok(
        {
            "confirmationId": record.confirmation_id,
            "status": record.status,
            "executable": executable,
            "toolCode": record.tool_code,
        }
    )
