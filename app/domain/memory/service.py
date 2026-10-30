import re
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.tenant import TenantContext
from app.domain.memory.models import MemoryEmbedding, MemoryEpisode, MemoryItem

ID_CARD_PATTERN = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
PHONE_PATTERN = re.compile(r"(?<!\d)1\d{10}(?!\d)")
SECRET_KEYWORDS = re.compile(r"密码|口令|password|验证码|银行卡|信用卡")

MEMORY_TYPES = {"WORKING", "EPISODIC", "SEMANTIC", "PROCEDURAL"}
DEFAULT_TTL_DAYS = {"SEMANTIC": 365, "EPISODIC": 180}


def contains_sensitive(text: str) -> bool:
    return bool(
        ID_CARD_PATTERN.search(text)
        or PHONE_PATTERN.search(text)
        or SECRET_KEYWORDS.search(text)
    )


async def add_memory(
    session: AsyncSession,
    ctx: TenantContext,
    *,
    memory_type: str,
    subject: str,
    predicate: str,
    object_value: str,
    source_type: str = "conversation",
    source_message_id: int | None = None,
    confidence: float = 0.6,
    importance: float = 0.5,
    ttl_days: int | None = None,
) -> MemoryItem | None:
    """写入一条记忆。含敏感信息的候选直接丢弃，不阻塞对话。"""
    if memory_type not in MEMORY_TYPES:
        raise ValueError(f"未知记忆类型: {memory_type}")
    if contains_sensitive(object_value) or contains_sensitive(subject):
        return None

    effective_ttl = ttl_days if ttl_days is not None else DEFAULT_TTL_DAYS.get(memory_type)
    expires_at = datetime.utcnow() + timedelta(days=effective_ttl) if effective_ttl else None
    item = MemoryItem(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        memory_type=memory_type,
        subject=subject,
        predicate=predicate,
        object_value=object_value,
        source_type=source_type,
        source_message_id=source_message_id,
        confidence=confidence,
        importance=importance,
        valid_from=datetime.utcnow(),
        expires_at=expires_at,
        status="ACTIVE",
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


def _score(item: MemoryItem, tokens: set[str], now: datetime) -> float:
    text = f"{item.subject}{item.predicate}{item.object_value}"
    overlap = sum(1 for token in tokens if token and token in text)
    recency = 0.0
    if item.valid_from:
        age_days = max((now - item.valid_from).days, 0)
        recency = 1.0 / (1.0 + age_days / 30)
    return overlap + item.importance * 0.5 + recency * 0.5


async def search_memories(
    session: AsyncSession,
    ctx: TenantContext,
    *,
    query: str,
    memory_types: list[str] | None = None,
    limit: int = 5,
) -> list[MemoryItem]:
    now = datetime.utcnow()
    result = await session.execute(
        select(MemoryItem).where(
            MemoryItem.tenant_id == ctx.tenant_id,
            MemoryItem.user_id == ctx.user_id,
            MemoryItem.status == "ACTIVE",
        )
    )
    candidates = [
        item
        for item in result.scalars().all()
        if (not memory_types or item.memory_type in memory_types)
        and (item.expires_at is None or item.expires_at > now)
    ]
    tokens = {token for token in query if not token.isspace()}
    ranked = sorted(candidates, key=lambda item: _score(item, tokens, now), reverse=True)
    return ranked[:limit]


async def add_episode(
    session: AsyncSession,
    ctx: TenantContext,
    *,
    conversation_id: int | None,
    summary: str,
    event: dict | None = None,
) -> MemoryEpisode | None:
    """情节记忆同样不得落库敏感信息，命中时直接跳过。"""
    if contains_sensitive(summary):
        return None
    episode = MemoryEpisode(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        conversation_id=conversation_id,
        summary=summary[:1000],
        event_json=event or {},
        occurred_at=datetime.utcnow(),
    )
    session.add(episode)
    await session.commit()
    await session.refresh(episode)
    return episode


async def add_procedure(
    session: AsyncSession,
    ctx: TenantContext,
    *,
    agent_code: str,
    tool_codes: list[str],
    importance: float = 0.7,
) -> MemoryItem | None:
    if not tool_codes:
        return None
    return await add_memory(
        session,
        ctx,
        memory_type="PROCEDURAL",
        subject=agent_code or "agent",
        predicate="tool_chain",
        object_value=",".join(tool_codes),
        confidence=0.6,
        importance=importance,
    )


async def delete_memory(session: AsyncSession, ctx: TenantContext, memory_id: int) -> None:
    result = await session.execute(
        select(MemoryItem).where(
            MemoryItem.id == memory_id, MemoryItem.tenant_id == ctx.tenant_id
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise NotFoundError("记忆不存在或无权访问")
    item.status = "DELETED"

    embeddings = await session.execute(
        select(MemoryEmbedding).where(
            MemoryEmbedding.memory_item_id == memory_id,
            MemoryEmbedding.tenant_id == ctx.tenant_id,
        )
    )
    for embedding in embeddings.scalars().all():
        embedding.status = "DELETED"
    await session.commit()


async def list_memories(
    session: AsyncSession, ctx: TenantContext, *, limit: int = 50
) -> list[MemoryItem]:
    result = await session.execute(
        select(MemoryItem)
        .where(
            MemoryItem.tenant_id == ctx.tenant_id,
            MemoryItem.user_id == ctx.user_id,
            MemoryItem.status == "ACTIVE",
        )
        .order_by(MemoryItem.id.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


def serialize_memory(item: MemoryItem) -> dict:
    return {
        "id": item.id,
        "type": item.memory_type,
        "subject": item.subject,
        "predicate": item.predicate,
        "value": item.object_value,
        "confidence": item.confidence,
        "importance": item.importance,
        "status": item.status,
        "validFrom": item.valid_from.isoformat() if item.valid_from else None,
    }
