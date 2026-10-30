import asyncio
import shlex
from typing import Any

import httpx

from app.domain.tool.executor import ToolContext, ToolResult
from app.integrations.mcp.transports import (
    HTTPTransport,
    MCPError,
    SSETransport,
    StdioTransport,
)

__all__ = ["MCPClient", "MCPToolExecutor", "MCPError"]


class MCPClient:
    """MCP 客户端，支持 HTTP、SSE、stdio 三种传输。"""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        headers: dict[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 10.0,
        mcp_transport=None,
    ) -> None:
        if mcp_transport is None:
            if not base_url:
                raise MCPError("HTTP MCP 需要 base_url")
            mcp_transport = HTTPTransport(
                base_url,
                headers=headers,
                timeout=timeout,
                httpx_transport=transport,
            )
        self._transport = mcp_transport
        self.timeout = timeout
        self._request_id = 0

    @classmethod
    def from_config(cls, config: dict[str, Any], *, timeout: float = 10.0) -> "MCPClient":
        kind = str(config.get("transport") or "http").lower()
        if kind == "stdio":
            command = config.get("command") or []
            if isinstance(command, str):
                command = shlex.split(command)
            return cls(
                mcp_transport=StdioTransport(
                    [str(item) for item in command],
                    env=config.get("env") or {},
                    cwd=config.get("cwd"),
                    timeout=timeout,
                ),
                timeout=timeout,
            )
        url = config.get("url") or config.get("base_url")
        if not url:
            raise MCPError("MCP 配置缺少 url")
        headers = config.get("headers") or {}
        httpx_transport = config.get("httpx_transport")
        if kind == "sse":
            return cls(
                mcp_transport=SSETransport(
                    str(url),
                    headers=headers,
                    timeout=timeout,
                    httpx_transport=httpx_transport,
                ),
                timeout=timeout,
            )
        return cls(
            str(url),
            headers=headers,
            timeout=timeout,
            transport=httpx_transport,
        )

    async def close(self) -> None:
        await self._transport.close()

    async def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._request_id += 1
        payload = {"jsonrpc": "2.0", "id": self._request_id, "method": method, "params": params}
        body = await asyncio.wait_for(self._transport.request(payload), self.timeout + 1)
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
        except asyncio.TimeoutError:
            return ToolResult(status="TIMEOUT", error_code="AC.MCP.TIMEOUT", error_message="MCP 调用超时")
        return ToolResult(status="SUCCESS", output=output)

    async def aclose(self) -> None:
        await self.client.close()
