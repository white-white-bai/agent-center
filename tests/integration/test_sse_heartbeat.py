import asyncio
import json

from app.api.deps import get_model_router
from app.core.config import get_settings
from app.integrations.llm.client import LLMResponse
from app.integrations.llm.router import ModelRouter
from app.main import app

HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "u1", "X-Roles": "admin"}


class SlowClient:
    async def complete(self, request):
        await asyncio.sleep(0.15)
        return LLMResponse(content='{"type":"final","answer":"慢回答"}', model=request.model)

    async def stream(self, request):
        yield ""


async def test_sse_emits_heartbeat_when_idle(async_client, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "sse_heartbeat_seconds", 0.01)
    app.dependency_overrides[get_model_router] = lambda: ModelRouter(SlowClient())

    agent_id = (
        await async_client.post(
            "/api/v1/admin/agents",
            json={"code": "heartbeat_agent", "name": "心跳", "domain_code": "district_service"},
            headers=HEADERS,
        )
    ).json()["data"]["id"]
    version_id = (
        await async_client.post(
            f"/api/v1/admin/agents/{agent_id}/versions",
            json={"role": "顾问", "model_policy": {"primary": "primary"}},
            headers=HEADERS,
        )
    ).json()["data"]["id"]
    await async_client.post(
        f"/api/v1/admin/agents/{agent_id}/publish",
        json={"version_id": version_id},
        headers=HEADERS,
    )
    session_id = (
        await async_client.post("/api/v1/chat/sessions", json={"channel": "web"}, headers=HEADERS)
    ).json()["data"]["sessionId"]

    response = await async_client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"message": "你好"},
        headers=HEADERS,
    )

    events = []
    for block in response.text.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("event: "):
                events.append(line[len("event: ") :])
    assert "heartbeat" in events
    assert events[-1] == "message.end"
