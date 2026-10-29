import asyncio

import pytest

from app.core.exceptions import AppError
from app.infrastructure.redis.backend import InMemoryBackend
from app.infrastructure.redis.event_stream import publish_event, read_events
from app.runtime.resilience import Resilience, distributed_lock


async def test_distributed_lock_serializes_same_key() -> None:
    backend = InMemoryBackend()
    active = 0
    peak = 0

    async def worker() -> None:
        nonlocal active, peak
        async with distributed_lock("k", backend=backend, ttl_ms=5000, wait_timeout_ms=5000):
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.02)
            active -= 1

    await asyncio.gather(*(worker() for _ in range(4)))

    assert peak == 1


async def test_distributed_lock_times_out() -> None:
    backend = InMemoryBackend()
    await backend.set_nx("k", "other", 5000)

    with pytest.raises(AppError):
        async with distributed_lock("k", backend=backend, wait_timeout_ms=100):
            pass


async def test_redis_rate_limiter_counts_per_window() -> None:
    resilience = Resilience(backend=InMemoryBackend())

    await resilience.check_rate("tool", limit=2, window_seconds=60)
    await resilience.check_rate("tool", limit=2, window_seconds=60)

    with pytest.raises(Exception) as exc:
        await resilience.check_rate("tool", limit=2, window_seconds=60)
    assert getattr(exc.value, "code", "") == "AC.TOOL.RATE_LIMITED"


async def test_event_stream_round_trip_and_resume() -> None:
    backend = InMemoryBackend()

    await publish_event("t1", "run_1", 1, "run.start", {"a": 1}, backend=backend)
    await publish_event("t1", "run_1", 2, "message.delta", {"content": "你"}, backend=backend)
    await publish_event("t1", "run_1", 3, "message.end", {}, backend=backend)

    all_events = await read_events("t1", "run_1", backend=backend)
    resumed = await read_events("t1", "run_1", after_seq=2, backend=backend)

    assert [event["seq"] for event in all_events] == [1, 2, 3]
    assert [event["seq"] for event in resumed] == [3]
    assert resumed[0]["id"] == "run_1:3"
