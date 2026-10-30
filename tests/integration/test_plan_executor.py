import json

from sqlalchemy import select

from app.api.deps import get_model_router
from app.domain.session.models import Run, RunStep
from app.domain.tool.executor import function_tool_executor
from app.domain.tool.models import ToolConfirmation
from app.integrations.llm.client import LLMResponse
from app.integrations.llm.router import ModelRouter
from app.main import app

HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "u1", "X-Roles": "admin"}


class ScriptedClient:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)

    async def complete(self, request):
        return LLMResponse(
            content=self.replies.pop(0), model=request.model, token_input=1, token_output=1
        )

    async def stream(self, request):
        response = await self.complete(request)
        yield response.content


def _override_router(client: ScriptedClient) -> None:
    app.dependency_overrides[get_model_router] = lambda: ModelRouter(client)


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


async def _tool(client, code: str, *, write: bool = False) -> None:
    response = await client.post(
        "/api/v1/admin/tools",
        json={
            "tool_code": code,
            "name": code,
            "source_type": "FUNCTION",
            "write_operation": write,
        },
        headers=HEADERS,
    )
    assert response.status_code == 200


async def _agent(client, code: str, tools: list[str]) -> None:
    agent = (
        await client.post(
            "/api/v1/admin/agents",
            json={"code": code, "name": code, "domain_code": "district_service"},
            headers=HEADERS,
        )
    ).json()["data"]
    version = (
        await client.post(
            f"/api/v1/admin/agents/{agent['id']}/versions",
            json={
                "role": "计划执行",
                "tools": tools,
                "model_policy": {"primary": "primary", "max_steps": 4},
            },
            headers=HEADERS,
        )
    ).json()["data"]
    await client.post(
        f"/api/v1/admin/agents/{agent['id']}/publish",
        json={"version_id": version["id"]},
        headers=HEADERS,
    )


async def _send(client, agent_code: str) -> str:
    session_id = (
        await client.post(
            "/api/v1/chat/sessions", json={"channel": "web"}, headers=HEADERS
        )
    ).json()["data"]["sessionId"]
    response = await client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"message": "执行计划", "agentCode": agent_code},
        headers={**HEADERS, "Accept": "text/event-stream"},
    )
    assert response.status_code == 200
    return response.text


async def test_plan_executes_readonly_tools_in_order(async_client, db_session) -> None:
    calls: list[str] = []

    async def echo(arguments, context):
        calls.append("echo")
        return {"value": arguments.get("text")}

    async def upper(arguments, context):
        calls.append("upper")
        return {"value": str(arguments.get("text", "")).upper()}

    function_tool_executor.register("plan_echo", echo)
    function_tool_executor.register("plan_upper", upper)
    await _tool(async_client, "plan_echo")
    await _tool(async_client, "plan_upper")
    await _agent(async_client, "plan_agent", ["plan_echo", "plan_upper"])
    _override_router(
        ScriptedClient(
            [
                json.dumps(
                    {
                        "type": "plan",
                        "steps": [
                            {"tool": "plan_echo", "arguments": {"text": "abc"}},
                            {"tool": "plan_upper", "arguments": {"text": "abc"}},
                        ],
                    },
                    ensure_ascii=False,
                ),
                '{"type":"final","answer":"计划结果已汇总。"}',
            ]
        )
    )

    body = await _send(async_client, "plan_agent")

    assert _answer(body) == "计划结果已汇总。"
    names = [name for name, _ in _events(body)]
    assert names.count("tool.call") == 2
    assert names.count("tool.result") == 2
    assert calls == ["echo", "upper"]

    steps = list((await db_session.execute(select(RunStep))).scalars().all())
    plan_step = next(step for step in steps if step.step_type == "PLAN_EXECUTOR")
    assert plan_step.status == "SUCCESS"
    run = (await db_session.execute(select(Run))).scalars().one()
    assert run.tool_call_count == 2


async def test_plan_rejects_unauthorized_tool(async_client, db_session) -> None:
    executed = {"count": 0}

    async def forbidden(arguments, context):
        executed["count"] += 1
        return {"ok": True}

    function_tool_executor.register("plan_forbidden", forbidden)
    await _agent(async_client, "plan_auth_agent", [])
    _override_router(
        ScriptedClient(
            [
                '{"type":"plan","steps":[{"tool":"plan_forbidden","arguments":{}}]}',
                '{"type":"final","answer":"步骤未授权，已说明。"}',
            ]
        )
    )

    body = await _send(async_client, "plan_auth_agent")

    assert _answer(body) == "步骤未授权，已说明。"
    assert executed["count"] == 0
    steps = list((await db_session.execute(select(RunStep))).scalars().all())
    plan_step = next(step for step in steps if step.step_type == "PLAN_EXECUTOR")
    assert plan_step.status == "FAILED"
    assert "AC.TOOL.UNAUTHORIZED" in (plan_step.output_summary or "")


async def test_plan_rejects_write_tool_without_confirmation(async_client, db_session) -> None:
    async def write_handler(arguments, context):
        return {"submitted": True}

    function_tool_executor.register("plan_write", write_handler)
    await _tool(async_client, "plan_write", write=True)
    await _agent(async_client, "plan_write_agent", ["plan_write"])
    _override_router(
        ScriptedClient(
            [
                '{"type":"plan","steps":[{"tool":"plan_write","arguments":{}}]}',
                '{"type":"final","answer":"写操作需要单独确认。"}',
            ]
        )
    )

    body = await _send(async_client, "plan_write_agent")

    assert _answer(body) == "写操作需要单独确认。"
    steps = list((await db_session.execute(select(RunStep))).scalars().all())
    plan_step = next(step for step in steps if step.step_type == "PLAN_EXECUTOR")
    assert "AC.TOOL.CONFIRMATION_REQUIRED" in (plan_step.output_summary or "")
    confirmations = list(
        (await db_session.execute(select(ToolConfirmation))).scalars().all()
    )
    assert confirmations == []
