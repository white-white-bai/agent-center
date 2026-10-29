from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import TenantContext
from app.domain.session.models import Conversation, Message

SUMMARY_TRIGGER_MESSAGES = 12
SUMMARY_KEEP_LAST = 6
SUMMARY_MAX_CHARS = 800


def compress_messages(messages: list[Message], keep_last: int = SUMMARY_KEEP_LAST) -> str:
    """规则式压缩：保留早期问题与关键结论，控制摘要长度。

    生产环境应替换为模型摘要，见 docs/open-questions.md。
    """
    if len(messages) <= keep_last:
        return ""
    older = messages[:-keep_last]
    user_questions = [message.content for message in older if message.role == "user"]
    assistant_conclusions = [message.content for message in older if message.role == "assistant"]

    parts: list[str] = []
    if user_questions:
        parts.append("历史问题：" + "；".join(item[:80] for item in user_questions[-5:]))
    if assistant_conclusions:
        parts.append("历史结论：" + "；".join(item[:120] for item in assistant_conclusions[-3:]))
    summary = "。".join(parts)
    return summary[:SUMMARY_MAX_CHARS]


async def should_compress(session: AsyncSession, tenant_id: str, conversation_id: int) -> bool:
    result = await session.execute(
        select(func.count(Message.id)).where(
            Message.tenant_id == tenant_id, Message.conversation_id == conversation_id
        )
    )
    return (result.scalar_one() or 0) > SUMMARY_TRIGGER_MESSAGES


async def summarize_conversation(
    session: AsyncSession, ctx: TenantContext, conversation: Conversation
) -> str | None:
    result = await session.execute(
        select(Message)
        .where(
            Message.tenant_id == ctx.tenant_id,
            Message.conversation_id == conversation.id,
        )
        .order_by(Message.id.asc())
    )
    messages = list(result.scalars().all())
    summary = compress_messages(messages)
    if not summary:
        return None
    conversation.context_summary = summary
    await session.commit()
    return summary
