from contextlib import asynccontextmanager

import pytest

from app.core.tenant import TenantContext
from app.domain.session import chat_service


class _FakeSession:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def commit(self) -> None:
        self.events.append("commit")

    async def refresh(self, instance) -> None:
        self.events.append("refresh")


async def test_stream_message_ends_read_transaction_before_lock(monkeypatch) -> None:
    session = _FakeSession()
    conversation = type("Conv", (), {"id": 42})()
    ctx = TenantContext(tenant_id="t1", user_id="u1")

    @asynccontextmanager
    async def fake_lock(key: str, **kwargs):
        session.events.append(f"lock:{key}")
        yield

    async def fake_stream(session, ctx, **kwargs):
        yield "chunk"

    from app.runtime import resilience

    monkeypatch.setattr(resilience, "distributed_lock", fake_lock)
    monkeypatch.setattr(chat_service, "_stream_message_locked", fake_stream)

    chunks = [
        chunk
        async for chunk in chat_service.stream_message(
            session, ctx, conversation=conversation
        )
    ]

    assert chunks == ["chunk"]
    assert session.events == [
        "commit",
        "lock:lock:conversation:t1:42",
        "refresh",
    ]
