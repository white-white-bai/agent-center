HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "u1", "X-Roles": "admin"}


async def _prepare_agent(client) -> None:
    agent_id = (
        await client.post(
            "/api/v1/admin/agents",
            json={"code": "safety_agent", "name": "安全测试", "domain_code": "district_service"},
            headers=HEADERS,
        )
    ).json()["data"]["id"]
    version_id = (
        await client.post(
            f"/api/v1/admin/agents/{agent_id}/versions",
            json={"role": "顾问", "goal": "答疑", "model_policy": {"primary": "primary"}},
            headers=HEADERS,
        )
    ).json()["data"]["id"]
    await client.post(
        f"/api/v1/admin/agents/{agent_id}/publish",
        json={"version_id": version_id},
        headers=HEADERS,
    )


async def test_input_safety_block_stops_run(async_client, db_session, monkeypatch) -> None:
    import json

    from sqlalchemy import select

    from app.api.deps import get_model_router
    from app.core.config import get_settings
    from app.domain.session.models import Run
    from app.integrations.llm.client import LLMResponse
    from app.integrations.llm.router import ModelRouter
    from app.main import app

    class Client:
        async def complete(self, request):  # pragma: no cover - 不应被调用
            return LLMResponse(content='{"type":"final","answer":"不应调用"}', model=request.model)

        async def stream(self, request):
            yield ""

    monkeypatch.setattr(get_settings(), "sensitive_words", "违禁词")
    app.dependency_overrides[get_model_router] = lambda: ModelRouter(Client())
    await _prepare_agent(async_client)
    session_id = (
        await async_client.post("/api/v1/chat/sessions", json={"channel": "web"}, headers=HEADERS)
    ).json()["data"]["sessionId"]

    response = await async_client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"message": "包含违禁词的请求"},
        headers=HEADERS,
    )

    events = []
    for block in response.text.strip().split("\n\n"):
        name = None
        data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        if name:
            events.append((name, data))

    assert events[0][0] == "error"
    assert events[0][1]["code"] == "AC.SAFETY.BLOCKED"
    assert events[-1][1]["finishReason"] == "safety_blocked"
    runs = (await db_session.execute(select(Run))).scalars().all()
    assert runs == []


async def test_output_safety_replaces_answer(async_client, monkeypatch) -> None:
    from app.api.deps import get_model_router
    from app.core.config import get_settings
    from app.integrations.llm.client import LLMResponse
    from app.integrations.llm.router import ModelRouter
    from app.main import app

    class Client:
        async def complete(self, request):
            return LLMResponse(content='{"type":"final","answer":"含违禁词的输出"}', model=request.model)

        async def stream(self, request):
            yield ""

    monkeypatch.setattr(get_settings(), "sensitive_words", "违禁词")
    app.dependency_overrides[get_model_router] = lambda: ModelRouter(Client())
    await _prepare_agent(async_client)
    session_id = (
        await async_client.post("/api/v1/chat/sessions", json={"channel": "web"}, headers=HEADERS)
    ).json()["data"]["sessionId"]

    response = await async_client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"message": "正常咨询"},
        headers=HEADERS,
    )

    assert "抱歉，该内容不符合平台使用规范" in response.text
    assert "含违禁词的输出" not in response.text
