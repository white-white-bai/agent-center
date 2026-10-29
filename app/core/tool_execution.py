import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, ValidationError
from app.core.tenant import TenantContext
from app.domain.safety.service import get_safety_service
from app.domain.tool.models import ToolDefinition
from app.domain.tool.service import get_tool, validate_arguments
from app.runtime.resilience import get_resilience


async def prepare_read_only_tool(
    session: AsyncSession,
    ctx: TenantContext,
    tool_code: str,
    arguments: dict,
) -> ToolDefinition:
    """校验只读工具并做限流/熔断检查，不执行也不写库。

    供 Fan-out 在并发执行前串行校验，避免并发写同一会话。
    """
    tool = await get_tool(session, ctx, tool_code)
    if tool.write_operation:
        raise ValidationError(f"写操作工具不能并行执行: {tool_code}")
    validate_arguments(tool.input_schema_json, arguments)

    argument_check = get_safety_service().check_local(
        json.dumps(arguments, ensure_ascii=False), "tool_arguments"
    )
    if not argument_check.allowed:
        raise ValidationError(f"工具参数未通过安全检查：{argument_check.reason}")

    resilience = get_resilience()
    limiter_key = f"{ctx.tenant_id}:{tool_code}"
    await resilience.check_rate(
        limiter_key,
        limit=int(tool.rate_limit_policy_json.get("limit", 0)),
        window_seconds=int(tool.rate_limit_policy_json.get("window_seconds", 60)),
    )
    await resilience.check_circuit(limiter_key)
    return tool


__all__ = ["prepare_read_only_tool", "AppError"]
