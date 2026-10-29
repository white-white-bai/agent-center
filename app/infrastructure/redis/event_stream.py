import json

from app.infrastructure.redis.backend import Backend, get_backend


def stream_key(tenant_id: str, run_id: str) -> str:
    return f"events:{tenant_id}:{run_id}"


async def publish_event(
    tenant_id: str,
    run_id: str,
    seq: int,
    event: str,
    data: dict,
    *,
    backend: Backend | None = None,
    max_len: int = 2000,
) -> str:
    store = backend or get_backend()
    fields = {
        "seq": str(seq),
        "event": event,
        "data": json.dumps(data, ensure_ascii=False),
    }
    return await store.xadd(stream_key(tenant_id, run_id), fields)


async def read_events(
    tenant_id: str,
    run_id: str,
    *,
    after_seq: int = 0,
    limit: int = 500,
    backend: Backend | None = None,
) -> list[dict]:
    store = backend or get_backend()
    entries = await store.xrange(stream_key(tenant_id, run_id), count=limit)
    events: list[dict] = []
    for event_id, fields in entries:
        seq = int(fields.get("seq") or 0)
        if seq <= after_seq:
            continue
        events.append(
            {
                "id": f"{run_id}:{seq}",
                "seq": seq,
                "event": fields.get("event"),
                "data": json.loads(fields.get("data") or "{}"),
                "streamId": event_id,
            }
        )
    return events


def serialize_stream_event(event: dict) -> dict:
    return {
        "id": event["id"],
        "seq": event["seq"],
        "event": event["event"],
        "data": event["data"],
    }
