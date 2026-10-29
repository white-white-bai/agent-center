import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.core.tenant import TenantContext
from app.core.tracing import get_trace_id
from app.domain.agent.service import get_published_version
from app.domain.session.models import Conversation, ConversationTurn, Message, Run
from app.runtime.context import RunContext, RuntimeResult
from app.runtime.react_executor import ReActExecutor
from app.runtime.registry import run_registry

ANSWER_CHUNK_SIZE = 20


class _EventStream:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.seq = 0

    def format(self, event: str, data: dict) -> str:
        self.seq += 1
        payload = json.dumps(data, ensure_ascii=False)
        return f"id: {self.run_id}:{self.seq}\nevent: {event}\ndata: {payload}\n\n"


async def _next_turn_no(session: AsyncSession, tenant_id: str, conversation_id: int) -> int:
    result = await session.execute(
        select(func.max(ConversationTurn.turn_no)).where(
            ConversationTurn.tenant_id == tenant_id,
            ConversationTurn.conversation_id == conversation_id,
        )
    )
    return (result.scalar_one_or_none() or 0) + 1


async def _find_duplicate(
    session: AsyncSession, tenant_id: str, conversation_id: int, client_message_id: str
) -> Message | None:
    result = await session.execute(
        select(Message).where(
            Message.tenant_id == tenant_id,
            Message.conversation_id == conversation_id,
            Message.client_message_id == client_message_id,
            Message.role == "user",
        )
    )
    user_message = result.scalar_one_or_none()
    if user_message is None or user_message.turn_id is None:
        return None
    turn = await session.get(ConversationTurn, user_message.turn_id)
    if turn is None or turn.assistant_message_id is None:
        return None
    return await session.get(Message, turn.assistant_message_id)


async def resolve_agent(session: AsyncSession, ctx: TenantContext, conversation: Conversation, agent_code: str | None):
    if conversation.status not in {"ACTIVE", "WAITING_USER", "WAITING_CONFIRM"}:
        raise ConflictError(f"当前会话状态不允许发送消息: {conversation.status}")

    resolved_code = agent_code or conversation.current_agent_code
    if resolved_code:
        return await get_published_version(session, ctx, resolved_code)
    resolved = await _first_published_agent(session, ctx)
    if resolved is None:
        raise ConflictError("租户下没有已发布的 Agent，无法处理消息")
    return resolved


async def find_duplicate_reply(
    session: AsyncSession, ctx: TenantContext, conversation: Conversation, client_message_id: str | None
) -> Message | None:
    if not client_message_id:
        return None
    return await _find_duplicate(session, ctx.tenant_id, conversation.id, client_message_id)


