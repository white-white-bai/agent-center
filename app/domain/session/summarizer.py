from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import TenantContext
from app.domain.session.models import Conversation, Message

SUMMARY_TRIGGER_MESSAGES = 12
SUMMARY_KEEP_LAST = 6
SUMMARY_MAX_CHARS = 800


def compress_messages(
    messages: list[Message],
    keep_last: int = SUMMARY_KEEP_LAST,
    *,
    max_chars: int | None = None,
) -> str:
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
    return summary[: max_chars or SUMMARY_MAX_CHARS]


async def should_compress(session: AsyncSession, tenant_id: str, conversation_id: int) -> bool:
    result = await session.execute(
        select(func.count(Message.id)).where(
            Message.tenant_id == tenant_id, Message.conversation_id == conversation_id
        )
    )
    return (result.scalar_one() or 0) > SUMMARY_TRIGGER_MESSAGES


SUMMARY_PROMPT = """请把下面的会话压缩为不超过 {max_chars} 字的中文摘要，保留已确认事实、未完成任务与关键结论。
会话内容：
{content}
只输出 JSON：{{"summary":"摘要内容"}}
"""


async def _model_summary(
    messages: list[Message],
    router,
    model: str,
    ctx,
    session,
    *,
    prompt_max_chars: int,
    hard_max_chars: int,
) -> str | None:
    import json

    from app.integrations.llm.client import ChatMessage as LLMMessage
    from app.integrations.llm.client import LLMRequest

    content = "\n".join(f"{m.role}: {m.content}" for m in messages[-20:])
    request = LLMRequest(
        messages=[
            LLMMessage(
                role="user",
                content=SUMMARY_PROMPT.format(
                    content=content, max_chars=prompt_max_chars
                ),
            )
        ],
        model=model,
        response_format={"type": "json_object"},
    )
    response = await router.complete(session, ctx, request, primary_model=model, max_retries=0)
    payload = json.loads(response.content)
    summary = (payload.get("summary") or "").strip()
    return summary[:hard_max_chars] or None


async def summarize_conversation(
    session: AsyncSession,
    ctx: TenantContext,
    conversation: Conversation,
    *,
    router=None,
    model: str | None = None,
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

    from app.core.config import get_settings

    settings = get_settings()
    summary: str | None = None
    if router is not None and messages:
        try:
            summary = await _model_summary(
                messages,
                router,
                model or settings.llm_model,
                ctx,
                session,
                prompt_max_chars=settings.summary_prompt_max_chars,
                hard_max_chars=settings.summary_max_chars,
            )
        except Exception:  # noqa: BLE001 - 模型摘要失败回退规则摘要
            summary = None
    if summary is None:
        summary = compress_messages(messages, max_chars=settings.summary_max_chars)
    if not summary:
        return None
    conversation.context_summary = summary
    await session.commit()
    return summary
