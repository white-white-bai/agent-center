import json

from sqlalchemy import select

from app.api.deps import get_model_router
from app.integrations.llm.client import LLMResponse
from app.integrations.llm.router import ModelRouter
from app.main import app

HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "u1", "X-Roles": "admin"}


class ScriptedClient:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        return LLMResponse(content=self.replies.pop(0), model=request.model, token_input=5, token_output=5)

    async def stream(self, request):
        response = await self.complete(request)
        yield response.content


async def _prepare_agent(client) -> None:
    agent_id = (
        await client.post(
            "/api/v1/admin/agents",
            json={"code": "district_consult", "name": "区级咨询", "domain_code": "district_service"},
            headers=HEADERS,
        )
    ).json()["data"]["id"]
    version_id = (
        await client.post(
            f"/api/v1/admin/agents/{agent_id}/versions",
            json={"role": "顾问", "goal": "答疑", "model_policy": {"primary": "primary", "max_steps": 3}},
            headers=HEADERS,
        )
    ).json()["data"]["id"]
    await client.post(
        f"/api/v1/admin/agents/{agent_id}/publish",
        json={"version_id": version_id},
        headers=HEADERS,
    )


def _override_router(client) -> None:
    app.dependency_overrides[get_model_router] = lambda: ModelRouter(client)


def _sse_events(body: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in body.strip().split("\n\n"):
        name = None
        data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        if name:
            events.append((name, data))
    return events


async def test_send_message_streams_and_persists(async_client, db_session) -> None:
    await _prepare_agent(async_client)
    _override_router(ScriptedClient(['{"type":"final","answer":"需要提交身份证和营业执照。"}']))

    session_id = (
        await async_client.post("/api/v1/chat/sessions", json={"channel": "web"}, headers=HEADERS)
    ).json()["data"]["sessionId"]

    response = await async_client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"message": "营业执照怎么办理", "clientMessageId": "msg-1"},
        headers={**HEADERS, "Accept": "text/event-stream"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _sse_events(response.text)
    names = [name for name, _ in events]
    assert names[0] == "run.start"
    assert "message.delta" in names
    assert names[-1] == "message.end"
    assert events[-1][1]["finishReason"] == "completed"

    answer = "".join(data["content"] for name, data in events if name == "message.delta")
    assert answer == "需要提交身份证和营业执照。"

    from app.domain.session.models import Message, Run

    messages = (await db_session.execute(select(Message))).scalars().all()
    assert [m.role for m in messages] == ["user", "assistant"]
    runs = (await db_session.execute(select(Run))).scalars().all()
    assert len(runs) == 1
    assert runs[0].status == "COMPLETED"


async def test_duplicate_client_message_id_replays_answer(async_client) -> None:
    await _prepare_agent(async_client)
    _override_router(
        ScriptedClient(['{"type":"final","answer":"第一次回答"}', '{"type":"final","answer":"不应调用"}'])
    )
    session_id = (
        await async_client.post("/api/v1/chat/sessions", json={"channel": "web"}, headers=HEADERS)
    ).json()["data"]["sessionId"]

    first = await async_client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"message": "问题", "clientMessageId": "same-id"},
        headers=HEADERS,
    )
    second = await async_client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"message": "问题", "clientMessageId": "same-id"},
        headers=HEADERS,
    )

    events = _sse_events(second.text)
    assert events[-1][1]["finishReason"] == "duplicate"
    answer = "".join(data["content"] for name, data in events if name == "message.delta")
    assert answer == "第一次回答"
    assert first.status_code == 200


async def test_streaming_requires_published_agent(async_client) -> None:
    session_id = (
        await async_client.post("/api/v1/chat/sessions", json={"channel": "web"}, headers=HEADERS)
    ).json()["data"]["sessionId"]

    response = await async_client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"message": "你好"},
        headers=HEADERS,
    )

    assert response.status_code == 409
    assert response.json()["code"] == "AC.COMMON.CONFLICT"


async def test_interrupt_marks_queued_run(async_client, db_session) -> None:
    from app.domain.session.models import Run

    session_id = (
        await async_client.post("/api/v1/chat/sessions", json={"channel": "web"}, headers=HEADERS)
    ).json()["data"]["sessionId"]
    db_session.add(
        Run(
            id="run_manual",
            tenant_id="t1",
            conversation_id=int(session_id),
            trace_id="trace_x",
            status="QUEUED",
        )
    )
    await db_session.commit()

    response = await async_client.post(
        f"/api/v1/chat/sessions/{session_id}/interrupt",
        json={"runId": "run_manual", "reason": "user_interrupt"},
        headers=HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["data"]["accepted"] is True
    assert response.json()["data"]["status"] == "INTERRUPTED"


async def test_interrupt_completed_run_is_rejected_as_noop(async_client, db_session) -> None:
    from app.domain.session.models import Run

    session_id = (
        await async_client.post("/api/v1/chat/sessions", json={"channel": "web"}, headers=HEADERS)
    ).json()["data"]["sessionId"]
    db_session.add(
        Run(
            id="run_done",
            tenant_id="t1",
            conversation_id=int(session_id),
            trace_id="trace_y",
            status="COMPLETED",
        )
    )
    await db_session.commit()

    response = await async_client.post(
        f"/api/v1/chat/sessions/{session_id}/interrupt",
        json={"runId": "run_done"},
        headers=HEADERS,
    )

    assert response.json()["data"]["accepted"] is False


async def test_interrupt_is_tenant_isolated(async_client, db_session) -> None:
    from app.domain.session.models import Run

    session_id = (
        await async_client.post("/api/v1/chat/sessions", json={"channel": "web"}, headers=HEADERS)
    ).json()["data"]["sessionId"]
    db_session.add(
        Run(
            id="run_other",
            tenant_id="t2",
            conversation_id=int(session_id),
            trace_id="trace_z",
            status="RUNNING",
        )
    )
    await db_session.commit()

    response = await async_client.post(
        f"/api/v1/chat/sessions/{session_id}/interrupt",
        json={"runId": "run_other"},
        headers=HEADERS,
    )

    assert response.status_code == 404
