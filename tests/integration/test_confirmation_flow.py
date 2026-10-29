import json

from sqlalchemy import select

from app.api.deps import get_model_router
from app.domain.tool.executor import function_tool_executor
from app.integrations.llm.client import LLMResponse
from app.integrations.llm.router import ModelRouter
from app.main import app

HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "u1", "X-Roles": "admin"}


class Client:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)

    async def complete(self, request):
        return LLMResponse(content=self.replies.pop(0), model=request.model)

    async def stream(self, request):
        yield ""


def _events(body: str):
    result = []
    for block in body.strip().split("\n\n"):
        name = None
        data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        if name:
            result.append((name, data))
    return result


async def _setup(async_client, calls: list) -> tuple[str, int]:
    async def handler(args, context):
        calls.append(args)
        return {"submitted": True, "matter": args.get("matter")}

    function_tool_executor.register("matter.submit", handler)
    await async_client.post(
        "/api/v1/admin/tools",
        json={
            "tool_code": "matter.submit",
            "name": "提交申请",
            "write_operation": True,
            "input_schema": {"type": "object", "properties": {"matter": {"type": "string"}}},
        },
        headers=HEADERS,
    )
    agent_id = (
        await async_client.post(
            "/api/v1/admin/agents",
            json={"code": "confirm_agent", "name": "确认测试", "domain_code": "district_service"},
            headers=HEADERS,
        )
    ).json()["data"]["id"]
    version_id = (
        await async_client.post(
            f"/api/v1/admin/agents/{agent_id}/versions",
            json={
                "role": "顾问",
                "model_policy": {"primary": "primary"},
                "tools": ["matter.submit"],
            },
            headers=HEADERS,
        )
    ).json()["data"]["id"]
    await async_client.post(
        f"/api/v1/admin/agents/{agent_id}/publish", json={"version_id": version_id}, headers=HEADERS
    )
    session_id = (
        await async_client.post("/api/v1/chat/sessions", json={"channel": "web"}, headers=HEADERS)
    ).json()["data"]["sessionId"]
    return session_id, agent_id


async def test_write_tool_requires_confirmation(async_client) -> None:
    calls: list = []
    session_id, _ = await _setup(async_client, calls)
    app.dependency_overrides[get_model_router] = lambda: ModelRouter(
        Client(['{"type":"tool_call","tool":"matter.submit","arguments":{"matter":"营业执照"}}'])
    )

    response = await async_client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"message": "帮我提交营业执照申请"},
        headers=HEADERS,
    )

    events = _events(response.text)
    names = [name for name, _ in events]
    assert "confirmation.required" in names
    confirmation_id = next(data["confirmationId"] for name, data in events if name == "confirmation.required")
    assert events[-1][1]["finishReason"] == "waiting_confirm"
    assert calls == []

    conversation = (
        await async_client.get(f"/api/v1/chat/sessions/{session_id}", headers=HEADERS)
    ).json()["data"]
    assert conversation["status"] == "WAITING_CONFIRM"

    return confirmation_id


async def test_confirm_executes_write_tool(async_client) -> None:
    calls: list = []
    session_id, _ = await _setup(async_client, calls)
    app.dependency_overrides[get_model_router] = lambda: ModelRouter(
        Client(['{"type":"tool_call","tool":"matter.submit","arguments":{"matter":"营业执照"}}'])
    )
    response = await async_client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"message": "帮我提交营业执照申请"},
        headers=HEADERS,
    )
    confirmation_id = next(
        data["confirmationId"] for name, data in _events(response.text) if name == "confirmation.required"
    )

    decided = await async_client.post(
        f"/api/v1/chat/sessions/{session_id}/confirmations/{confirmation_id}",
        json={"decision": "confirm"},
        headers=HEADERS,
    )

    data = decided.json()["data"]
    assert data["executable"] is True
    assert data["execution"]["status"] == "SUCCESS"
    assert data["execution"]["output"]["submitted"] is True
    assert calls == [{"matter": "营业执照"}]

    conversation = (
        await async_client.get(f"/api/v1/chat/sessions/{session_id}", headers=HEADERS)
    ).json()["data"]
    assert conversation["status"] == "ACTIVE"


async def test_run_checkpoints_are_persisted(async_client, db_session) -> None:
    from app.domain.session.models import RunCheckpoint

    calls: list = []
    session_id, _ = await _setup(async_client, calls)
    app.dependency_overrides[get_model_router] = lambda: ModelRouter(
        Client(
            [
                '{"type":"tool_call","tool":"matter.submit","arguments":{"matter":"营业执照"}}',
                '{"type":"final","answer":"已处理"}',
            ]
        )
    )
    await async_client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"message": "办理"},
        headers=HEADERS,
    )

    checkpoints = (await db_session.execute(select(RunCheckpoint))).scalars().all()
    assert checkpoints
