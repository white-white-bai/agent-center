import json

import httpx

from app.domain.tool.executor import ToolContext
from app.integrations.http_tool import HTTPToolExecutor
from app.integrations.openapi import parse_openapi


async def test_http_executor_posts_arguments_and_returns_json() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={"status": "已受理"})

    executor = HTTPToolExecutor("http://biz.local/matters/status", transport=httpx.MockTransport(handler))
    result = await executor.execute(
        tool_code="matter.status.query",
        arguments={"application_number": "A1"},
        context=ToolContext(
            tenant_id="t1", user_id="u1", trace_id="trace_1", idempotency_key="idem_1"
        ),
    )

    assert result.ok
    assert result.output == {"status": "已受理"}
    assert captured["body"] == {"application_number": "A1"}
    assert captured["headers"]["x-user-id"] == "u1"
    assert captured["headers"]["idempotency-key"] == "idem_1"


async def test_http_executor_maps_error_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    executor = HTTPToolExecutor("http://biz.local/x", transport=httpx.MockTransport(handler))
    result = await executor.execute(
        tool_code="x", arguments={}, context=ToolContext(tenant_id="t1", user_id="u1")
    )

    assert result.status == "FAILED"
    assert result.error_code == "AC.TOOL.HTTP_ERROR"


async def test_http_executor_dry_run_skips_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - 不应被调用
        raise AssertionError("dry run 不应发起请求")

    executor = HTTPToolExecutor("http://biz.local/x", transport=httpx.MockTransport(handler))
    result = await executor.execute(
        tool_code="x",
        arguments={},
        context=ToolContext(tenant_id="t1", user_id="u1", dry_run=True),
    )

    assert result.ok
    assert result.output["dryRun"] is True


def test_parse_openapi_generates_tools() -> None:
    spec = {
        "paths": {
            "/matters/status": {
                "get": {
                    "operationId": "matter.status.query",
                    "summary": "查询办理进度",
                    "parameters": [
                        {"name": "application_number", "in": "query", "required": True, "schema": {"type": "string"}}
                    ],
                }
            },
            "/matters/submit": {
                "post": {
                    "summary": "提交申请",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["matter_type"],
                                    "properties": {"matter_type": {"type": "string"}},
                                }
                            }
                        }
                    },
                }
            },
        }
    }

    tools = parse_openapi(spec)

    assert len(tools) == 2
    query_tool = next(tool for tool in tools if tool["tool_code"] == "matter.status.query")
    assert query_tool["input_schema"]["required"] == ["application_number"]
    assert query_tool["write_operation"] is False

    submit_tool = next(tool for tool in tools if tool["tool_code"] == "post.matters.submit")
    assert submit_tool["write_operation"] is True
    assert submit_tool["input_schema"]["required"] == ["matter_type"]
