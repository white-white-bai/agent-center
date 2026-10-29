from sqlalchemy import select

from app.core.tenant import TenantContext
from app.domain.session.models import Conversation, Run, RunStep
from app.domain.tool.executor import FunctionToolExecutor
from app.domain.tool.models import ToolDefinition
from app.integrations.llm.client import LLMResponse
from app.integrations.llm.router import ModelRouter
from app.runtime.context import RunContext
from app.runtime.react_executor import ReActExecutor

CTX = TenantContext(tenant_id="t1", user_id="u1")


class ScriptedClient:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)

    async def complete(self, request):
        return LLMResponse(content=self.replies.pop(0), model=request.model)

    async def stream(self, request):
        yield ""


def _run_ctx(run_id: str = "run_fanout") -> RunContext:
    return RunContext(
        run_id=run_id,
        tenant_id="t1",
        user_id="u1",
        conversation_id=1,
        turn_id=None,
        agent_code="fanout_agent",
        trace_id="trace",
        user_message="并行查询",
        agent_config={},
        model_policy={"primary": "primary"},
        allowed_tools=["tool.a", "tool.b"],
        max_steps=4,
    )


async def _seed(db_session, run_id: str = "run_fanout") -> None:
    conversation = await db_session.get(Conversation, 1)
    if conversation is None:
        db_session.add(
            Conversation(id=1, tenant_id="t1", user_id="u1", channel="web", status="ACTIVE")
        )
        await db_session.commit()
    db_session.add_all(
        [
            ToolDefinition(
                tenant_id="t1", tool_code="tool.a", name="A", input_schema_json={"type": "object"}
            ),
            ToolDefinition(
                tenant_id="t1", tool_code="tool.b", name="B", input_schema_json={"type": "object"}
            ),
            Run(id=run_id, tenant_id="t1", conversation_id=1, trace_id="trace", status="QUEUED"),
        ]
    )
    await db_session.commit()


async def test_fanout_runs_read_tools_in_parallel(db_session) -> None:
    await _seed(db_session)
    calls: list[str] = []
    executor = FunctionToolExecutor()

    async def handler_a(args, context):
        calls.append("a")
        return {"value": "A"}

    async def handler_b(args, context):
        calls.append("b")
        return {"value": "B"}

    executor.register("tool.a", handler_a)
    executor.register("tool.b", handler_b)

    client = ScriptedClient(
        [
            '{"type":"fanout","tasks":[{"tool":"tool.a","arguments":{}},{"tool":"tool.b","arguments":{}}]}',
            '{"type":"final","answer":"并行完成"}',
        ]
    )

    result = await ReActExecutor(db_session, ModelRouter(client), executor).run(CTX, _run_ctx())

    assert result.status == "COMPLETED"
    assert result.tool_calls == 2
    assert sorted(calls) == ["a", "b"]
    steps = (await db_session.execute(select(RunStep))).scalars().all()
    assert any("tool.a#0" in (step.output_summary or "") for step in steps)


async def test_fanout_marks_partial_failure(db_session) -> None:
    await _seed(db_session, run_id="run_fanout_partial")
    executor = FunctionToolExecutor()

    async def ok_handler(args, context):
        return {"value": "ok"}

    async def broken_handler(args, context):
        raise RuntimeError("boom")

    executor.register("tool.a", ok_handler)
    executor.register("tool.b", broken_handler)

    client = ScriptedClient(
        [
            '{"type":"fanout","tasks":[{"tool":"tool.a","arguments":{}},{"tool":"tool.b","arguments":{}}]}',
            '{"type":"final","answer":"部分完成"}',
        ]
    )

    result = await ReActExecutor(db_session, ModelRouter(client), executor).run(
        CTX, _run_ctx("run_fanout_partial")
    )

    assert result.status == "COMPLETED"
    steps = (await db_session.execute(select(RunStep))).scalars().all()
    partial_steps = [step for step in steps if step.status == "PARTIAL"]
    assert partial_steps
    assert "tool.b" in (partial_steps[0].output_summary or "")
