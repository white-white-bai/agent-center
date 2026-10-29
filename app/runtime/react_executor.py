import json
import time
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.tenant import TenantContext
from app.domain.tool.executor import ToolContext
from app.domain.tool.service import invoke_tool
from app.domain.tool.executor import ToolExecutor
from app.integrations.llm.client import ChatMessage, LLMRequest
from app.integrations.llm.router import ModelRouter
from app.runtime.context import RunContext, RuntimeResult
from app.runtime.decisions import ClarifyDecision, FinalDecision, ToolCallDecision, parse_decision

SYSTEM_TEMPLATE = """你是{role}。
目标：{goal}
约束：{constraints}

你只能输出 JSON，格式三选一：
1. 调用工具：{{"type":"tool_call","tool":"工具编码","arguments":{{...}}}}
2. 最终回答：{{"type":"final","answer":"回答内容"}}
3. 澄清追问：{{"type":"clarify","question":"追问内容"}}
可用工具：{tools}
"""


def build_system_prompt(config: dict, allowed_tools: list[str]) -> str:
    constraints = config.get("constraints") or []
    return SYSTEM_TEMPLATE.format(
        role=config.get("role") or "政务智能助手",
        goal=config.get("goal") or "准确回答用户问题",
        constraints="；".join(constraints) if constraints else "无",
        tools="、".join(allowed_tools) if allowed_tools else "无",
    )


class ReActExecutor:
    def __init__(self, session: AsyncSession, router: ModelRouter, tool_executor: ToolExecutor) -> None:
        self.session = session
        self.router = router
        self.tool_executor = tool_executor

    async def run(self, ctx: TenantContext, run_ctx: RunContext) -> RuntimeResult:
        from app.domain.session.models import Run, RunStep

        result = RuntimeResult(run_id=run_ctx.run_id, status="RUNNING")
        started = time.monotonic()
        messages = [
            ChatMessage(role="system", content=build_system_prompt(run_ctx.agent_config, run_ctx.allowed_tools)),
            ChatMessage(role="user", content=run_ctx.user_message),
        ]
        model_policy = run_ctx.model_policy or {}
        primary = model_policy.get("primary", "stub-primary")
        fallback = model_policy.get("fallback")

        run = await self.session.get(Run, run_ctx.run_id)
        if run is not None:
            run.status = "RUNNING"
            run.started_at = datetime.utcnow()
            await self.session.commit()

        step_no = 0
        while step_no < run_ctx.max_steps:
            if (time.monotonic() - started) * 1000 > run_ctx.timeout_ms:
                result.status = "FAILED"
                result.error_code = "AC.RUN.TIMEOUT"
                break
            if result.token_input + result.token_output > run_ctx.token_budget:
                result.status = "FAILED"
                result.error_code = "AC.RUN.BUDGET_EXCEEDED"
                break

            step_no += 1
            request = LLMRequest(messages=messages, model=primary, response_format={"type": "json_object"})
            response = await self.router.complete(
                self.session,
                ctx,
                request,
                primary_model=primary,
                fallback_model=fallback,
                max_retries=int(model_policy.get("max_retries", 1)),
                run_id=run_ctx.run_id,
            )
            result.token_input += response.token_input
            result.token_output += response.token_output
            await self._record_step(ctx, run_ctx, step_no, "MODEL_RESPONSE", response.content[:2000])

            decision = parse_decision(response.content)
            if isinstance(decision, FinalDecision):
                await self._record_step(ctx, run_ctx, step_no, "FINAL_RESPONSE", decision.answer[:2000])
                result.status = "COMPLETED"
                result.answer = decision.answer
                break
            if isinstance(decision, ClarifyDecision):
                await self._record_step(ctx, run_ctx, step_no, "CLARIFICATION", decision.question[:2000])
                result.status = "WAITING_USER"
                result.question = decision.question
                break
            if isinstance(decision, ToolCallDecision):
                if decision.tool not in run_ctx.allowed_tools:
                    await self._record_step(
                        ctx, run_ctx, step_no, "TOOL_CALL", f"未授权工具: {decision.tool}", status="FAILED"
                    )
                    messages.append(
                        ChatMessage(role="user", content=f"工具 {decision.tool} 未被授权，请改用可用工具或直接回答。")
                    )
                    continue
                try:
                    tool_result = await invoke_tool(
                        self.session,
                        ctx,
                        self.tool_executor,
                        tool_code=decision.tool,
                        arguments=decision.arguments,
                        tool_context=ToolContext(
                            tenant_id=ctx.tenant_id,
                            user_id=ctx.user_id,
                            conversation_id=run_ctx.conversation_id,
                            run_id=run_ctx.run_id,
                            trace_id=run_ctx.trace_id,
                        ),
                        allow_write=False,
                    )
                except AppError as exc:
                    await self._record_step(
                        ctx, run_ctx, step_no, "TOOL_CALL", f"{decision.tool}: {exc.message}", status="FAILED"
                    )
                    messages.append(
                        ChatMessage(role="user", content=f"工具 {decision.tool} 调用失败：{exc.message}")
                    )
                    continue
                result.tool_calls += 1
                await self._record_step(
                    ctx,
                    run_ctx,
                    step_no,
                    "TOOL_RESULT",
                    json.dumps(tool_result.output, ensure_ascii=False)[:2000],
                    status=tool_result.status,
                )
                messages.append(
                    ChatMessage(
                        role="user",
                        content=(
                            "<tool_result untrusted=\"true\">"
                            + json.dumps(tool_result.output, ensure_ascii=False)
                            + "</tool_result>\n请基于工具结果继续推理。"
                        ),
                    )
                )
                continue
        else:
            result.status = "FAILED"
            result.error_code = "AC.RUN.STEP_BUDGET_EXCEEDED"

        result.steps = step_no
        await self._finish(ctx, run_ctx, result)
        return result

    async def _record_step(
        self,
        ctx: TenantContext,
        run_ctx: RunContext,
        step_no: int,
        step_type: str,
        summary: str,
        *,
        status: str = "SUCCESS",
    ) -> None:
        from app.domain.session.models import RunStep

        self.session.add(
            RunStep(
                tenant_id=ctx.tenant_id,
                run_id=run_ctx.run_id,
                step_no=step_no,
                step_type=step_type,
                status=status,
                output_summary=summary,
            )
        )
        await self.session.commit()

    async def _finish(self, ctx: TenantContext, run_ctx: RunContext, result: RuntimeResult) -> None:
        from app.domain.session.models import Run

        run = await self.session.get(Run, run_ctx.run_id)
        if run is not None:
            run.status = result.status if result.status != "RUNNING" else "FAILED"
            run.current_step = result.steps
            run.tool_call_count = result.tool_calls
            run.token_input = result.token_input
            run.token_output = result.token_output
            run.ended_at = datetime.utcnow()
            run.error_code = result.error_code
            await self.session.commit()
