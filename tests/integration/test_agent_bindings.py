from sqlalchemy import select

from app.api.deps import get_model_router
from app.domain.prompt.models import PromptBinding
from app.domain.tool.models import ToolBinding
from app.integrations.llm.client import LLMResponse
from app.integrations.llm.router import ModelRouter
from app.main import app

HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "admin1", "X-Roles": "admin"}


class Client:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        return LLMResponse(content=self.reply, model=request.model)

    async def stream(self, request):
        yield ""


async def _agent_with_version(async_client, tools: list[str], prompt_version_id: int | None = None) -> int:
    agent_id = (
        await async_client.post(
            "/api/v1/admin/agents",
            json={"code": f"bind_{tools and tools[0] or 'none'}", "name": "绑定", "domain_code": "district_service"},
            headers=HEADERS,
        )
    ).json()["data"]["id"]
    version_id = (
        await async_client.post(
            f"/api/v1/admin/agents/{agent_id}/versions",
            json={
                "role": "顾问",
                "model_policy": {"primary": "primary"},
                "tools": tools,
                "prompt_version_id": prompt_version_id,
            },
            headers=HEADERS,
        )
    ).json()["data"]["id"]
    await async_client.post(
        f"/api/v1/admin/agents/{agent_id}/publish",
        json={"version_id": version_id},
        headers=HEADERS,
    )
    return agent_id


async def test_version_creation_writes_bindings(async_client, db_session) -> None:
    template_id = (
        await async_client.post(
            "/api/v1/admin/prompts", json={"code": "bind_p", "name": "绑定提示词"}, headers=HEADERS
        )
    ).json()["data"]["id"]
    prompt_version_id = (
        await async_client.post(
            f"/api/v1/admin/prompts/{template_id}/versions",
            json={"content": "hi {{question}}"},
            headers=HEADERS,
        )
    ).json()["data"]["id"]

    agent_id = await _agent_with_version(async_client, ["tool.a", "tool.b"], prompt_version_id)

    tools = (
        await db_session.execute(select(ToolBinding).where(ToolBinding.agent_id == agent_id))
    ).scalars().all()
    assert {row.tool_code for row in tools} == {"tool.a", "tool.b"}

    prompts = (
        await db_session.execute(select(PromptBinding).where(PromptBinding.agent_id == agent_id))
    ).scalars().all()
    assert prompts[0].prompt_version_id == prompt_version_id
    assert prompts[0].prompt_template_id == template_id


async def test_runtime_uses_updated_tool_bindings(async_client) -> None:
    agent_id = await _agent_with_version(async_client, ["tool.old"])
    scripted = Client('{"type":"final","answer":"ok"}')
    app.dependency_overrides[get_model_router] = lambda: ModelRouter(scripted)

    await async_client.put(
        f"/api/v1/admin/agents/{agent_id}/bindings",
        json={"tools": ["tool.new"]},
        headers=HEADERS,
    )
    session_id = (
        await async_client.post("/api/v1/chat/sessions", json={"channel": "web"}, headers=HEADERS)
    ).json()["data"]["sessionId"]

    await async_client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"message": "你好"},
        headers=HEADERS,
    )

    system_prompt = scripted.requests[0].messages[0].content
    assert "tool.new" in system_prompt
    assert "tool.old" not in system_prompt


async def test_get_bindings_returns_current_state(async_client) -> None:
    agent_id = await _agent_with_version(async_client, ["tool.x"])

    response = await async_client.get(
        f"/api/v1/admin/agents/{agent_id}/bindings", headers=HEADERS
    )

    assert response.json()["data"]["tools"] == ["tool.x"]


async def test_bindings_update_is_tenant_isolated(async_client) -> None:
    agent_id = await _agent_with_version(async_client, ["tool.x"])

    response = await async_client.put(
        f"/api/v1/admin/agents/{agent_id}/bindings",
        json={"tools": ["tool.y"]},
        headers={"X-Tenant-Id": "t2", "X-User-Id": "admin2", "X-Roles": "admin"},
    )

    assert response.status_code == 404
