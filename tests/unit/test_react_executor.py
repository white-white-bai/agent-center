import pytest

from app.core.exceptions import ValidationError
from app.core.tenant import TenantContext
from app.runtime.decisions import (
    ClarifyDecision,
    FinalDecision,
    SlotsDecision,
    ToolCallDecision,
    TopicDecision,
    parse_decision,
)
from app.integrations.llm.client import LLMResponse


def test_parse_final_decision() -> None:
    decision = parse_decision('{"type":"final","answer":"你好"}')

    assert isinstance(decision, FinalDecision)
    assert decision.answer == "你好"


def test_parse_tool_call_decision() -> None:
    decision = parse_decision('{"type":"tool_call","tool":"echo","arguments":{"a":1}}')

    assert isinstance(decision, ToolCallDecision)
    assert decision.tool == "echo"
    assert decision.arguments == {"a": 1}


def test_parse_clarify_decision() -> None:
    decision = parse_decision('{"type":"clarify","question":"哪个区？"}')

    assert isinstance(decision, ClarifyDecision)
    assert decision.question == "哪个区？"


def test_parse_decision_from_code_fence() -> None:
    decision = parse_decision('```json\n{"type":"final","answer":"ok"}\n```')

    assert isinstance(decision, FinalDecision)


def test_parse_invalid_json_raises() -> None:
    with pytest.raises(ValidationError):
        parse_decision("not json")


def test_parse_slots_decision() -> None:
    decision = parse_decision('{"type":"slots","slots":{"matter_type":"营业执照"}}')

    assert isinstance(decision, SlotsDecision)
    assert decision.slots == {"matter_type": "营业执照"}


def test_parse_slots_requires_object() -> None:
    with pytest.raises(ValidationError):
        parse_decision('{"type":"slots","slots":"bad"}')


def test_parse_topic_decisions() -> None:
    switch = parse_decision('{"type":"topic","action":"switch","topic":"社保查询"}')
    resume = parse_decision('{"type":"topic","action":"resume"}')

    assert isinstance(switch, TopicDecision)
    assert switch.action == "switch"
    assert switch.topic == "社保查询"
    assert resume.action == "resume"


def test_parse_topic_requires_valid_action() -> None:
    with pytest.raises(ValidationError):
        parse_decision('{"type":"topic","action":"unknown"}')
    with pytest.raises(ValidationError):
        parse_decision('{"type":"topic","action":"switch"}')


def test_parse_unknown_type_raises() -> None:
    with pytest.raises(ValidationError):
        parse_decision('{"type":"unknown"}')


def test_parse_tool_call_without_tool_raises() -> None:
    with pytest.raises(ValidationError):
        parse_decision('{"type":"tool_call"}')


class ScriptedLLMClient:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        content = self.replies.pop(0)
        return LLMResponse(content=content, model=request.model, token_input=10, token_output=5)

    async def stream(self, request):
        response = await self.complete(request)
        yield response.content


async def _create_run(db_session, *, run_id: str = "run_test", agent_code: str = "agent_x") -> None:
    from app.domain.session.models import Conversation, Run

    conversation = Conversation(tenant_id="t1", user_id="u1", channel="web", status="ACTIVE")
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)

    db_session.add(
        Run(
            id=run_id,
            tenant_id="t1",
            conversation_id=conversation.id,
            agent_code=agent_code,
            trace_id="trace_1",
            status="QUEUED",
        )
    )
    await db_session.commit()


def _run_ctx(run_id: str = "run_test", **overrides):
    from app.runtime.context import RunContext

    data = dict(
        run_id=run_id,
        tenant_id="t1",
        user_id="u1",
        conversation_id=1,
        turn_id=None,
        agent_code="agent_x",
        trace_id="trace_1",
        user_message="你好",
        agent_config={"role": "顾问", "goal": "答疑"},
        model_policy={"primary": "primary"},
        allowed_tools=["echo"],
        max_steps=4,
        token_budget=1000,
        timeout_ms=5000,
    )
    data.update(overrides)
    return RunContext(**data)


