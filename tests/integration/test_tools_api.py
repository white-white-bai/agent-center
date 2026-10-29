ADMIN = {"X-Tenant-Id": "t1", "X-User-Id": "admin1", "X-Roles": "admin"}


def _register_echo_tool(client, *, write: bool = False) -> None:
    response = client.post(
        "/api/v1/admin/tools",
        json={
            "tool_code": "echo",
            "name": "回声工具",
            "input_schema": {
                "type": "object",
                "required": ["text"],
                "properties": {"text": {"type": "string"}},
            },
            "write_operation": write,
        },
        headers=ADMIN,
    )
    assert response.status_code == 200


def test_tool_test_endpoint(client) -> None:
    from app.domain.tool.executor import function_tool_executor

    async def handler(args: dict, ctx) -> dict:
        return {"echo": args["text"]}

    function_tool_executor.register("echo", handler)
    _register_echo_tool(client)

    response = client.post(
        "/api/v1/admin/tools/echo/test",
        json={"arguments": {"text": "hello"}},
        headers=ADMIN,
    )

    assert response.status_code == 200
    assert response.json()["data"]["output"] == {"echo": "hello"}


def test_tool_argument_validation_rejects_bad_payload(client) -> None:
    from app.domain.tool.executor import function_tool_executor

    async def handler(args: dict, ctx) -> dict:
        return {}

    function_tool_executor.register("echo", handler)
    _register_echo_tool(client)

    response = client.post(
        "/api/v1/admin/tools/echo/test",
        json={"arguments": {}},
        headers=ADMIN,
    )

    assert response.status_code == 422
    assert response.json()["code"] == "AC.COMMON.VALIDATION_FAILED"


def test_write_tool_requires_confirmation_before_execution(client) -> None:
    from app.domain.tool.executor import function_tool_executor

    async def handler(args: dict, ctx) -> dict:
        return {"ok": True}

    function_tool_executor.register("submit_form", handler)
    client.post(
        "/api/v1/admin/tools",
        json={"tool_code": "submit_form", "name": "提交表单", "write_operation": True},
        headers=ADMIN,
    )

    response = client.post(
        "/api/v1/admin/tools/submit_form/test",
        json={"arguments": {}},
        headers=ADMIN,
    )

    assert response.status_code == 422
    assert "确认" in response.json()["message"]


def test_unknown_tool_returns_404(client) -> None:
    response = client.post(
        "/api/v1/admin/tools/not_exist/test",
        json={"arguments": {}},
        headers=ADMIN,
    )

    assert response.status_code == 404
