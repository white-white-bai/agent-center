import json
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.tenant import TenantContext
from app.domain.tool.executor import ToolContext, ToolExecutor
from app.domain.tool.service import get_tool, invoke_tool
from app.runtime.context import RunContext

MAX_PLAN_STEPS = 8
EventSink = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class PlanStepOutcome:
    index: int
    tool_code: str
    status: str
    output: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    duration_ms: int = 0


@dataclass
class PlanOutcome:
    steps: list[PlanStepOutcome] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(step.status == "SUCCESS" for step in self.steps)

    def to_observations(self) -> str:
        lines = []
        for step in self.steps:
            payload = {
                "step": step.index,
                "tool": step.tool_code,
                "status": step.status,
                "output": step.output,
                "errorCode": step.error_code,
                "error": step.error_message,
            }
            lines.append(json.dumps(payload, ensure_ascii=False)[:2000])
        return (
            '<plan_results untrusted="true">\n'
            + "\n".join(lines)
            + "\n</plan_results>\n请基于计划结果继续推理；缺失或失败的步骤必须明确说明。"
        )


class PlanExecutor:
    """独立计划执行器：按序执行只读工具计划，写操作仍走确认式 tool_call。"""

    def __init__(
        self,
        session: AsyncSession,
        ctx: TenantContext,
        tool_executor: ToolExecutor,
        run_ctx: RunContext,
        *,
        on_event: EventSink | None = None,
    ) -> None:
        self.session = session
        self.ctx = ctx
        self.tool_executor = tool_executor
        self.run_ctx = run_ctx
        self.on_event = on_event

    async def _emit(self, event: dict[str, Any]) -> None:
        if self.on_event is not None:
            await self.on_event(event)

    async def execute(self, steps: list[dict[str, Any]]) -> PlanOutcome:
        outcome = PlanOutcome()
        deadline = time.monotonic() + self.run_ctx.timeout_ms / 1000
        for index, step in enumerate(steps[:MAX_PLAN_STEPS]):
            tool_code = str(step.get("tool") or "")
            arguments = step.get("arguments") or {}
            if time.monotonic() > deadline:
                outcome.steps.append(
                    PlanStepOutcome(
                        index=index,
                        tool_code=tool_code,
                        status="FAILED",
                        error_code="AC.PLAN.TIMEOUT",
                        error_message="计划执行超时",
                    )
                )
                break
            if tool_code not in self.run_ctx.allowed_tools:
                outcome.steps.append(
                    PlanStepOutcome(
                        index=index,
                        tool_code=tool_code,
                        status="FAILED",
                        error_code="AC.TOOL.UNAUTHORIZED",
                        error_message="工具未被授权",
                    )
                )
                continue
            if not isinstance(arguments, dict):
                outcome.steps.append(
                    PlanStepOutcome(
                        index=index,
                        tool_code=tool_code,
                        status="FAILED",
                        error_code="AC.PLAN.INVALID_ARGUMENTS",
                        error_message="arguments 必须是对象",
                    )
                )
                continue
            try:
                definition = await get_tool(self.session, self.ctx, tool_code)
                if definition.write_operation:
                    outcome.steps.append(
                        PlanStepOutcome(
                            index=index,
                            tool_code=tool_code,
                            status="FAILED",
                            error_code="AC.TOOL.CONFIRMATION_REQUIRED",
                            error_message="写操作必须在计划外通过 tool_call 单独确认",
                        )
                    )
                    continue
            except AppError as exc:
                outcome.steps.append(
                    PlanStepOutcome(
                        index=index,
                        tool_code=tool_code,
                        status="FAILED",
                        error_code=exc.code,
                        error_message=exc.message,
                    )
                )
                continue

            await self._emit(
                {"event": "tool.call", "data": {"toolCode": tool_code, "arguments": arguments}}
            )
            started = time.perf_counter()
            try:
                result = await invoke_tool(
                    self.session,
                    self.ctx,
                    self.tool_executor,
                    tool_code=tool_code,
                    arguments=arguments,
                    tool_context=ToolContext(
                        tenant_id=self.ctx.tenant_id,
                        user_id=self.ctx.user_id,
                        conversation_id=self.run_ctx.conversation_id,
                        run_id=self.run_ctx.run_id,
                        trace_id=self.run_ctx.trace_id,
                    ),
                    allow_write=False,
                )
                step_outcome = PlanStepOutcome(
                    index=index,
                    tool_code=tool_code,
                    status=result.status,
                    output=result.output,
                    error_code=result.error_code,
                    error_message=result.error_message,
                    duration_ms=result.duration_ms,
                )
            except AppError as exc:
                step_outcome = PlanStepOutcome(
                    index=index,
                    tool_code=tool_code,
                    status="FAILED",
                    error_code=exc.code,
                    error_message=exc.message,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )
            except Exception as exc:  # noqa: BLE001 - 单步失败不终止后续计划
                step_outcome = PlanStepOutcome(
                    index=index,
                    tool_code=tool_code,
                    status="FAILED",
                    error_code="AC.PLAN.EXECUTION_FAILED",
                    error_message=str(exc)[:300],
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )
            outcome.steps.append(step_outcome)
            await self._emit(
                {
                    "event": "tool.result",
                    "data": {
                        "toolCode": tool_code,
                        "status": step_outcome.status,
                        "summary": json.dumps(step_outcome.output, ensure_ascii=False)[:500],
                    },
                }
            )
        return outcome
