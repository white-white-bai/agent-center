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
from app.runtime.builder import ContextBuilder
from app.runtime.context import RunContext, RuntimeResult
from app.runtime.react_executor import ReActExecutor, build_system_prompt
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


async def resolve_agent(
    session: AsyncSession,
    ctx: TenantContext,
    conversation: Conversation,
    agent_code: str | None,
    message: str = "",
):
    if conversation.status not in {"ACTIVE", "WAITING_USER", "WAITING_CONFIRM"}:
        raise ConflictError(f"当前会话状态不允许发送消息: {conversation.status}")

    resolved_code = agent_code or conversation.current_agent_code
    if resolved_code:
        return await get_published_version(session, ctx, resolved_code)

    from app.runtime.supervisor import route

    metadata = (conversation.session_state_json or {}).get("metadata") or {}
    result = await route(
        session,
        ctx,
        message=message,
        channel=conversation.channel,
        region=metadata.get("region_code"),
    )
    if result.selected_agent is None or result.need_clarification:
        raise ConflictError("无法确定由哪个 Agent 处理，请补充业务领域或指定 agentCode")
    return await get_published_version(session, ctx, result.selected_agent)


async def find_duplicate_reply(
    session: AsyncSession, ctx: TenantContext, conversation: Conversation, client_message_id: str | None
) -> Message | None:
    if not client_message_id:
        return None
    return await _find_duplicate(session, ctx.tenant_id, conversation.id, client_message_id)


async def stream_message(
    session: AsyncSession,
    ctx: TenantContext,
    **kwargs,
) -> AsyncIterator[str]:
    """同一会话串行处理，避免并发写会话状态与 Run。"""
    from app.runtime.locks import conversation_lock_key
    from app.runtime.resilience import distributed_lock

    conversation: Conversation = kwargs["conversation"]
    async with distributed_lock(conversation_lock_key(ctx.tenant_id, conversation.id)):
        async for chunk in _stream_message_locked(session, ctx, **kwargs):
            yield chunk


