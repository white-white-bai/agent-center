import asyncio
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from app.core.exceptions import AppError
from app.infrastructure.redis.backend import Backend, get_backend
from app.domain.tool.resilience import (
    CircuitBreaker,
    CircuitOpenError,
    RateLimitedError,
    RateLimiter,
)

LOCK_RETRY_INTERVAL = 0.05


def conversation_lock_key(tenant_id: str, conversation_id: int) -> str:
    return f"lock:conversation:{tenant_id}:{conversation_id}"


@asynccontextmanager
async def distributed_lock(
    key: str,
    *,
    backend: Backend | None = None,
    ttl_ms: int = 60000,
    wait_timeout_ms: int = 30000,
):
    store = backend or get_backend()
    token = uuid4().hex
    deadline = time.monotonic() + wait_timeout_ms / 1000
    acquired = False
    while time.monotonic() < deadline:
        if await store.set_nx(key, token, ttl_ms):
            acquired = True
            break
        await asyncio.sleep(LOCK_RETRY_INTERVAL)
    if not acquired:
        raise AppError("会话正在处理中，请稍后重试", code="AC.SESSION.LOCK_TIMEOUT")
    try:
        yield
    finally:
        await store.delete_if_value(key, token)


class Resilience:
    """限流与熔断：默认内存实现，Redis 可用时计数跨实例共享。"""

    def __init__(self, backend: Backend | None = None) -> None:
        self.backend = backend or get_backend()
        self._rate = RateLimiter()
        self._breaker = CircuitBreaker()

    async def check_rate(self, key: str, *, limit: int, window_seconds: int) -> None:
        if limit <= 0:
            return
        if getattr(self.backend, "is_memory", False):
            self._rate.check(key, limit=limit, window_seconds=window_seconds)
            return
        count = await self.backend.incr_window(f"rate:{key}", window_seconds * 1000)
        if count > limit:
            raise RateLimitedError()

    async def check_circuit(self, key: str) -> None:
        if getattr(self.backend, "is_memory", False):
            self._breaker.check(key)
            return
        state = await self.backend.get_value(f"circuit:state:{key}")
        if state == "OPEN":
            raise CircuitOpenError()

    async def record(self, key: str, *, success: bool) -> None:
        if getattr(self.backend, "is_memory", False):
            self._breaker.record(key, success=success)
            return
        total = await self.backend.incr_window(f"circuit:total:{key}", 60000)
        if success:
            failures = await self.backend.get_int(f"circuit:fail:{key}")
        else:
            failures = await self.backend.incr_window(f"circuit:fail:{key}", 60000)
        if total >= 10 and failures / total > 0.5:
            await self.backend.set_value(f"circuit:state:{key}", "OPEN", 60000)


_resilience: Resilience | None = None


def get_resilience() -> Resilience:
    global _resilience
    if _resilience is None:
        _resilience = Resilience()
    return _resilience


def reset_resilience() -> None:
    global _resilience
    _resilience = None
