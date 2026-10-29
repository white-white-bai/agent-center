import asyncio
import time
from collections import defaultdict
from typing import Any, Protocol


class Backend(Protocol):
    async def set_nx(self, key: str, value: str, ttl_ms: int) -> bool: ...

    async def delete_if_value(self, key: str, value: str) -> bool: ...

    async def incr_window(self, key: str, window_ms: int) -> int: ...

    async def get_int(self, key: str) -> int: ...

    async def set_value(self, key: str, value: str, ttl_ms: int) -> None: ...

    async def get_value(self, key: str) -> str | None: ...

    async def xadd(self, stream: str, fields: dict[str, str]) -> str: ...

    async def xrange(self, stream: str, count: int = 1000) -> list[tuple[str, dict[str, str]]]: ...


class InMemoryBackend:
    """测试与单实例部署使用的内存后端。"""

    is_memory = True

    def __init__(self) -> None:
        self._values: dict[str, tuple[str, float | None]] = {}
        self._counters: dict[str, tuple[int, float]] = {}
        self._streams: dict[str, list[tuple[str, dict[str, str]]]] = defaultdict(list)
        self._seq = 0
        self._lock = asyncio.Lock()

    def _expired(self, expires_at: float | None) -> bool:
        return expires_at is not None and expires_at <= time.monotonic()

    async def set_nx(self, key: str, value: str, ttl_ms: int) -> bool:
        async with self._lock:
            existing = self._values.get(key)
            if existing and not self._expired(existing[1]):
                return False
            expires = time.monotonic() + ttl_ms / 1000 if ttl_ms else None
            self._values[key] = (value, expires)
            return True

    async def delete_if_value(self, key: str, value: str) -> bool:
        async with self._lock:
            existing = self._values.get(key)
            if existing and existing[0] == value:
                del self._values[key]
                return True
            return False

    async def incr_window(self, key: str, window_ms: int) -> int:
        async with self._lock:
            now = time.monotonic()
            count, expires = self._counters.get(key, (0, now + window_ms / 1000))
            if expires <= now:
                count, expires = 0, now + window_ms / 1000
            count += 1
            self._counters[key] = (count, expires)
            return count

    async def get_int(self, key: str) -> int:
        existing = self._values.get(key)
        if existing and not self._expired(existing[1]):
            return int(existing[0])
        return 0

    async def set_value(self, key: str, value: str, ttl_ms: int) -> None:
        async with self._lock:
            expires = time.monotonic() + ttl_ms / 1000 if ttl_ms else None
            self._values[key] = (value, expires)

    async def get_value(self, key: str) -> str | None:
        existing = self._values.get(key)
        if existing and not self._expired(existing[1]):
            return existing[0]
        return None

    async def xadd(self, stream: str, fields: dict[str, str]) -> str:
        async with self._lock:
            self._seq += 1
            event_id = f"{int(time.time() * 1000)}-{self._seq}"
            self._streams[stream].append((event_id, fields))
            return event_id

    async def xrange(self, stream: str, count: int = 1000) -> list[tuple[str, dict[str, str]]]:
        return list(self._streams.get(stream, []))[-count:]


class RedisBackend:
    """Redis 后端，按需导入 redis 客户端。"""

    def __init__(self, url: str) -> None:
        import redis.asyncio as redis

        self._redis = redis.from_url(url, decode_responses=True)

    async def set_nx(self, key: str, value: str, ttl_ms: int) -> bool:
        return bool(await self._redis.set(key, value, nx=True, px=ttl_ms or None))

    async def delete_if_value(self, key: str, value: str) -> bool:
        script = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
        return bool(await self._redis.eval(script, 1, key, value))

    async def incr_window(self, key: str, window_ms: int) -> int:
        count = await self._redis.incr(key)
        if count == 1:
            await self._redis.pexpire(key, window_ms)
        return int(count)

    async def get_int(self, key: str) -> int:
        value = await self._redis.get(key)
        return int(value) if value else 0

    async def set_value(self, key: str, value: str, ttl_ms: int) -> None:
        await self._redis.set(key, value, px=ttl_ms or None)

    async def get_value(self, key: str) -> str | None:
        return await self._redis.get(key)

    async def xadd(self, stream: str, fields: dict[str, str]) -> str:
        return str(await self._redis.xadd(stream, fields))

    async def xrange(self, stream: str, count: int = 1000) -> list[tuple[str, dict[str, str]]]:
        entries = await self._redis.xrevrange(stream, count=count)
        return [(entry_id, fields) for entry_id, fields in reversed(entries)]


_backend: Backend | None = None


def get_backend() -> Backend:
    global _backend
    if _backend is not None:
        return _backend
    from app.core.config import get_settings

    settings = get_settings()
    if settings.redis_url:
        try:
            _backend = RedisBackend(settings.redis_url)
            return _backend
        except Exception:  # noqa: BLE001 - Redis 不可用时降级为内存实现
            pass
    _backend = InMemoryBackend()
    return _backend


def reset_backend(backend: Backend | None = None) -> None:
    global _backend
    _backend = backend