async def stream_message(
    session: AsyncSession,
    ctx: TenantContext,
    *,
    conversation: Conversation,
    text: str,
    client_message_id: str | None,
    agent,
    version,
    router,
    tool_executor,
    duplicate: Message | None = None,
) -> AsyncIterator[str]:
    if duplicate is not None:
        stream = _EventStream("duplicate")
        yield stream.format("message.delta", {"runId": None, "seq": 1, "content": duplicate.content})
        yield stream.format("message.end", {"runId": None, "finishReason": "duplicate"})
        return

    turn_no = await _next_turn_no(session, ctx.tenant_id, conversation.id)
    turn = ConversationTurn(
        tenant_id=ctx.tenant_id,
        conversation_id=conversation.id,
        turn_no=turn_no,
        status="OPEN",
        started_at=datetime.utcnow(),
    )
    session.add(turn)
    await session.commit()
    await session.refresh(turn)

    user_message = Message(
        tenant_id=ctx.tenant_id,
        conversation_id=conversation.id,
        turn_id=turn.id,
        role="user",
        content=text,
        client_message_id=client_message_id,
    )
    session.add(user_message)
    await session.commit()
    await session.refresh(user_message)
    turn.user_message_id = user_message.id

    run_id = f"run_{uuid4().hex}"
    trace_id = get_trace_id() or f"trace_{uuid4().hex}"
    run = Run(
        id=run_id,
        tenant_id=ctx.tenant_id,
        conversation_id=conversation.id,
        turn_id=turn.id,
        agent_version_id=version.id,
        agent_code=agent.code,
        trace_id=trace_id,
        status="QUEUED",
        step_budget=int(version.model_policy_json.get("max_steps", 8)),
        token_budget=int(version.model_policy_json.get("token_budget", 32000)),
    )
    session.add(run)
    conversation.current_agent_code = agent.code
    conversation.last_message_at = datetime.utcnow()
    await session.commit()

    stream = _EventStream(run_id)
    yield stream.format("run.start", {"runId": run_id, "agentCode": agent.code, "traceId": trace_id})

    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    async def on_event(event: dict) -> None:
        await queue.put(event)

    run_ctx = RunContext(
        run_id=run_id,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        conversation_id=conversation.id,
        turn_id=turn.id,
        agent_code=agent.code,
        trace_id=trace_id,
        user_message=text,
        agent_config=version.config_json,
        model_policy=version.model_policy_json,
        allowed_tools=list(version.tool_bindings_json or []),
        max_steps=int(version.model_policy_json.get("max_steps", 8)),
        token_budget=int(version.model_policy_json.get("token_budget", 32000)),
        timeout_ms=int(version.model_policy_json.get("timeout_ms", 30000)),
    )
    executor = ReActExecutor(
        session,
        router,
        tool_executor,
        on_event=on_event,
        registry=run_registry,
    )
    run_registry.register(run_id)
    task = asyncio.create_task(executor.run(ctx, run_ctx))

    try:
        while True:
            if task.done() and queue.empty():
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=0.05)
            except asyncio.TimeoutError:
                continue
            if event is None:
                break
            yield stream.format(event["event"], event["data"])

        result: RuntimeResult = await task
    finally:
        run_registry.finish(run_id)

    if result.status == "COMPLETED":
        for chunk in _stream_answer(stream, result.answer):
            yield chunk
        assistant_message = await _save_assistant(session, ctx, conversation, turn, result.answer)
        turn.status = "ANSWERED"
        conversation.status = "ACTIVE"
        yield stream.format(
            "message.end",
            {
                "runId": run_id,
                "finishReason": "completed",
                "usage": {"input": result.token_input, "output": result.token_output},
                "messageId": str(assistant_message.id),
            },
        )
    elif result.status == "WAITING_USER":
        for chunk in _stream_answer(stream, result.question):
            yield chunk
        assistant_message = await _save_assistant(session, ctx, conversation, turn, result.question)
        turn.status = "AWAITING_CLARIFICATION"
        conversation.status = "WAITING_USER"
        yield stream.format(
            "message.end",
            {"runId": run_id, "finishReason": "waiting_user", "messageId": str(assistant_message.id)},
        )
    elif result.status == "INTERRUPTED":
        turn.status = "ANSWERED"
        conversation.status = "ACTIVE"
        yield stream.format("message.end", {"runId": run_id, "finishReason": "interrupted"})
    else:
        turn.status = "ANSWERED"
        conversation.status = "ACTIVE"
        yield stream.format(
            "error",
            {"runId": run_id, "code": result.error_code or "AC.RUN.FAILED", "message": "本轮执行未能完成"},
        )
        yield stream.format("message.end", {"runId": run_id, "finishReason": "failed"})

    turn.ended_at = datetime.utcnow()
    await session.commit()


def _stream_answer(stream: _EventStream, answer: str) -> AsyncIterator[str]:
    for index in range(0, len(answer), ANSWER_CHUNK_SIZE):
        yield stream.format(
            "message.delta",
            {"runId": stream.run_id, "seq": stream.seq + 1, "content": answer[index : index + ANSWER_CHUNK_SIZE]},
        )


async def _save_assistant(
    session: AsyncSession,
    ctx: TenantContext,
    conversation: Conversation,
    turn: ConversationTurn,
    content: str,
) -> Message:
    message = Message(
        tenant_id=ctx.tenant_id,
        conversation_id=conversation.id,
        turn_id=turn.id,
        role="assistant",
        content=content,
        token_count=len(content),
    )
    session.add(message)
    await session.commit()
    await session.refresh(message)
    turn.assistant_message_id = message.id
    await session.commit()
    return message


async def _first_published_agent(session: AsyncSession, ctx: TenantContext):
    from app.domain.agent.models import AgentDefinition
    from app.domain.agent.service import get_published_version

    result = await session.execute(
        select(AgentDefinition)
        .where(AgentDefinition.tenant_id == ctx.tenant_id, AgentDefinition.lifecycle == "PUBLISHED")
        .order_by(AgentDefinition.id.asc())
        .limit(1)
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        return None
    return await get_published_version(session, ctx, agent.code)
