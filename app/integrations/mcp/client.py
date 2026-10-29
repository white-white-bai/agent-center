from typing import Any

import httpx

from app.domain.tool.executor import ToolContext, ToolResult


class MCPError(Exception):
    pass


class MCPClient:
    """最小 MCP 客户端，基于 JSON-RPC over HTTP。

    stdio 传输需要在独立进程中运行，首期仅支持远程 HTTP 接入。
    """

    def __init__(
        self,
        base_url: str,
        *,
        headers: dict[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = headers or {}
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self.headers,
            transport=transport,
            timeout=timeout,
        )
        self._request_id = 0

    async def close(self) -> None:
        await self._client.aclose()

    async def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._request_id += 1
        payload = {"jsonrpc": "2.0", "id": self._request_id, "method": method, "params": params}
        response = await self._client.post("", json=payload)
        response.raise_for_status()
        body = response.json()
        if "error" in body:
            raise MCPError(body["error"].get("message", "MCP 调用失败"))
        return body.get("result") or {}

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self._rpc("tools/list", {})
        return list(result.get("tools") or [])

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await self._rpc("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise MCPError(result.get("error") or "MCP 工具执行失败")
        return result


class MCPToolExecutor:
    """将 MCP 工具适配为统一 ToolExecutor 协议。"""

    def __init__(self, client: MCPClient) -> None:
        self.client = client

    async def execute(self, *, tool_code: str, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            output = await self.client.call_tool(tool_code, arguments)
        except MCPError as exc:
            return ToolResult(status="FAILED", error_code="AC.MCP.ERROR", error_message=str(exc))
        except httpx.HTTPError as exc:
            return ToolResult(status="FAILED", error_code="AC.MCP.NETWORK", error_message=str(exc))
        return ToolResult(status="SUCCESS", output=output)