async def test_executor_completes_with_final_answer(db_session) -> None:
    from sqlalchemy import select

    from app.domain.session.models import Run, RunStep
    from app.integrations.llm.router import ModelRouter
    from app.runtime.react_executor import ReActExecutor
    from app.domain.tool.executor import FunctionToolExecutor

    await _create_run(db_session)
    client = ScriptedLLMClient(['{"type":"final","answer":"您好"}'])
    result = await ReActExecutor(db_session, ModelRouter(client), FunctionToolExecutor()).run(
        TenantContext(tenant_id="t1", user_id="u1"), _run_ctx()
    )

    assert result.status == "COMPLETED"
    assert result.answer == "您好"
    run = await db_session.get(Run, "run_test")
    assert run.status == "COMPLETED"
    steps = (await db_session.execute(select(RunStep))).scalars().all()
    assert [s.step_type for s in steps] == ["MODEL_RESPONSE", "FINAL_RESPONSE"]


async def test_executor_runs_tool_then_answers(db_session) -> None:
    from app.domain.tool.executor import FunctionToolExecutor
    from app.domain.tool.models import ToolDefinition, ToolInvokeLog
    from app.integrations.llm.router import ModelRouter
    from app.runtime.react_executor import ReActExecutor
    from sqlalchemy import select

    await _create_run(db_session)
    db_session.add(
        ToolDefinition(
            tenant_id="t1",
            tool_code="echo",
            name="回声",
            input_schema_json={"type": "object", "properties": {"text": {"type": "string"}}},
        )
    )
    await db_session.commit()

    executor = FunctionToolExecutor()

    async def handler(args, context):
        return {"echo": args["text"]}

    executor.register("echo", handler)
    client = ScriptedLLMClient(
        [
            '{"type":"tool_call","tool":"echo","arguments":{"text":"hi"}}',
            '{"type":"final","answer":"已查到 hi"}',
        ]
    )

    result = await ReActExecutor(db_session, ModelRouter(client), executor).run(
        TenantContext(tenant_id="t1", user_id="u1"), _run_ctx()
    )

    assert result.status == "COMPLETED"
    assert result.tool_calls == 1
    assert client.calls == 2
    logs = (await db_session.execute(select(ToolInvokeLog))).scalars().all()
    assert len(logs) == 1
    assert logs[0].status == "SUCCESS"


async def test_executor_rejects_unbound_tool(db_session) -> None:
    from app.domain.tool.executor import FunctionToolExecutor
    from app.integrations.llm.router import ModelRouter
    from app.runtime.react_executor import ReActExecutor

    await _create_run(db_session)
    client = ScriptedLLMClient(
        [
            '{"type":"tool_call","tool":"not_bound","arguments":{}}',
            '{"type":"final","answer":"抱歉"}',
        ]
    )

    result = await ReActExecutor(db_session, ModelRouter(client), FunctionToolExecutor()).run(
        TenantContext(tenant_id="t1", user_id="u1"), _run_ctx()
    )

    assert result.status == "COMPLETED"
    assert result.tool_calls == 0
    assert client.calls == 2


async def test_executor_stops_at_step_budget(db_session) -> None:
    from app.domain.tool.executor import FunctionToolExecutor
    from app.integrations.llm.router import ModelRouter
    from app.runtime.react_executor import ReActExecutor

    await _create_run(db_session)
    reply = '{"type":"tool_call","tool":"missing","arguments":{}}'
    client = ScriptedLLMClient([reply] * 5)

    result = await ReActExecutor(db_session, ModelRouter(client), FunctionToolExecutor()).run(
        TenantContext(tenant_id="t1", user_id="u1"), _run_ctx(max_steps=3)
    )

    assert result.status == "FAILED"
    assert result.error_code == "AC.RUN.STEP_BUDGET_EXCEEDED"
    assert result.steps == 3


