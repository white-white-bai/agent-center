from sqlalchemy import select

from app.core.tenant import TenantContext
from app.domain.memory import service
from app.domain.memory.models import MemoryItem


async def _add(db_session, ctx: TenantContext | None = None, **overrides):
    ctx = ctx or TenantContext(tenant_id="t1", user_id="u1")
    data = dict(
        memory_type="SEMANTIC",
        subject="所在区域",
        predicate="lives_in",
        object_value="常州天宁区",
        confidence=0.9,
        importance=0.8,
    )
    data.update(overrides)
    return await service.add_memory(db_session, ctx, **data)


async def test_add_and_search_memory(db_session) -> None:
    ctx = TenantContext(tenant_id="t1", user_id="u1")
    await _add(db_session)

    found = await service.search_memories(db_session, ctx, query="天宁区办事")

    assert len(found) == 1
    assert found[0].object_value == "常州天宁区"


async def test_sensitive_memory_is_rejected(db_session) -> None:
    ctx = TenantContext(tenant_id="t1", user_id="u1")

    item = await _add(db_session, object_value="身份证 320402199001011234")

    assert item is None
    assert (await service.list_memories(db_session, ctx)) == []


async def test_memory_is_tenant_and_user_isolated(db_session) -> None:
    ctx = TenantContext(tenant_id="t1", user_id="u1")
    await _add(db_session)

    other_user = TenantContext(tenant_id="t1", user_id="u2")
    other_tenant = TenantContext(tenant_id="t2", user_id="u1")

    assert await service.list_memories(db_session, other_user) == []
    assert await service.list_memories(db_session, other_tenant) == []


async def test_deleted_memory_is_not_searchable(db_session) -> None:
    ctx = TenantContext(tenant_id="t1", user_id="u1")
    item = await _add(db_session)

    await service.delete_memory(db_session, ctx, item.id)

    assert await service.search_memories(db_session, ctx, query="天宁区") == []
    stored = (await db_session.execute(select(MemoryItem))).scalars().all()
    assert stored[0].status == "DELETED"


async def test_expired_memory_is_not_searchable(db_session) -> None:
    from datetime import datetime, timedelta

    ctx = TenantContext(tenant_id="t1", user_id="u1")
    item = await _add(db_session)
    item.expires_at = datetime.utcnow() - timedelta(days=1)
    await db_session.commit()

    assert await service.search_memories(db_session, ctx, query="天宁区") == []
