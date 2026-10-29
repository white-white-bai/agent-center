import time
from collections import defaultdict, deque
from dataclasses import dataclass, field

from app.core.exceptions import AppError


class RateLimitedError(AppError):
    status_code = 429
    code = "AC.TOOL.RATE_LIMITED"
    message = "工具调用超出限流阈值"


class CircuitOpenError(AppError):
    status_code = 503
    code = "AC.TOOL.CIRCUIT_OPEN"
    message = "工具已熔断，请稍后重试"


@dataclass
class RateLimiter:
    """进程内滑动窗口限流。

    多实例部署时需替换为 Redis 实现，见 docs/open-questions.md。
    """

    _hits: dict[str, deque[float]] = field(default_factory=lambda: defaultdict(deque))

    def check(self, key: str, *, limit: int, window_seconds: int) -> None:
        if limit <= 0:
            return
        now = time.monotonic()
        bucket = self._hits[key]
        while bucket and now - bucket[0] > window_seconds:
            bucket.popleft()
        if len(bucket) >= limit:
            raise RateLimitedError()
        bucket.append(now)

    def reset(self) -> None:
        self._hits.clear()


@dataclass
class CircuitBreaker:
    """工具熔断：CLOSED → OPEN → HALF_OPEN → CLOSED。"""

    failure_threshold: float = 0.5
    min_samples: int = 10
    window_seconds: int = 30
    open_seconds: int = 60

    _events: dict[str, deque[tuple[float, bool]]] = field(default_factory=lambda: defaultdict(deque))
    _state: dict[str, str] = field(default_factory=dict)
    _opened_at: dict[str, float] = field(default_factory=dict)

    def state(self, key: str) -> str:
        current = self._state.get(key, "CLOSED")
        if current == "OPEN" and time.monotonic() - self._opened_at.get(key, 0) >= self.open_seconds:
            self._state[key] = "HALF_OPEN"
            return "HALF_OPEN"
        return current

    def check(self, key: str) -> None:
        if self.state(key) == "OPEN":
            raise CircuitOpenError()
        if self.state(key) == "HALF_OPEN":
            self._state[key] = "CLOSED"
            self._events[key].clear()

    def record(self, key: str, *, success: bool) -> None:
        now = time.monotonic()
        bucket = self._events[key]
        bucket.append((now, success))
        while bucket and now - bucket[0][0] > self.window_seconds:
            bucket.popleft()
        total = len(bucket)
        failures = sum(1 for _, ok in bucket if not ok)
        if total >= self.min_samples and failures / total > self.failure_threshold:
            self._state[key] = "OPEN"
            self._opened_at[key] = now

    def reset(self) -> None:
        self._events.clear()
        self._state.clear()
        self._opened_at.clear()


rate_limiter = RateLimiter()
circuit_breaker = CircuitBreaker()