async def test_executor_records_slots_and_persists_state(db_session) -> None:
    from app.domain.session.models import Conversation
    from app.domain.tool.executor import FunctionToolExecutor
    from app.integrations.llm.router import ModelRouter
    from app.runtime.react_executor import ReActExecutor

    await _create_run(db_session)
    client = ScriptedLLMClient(
        [
            '{"type":"slots","slots":{"matter_type":"营业执照办理"}}',
            '{"type":"final","answer":"已记录"}',
        ]
    )

    result = await ReActExecutor(db_session, ModelRouter(client), FunctionToolExecutor()).run(
        TenantContext(tenant_id="t1", user_id="u1"),
        _run_ctx(
            agent_config={
                "role": "顾问",
                "goal": "答疑",
                "required_slots": ["matter_type"],
                "slot_questions": {"matter_type": "请提供事项名称"},
            }
        ),
    )

    assert result.status == "COMPLETED"
    conversation = await db_session.get(Conversation, 1)
    assert conversation.session_state_json["slots"]["matter_type"]["value"] == "营业执照办理"
    assert conversation.session_state_json["slots"]["matter_type"]["status"] == "filled"


async def test_executor_asks_for_missing_slot(db_session) -> None:
    from app.domain.tool.executor import FunctionToolExecutor
    from app.integrations.llm.router import ModelRouter
    from app.runtime.react_executor import ReActExecutor

    await _create_run(db_session)
    client = ScriptedLLMClient(['{"type":"slots","slots":{"matter_type":"营业执照"}}'])

    result = await ReActExecutor(db_session, ModelRouter(client), FunctionToolExecutor()).run(
        TenantContext(tenant_id="t1", user_id="u1"),
        _run_ctx(
            agent_config={
                "role": "顾问",
                "goal": "答疑",
                "required_slots": ["matter_type", "application_number"],
                "slot_questions": {"application_number": "请提供申请编号"},
            }
        ),
    )

    assert result.status == "WAITING_USER"
    assert result.question == "请提供申请编号"


async def test_executor_switches_and_resumes_topic(db_session) -> None:
    from app.domain.session.models import Conversation
    from app.domain.tool.executor import FunctionToolExecutor
    from app.integrations.llm.router import ModelRouter
    from app.runtime.react_executor import ReActExecutor

    await _create_run(db_session)
    conversation = await db_session.get(Conversation, 1)
    conversation.session_state_json = {
        "active_topic": "营业执照办理",
        "topic_stack": [],
    }
    await db_session.commit()

    switch_client = ScriptedLLMClient(
        [
            '{"type":"topic","action":"switch","topic":"社保查询"}',
            '{"type":"final","answer":"已切换"}',
        ]
    )
    result = await ReActExecutor(
        db_session, ModelRouter(switch_client), FunctionToolExecutor()
    ).run(TenantContext(tenant_id="t1", user_id="u1"), _run_ctx())

    assert result.status == "COMPLETED"
    await db_session.refresh(conversation)
    assert conversation.session_state_json["active_topic"] == "社保查询"
    assert conversation.session_state_json["topic_stack"][-1]["topic"] == "营业执照办理"

    from app.domain.session.models import Run

    db_session.add(
        Run(
            id="run_resume",
            tenant_id="t1",
            conversation_id=1,
            trace_id="trace_2",
            status="QUEUED",
        )
    )
    await db_session.commit()

    resume_client = ScriptedLLMClient(
        ['{"type":"topic","action":"resume"}', '{"type":"final","answer":"已恢复"}']
    )
    await ReActExecutor(db_session, ModelRouter(resume_client), FunctionToolExecutor()).run(
        TenantContext(tenant_id="t1", user_id="u1"), _run_ctx(run_id="run_resume")
    )

    await db_session.refresh(conversation)
    assert conversation.session_state_json["active_topic"] == "营业执照办理"
    assert conversation.session_state_json["topic_stack"] == []


async def test_executor_returns_clarification(db_session) -> None:
    from app.domain.tool.executor import FunctionToolExecutor
    from app.integrations.llm.router import ModelRouter
    from app.runtime.react_executor import ReActExecutor

    await _create_run(db_session)
    client = ScriptedLLMClient(['{"type":"clarify","question":"请提供事项名称"}'])

    result = await ReActExecutor(db_session, ModelRouter(client), FunctionToolExecutor()).run(
        TenantContext(tenant_id="t1", user_id="u1"), _run_ctx()
    )

    assert result.status == "WAITING_USER"
    assert result.question == "请提供事项名称"
