from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import TenantContext
from app.domain.session.events import RunEvent


async def list_events(
    session: AsyncSession,
    ctx: TenantContext,
    run_id: str,
    *,
    after_seq: int = 0,
    limit: int = 500,
) -> list[RunEvent]:
    result = await session.execute(
        select(RunEvent)
        .where(
            RunEvent.tenant_id == ctx.tenant_id,
            RunEvent.run_id == run_id,
            RunEvent.seq > after_seq,
        )
        .order_by(RunEvent.seq.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


def parse_last_event_id(value: str | None) -> int:
    if not value:
        return 0
    if ":" in value:
        _, _, seq = value.rpartition(":")
        try:
            return int(seq)
        except ValueError:
            return 0
    try:
        return int(value)
    except ValueError:
        return 0


async def load_events(
    session: AsyncSession,
    ctx: TenantContext,
    run_id: str,
    *,
    after_seq: int = 0,
    limit: int = 500,
) -> list[dict]:
    """优先读取 Redis Stream（实时），回退到数据库持久化事件。"""
    from app.infrastructure.redis.event_stream import read_events, serialize_stream_event

    stream_events = await read_events(ctx.tenant_id, run_id, after_seq=after_seq, limit=limit)
    if stream_events:
        return [serialize_stream_event(event) for event in stream_events]
    rows = await list_events(session, ctx, run_id, after_seq=after_seq, limit=limit)
    return [serialize_event(row) for row in rows]


def format_sse(event: dict) -> str:
    import json

    return (
        f"id: {event['id']}\n"
        f"event: {event['event']}\n"
        f"data: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
    )


def serialize_event(event: RunEvent) -> dict:
    return {
        "id": f"{event.run_id}:{event.seq}",
        "seq": event.seq,
        "event": event.event,
        "data": event.data_json,
        "createdAt": event.created_at.isoformat() if event.created_at else None,
    }
