from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.core.tenant import TenantContext
from app.domain.agent.models import AgentDefinition
from app.domain.agent.service import get_published_version
from app.domain.session.models import Conversation

MAX_HANDOFF_HOPS = 3


@dataclass
class HandoffRequest:
    from_agent: str
    to_agent: str
    reason: str
    goal: str = ""
    confirmed_facts: dict = field(default_factory=dict)
    pending_slots: list[str] = field(default_factory=list)
    already_asked: list[str] = field(default_factory=list)
    tool_results: list = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)


def _hops(conversation: Conversation) -> int:
    return int((conversation.session_state_json or {}).get("handoff_hops", 0))


async def validate_and_apply(
    session: AsyncSession,
    ctx: TenantContext,
    conversation: Conversation,
    request: HandoffRequest,
) -> tuple[AgentDefinition, object]:
    if request.from_agent == request.to_agent:
        raise ConflictError("不能交接给自己")
    if _hops(conversation) >= MAX_HANDOFF_HOPS:
        raise ConflictError(f"交接次数超过上限（{MAX_HANDOFF_HOPS}），已阻止循环交接")

    result = await session.execute(
        select(AgentDefinition).where(
            AgentDefinition.tenant_id == ctx.tenant_id,
            AgentDefinition.code == request.to_agent,
        )
    )
    target = result.scalar_one_or_none()
    if target is None:
        raise NotFoundError(f"目标 Agent 不存在或无权访问: {request.to_agent}")
    if target.lifecycle != "PUBLISHED":
        raise ConflictError(f"目标 Agent 未发布: {request.to_agent}")

    agent, version = await get_published_version(session, ctx, request.to_agent)

    state = dict(conversation.session_state_json or {})
    state["handoff_hops"] = _hops(conversation) + 1
    state["last_handoff"] = {
        "from": request.from_agent,
        "to": request.to_agent,
        "reason": request.reason,
        "confirmed_facts": request.confirmed_facts,
        "pending_slots": request.pending_slots,
        "already_asked": request.already_asked,
    }
    conversation.session_state_json = state
    conversation.current_agent_code = request.to_agent
    await session.commit()
    return agent, version
