import pytest

from app.domain.tool.resilience import CircuitBreaker, CircuitOpenError, RateLimitedError, RateLimiter


def test_rate_limiter_allows_under_limit_and_blocks_over_limit() -> None:
    limiter = RateLimiter()

    limiter.check("k", limit=2, window_seconds=60)
    limiter.check("k", limit=2, window_seconds=60)

    with pytest.raises(RateLimitedError):
        limiter.check("k", limit=2, window_seconds=60)


def test_rate_limiter_is_isolated_per_key() -> None:
    limiter = RateLimiter()
    limiter.check("a", limit=1, window_seconds=60)
    limiter.check("b", limit=1, window_seconds=60)


def test_rate_limiter_zero_limit_means_unlimited() -> None:
    limiter = RateLimiter()
    for _ in range(10):
        limiter.check("k", limit=0, window_seconds=60)


def test_circuit_opens_after_failure_threshold() -> None:
    breaker = CircuitBreaker(failure_threshold=0.5, min_samples=4, open_seconds=60)
    for _ in range(3):
        breaker.record("tool", success=False)
    breaker.record("tool", success=True)

    assert breaker.state("tool") == "OPEN"
    with pytest.raises(CircuitOpenError):
        breaker.check("tool")


def test_circuit_does_not_open_below_min_samples() -> None:
    breaker = CircuitBreaker(failure_threshold=0.5, min_samples=10)
    for _ in range(5):
        breaker.record("tool", success=False)

    assert breaker.state("tool") == "CLOSED"
    breaker.check("tool")


def test_circuit_half_open_transitions_to_closed_on_probe() -> None:
    breaker = CircuitBreaker(failure_threshold=0.5, min_samples=2, open_seconds=60)
    breaker.record("tool", success=False)
    breaker.record("tool", success=False)
    assert breaker.state("tool") == "OPEN"

    breaker._opened_at["tool"] -= 61
    assert breaker.state("tool") == "HALF_OPEN"

    breaker.check("tool")
    assert breaker.state("tool") == "CLOSED"
