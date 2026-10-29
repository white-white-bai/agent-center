from app.core.tenant import TenantContext
from app.domain.tool import credentials, service
from app.domain.tool.executor import FunctionToolExecutor

CTX = TenantContext(tenant_id="t1", user_id="u1")


async def test_http_executor_uses_encrypted_credential(db_session) -> None:
    tool = await service.create_tool(
        db_session,
        CTX,
        tool_code="secure.http",
        name="安全接口",
        description=None,
        source_type="HTTP",
        input_schema={},
        endpoint="http://biz.local/secure",
        auth_policy={
            "method": "POST",
            "headers": {"X-Static": "static-value"},
            "credential_map": {"X-Api-Key": "api_key"},
        },
    )
    await credentials.save_credential(
        db_session, CTX, tool_code="secure.http", name="api_key", value="sk-secret"
    )

    executor = await service._resolve_executor(db_session, CTX, tool, FunctionToolExecutor())

    assert executor.headers["X-Api-Key"] == "sk-secret"
    assert executor.headers["X-Static"] == "static-value"


async def test_missing_credential_is_skipped(db_session) -> None:
    tool = await service.create_tool(
        db_session,
        CTX,
        tool_code="missing.http",
        name="缺凭证",
        description=None,
        source_type="HTTP",
        input_schema={},
        endpoint="http://biz.local/x",
        auth_policy={"credential_map": {"X-Api-Key": "not_exist"}},
    )

    executor = await service._resolve_executor(db_session, CTX, tool, FunctionToolExecutor())

    assert "X-Api-Key" not in executor.headers


async def test_function_tool_keeps_default_executor(db_session) -> None:
    tool = await service.create_tool(
        db_session,
        CTX,
        tool_code="fn.tool",
        name="函数工具",
        description=None,
        source_type="FUNCTION",
        input_schema={},
    )
    default = FunctionToolExecutor()

    executor = await service._resolve_executor(db_session, CTX, tool, default)

    assert executor is default
