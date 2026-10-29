import json

import httpx

from app.domain.tool.executor import ToolContext
from app.integrations.mcp.client import MCPClient, MCPToolExecutor


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


async def test_mcp_list_tools_and_call() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen.append(payload)
        if payload["method"] == "tools/list":
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": payload["id"], "result": {"tools": [{"name": "search"}]}},
            )
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": payload["id"], "result": {"content": [{"text": "ok"}]}},
        )

    client = MCPClient("http://mcp.local", transport=_transport(handler))
    tools = await client.list_tools()
    result = await client.call_tool("search", {"q": "政策"})
    await client.close()

    assert tools == [{"name": "search"}]
    assert result == {"content": [{"text": "ok"}]}
    assert seen[1]["params"] == {"name": "search", "arguments": {"q": "政策"}}


async def test_mcp_executor_returns_tool_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": payload["id"], "result": {"content": [{"text": "结果"}]}},
        )

    executor = MCPToolExecutor(MCPClient("http://mcp.local", transport=_transport(handler)))
    result = await executor.execute(
        tool_code="search", arguments={"q": "x"}, context=ToolContext(tenant_id="t1", user_id="u1")
    )

    assert result.ok
    assert result.output["content"][0]["text"] == "结果"


async def test_mcp_executor_maps_rpc_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": payload["id"], "error": {"message": "工具不存在"}},
        )

    executor = MCPToolExecutor(MCPClient("http://mcp.local", transport=_transport(handler)))
    result = await executor.execute(
        tool_code="missing", arguments={}, context=ToolContext(tenant_id="t1", user_id="u1")
    )

    assert result.status == "FAILED"
    assert result.error_code == "AC.MCP.ERROR"
    assert "工具不存在" in (result.error_message or "")
