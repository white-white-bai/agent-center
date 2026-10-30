import json

from sqlalchemy import select

from app.api.deps import get_model_router
from app.domain.session.models import Run, RunStep
from app.integrations.llm.client import LLMResponse
from app.integrations.llm.router import ModelRouter
from app.main import app
from app.runtime.critic import DEFAULT_FALLBACK_ANSWER

HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "u1", "X-Roles": "admin"}


class ScriptedClient:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        return LLMResponse(
            content=self.replies.pop(0),
            model=request.model,
            token_input=5,
            token_output=5,
        )

    async def stream(self, request):
        response = await self.complete(request)
        yield response.content


async def _prepare_agent(client, critic_policy: dict) -> None:
    agent_id = (
        await client.post(
            "/api/v1/admin/agents",
            json={"code": "critic_agent", "name": "评审", "domain_code": "district_service"},
            headers=HEADERS,
        )
    ).json()["data"]["id"]
    version_id = (
        await client.post(
            f"/api/v1/admin/agents/{agent_id}/versions",
            json={
                "role": "顾问",
                "model_policy": {"primary": "primary", "max_steps": 3},
                "critic_policy": critic_policy,
            },
            headers=HEADERS,
        )
    ).json()["data"]["id"]
    await client.post(
        f"/api/v1/admin/agents/{agent_id}/publish",
        json={"version_id": version_id},
        headers=HEADERS,
    )


def _override_router(client: ScriptedClient) -> None:
    app.dependency_overrides[get_model_router] = lambda: ModelRouter(client)


def _answer(body: str) -> str:
    parts = []
    for block in body.strip().split("\n\n"):
        name = None
        data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        if name == "message.delta" and data:
            parts.append(data.get("content", ""))
    return "".join(parts)


async def _send(client, message: str):
    session_id = (
        await client.post("/api/v1/chat/sessions", json={"channel": "web"}, headers=HEADERS)
    ).json()["data"]["sessionId"]
    return await client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"message": message},
        headers={**HEADERS, "Accept": "text/event-stream"},
    )


async def test_critic_revises_high_risk_answer(async_client, db_session) -> None:
    await _prepare_agent(
        async_client,
        {"enabled": True, "mode": "always", "timeout_ms": 5000},
    )
    _override_router(
        ScriptedClient(
            [
                '{"type":"final","answer":"补贴金额为 500 元。"}',
                '{"verdict":"revise","reason":"金额无知识依据","revised_answer":"补贴金额以官方公布为准。"}',
            ]
        )
    )

    response = await _send(async_client, "残疾人补贴金额是多少")

    assert response.status_code == 200
    assert _answer(response.text) == "补贴金额以官方公布为准。"
    steps = list((await db_session.execute(select(RunStep))).scalars().all())
    assert any(step.step_type == "CRITIC_REVIEW" for step in steps)
    run = (await db_session.execute(select(Run))).scalars().one()
    assert run.token_input == 10
    assert run.token_output == 10


async def test_critic_reject_returns_safe_fallback(async_client) -> None:
    await _prepare_agent(
        async_client,
        {"enabled": True, "mode": "always", "timeout_ms": 5000},
    )
    _override_router(
        ScriptedClient(
            [
                '{"type":"final","answer":"报销比例为 90%。"}',
                '{"verdict":"reject","reason":"比例无依据"}',
            ]
        )
    )

    response = await _send(async_client, "医保报销比例是多少")

    assert _answer(response.text) == DEFAULT_FALLBACK_ANSWER


async def test_critic_skips_low_risk_question(async_client, db_session) -> None:
    await _prepare_agent(
        async_client,
        {"enabled": True, "mode": "risk", "timeout_ms": 5000},
    )
    client = ScriptedClient(['{"type":"final","answer":"您好。"}'])
    _override_router(client)

    response = await _send(async_client, "你好")

    assert _answer(response.text) == "您好。"
    assert len(client.requests) == 1
    steps = list((await db_session.execute(select(RunStep))).scalars().all())
    assert all(step.step_type != "CRITIC_REVIEW" for step in steps)


async def test_critic_invalid_output_passes_by_default(async_client) -> None:
    await _prepare_agent(
        async_client,
        {"enabled": True, "mode": "always", "timeout_ms": 5000},
    )
    _override_router(
        ScriptedClient(
            [
                '{"type":"final","answer":"请以官方公布为准。"}',
                "这不是 JSON",
            ]
        )
    )

    response = await _send(async_client, "补贴政策是什么")

    assert _answer(response.text) == "请以官方公布为准。"
