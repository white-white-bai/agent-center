import json

HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "u1", "X-Roles": "admin"}


class ScriptedClient:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    async def complete(self, request):
        from app.integrations.llm.client import LLMResponse

        return LLMResponse(content=self.reply, model=request.model)

    async def stream(self, request):
        response = await self.complete(request)
        yield response.content


def _events(body: str) -> list[tuple[str, dict, str]]:
    events = []
    for block in body.strip().split("\n\n"):
        event_id = ""
        name = None
        data = None
        for line in block.splitlines():
            if line.startswith("id: "):
                event_id = line[4:]
            elif line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if name:
            events.append((name, data, event_id))
    return events


async def _prepare_run(client) -> tuple[str, str]:
    from app.api.deps import get_model_router
    from app.integrations.llm.router import ModelRouter
    from app.main import app

    app.dependency_overrides[get_model_router] = lambda: ModelRouter(
        ScriptedClient('{"type":"final","answer":"会话流测试回答"}')
    )
    agent = (
        await client.post(
            "/api/v1/admin/agents",
            json={"code": "stream_agent", "name": "流", "domain_code": "district_service"},
            headers=HEADERS,
        )
    ).json()["data"]
    version = (
        await client.post(
            f"/api/v1/admin/agents/{agent['id']}/versions",
            json={"role": "流", "model_policy": {"primary": "primary", "max_steps": 2}},
            headers=HEADERS,
        )
    ).json()["data"]
    await client.post(
        f"/api/v1/admin/agents/{agent['id']}/publish",
        json={"version_id": version["id"]},
        headers=HEADERS,
    )
    session_id = (
        await client.post(
            "/api/v1/chat/sessions", json={"channel": "web"}, headers=HEADERS
        )
    ).json()["data"]["sessionId"]
    response = await client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"message": "你好", "agentCode": "stream_agent"},
        headers={**HEADERS, "Accept": "text/event-stream"},
    )
    run_id = next(
        data["runId"] for name, data, _ in _events(response.text) if name == "run.start"
    )
    return str(session_id), run_id


async def test_session_stream_heartbeat_and_replay(async_client) -> None:
    session_id, run_id = await _prepare_run(async_client)

    first = await async_client.get(
        f"/api/v1/chat/sessions/{session_id}/stream",
        params={"timeoutSeconds": 0.5, "pollSeconds": 0.1, "heartbeatSeconds": 0.1},
        headers=HEADERS,
    )
    assert first.status_code == 200
    events = _events(first.text)
    names = [name for name, _, _ in events]
    assert names[0] == "stream.ready"
    assert "run.start" in names
    assert "message.end" in names
    assert "heartbeat" in names
    assert names[-1] == "stream.end"

    middle_id = next(
        event_id
        for name, data, event_id in events
        if name == "run.start" and data.get("runId") == run_id
    )
    replay = await async_client.get(
        f"/api/v1/chat/sessions/{session_id}/stream",
        params={
            "lastEventId": middle_id,
            "timeoutSeconds": 0.3,
            "pollSeconds": 0.1,
            "heartbeatSeconds": 0,
        },
        headers=HEADERS,
    )
    replayed = _events(replay.text)
    replayed_names = [name for name, _, _ in replayed]
    assert "run.start" not in replayed_names
    assert "message.end" in replayed_names
    ids = [event_id for _, _, event_id in replayed if event_id.startswith("run_")]
    assert len(ids) == len(set(ids))


async def test_session_stream_is_tenant_isolated(async_client) -> None:
    session_id, _ = await _prepare_run(async_client)
    response = await async_client.get(
        f"/api/v1/chat/sessions/{session_id}/stream",
        params={"timeoutSeconds": 0.2, "pollSeconds": 0.1},
        headers={"X-Tenant-Id": "t2", "X-User-Id": "u2", "X-Roles": "admin"},
    )
    assert response.status_code == 404
