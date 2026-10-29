import json
from dataclasses import replace

import jsonschema
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.core.tenant import TenantContext
from app.domain.tool import idempotency
from app.domain.tool.executor import ToolContext, ToolExecutor, ToolResult
from app.domain.tool.idempotency import build_idempotency_key
from app.domain.tool.models import ToolDefinition, ToolIdempotencyRecord, ToolInvokeLog
from app.runtime.resilience import get_resilience


async def _load_idempotency_record(
    session: AsyncSession, ctx: TenantContext, tool_code: str, idempotency_key: str
) -> ToolIdempotencyRecord | None:
    result = await session.execute(
        select(ToolIdempotencyRecord).where(
            ToolIdempotencyRecord.tenant_id == ctx.tenant_id,
            ToolIdempotencyRecord.tool_code == tool_code,
            ToolIdempotencyRecord.idempotency_key == idempotency_key,
        )
    )
    return result.scalar_one_or_none()


def _resolve_executor(tool: ToolDefinition, default: ToolExecutor) -> ToolExecutor:
    if tool.source_type in {"HTTP", "OPENAPI"} and tool.endpoint:
        from app.integrations.http_tool import HTTPToolExecutor

        return HTTPToolExecutor(
            tool.endpoint,
            method=(tool.auth_policy_json or {}).get("method", "POST"),
            headers=(tool.auth_policy_json or {}).get("headers") or {},
            timeout_ms=tool.timeout_ms,
        )
    return default


def validate_arguments(schema: dict, arguments: dict) -> None:
    if not schema:
        return
    try:
        jsonschema.validate(instance=arguments, schema=schema)
    except jsonschema.ValidationError as exc:
        raise ValidationError(f"工具参数校验失败: {exc.message}") from exc


async def create_tool(
    session: AsyncSession,
    ctx: TenantContext,
    *,
    tool_code: str,
    name: str,
    description: str | None,
    source_type: str,
    input_schema: dict,
    output_schema: dict | None = None,
    timeout_ms: int = 5000,
    write_operation: bool = False,
    require_confirmation: bool = False,
    idempotent: bool = False,
    endpoint: str | None = None,
    rate_limit_policy: dict | None = None,
    auth_policy: dict | None = None,
) -> ToolDefinition:
    tool = ToolDefinition(
        tenant_id=ctx.tenant_id,
        tool_code=tool_code,
        name=name,
        description=description,
        source_type=source_type,
        endpoint=endpoint,
        input_schema_json=input_schema,
        output_schema_json=output_schema or {},
        timeout_ms=timeout_ms,
        auth_policy_json=auth_policy or {},
        rate_limit_policy_json=rate_limit_policy or {},
        write_operation=write_operation,
        require_confirmation=require_confirmation or write_operation,
        idempotent=idempotent,
    )
    session.add(tool)
    await session.commit()
    await session.refresh(tool)
    return tool


async def get_tool(session: AsyncSession, ctx: TenantContext, tool_code: str) -> ToolDefinition:
    result = await session.execute(
        select(ToolDefinition)
        .where(ToolDefinition.tenant_id == ctx.tenant_id, ToolDefinition.tool_code == tool_code)
        .order_by(ToolDefinition.version_no.desc())
        .limit(1)
    )
    tool = result.scalar_one_or_none()
    if tool is None:
        raise NotFoundError(f"工具不存在: {tool_code}")
    if tool.status != "ENABLED":
        raise ValidationError(f"工具已禁用: {tool_code}")
    return tool


async def invoke_tool(
    session: AsyncSession,
    ctx: TenantContext,
    executor: ToolExecutor,
    *,
    tool_code: str,
    arguments: dict,
    tool_context: ToolContext,
    allow_write: bool = False,
) -> ToolResult:
    tool = await get_tool(session, ctx, tool_code)
    if tool.write_operation and not allow_write:
        raise ValidationError("写操作工具必须经过用户确认后才能执行")
    validate_arguments(tool.input_schema_json, arguments)

    from app.domain.safety.service import get_safety_service

    argument_check = get_safety_service().check_local(
        json.dumps(arguments, ensure_ascii=False), "tool_arguments"
    )
    if not argument_check.allowed:
        raise ValidationError(f"工具参数未通过安全检查：{argument_check.reason}")

    executor = _resolve_executor(tool, executor)

    limiter_key = f"{ctx.tenant_id}:{tool_code}"
    resilience = get_resilience()
    await resilience.check_rate(
        limiter_key,
        limit=int(tool.rate_limit_policy_json.get("limit", 0)),
        window_seconds=int(tool.rate_limit_policy_json.get("window_seconds", 60)),
    )
    await resilience.check_circuit(limiter_key)

    if tool.write_operation and tool.idempotent:
        key = tool_context.idempotency_key or build_idempotency_key(
            tool_context.run_id, tool_code, arguments
        )
        completed = await idempotency.begin(
            session, ctx, tool_code=tool_code, idempotency_key=key, arguments=arguments
        )
        if completed is not None:
            return ToolResult(status="SUCCESS", output=completed.response_json or {}, cached=True)
        tool_context = replace(tool_context, idempotency_key=key)

    result = await executor.execute(tool_code=tool_code, arguments=arguments, context=tool_context)
    await resilience.record(limiter_key, success=result.ok)

    from app.core.redaction import redact

    safe_arguments = redact(arguments)
    safe_summary = redact(str(result.output))[:2000] if result.output else result.error_message

    if tool.write_operation and tool.idempotent:
        record = await _load_idempotency_record(session, ctx, tool_code, tool_context.idempotency_key or "")
        if record is not None:
            if result.ok:
                await idempotency.complete(session, record, response=result.output)
            else:
                await idempotency.fail(
                    session, ctx, tool_code=tool_code, idempotency_key=tool_context.idempotency_key or ""
                )

    session.add(
        ToolInvokeLog(
            tenant_id=ctx.tenant_id,
            run_id=tool_context.run_id,
            tool_code=tool_code,
            user_id=ctx.user_id,
            status=result.status,
            arguments_json=safe_arguments,
            result_summary=safe_summary,
            error_code=result.error_code,
            duration_ms=result.duration_ms,
            idempotency_key=tool_context.idempotency_key,
        )
    )
    await session.commit()
    return result
