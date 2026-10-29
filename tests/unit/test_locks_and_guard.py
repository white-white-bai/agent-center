import asyncio

import pytest

from app.core.exceptions import ValidationError
from app.core.tenant import TenantContext
from app.runtime.locks import KeyedLock


async def test_keyed_lock_serializes_same_key() -> None:
    locks = KeyedLock()
    active = 0
    peak = 0

    async def worker() -> None:
        nonlocal active, peak
        async with locks.acquire("k"):
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.02)
            active -= 1

    await asyncio.gather(*(worker() for _ in range(4)))

    assert peak == 1


async def test_keyed_lock_keeps_different_keys_parallel() -> None:
    locks = KeyedLock()
    order: list[str] = []

    async def worker(name: str) -> None:
        async with locks.acquire(name):
            order.append(name)
            await asyncio.sleep(0.05)

    await asyncio.gather(worker("a"), worker("b"))

    assert sorted(order) == ["a", "b"]


async def test_tool_arguments_with_sensitive_word_are_rejected(db_session, monkeypatch) -> None:
    from app.core.config import get_settings
    from app.domain.tool import service
    from app.domain.tool.executor import FunctionToolExecutor, ToolContext

    monkeypatch.setattr(get_settings(), "sensitive_words", "违禁参数")
    ctx = TenantContext(tenant_id="t1", user_id="u1")
    await service.create_tool(
        db_session,
        ctx,
        tool_code="echo_checked",
        name="回声",
        description=None,
        source_type="FUNCTION",
        input_schema={"type": "object"},
    )
    executor = FunctionToolExecutor()

    async def handler(args, context):
        return {"ok": True}

    executor.register("echo_checked", handler)

    with pytest.raises(ValidationError) as exc:
        await service.invoke_tool(
            db_session,
            ctx,
            executor,
            tool_code="echo_checked",
            arguments={"text": "违禁参数内容"},
            tool_context=ToolContext(tenant_id="t1", user_id="u1"),
        )

    assert "安全检查" in str(exc.value)
