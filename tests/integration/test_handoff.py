import pytest

from app.core.exceptions import ConflictError, NotFoundError
from app.core.tenant import TenantContext
from app.domain.agent.models import AgentDefinition, AgentVersion
from app.domain.session.models import Conversation
from app.runtime.handoff import HandoffRequest, validate_and_apply

CTX = TenantContext(tenant_id="t1", user_id="u1")


async def _agent(db_session, code: str, *, tenant: str = "t1", published: bool = True) -> AgentDefinition:
    agent = AgentDefinition(
        tenant_id=tenant,
        code=code,
        name=code,
        domain_code="d1",
        lifecycle="PUBLISHED" if published else "DRAFT",
    )
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    version = AgentVersion(
        tenant_id=tenant,
        agent_id=agent.id,
        version_no=1,
        config_json={},
        status="PUBLISHED" if published else "DRAFT",
    )
    db_session.add(version)
    await db_session.commit()
    await db_session.refresh(version)
    if published:
        agent.current_version_id = version.id
        await db_session.commit()
    return agent


async def _conversation(db_session, state: dict | None = None) -> Conversation:
    conversation = Conversation(
        tenant_id="t1",
        user_id="u1",
        channel="web",
        status="ACTIVE",
        current_agent_code="agent_a",
        session_state_json=state or {},
    )
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)
    return conversation


def _request(to_agent: str, from_agent: str = "agent_a") -> HandoffRequest:
    return HandoffRequest(from_agent=from_agent, to_agent=to_agent, reason="需要办理业务")


async def test_handoff_updates_conversation_and_hops(db_session) -> None:
    await _agent(db_session, "agent_b")
    conversation = await _conversation(db_session)

    agent, version = await validate_and_apply(db_session, CTX, conversation, _request("agent_b"))

    assert agent.code == "agent_b"
    await db_session.refresh(conversation)
    assert conversation.current_agent_code == "agent_b"
    assert conversation.session_state_json["handoff_hops"] == 1
    assert conversation.session_state_json["last_handoff"]["reason"] == "需要办理业务"


async def test_handoff_to_self_is_rejected(db_session) -> None:
    await _agent(db_session, "agent_a")
    conversation = await _conversation(db_session)

    with pytest.raises(ConflictError):
        await validate_and_apply(db_session, CTX, conversation, _request("agent_a"))


async def test_handoff_stops_after_max_hops(db_session) -> None:
    await _agent(db_session, "agent_b")
    conversation = await _conversation(db_session, state={"handoff_hops": 3})

    with pytest.raises(ConflictError):
        await validate_and_apply(db_session, CTX, conversation, _request("agent_b"))


async def test_handoff_to_unpublished_agent_is_rejected(db_session) -> None:
    await _agent(db_session, "draft_agent", published=False)
    conversation = await _conversation(db_session)

    with pytest.raises(ConflictError):
        await validate_and_apply(db_session, CTX, conversation, _request("draft_agent"))


async def test_handoff_to_other_tenant_agent_is_not_found(db_session) -> None:
    await _agent(db_session, "other_tenant_agent", tenant="t2")
    conversation = await _conversation(db_session)

    with pytest.raises(NotFoundError):
        await validate_and_apply(db_session, CTX, conversation, _request("other_tenant_agent"))


async def test_executor_emits_handoff_and_switches_agent(db_session) -> None:
    from sqlalchemy import select

    from app.domain.session.models import Run, RunStep
    from app.domain.tool.executor import FunctionToolExecutor
    from app.integrations.llm.router import ModelRouter
    from app.runtime.context import RunContext
    from app.runtime.react_executor import ReActExecutor
    from tests.unit.test_react_executor import ScriptedLLMClient

    await _agent(db_session, "agent_b")
    conversation = await _conversation(db_session)
    db_session.add(
        Run(
            id="run_ho",
            tenant_id="t1",
            conversation_id=conversation.id,
            agent_code="agent_a",
            trace_id="trace",
            status="QUEUED",
        )
    )
    await db_session.commit()

    client = ScriptedLLMClient(['{"type":"handoff","to":"agent_b","reason":"跨域办理"}'])
    run_ctx = RunContext(
        run_id="run_ho",
        tenant_id="t1",
        user_id="u1",
        conversation_id=conversation.id,
        turn_id=None,
        agent_code="agent_a",
        trace_id="trace",
        user_message="我要办理",
        agent_config={},
        model_policy={"primary": "primary"},
    )

    result = await ReActExecutor(db_session, ModelRouter(client), FunctionToolExecutor()).run(CTX, run_ctx)

    assert result.status == "HANDOFF"
    await db_session.refresh(conversation)
    assert conversation.current_agent_code == "agent_b"
    steps = (await db_session.execute(select(RunStep))).scalars().all()
    assert any(step.step_type == "HANDOFF" for step in steps)
