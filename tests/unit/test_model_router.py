import asyncio

import pytest

from app.core.exceptions import ModelUnavailableError
from app.core.tenant import TenantContext
from app.integrations.llm.client import ChatMessage, LLMRequest, StubLLMClient
from app.integrations.llm.router import ModelRouter


def _request(model: str = "primary") -> LLMRequest:
    return LLMRequest(messages=[ChatMessage(role="user", content="你好")], model=model)


async def test_router_uses_primary_model(db_session) -> None:
    client = StubLLMClient(reply="答案")
    ctx = TenantContext(tenant_id="t1", user_id="u1")

    response = await ModelRouter(client).complete(
        db_session, ctx, _request(), primary_model="primary"
    )

    assert response.content == "答案"
    assert client.calls[0].model == "primary"


async def test_router_falls_back_to_secondary_model(db_session) -> None:
    client = StubLLMClient(reply="降级答案", fail_models={"primary"})
    ctx = TenantContext(tenant_id="t1", user_id="u1")

    response = await ModelRouter(client).complete(
        db_session,
        ctx,
        _request(),
        primary_model="primary",
        fallback_model="fallback",
        max_retries=0,
    )

    assert response.model == "fallback"
    assert response.content == "降级答案"
    assert [call.model for call in client.calls] == ["primary", "fallback"]


async def test_router_raises_when_all_models_fail(db_session) -> None:
    client = StubLLMClient(fail_models={"primary", "fallback"})
    ctx = TenantContext(tenant_id="t1", user_id="u1")

    with pytest.raises(ModelUnavailableError):
        await ModelRouter(client).complete(
            db_session,
            ctx,
            _request(),
            primary_model="primary",
            fallback_model="fallback",
            max_retries=0,
        )


async def test_router_records_usage(db_session) -> None:
    from sqlalchemy import select

    from app.domain.model.models import ModelUsageLog

    ctx = TenantContext(tenant_id="t1", user_id="u1")
    await ModelRouter(StubLLMClient(reply="abc")).complete(
        db_session, ctx, _request(), primary_model="primary", run_id="run_1"
    )

    result = await db_session.execute(select(ModelUsageLog))
    logs = result.scalars().all()
    assert len(logs) == 1
    assert logs[0].status == "SUCCESS"
    assert logs[0].token_input > 0
    assert logs[0].token_output == 3


async def test_router_timeout_is_retried(db_session, monkeypatch) -> None:
    class SlowClient(StubLLMClient):
        async def complete(self, request):
            await asyncio.sleep(1)
            return await super().complete(request)

    request = LLMRequest(messages=[], model="primary", timeout_ms=10)
    with pytest.raises(ModelUnavailableError):
        await ModelRouter(SlowClient()).complete(
            db_session,
            TenantContext(tenant_id="t1", user_id="u1"),
            request,
            primary_model="primary",
            max_retries=0,
        )
