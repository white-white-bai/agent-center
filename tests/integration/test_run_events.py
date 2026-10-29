import io
import json

from app.api.deps import get_model_router
from app.integrations.llm.client import LLMResponse
from app.integrations.llm.router import ModelRouter
from app.main import app

HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "u1", "X-Roles": "admin"}


class Client:
    async def complete(self, request):
        return LLMResponse(content='{"type":"final","answer":"回答内容可重放"}', model=request.model)

    async def stream(self, request):
        yield ""


async def _send(async_client) -> str:
    agent_id = (
        await async_client.post(
            "/api/v1/admin/agents",
            json={"code": "replay_agent", "name": "重放", "domain_code": "district_service"},
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
        f"/api/v1/admin/agents/{agent_id}/publish", json={"version_id": version_id}, headers=HEADERS
    )
    app.dependency_overrides[get_model_router] = lambda: ModelRouter(Client())
    session_id = (
        await async_client.post("/api/v1/chat/sessions", json={"channel": "web"}, headers=HEADERS)
    ).json()["data"]["sessionId"]
    response = await async_client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"message": "你好"},
        headers=HEADERS,
    )
    run_id = None
    for block in response.text.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
                if "runId" in data and data["runId"]:
                    run_id = data["runId"]
                    break
        if run_id:
            break
    return session_id, run_id


async def test_events_are_persisted_and_replayable(async_client) -> None:
    session_id, run_id = await _send(async_client)

    events = (
        await async_client.get(
            f"/api/v1/chat/sessions/{session_id}/runs/{run_id}/events", headers=HEADERS
        )
    ).json()["data"]

    assert events[0]["event"] == "run.start"
    assert events[-1]["event"] == "message.end"
    seqs = [event["seq"] for event in events]
    assert seqs == sorted(seqs)
    assert len(seqs) == len(set(seqs))
    deltas = [event for event in events if event["event"] == "message.delta"]
    assert "".join(event["data"]["content"] for event in deltas) == "回答内容可重放"


async def test_replay_can_resume_from_last_event_id(async_client) -> None:
    session_id, run_id = await _send(async_client)
    all_events = (
        await async_client.get(
            f"/api/v1/chat/sessions/{session_id}/runs/{run_id}/events", headers=HEADERS
        )
    ).json()["data"]
    cut = all_events[1]

    resumed = (
        await async_client.get(
            f"/api/v1/chat/sessions/{session_id}/runs/{run_id}/events",
            params={"lastEventId": cut["id"]},
            headers=HEADERS,
        )
    ).json()["data"]

    assert resumed
    assert all(event["seq"] > cut["seq"] for event in resumed)
    assert resumed[-1]["event"] == "message.end"


async def test_stream_endpoint_resumes_from_last_event_id(async_client) -> None:
    session_id, run_id = await _send(async_client)
    all_events = (
        await async_client.get(
            f"/api/v1/chat/sessions/{session_id}/runs/{run_id}/events", headers=HEADERS
        )
    ).json()["data"]
    cut = all_events[0]

    response = await async_client.get(
        f"/api/v1/chat/sessions/{session_id}/runs/{run_id}/stream",
        params={"lastEventId": cut["id"]},
        headers=HEADERS,
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "stream.end" in response.text
    ids = [
        line[len("id: ") :]
        for line in response.text.splitlines()
        if line.startswith("id: ") and not line.endswith(":end")
    ]
    assert f"{run_id}:{cut['seq']}" not in ids
    assert all(int(item.split(":")[1]) > cut["seq"] for item in ids if item.split(":")[0] == run_id)


async def test_stream_endpoint_is_tenant_isolated(async_client) -> None:
    session_id, run_id = await _send(async_client)

    response = await async_client.get(
        f"/api/v1/chat/sessions/{session_id}/runs/{run_id}/stream",
        headers={"X-Tenant-Id": "t2", "X-User-Id": "u2"},
    )

    assert response.status_code == 404


async def test_replay_is_tenant_isolated(async_client) -> None:
    session_id, run_id = await _send(async_client)

    response = await async_client.get(
        f"/api/v1/chat/sessions/{session_id}/runs/{run_id}/events",
        headers={"X-Tenant-Id": "t2", "X-User-Id": "u2"},
    )

    assert response.status_code == 404
