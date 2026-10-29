import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.session.models import Conversation, Message
from app.runtime.context_builder import (
    PRIORITY_AGENT,
    PRIORITY_KNOWLEDGE,
    PRIORITY_MEMORY,
    PRIORITY_PROFILE,
    PRIORITY_RECENT,
    PRIORITY_SAFETY,
    PRIORITY_STATE,
    PRIORITY_SUMMARY,
    SAFETY_BASELINE,
    BuiltContext,
    Section,
    default_reserve,
    fit_budget,
)


async def _recent_messages(
    session: AsyncSession,
    tenant_id: str,
    conversation_id: int,
    limit: int = 6,
    exclude_message_id: int | None = None,
) -> list[Message]:
    query = select(Message).where(
        Message.tenant_id == tenant_id, Message.conversation_id == conversation_id
    )
    if exclude_message_id is not None:
        query = query.where(Message.id != exclude_message_id)
    result = await session.execute(query.order_by(Message.id.desc()).limit(limit))
    return list(reversed(result.scalars().all()))


class ContextBuilder:
    """按优先级装配上下文，超预算时从低优先级裁剪。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def build(
        self,
        *,
        tenant_id: str,
        conversation: Conversation,
        agent_prompt: str,
        user_message: str,
        token_budget: int = 32000,
        profile_summary: str = "",
        memories: list[str] | None = None,
        knowledge_snippets: list[str] | None = None,
        exclude_message_id: int | None = None,
    ) -> BuiltContext:
        sections = [
            Section(name="safety", priority=PRIORITY_SAFETY, content=SAFETY_BASELINE),
            Section(name="agent", priority=PRIORITY_AGENT, content=agent_prompt),
            Section(
                name="session_state",
                priority=PRIORITY_STATE,
                content="会话状态：" + json.dumps(conversation.session_state_json or {}, ensure_ascii=False),
            ),
        ]

        recent = await _recent_messages(
            self.session, tenant_id, conversation.id, exclude_message_id=exclude_message_id
        )
        recent_text = "\n".join(f"{message.role}: {message.content}" for message in recent)
        sections.append(Section(name="recent_messages", priority=PRIORITY_RECENT, content=recent_text))

        if conversation.context_summary:
            sections.append(
                Section(name="summary", priority=PRIORITY_SUMMARY, content=conversation.context_summary)
            )
        if knowledge_snippets:
            sections.append(
                Section(
                    name="knowledge",
                    priority=PRIORITY_KNOWLEDGE,
                    content="知识片段：\n" + "\n".join(knowledge_snippets),
                )
            )
        if profile_summary:
            sections.append(Section(name="profile", priority=PRIORITY_PROFILE, content=profile_summary))
        if memories:
            sections.append(
                Section(name="memory", priority=PRIORITY_MEMORY, content="记忆：\n" + "\n".join(memories))
            )

        sections.append(
            Section(name="user_message", priority=PRIORITY_RECENT, content=f"user: {user_message}")
        )

        return fit_budget(
            sections, token_budget=token_budget, reserve_tokens=default_reserve(token_budget)
        )
