from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.api.deps import CurrentTenant, DbSession
from app.core.responses import ok
from app.domain.memory import service

router = APIRouter(prefix="/memory", tags=["memory"])


class CreateMemoryRequest(BaseModel):
    memoryType: str = Field(default="SEMANTIC")
    subject: str = Field(min_length=1, max_length=200)
    predicate: str = Field(min_length=1, max_length=200)
    value: str = Field(min_length=1)
    confidence: float = Field(default=0.6, ge=0, le=1)
    importance: float = Field(default=0.5, ge=0, le=1)
    ttlDays: int | None = Field(default=None, ge=1)


@router.get("")
async def list_memories(session: DbSession, ctx: CurrentTenant, limit: int = Query(default=50, ge=1, le=200)) -> dict:
    items = await service.list_memories(session, ctx, limit=limit)
    return ok([service.serialize_memory(item) for item in items])


@router.get("/search")
async def search_memories(
    session: DbSession,
    ctx: CurrentTenant,
    q: str = Query(min_length=1),
    limit: int = Query(default=5, ge=1, le=50),
) -> dict:
    items = await service.search_memories(session, ctx, query=q, limit=limit)
    return ok([service.serialize_memory(item) for item in items])


@router.post("")
async def create_memory(payload: CreateMemoryRequest, session: DbSession, ctx: CurrentTenant) -> dict:
    item = await service.add_memory(
        session,
        ctx,
        memory_type=payload.memoryType,
        subject=payload.subject,
        predicate=payload.predicate,
        object_value=payload.value,
        confidence=payload.confidence,
        importance=payload.importance,
        ttl_days=payload.ttlDays,
    )
    if item is None:
        return ok({"stored": False, "reason": "包含敏感信息，已忽略"})
    return ok({"stored": True, "memory": service.serialize_memory(item)})


@router.delete("/{memory_id}")
async def delete_memory(memory_id: int, session: DbSession, ctx: CurrentTenant) -> dict:
    await service.delete_memory(session, ctx, memory_id)
    return ok({"deleted": True})
