import asyncio

import pytest

from app.domain.tool.executor import FunctionToolExecutor, ToolContext
from app.domain.tool.service import validate_arguments
from app.core.exceptions import ValidationError


async def test_function_executor_runs_registered_handler() -> None:
    executor = FunctionToolExecutor()

    async def handler(args: dict, ctx: ToolContext) -> dict:
        return {"echo": args["text"], "user": ctx.user_id}

    executor.register("echo", handler)
    result = await executor.execute(
        tool_code="echo",
        arguments={"text": "hi"},
        context=ToolContext(tenant_id="t1", user_id="u1"),
    )

    assert result.ok
    assert result.output == {"echo": "hi", "user": "u1"}


async def test_function_executor_reports_missing_handler() -> None:
    result = await FunctionToolExecutor().execute(
        tool_code="missing",
        arguments={},
        context=ToolContext(tenant_id="t1", user_id="u1"),
    )

    assert not result.ok
    assert result.error_code == "AC.TOOL.NOT_IMPLEMENTED"


async def test_function_executor_converts_exceptions() -> None:
    executor = FunctionToolExecutor()

    async def broken(args: dict, ctx: ToolContext) -> dict:
        raise RuntimeError("boom")

    executor.register("broken", broken)
    result = await executor.execute(
        tool_code="broken",
        arguments={},
        context=ToolContext(tenant_id="t1", user_id="u1"),
    )

    assert result.status == "FAILED"
    assert result.error_code == "AC.TOOL.EXECUTION_FAILED"
    assert "boom" in (result.error_message or "")


def test_validate_arguments_accepts_valid_payload() -> None:
    validate_arguments({"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}}, {"a": "x"})


def test_validate_arguments_rejects_invalid_payload() -> None:
    with pytest.raises(ValidationError):
        validate_arguments({"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}}, {})
