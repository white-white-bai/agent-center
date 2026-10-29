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


def serialize_event(event: RunEvent) -> dict:
    return {
        "id": f"{event.run_id}:{event.seq}",
        "seq": event.seq,
        "event": event.event,
        "data": event.data_json,
        "createdAt": event.created_at.isoformat() if event.created_at else None,
    }
