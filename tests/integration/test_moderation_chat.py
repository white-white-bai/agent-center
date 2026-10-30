import json

import httpx

from app.api.deps import get_model_router
from app.domain.safety import service as safety_service
from app.domain.safety.service import REFUSAL_MESSAGE, SafetyService
from app.integrations.llm.client import LLMResponse
from app.integrations.llm.router import ModelRouter
from app.main import app

HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "u1", "X-Roles": "admin"}


class ScriptedClient:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)

    async def complete(self, request):
        return LLMResponse(content=self.replies.pop(0), model=request.model)

    async def stream(self, request):
        response = await self.complete(request)
        yield response.content


def _events(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        name = None
        data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if name:
            events.append((name, data))
    return events


def _answer(body: str) -> str:
    return "".join(
        data.get("content", "")
        for name, data in _events(body)
        if name == "message.delta"
    )


def _moderation() -> SafetyService:
    def handle(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        blocked = "BLOCK" in str(payload.get("text", ""))
        return httpx.Response(
            200,
            json={"blocked": blocked, "reason": "模拟拦截", "category": "MOCK"},
        )

    return SafetyService(
        moderation_url="http://moderation/moderate",
        transport=httpx.MockTransport(handle),
    )


async def _prepare_agent(client) -> None:
    agent = (
        await client.post(
            "/api/v1/admin/agents",
            json={"code": "moderation_agent", "name": "审核", "domain_code": "district_service"},
            headers=HEADERS,
        )
    ).json()["data"]
    version = (
        await client.post(
            f"/api/v1/admin/agents/{agent['id']}/versions",
            json={"role": "顾问", "model_policy": {"primary": "primary", "max_steps": 2}},
            headers=HEADERS,
        )
    ).json()["data"]
    await client.post(
        f"/api/v1/admin/agents/{agent['id']}/publish",
        json={"version_id": version["id"]},
        headers=HEADERS,
    )


async def _send(client, message: str) -> str:
    session_id = (
        await client.post(
            "/api/v1/chat/sessions", json={"channel": "web"}, headers=HEADERS
        )
    ).json()["data"]["sessionId"]
    response = await client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"message": message, "agentCode": "moderation_agent"},
        headers={**HEADERS, "Accept": "text/event-stream"},
    )
    assert response.status_code == 200
    return response.text


async def test_chat_blocks_input_and_output(async_client, monkeypatch) -> None:
    await _prepare_agent(async_client)
    app.dependency_overrides[get_model_router] = lambda: ModelRouter(
        ScriptedClient(['{"type":"final","answer":"BLOCK_OUTPUT"}'])
    )
    monkeypatch.setattr(safety_service, "get_safety_service", _moderation)

    input_events = _events(await _send(async_client, "BLOCK_INPUT"))
    assert any(
        name == "error" and data.get("code") == "AC.SAFETY.BLOCKED"
        for name, data in input_events
    )

    output_body = await _send(async_client, "正常问题")
    assert _answer(output_body) == REFUSAL_MESSAGE
    assert not any(name == "error" for name, _ in _events(output_body))
