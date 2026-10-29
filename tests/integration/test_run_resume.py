import json

from sqlalchemy import select

from app.api.deps import get_model_router
from app.domain.session.models import Conversation, Message, Run, RunStep
from app.integrations.llm.client import LLMResponse
from app.integrations.llm.router import ModelRouter
from app.main import app

HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "u1", "X-Roles": "admin"}


class Client:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    async def complete(self, request):
        return LLMResponse(content=self.reply, model=request.model, token_input=5, token_output=5)

    async def stream(self, request):
        yield ""


async def _seed_failed_run(async_client, db_session) -> tuple[int, str]:
    agent_id = (
        await async_client.post(
            "/api/v1/admin/agents",
            json={"code": "resume_agent", "name": "恢复测试", "domain_code": "district_service"},
            headers=HEADERS,
        )
    ).json()["data"]["id"]
    version_id = (
        await async_client.post(
            f"/api/v1/admin/agents/{agent_id}/versions",
            json={"role": "顾问", "model_policy": {"primary": "primary", "max_steps": 3}},
            headers=HEADERS,
        )
    ).json()["data"]["id"]
    await async_client.post(
        f"/api/v1/admin/agents/{agent_id}/publish",
        json={"version_id": version_id},
        headers=HEADERS,
    )

    conversation = Conversation(tenant_id="t1", user_id="u1", channel="web", status="ACTIVE")
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)
    db_session.add(
        Message(
            tenant_id="t1",
            conversation_id=conversation.id,
            role="user",
            content="营业执照怎么办理",
        )
    )
    run = Run(
        id="run_failed",
        tenant_id="t1",
        conversation_id=conversation.id,
        agent_version_id=version_id,
        agent_code="resume_agent",
        trace_id="trace_old",
        status="FAILED",
        token_input=100,
        tool_call_count=1,
    )
    db_session.add(run)
    db_session.add(
        RunStep(
            tenant_id="t1",
            run_id="run_failed",
            step_no=1,
            step_type="MODEL_RESPONSE",
            status="SUCCESS",
            output_summary="失败前的一步",
        )
    )
    await db_session.commit()
    return conversation.id, version_id


async def test_resume_failed_run_creates_child_run(async_client, db_session) -> None:
    conversation_id, _ = await _seed_failed_run(async_client, db_session)
    app.dependency_overrides[get_model_router] = lambda: ModelRouter(
        Client('{"type":"final","answer":"恢复后的回答"}')
    )

    response = await async_client.post(
        f"/api/v1/chat/sessions/{conversation_id}/runs/run_failed/resume", headers=HEADERS
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "COMPLETED"
    assert data["answer"] == "恢复后的回答"
    assert data["parentRunId"] == "run_failed"

    runs = (await db_session.execute(select(Run))).scalars().all()
    child = next(run for run in runs if run.parent_run_id == "run_failed")
    assert child.status == "COMPLETED"
    assert child.token_input >= 100

    messages = (await db_session.execute(select(Message))).scalars().all()
    assert messages[-1].content == "恢复后的回答"


async def test_resume_rejects_completed_run(async_client, db_session) -> None:
    conversation_id, _ = await _seed_failed_run(async_client, db_session)
    run = await db_session.get(Run, "run_failed")
    run.status = "COMPLETED"
    await db_session.commit()
    app.dependency_overrides[get_model_router] = lambda: ModelRouter(Client('{"type":"final","answer":"x"}'))

    response = await async_client.post(
        f"/api/v1/chat/sessions/{conversation_id}/runs/run_failed/resume", headers=HEADERS
    )

    assert response.status_code == 409


async def test_resume_is_tenant_isolated(async_client, db_session) -> None:
    conversation_id, _ = await _seed_failed_run(async_client, db_session)

    response = await async_client.post(
        f"/api/v1/chat/sessions/{conversation_id}/runs/run_failed/resume",
        headers={"X-Tenant-Id": "t2", "X-User-Id": "u2"},
    )

    assert response.status_code == 404
