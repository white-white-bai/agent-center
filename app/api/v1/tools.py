from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import CurrentTenant, DbSession
from app.core.exceptions import MCPUnavailableError, ValidationError
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


class CredentialRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1)


class ImportOpenApiRequest(BaseModel):
    spec: dict = Field(default_factory=dict)
    base_url: str | None = Field(default=None, max_length=500)
    auto_register: bool = False


class ImportMCPRequest(BaseModel):
    transport: str = Field(default="http", max_length=20)
    url: str | None = Field(default=None, max_length=500)
    command: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    tool_prefix: str | None = Field(default=None, max_length=50)
    write_operation: bool = False
    auto_register: bool = False
    timeout_ms: int = Field(default=10000, ge=1000, le=60000)


def _mcp_config(payload: ImportMCPRequest) -> dict:
    transport = payload.transport.lower()
    if transport not in {"http", "sse", "stdio"}:
        raise ValidationError("MCP transport 仅支持 http、sse、stdio")
    if transport in {"http", "sse"} and not payload.url:
        raise ValidationError("HTTP/SSE 传输必须提供 url")
    if transport == "stdio" and not payload.command:
        raise ValidationError("stdio 传输必须提供 command")
    config: dict = {"transport": transport}
    if payload.url:
        config["url"] = payload.url
    if payload.command:
        config["command"] = payload.command
    if payload.env:
        config["env"] = payload.env
    if payload.headers:
        config["headers"] = payload.headers
    return config


@router.post("/import-mcp")
async def import_mcp(payload: ImportMCPRequest, session: DbSession, ctx: CurrentTenant) -> dict:
    import asyncio

    from app.integrations.mcp.client import MCPClient, MCPError

    config = _mcp_config(payload)
    prefix = (payload.tool_prefix or "").strip()
    client = MCPClient.from_config(config, timeout=payload.timeout_ms / 1000)
    try:
        remote_tools = await client.list_tools()
    except (MCPError, OSError, asyncio.TimeoutError) as exc:
        raise MCPUnavailableError(f"MCP 工具列表获取失败: {exc}") from exc
    finally:
        await client.close()

    preview = []
    for remote in remote_tools:
        name = str(remote.get("name") or "").strip()
        if not name:
            continue
        tool_code = f"{prefix}{name}"
        annotations = remote.get("annotations") or {}
        write_operation = payload.write_operation or annotations.get("readOnlyHint") is False
        preview.append(
            {
                "toolCode": tool_code,
                "name": remote.get("title") or name,
                "description": remote.get("description"),
                "inputSchema": remote.get("inputSchema") or remote.get("input_schema") or {},
                "writeOperation": write_operation,
            }
        )

    created: list[str] = []
    skipped: list[str] = []
    if payload.auto_register:
        for item in preview:
            if len(item["toolCode"]) > 100:
                raise ValidationError(f"MCP 工具编码过长: {item['toolCode']}")
            existing = await service.find_tool(session, ctx, item["toolCode"])
            if existing is not None:
                skipped.append(item["toolCode"])
                continue
            await service.create_tool(
                session,
                ctx,
                tool_code=item["toolCode"],
                name=item["name"],
                description=item["description"],
                source_type="MCP",
                input_schema=item["inputSchema"],
                write_operation=item["writeOperation"],
                endpoint=payload.url,
                auth_policy=config,
            )
            created.append(item["toolCode"])

    from app.domain.evaluation import audit

    await audit.record_audit(
        session,
        ctx,
        action="tool.import_mcp",
        resource_type="tool",
        detail={
            "transport": config["transport"],
            "total": len(preview),
            "created": created,
            "skipped": skipped,
        },
    )
    return ok(
        {
            "total": len(preview),
            "created": created,
            "skipped": skipped,
            "preview": preview,
        }
    )


@router.post("/import-openapi")
async def import_openapi(payload: ImportOpenApiRequest, session: DbSession, ctx: CurrentTenant) -> dict:
    from app.integrations.openapi import parse_openapi

    parsed = parse_openapi(payload.spec)
    from app.domain.evaluation import audit

    if not parsed:
        return ok({"total": 0, "created": [], "skipped": [], "preview": []})

    created: list[str] = []
    skipped: list[str] = []
    if payload.auto_register:
        for item in parsed:
            existing = await service.find_tool(session, ctx, item["tool_code"])
            if existing is not None:
                skipped.append(item["tool_code"])
                continue
            endpoint = item["endpoint"]
            if payload.base_url:
                endpoint = payload.base_url.rstrip("/") + endpoint
            await service.create_tool(
                session,
                ctx,
                tool_code=item["tool_code"],
                name=item["name"],
                description=item.get("description"),
                source_type="OPENAPI",
                input_schema=item["input_schema"],
                write_operation=item["write_operation"],
                endpoint=endpoint,
                auth_policy={"method": item["method"].upper()},
            )
            created.append(item["tool_code"])

    await audit.record_audit(
        session,
        ctx,
        action="tool.import_openapi",
        resource_type="tool",
        detail={"total": len(parsed), "created": created, "skipped": skipped},
    )
    return ok(
        {
            "total": len(parsed),
            "created": created,
            "skipped": skipped,
            "preview": [
                {
                    "toolCode": item["tool_code"],
                    "name": item["name"],
                    "method": item["method"].upper(),
                    "endpoint": item["endpoint"],
                    "writeOperation": item["write_operation"],
                    "inputSchema": item["input_schema"],
                }
                for item in parsed
            ],
        }
    )


@router.post("/{tool_code}/credentials")
async def save_credential(
    tool_code: str, payload: CredentialRequest, session: DbSession, ctx: CurrentTenant
) -> dict:
    from app.domain.tool import credentials

    from app.domain.evaluation import audit

    record = await credentials.save_credential(
        session, ctx, tool_code=tool_code, name=payload.name, value=payload.value
    )
    await audit.record_audit(
        session,
        ctx,
        action="tool.credential.save",
        resource_type="tool_credential",
        resource_id=record.id,
        detail={"toolCode": tool_code, "name": record.name},
    )
    return ok({"id": record.id, "name": record.name, "keyVersion": record.key_version})


@router.get("/{tool_code}/credentials")
async def list_credentials(tool_code: str, session: DbSession, ctx: CurrentTenant) -> dict:
    from app.domain.tool import credentials

    records = await credentials.list_credentials(session, ctx, tool_code)
    return ok(
        [{"id": record.id, "name": record.name, "keyVersion": record.key_version} for record in records]
    )


@router.delete("/{tool_code}/credentials/{credential_id}")
async def delete_credential(
    tool_code: str, credential_id: int, session: DbSession, ctx: CurrentTenant
) -> dict:
    from app.domain.tool import credentials

    from app.domain.evaluation import audit

    await credentials.delete_credential(session, ctx, credential_id)
    await audit.record_audit(
        session,
        ctx,
        action="tool.credential.delete",
        resource_type="tool_credential",
        resource_id=credential_id,
        detail={"toolCode": tool_code},
    )
    return ok({"deleted": True})


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
