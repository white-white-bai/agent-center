from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.tenant import TenantContext
from app.domain.session.models import Conversation


async def create_conversation(
    session: AsyncSession,
    ctx: TenantContext,
    *,
    channel: str,
    agent_group_code: str | None = None,
    metadata: dict | None = None,
) -> Conversation:
    state = {"metadata": metadata or {}}
    conversation = Conversation(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        channel=channel,
        status="ACTIVE",
        agent_group_code=agent_group_code,
        session_state_json=state,
        last_message_at=datetime.utcnow(),
    )
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return conversation


async def get_conversation(session: AsyncSession, ctx: TenantContext, conversation_id: int) -> Conversation:
    result = await session.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == ctx.tenant_id,
        )
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise NotFoundError("会话不存在或无权访问")
    return conversation


def serialize_conversation(conversation: Conversation) -> dict:
    return {
        "sessionId": str(conversation.id),
        "channel": conversation.channel,
        "status": conversation.status,
        "agentGroupCode": conversation.agent_group_code,
        "currentAgentCode": conversation.current_agent_code,
        "sessionState": conversation.session_state_json,
        "lastMessageAt": conversation.last_message_at.isoformat() if conversation.last_message_at else None,
    }