async def _stream_message_locked(
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

    from app.domain.safety.service import REFUSAL_MESSAGE, get_safety_service

    safety = get_safety_service()
    input_check = await safety.check(text, "input")
    if not input_check.allowed:
        stream = _EventStream("blocked")
        yield stream.format(
            "error",
            {"runId": None, "code": "AC.SAFETY.BLOCKED", "message": input_check.reason},
        )
        yield stream.format("message.delta", {"runId": None, "seq": 1, "content": REFUSAL_MESSAGE})
        yield stream.format("message.end", {"runId": None, "finishReason": "safety_blocked"})
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
    event_buffer: list[dict] = []

    async def emit(event: str, data: dict) -> str:
        from app.infrastructure.redis.event_stream import publish_event

        text = stream.format(event, data)
        event_buffer.append({"seq": stream.seq, "event": event, "data": data})
        if run_id not in {"duplicate", "blocked"}:
            try:
                await publish_event(ctx.tenant_id, run_id, stream.seq, event, data)
            except Exception:  # noqa: BLE001 - 事件流不可用不影响对话
                pass
        return text

    yield await emit("run.start", {"runId": run_id, "agentCode": agent.code, "traceId": trace_id})

    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    async def on_event(event: dict) -> None:
        await queue.put(event)

    from app.core.config import get_settings

    settings = get_settings()
    model_policy = dict(version.model_policy_json or {})
    model_policy.setdefault("primary", settings.llm_model)
    model_policy.setdefault("fallback", settings.llm_fallback_model)
    token_budget = int(model_policy.get("token_budget", 32000))
    system_prompt, knowledge_results = await _build_system_prompt(
        session, ctx, conversation, version, user_message.id, text, token_budget, agent
    )

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
        model_policy=model_policy,
        allowed_tools=list(version.tool_bindings_json or []),
        max_steps=int(model_policy.get("max_steps", 8)),
        token_budget=token_budget,
        timeout_ms=int(model_policy.get("timeout_ms", settings.llm_timeout_ms)),
        system_prompt=system_prompt,
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
            yield await emit(event["event"], event["data"])

        result: RuntimeResult = await task
    finally:
        run_registry.finish(run_id)

    if result.status == "COMPLETED":
        output_check = await safety.check(result.answer, "output")
        if not output_check.allowed:
            result.answer = REFUSAL_MESSAGE
        async for chunk in _answer_events(stream, result.answer, emit):
            yield chunk
        assistant_message = await _save_assistant(session, ctx, conversation, turn, result.answer)
        if knowledge_results:
            for item in knowledge_results:
                yield await emit(
                    "citation",
                    {
                        "runId": run_id,
                        "docId": item["documentId"],
                        "chunkId": item["chunkId"],
                        "title": item["title"],
                        "clause": item.get("section"),
                        "url": item.get("sourceUrl"),
                    },
                )
            try:
                from app.domain.knowledge.citations import record_citations

                await record_citations(
                    session,
                    ctx,
                    run_id=run_id,
                    results=knowledge_results,
                    message_id=assistant_message.id,
                )
            except Exception:  # noqa: BLE001 - 引用落库失败不影响回答
                pass
        turn.status = "ANSWERED"
        conversation.status = "ACTIVE"
        yield await emit(
            "message.end",
            {
                "runId": run_id,
                "finishReason": "completed",
                "usage": {"input": result.token_input, "output": result.token_output},
                "messageId": str(assistant_message.id),
            },
        )
    elif result.status == "WAITING_USER":
        async for chunk in _answer_events(stream, result.question, emit):
            yield chunk
        assistant_message = await _save_assistant(session, ctx, conversation, turn, result.question)
        turn.status = "AWAITING_CLARIFICATION"
        conversation.status = "WAITING_USER"
        yield await emit(
            "message.end",
            {"runId": run_id, "finishReason": "waiting_user", "messageId": str(assistant_message.id)},
        )
    elif result.status == "HANDOFF":
        async for chunk in _answer_events(stream, result.answer, emit):
            yield chunk
        assistant_message = await _save_assistant(session, ctx, conversation, turn, result.answer)
        turn.status = "ANSWERED"
        conversation.status = "ACTIVE"
        yield await emit(
            "message.end",
            {"runId": run_id, "finishReason": "handoff", "messageId": str(assistant_message.id)},
        )
    elif result.status == "WAITING_CONFIRM":
        async for chunk in _answer_events(stream, result.confirmation_summary, emit):
            yield chunk
        assistant_message = await _save_assistant(
            session, ctx, conversation, turn, result.confirmation_summary
        )
        turn.status = "AWAITING_CONFIRMATION"
        conversation.status = "WAITING_CONFIRM"
        yield await emit(
            "message.end",
            {
                "runId": run_id,
                "finishReason": "waiting_confirm",
                "confirmationId": result.confirmation_id,
                "messageId": str(assistant_message.id),
            },
        )
    elif result.status == "INTERRUPTED":
        turn.status = "ANSWERED"
        conversation.status = "ACTIVE"
        yield await emit("message.end", {"runId": run_id, "finishReason": "interrupted"})
    else:
        turn.status = "ANSWERED"
        conversation.status = "ACTIVE"
        yield await emit(
            "error",
            {"runId": run_id, "code": result.error_code or "AC.RUN.FAILED", "message": "本轮执行未能完成"},
        )
        yield await emit("message.end", {"runId": run_id, "finishReason": "failed"})

    turn.ended_at = datetime.utcnow()
    await session.commit()

    if event_buffer:
        from app.domain.session.events import RunEvent

        session.add_all(
            [
                RunEvent(
                    tenant_id=ctx.tenant_id,
                    run_id=run_id,
                    seq=item["seq"],
                    event=item["event"],
                    data_json=item["data"],
                )
                for item in event_buffer
            ]
        )
        await session.commit()

    try:
        from app.domain.session.summarizer import should_compress, summarize_conversation

        if await should_compress(session, ctx.tenant_id, conversation.id):
            await summarize_conversation(session, ctx, conversation)
    except Exception:  # noqa: BLE001 - 摘要失败不得影响本轮对话
        pass


async def _answer_events(
    stream: _EventStream,
    answer: str,
    emit,
) -> AsyncIterator[str]:
    for index in range(0, len(answer), ANSWER_CHUNK_SIZE):
        yield await emit(
            "message.delta",
            {
                "runId": stream.run_id,
                "seq": stream.seq + 1,
                "content": answer[index : index + ANSWER_CHUNK_SIZE],
            },
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


async def _build_system_prompt(
    session: AsyncSession,
    ctx: TenantContext,
    conversation: Conversation,
    version,
    user_message_id: int,
    text: str,
    token_budget: int,
    agent=None,
) -> tuple[str, list[dict]]:
    from app.core.exceptions import ValidationError
    from app.domain.memory.service import search_memories
    from app.domain.profile.service import get_profile_summary
    from app.domain.prompt.models import PromptVersion
    from app.domain.prompt.service import render

    agent_prompt = build_system_prompt(
        version.config_json,
        list(version.tool_bindings_json or []),
        required_slots=version.config_json.get("required_slots") or [],
        session_state=conversation.session_state_json or {},
    )
    if version.prompt_version_id:
        prompt_version = await session.get(PromptVersion, version.prompt_version_id)
        if (
            prompt_version is not None
            and prompt_version.tenant_id == ctx.tenant_id
            and prompt_version.status == "PUBLISHED"
        ):
            variables = {
                "agent.role": version.config_json.get("role", ""),
                "goal": version.config_json.get("goal", ""),
                "question": text,
            }
            try:
                agent_prompt = agent_prompt + "\n\n" + render(prompt_version.content, variables)
            except ValidationError:
                pass

    profile_summary = ""
    memories: list[str] = []
    knowledge_results: list[dict] = []
    try:
        profile_summary = await get_profile_summary(session, ctx)
        items = await search_memories(session, ctx, query=text, limit=5)
        memories = [f"{item.subject}：{item.object_value}" for item in items]
    except Exception:  # noqa: BLE001 - 画像/记忆不可用不得阻塞对话
        pass

    try:
        from app.domain.knowledge.service import search as search_knowledge

        metadata = (conversation.session_state_json or {}).get("metadata") or {}
        knowledge_results = await search_knowledge(
            session,
            ctx,
            query=text,
            domain_code=getattr(agent, "domain_code", None),
            region_code=metadata.get("region_code"),
            top_k=5,
        )
    except Exception:  # noqa: BLE001 - 知识检索不可用不得阻塞对话
        knowledge_results = []

    built = await ContextBuilder(session).build(
        tenant_id=ctx.tenant_id,
        conversation=conversation,
        agent_prompt=agent_prompt,
        user_message=text,
        token_budget=token_budget,
        profile_summary=profile_summary,
        memories=memories,
        knowledge_snippets=[f"{item['title']}（{item.get('section') or '正文'}）：{item['content']}" for item in knowledge_results],
        exclude_message_id=user_message_id,
    )
    return built.to_prompt(), knowledge_results


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
