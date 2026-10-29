import asyncio

import pytest

from app.runtime.fanout import fan_out, reduce_outcomes


async def test_fan_out_collects_all_success_outputs() -> None:
    async def answer(value: str) -> dict:
        await asyncio.sleep(0.01)
        return {"value": value}

    result = await fan_out({"a": lambda: answer("1"), "b": lambda: answer("2")})

    assert result.partial is False
    assert result.outputs() == {"a": {"value": "1"}, "b": {"value": "2"}}


async def test_fan_out_tolerates_partial_failure() -> None:
    async def broken() -> dict:
        raise RuntimeError("boom")

    async def good() -> dict:
        return {"ok": True}

    result = await fan_out({"good": good, "broken": broken})
    summary = reduce_outcomes(result)

    assert result.partial is True
    assert summary["results"] == {"good": {"ok": True}}
    assert summary["failed"] == ["broken"]
    assert "部分信息获取失败" in summary["note"]


async def test_fan_out_marks_timeouts() -> None:
    async def slow() -> dict:
        await asyncio.sleep(1)
        return {}

    result = await fan_out({"slow": slow}, timeout_ms=10)

    assert result.outcomes[0].status == "TIMEOUT"
    assert result.outcomes[0].error_code == "AC.TASK.TIMEOUT"


async def test_fan_out_respects_concurrency_limit() -> None:
    active = 0
    peak = 0

    async def task() -> dict:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        return {}

    await fan_out({f"t{i}": task for i in range(6)}, max_concurrency=2)

    assert peak <= 2


async def test_fan_out_rejects_write_tasks() -> None:
    with pytest.raises(ValueError):
        await fan_out({}, read_only=False)
