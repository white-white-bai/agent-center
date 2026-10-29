import pytest

from app.core.exceptions import ConflictError
from app.domain.tool.idempotency import arguments_hash, build_idempotency_key, normalize_arguments


def test_normalize_arguments_is_order_insensitive() -> None:
    assert normalize_arguments({"b": 2, "a": 1}) == normalize_arguments({"a": 1, "b": 2})


def test_arguments_hash_differs_for_different_values() -> None:
    assert arguments_hash({"a": 1}) != arguments_hash({"a": 2})


def test_idempotency_key_is_stable() -> None:
    first = build_idempotency_key("run_1", "tool", {"a": 1})
    second = build_idempotency_key("run_1", "tool", {"a": 1})
    other_run = build_idempotency_key("run_2", "tool", {"a": 1})

    assert first == second
    assert first != other_run


async def test_idempotency_record_lifecycle(db_session) -> None:
    from app.core.tenant import TenantContext
    from app.domain.tool import idempotency

    ctx = TenantContext(tenant_id="t1", user_id="u1")

    first = await idempotency.begin(
        db_session, ctx, tool_code="submit", idempotency_key="k1", arguments={"a": 1}
    )
    assert first is None

    with pytest.raises(ConflictError):
        await idempotency.begin(
            db_session, ctx, tool_code="submit", idempotency_key="k1", arguments={"a": 1}
        )

    await idempotency.complete(db_session, await _load(db_session, ctx, "submit", "k1"), response={"ok": True})
    cached = await idempotency.begin(
        db_session, ctx, tool_code="submit", idempotency_key="k1", arguments={"a": 1}
    )
    assert cached is not None
    assert cached.response_json == {"ok": True}


async def test_idempotency_rejects_changed_arguments(db_session) -> None:
    from app.core.tenant import TenantContext
    from app.domain.tool import idempotency

    ctx = TenantContext(tenant_id="t1", user_id="u1")
    await idempotency.begin(db_session, ctx, tool_code="submit", idempotency_key="k2", arguments={"a": 1})
    await idempotency.complete(db_session, await _load(db_session, ctx, "submit", "k2"), response={"ok": True})

    with pytest.raises(ConflictError):
        await idempotency.begin(
            db_session, ctx, tool_code="submit", idempotency_key="k2", arguments={"a": 2}
        )


async def _load(session, ctx, tool_code: str, key: str):
    from sqlalchemy import select

    from app.domain.tool.models import ToolIdempotencyRecord

    result = await session.execute(
        select(ToolIdempotencyRecord).where(
            ToolIdempotencyRecord.tenant_id == ctx.tenant_id,
            ToolIdempotencyRecord.tool_code == tool_code,
            ToolIdempotencyRecord.idempotency_key == key,
        )
    )
    return result.scalar_one()
