import json

from sqlalchemy import select

from app.api.deps import get_model_router
from app.domain.memory.models import MemoryEpisode, MemoryItem
from app.domain.tool.executor import function_tool_executor
from app.integrations.llm.client import LLMResponse
from app.integrations.llm.router import ModelRouter
from app.main import app

HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "u1", "X-Roles": "admin"}


class Client:
    def __init__(self, replies: list[str]) -> None:
        self.replies = replies

    async def complete(self, request):
        return LLMResponse(content=self.replies.pop(0), model=request.model)

    async def stream(self, request):
        yield ""


def _override(replies: list[str]) -> None:
    app.dependency_overrides[get_model_router] = lambda: ModelRouter(Client(replies))


async def _agent(async_client, tools: list[str]) -> int:
    agent_id = (
        await async_client.post(
            "/api/v1/admin/agents",
            json={"code": "memory_agent", "name": "记忆", "domain_code": "district_service"},
            headers=HEADERS,
        )
    ).json()["data"]["id"]
    version_id = (
        await async_client.post(
            f"/api/v1/admin/agents/{agent_id}/versions",
            json={"role": "顾问", "model_policy": {"primary": "primary"}, "tools": tools},
            headers=HEADERS,
        )
    ).json()["data"]["id"]
    await async_client.post(
        f"/api/v1/admin/agents/{agent_id}/publish",
        json={"version_id": version_id},
        headers=HEADERS,
    )
    return agent_id


async def test_completed_turn_writes_episode(async_client, db_session) -> None:
    await _agent(async_client, [])
    _override(['{"type":"final","answer":"这是回答"}'])
    session_id = (
        await async_client.post("/api/v1/chat/sessions", json={"channel": "web"}, headers=HEADERS)
    ).json()["data"]["sessionId"]

    await async_client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"message": "这是问题"},
        headers=HEADERS,
    )

    episodes = (await db_session.execute(select(MemoryEpisode))).scalars().all()
    assert len(episodes) == 1
    assert "这是问题" in episodes[0].summary
    assert "这是回答" in episodes[0].summary


async def test_tool_chain_writes_procedure_memory(async_client, db_session) -> None:
    async def handler(args, context):
        return {"echo": args.get("text")}

    function_tool_executor.register("memory.echo", handler)
    await async_client.post(
        "/api/v1/admin/tools",
        json={
            "tool_code": "memory.echo",
            "name": "回声",
            "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}},
        },
        headers=HEADERS,
    )
    await _agent(async_client, ["memory.echo"])
    _override(
        [
            '{"type":"tool_call","tool":"memory.echo","arguments":{"text":"hi"}}',
            '{"type":"final","answer":"完成"}',
        ]
    )
    session_id = (
        await async_client.post("/api/v1/chat/sessions", json={"channel": "web"}, headers=HEADERS)
    ).json()["data"]["sessionId"]

    await async_client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"message": "帮我查询"},
        headers=HEADERS,
    )

    procedures = (
        await db_session.execute(
            select(MemoryItem).where(MemoryItem.memory_type == "PROCEDURAL")
        )
    ).scalars().all()
    assert len(procedures) == 1
    assert procedures[0].object_value == "memory.echo"
