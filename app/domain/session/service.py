from datetime import datetime

from sqlalchemy import func, select
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


async def list_conversations(
    session: AsyncSession,
    ctx: TenantContext,
    *,
    user_id: str | None = None,
    status: str | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Conversation], int]:
    conditions = [Conversation.tenant_id == ctx.tenant_id]
    if user_id:
        conditions.append(Conversation.user_id == user_id)
    if status:
        conditions.append(Conversation.status == status)
    if start_at:
        conditions.append(Conversation.last_message_at >= start_at)
    if end_at:
        conditions.append(Conversation.last_message_at <= end_at)

    total = await session.scalar(select(func.count(Conversation.id)).where(*conditions))
    result = await session.execute(
        select(Conversation)
        .where(*conditions)
        .order_by(Conversation.last_message_at.desc(), Conversation.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result.scalars().all()), int(total or 0)


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
