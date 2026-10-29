from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError
from app.core.tenant import TenantContext
from app.core.tracing import get_trace_id
from app.domain.agent.models import AgentVersion
from app.domain.session import chat_service
from app.domain.session.models import Conversation, Message, Run
from app.runtime.context import RunContext
from app.runtime.react_executor import ReActExecutor
from app.runtime.registry import run_registry

RESUMABLE_STATUSES = {"FAILED", "INTERRUPTED"}
TERMINAL_CHILD_STATUSES = {"QUEUED", "RUNNING"}


async def _last_user_message(session: AsyncSession, tenant_id: str, conversation_id: int) -> str:
    result = await session.execute(
        select(Message)
        .where(
            Message.tenant_id == tenant_id,
            Message.conversation_id == conversation_id,
            Message.role == "user",
        )
        .order_by(Message.id.desc())
        .limit(1)
    )
    message = result.scalar_one_or_none()
    return message.content if message else ""


async def resume_run(
    session: AsyncSession,
    ctx: TenantContext,
    conversation: Conversation,
    old_run: Run,
    *,
    router,
    tool_executor,
) -> dict:
    if old_run.status not in RESUMABLE_STATUSES:
        raise ConflictError(f"Run 当前状态不可恢复: {old_run.status}")

    children = await session.execute(
        select(Run).where(
            Run.tenant_id == ctx.tenant_id,
            Run.parent_run_id == old_run.id,
            Run.status.in_(TERMINAL_CHILD_STATUSES),
        )
    )
    if children.scalar_one_or_none() is not None:
        raise ConflictError("该 Run 已存在进行中的恢复任务")

    version = await session.get(AgentVersion, old_run.agent_version_id) if old_run.agent_version_id else None
    if version is None or version.tenant_id != ctx.tenant_id:
        raise NotFoundError("Run 关联的 Agent 版本不存在")

    settings = get_settings()
    model_policy = dict(version.model_policy_json or {})
    model_policy.setdefault("primary", settings.llm_model)
    model_policy.setdefault("fallback", settings.llm_fallback_model)

    user_text = await _last_user_message(session, ctx.tenant_id, conversation.id)
    token_budget = int(model_policy.get("token_budget", 32000))
    system_prompt, _ = await chat_service._build_system_prompt(
        session,
        ctx,
        conversation,
        version,
        user_message_id=0,
        text=user_text,
        token_budget=token_budget,
        agent=None,
    )

    new_run_id = f"run_{uuid4().hex}"
    trace_id = get_trace_id() or f"trace_{uuid4().hex}"
    new_run = Run(
        id=new_run_id,
        tenant_id=ctx.tenant_id,
        conversation_id=conversation.id,
        turn_id=old_run.turn_id,
        agent_version_id=version.id,
        agent_code=old_run.agent_code,
        parent_run_id=old_run.id,
        trace_id=trace_id,
        status="QUEUED",
        step_budget=int(model_policy.get("max_steps", 8)),
        token_budget=token_budget,
        token_input=old_run.token_input,
        token_output=old_run.token_output,
        tool_call_count=old_run.tool_call_count,
    )
    session.add(new_run)
    conversation.status = "ACTIVE"
    await session.commit()

    run_ctx = RunContext(
        run_id=new_run_id,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        conversation_id=conversation.id,
        turn_id=old_run.turn_id,
        agent_code=old_run.agent_code or "",
        trace_id=trace_id,
        user_message=user_text,
        agent_config=version.config_json,
        model_policy=model_policy,
        allowed_tools=list(version.tool_bindings_json or []),
        max_steps=int(model_policy.get("max_steps", 8)),
        token_budget=token_budget,
        timeout_ms=int(model_policy.get("timeout_ms", settings.llm_timeout_ms)),
        system_prompt=system_prompt,
    )
    run_registry.register(new_run_id)
    try:
        result = await ReActExecutor(
            session, router, tool_executor, registry=run_registry
        ).run(ctx, run_ctx)
    finally:
        run_registry.finish(new_run_id)

    result.token_input += old_run.token_input
    result.token_output += old_run.token_output
    result.tool_calls += old_run.tool_call_count
    refreshed = await session.get(Run, new_run_id)
    if refreshed is not None:
        refreshed.token_input = result.token_input
        refreshed.token_output = result.token_output
        refreshed.tool_call_count = result.tool_calls
        await session.commit()

    if result.status == "COMPLETED" and result.answer:
        assistant = Message(
            tenant_id=ctx.tenant_id,
            conversation_id=conversation.id,
            turn_id=old_run.turn_id,
            role="assistant",
            content=result.answer,
            token_count=len(result.answer),
        )
        session.add(assistant)
        conversation.status = "ACTIVE"
    elif result.status == "WAITING_USER":
        conversation.status = "WAITING_USER"
    elif result.status == "WAITING_CONFIRM":
        conversation.status = "WAITING_CONFIRM"
    conversation.last_message_at = datetime.utcnow()
    await session.commit()

    return {
        "runId": new_run_id,
        "parentRunId": old_run.id,
        "status": result.status,
        "answer": result.answer,
        "question": result.question,
        "steps": result.steps,
        "toolCalls": result.tool_calls,
        "confirmationId": result.confirmation_id,
    }
