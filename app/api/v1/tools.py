from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import CurrentTenant, DbSession
from app.core.responses import ok
from app.core.tenant import require_admin
from app.domain.tool import service

router = APIRouter(prefix="/admin/tools", tags=["tools"], dependencies=[Depends(require_admin)])


class CreateToolRequest(BaseModel):
    tool_code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    source_type: str = Field(default="FUNCTION", max_length=20)
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)
    endpoint: str | None = None
    timeout_ms: int = Field(default=5000, ge=100, le=60000)
    write_operation: bool = False
    idempotent: bool = False
    rate_limit_policy: dict = Field(default_factory=dict)
    headers: dict = Field(default_factory=dict)
    method: str = Field(default="POST", max_length=10)


class TestToolRequest(BaseModel):
    arguments: dict = Field(default_factory=dict)


def _serialize_tool(tool) -> dict:
    return {
        "id": tool.id,
        "toolCode": tool.tool_code,
        "name": tool.name,
        "description": tool.description,
        "sourceType": tool.source_type,
        "inputSchema": tool.input_schema_json,
        "writeOperation": tool.write_operation,
        "requireConfirmation": tool.require_confirmation,
        "idempotent": tool.idempotent,
        "timeoutMs": tool.timeout_ms,
        "status": tool.status,
    }


@router.post("")
async def create_tool(payload: CreateToolRequest, session: DbSession, ctx: CurrentTenant) -> dict:
    from app.domain.evaluation import audit

    tool = await service.create_tool(
        session,
        ctx,
        tool_code=payload.tool_code,
        name=payload.name,
        description=payload.description,
        source_type=payload.source_type,
        input_schema=payload.input_schema,
        output_schema=payload.output_schema,
        timeout_ms=payload.timeout_ms,
        write_operation=payload.write_operation,
        idempotent=payload.idempotent,
        endpoint=payload.endpoint,
        rate_limit_policy=payload.rate_limit_policy,
        auth_policy={"method": payload.method.upper(), "headers": payload.headers},
    )
    await audit.record_audit(
        session,
        ctx,
        action="tool.create",
        resource_type="tool",
        resource_id=tool.tool_code,
        detail={"writeOperation": tool.write_operation},
    )
    return ok(_serialize_tool(tool))


@router.post("/{tool_code}/test")
async def test_tool(tool_code: str, payload: TestToolRequest, session: DbSession, ctx: CurrentTenant) -> dict:
    from app.domain.tool.executor import ToolContext, function_tool_executor

    result = await service.invoke_tool(
        session,
        ctx,
        function_tool_executor,
        tool_code=tool_code,
        arguments=payload.arguments,
        tool_context=ToolContext(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            dry_run=True,
        ),
        allow_write=False,
    )
    return ok(
        {
            "status": result.status,
            "output": result.output,
            "errorCode": result.error_code,
            "durationMs": result.duration_ms,
        }
    )
