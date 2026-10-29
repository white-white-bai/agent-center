import asyncio
from contextlib import asynccontextmanager


class KeyedLock:
    """进程内按键互斥锁。

    多实例部署需替换为 Redis 分布式锁（带租约与 fencing token），见 docs/open-questions.md。
    """

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    @asynccontextmanager
    async def acquire(self, key: str, *, timeout_ms: int = 30000):
        lock = self._locks.setdefault(key, asyncio.Lock())
        acquired = False
        try:
            await asyncio.wait_for(lock.acquire(), timeout=timeout_ms / 1000)
            acquired = True
            yield
        finally:
            if acquired:
                lock.release()

    def is_locked(self, key: str) -> bool:
        lock = self._locks.get(key)
        return bool(lock and lock.locked())


conversation_locks = KeyedLock()


def conversation_lock_key(tenant_id: str, conversation_id: int) -> str:
    return f"conversation:{tenant_id}:{conversation_id}"
