import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolContext:
    tenant_id: str
    user_id: str
    conversation_id: int | None = None
    run_id: str | None = None
    trace_id: str | None = None
    idempotency_key: str | None = None
    deadline_ms: int | None = None
    dry_run: bool = False


@dataclass
class ToolResult:
    status: str
    output: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    duration_ms: int = 0
    cached: bool = False

    @property
    def ok(self) -> bool:
        return self.status == "SUCCESS"


class ToolExecutor(Protocol):
    async def execute(self, *, tool_code: str, arguments: dict[str, Any], context: ToolContext) -> ToolResult: ...


FunctionHandler = Callable[[dict[str, Any], ToolContext], Awaitable[dict[str, Any]]]


class FunctionToolExecutor:
    """进程内函数工具执行器，对应详细设计中的 Function Call 来源。"""

    def __init__(self) -> None:
        self._handlers: dict[str, FunctionHandler] = {}

    def register(self, tool_code: str, handler: FunctionHandler) -> None:
        self._handlers[tool_code] = handler

    def has(self, tool_code: str) -> bool:
        return tool_code in self._handlers

    async def execute(self, *, tool_code: str, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        started = time.perf_counter()
        handler = self._handlers.get(tool_code)
        if handler is None:
            return ToolResult(
                status="FAILED",
                error_code="AC.TOOL.NOT_IMPLEMENTED",
                error_message=f"工具未注册执行器: {tool_code}",
            )
        try:
            output = await handler(arguments, context)
        except asyncio.TimeoutError:
            return ToolResult(
                status="TIMEOUT",
                error_code="AC.TOOL.TIMEOUT",
                error_message="工具调用超时",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:  # noqa: BLE001 - 执行失败统一收敛为工具错误
            return ToolResult(
                status="FAILED",
                error_code="AC.TOOL.EXECUTION_FAILED",
                error_message=str(exc),
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        return ToolResult(
            status="SUCCESS",
            output=output,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )


function_tool_executor = FunctionToolExecutor()
