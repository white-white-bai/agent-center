from typing import Any

import httpx

from app.domain.tool.executor import ToolContext, ToolResult


class HTTPToolExecutor:
    """调用现有业务 HTTP 接口的工具执行器。"""

    def __init__(
        self,
        endpoint: str,
        *,
        method: str = "POST",
        headers: dict[str, str] | None = None,
        timeout_ms: int = 5000,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.method = method.upper()
        self.headers = headers or {}
        self.timeout_ms = timeout_ms
        self._transport = transport

    async def execute(self, *, tool_code: str, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        if context.dry_run:
            return ToolResult(status="SUCCESS", output={"dryRun": True, "endpoint": self.endpoint})

        headers = {
            **self.headers,
            "X-User-Id": context.user_id,
            "X-Tenant-Id": context.tenant_id,
        }
        if context.idempotency_key:
            headers["Idempotency-Key"] = context.idempotency_key
        if context.trace_id:
            headers["X-Trace-Id"] = context.trace_id

        async with httpx.AsyncClient(timeout=self.timeout_ms / 1000, transport=self._transport) as client:
            try:
                response = await client.request(self.method, self.endpoint, json=arguments, headers=headers)
            except httpx.TimeoutException:
                return ToolResult(status="TIMEOUT", error_code="AC.TOOL.TIMEOUT", error_message="HTTP 工具超时")
            except httpx.HTTPError as exc:
                return ToolResult(
                    status="FAILED", error_code="AC.TOOL.NETWORK", error_message=str(exc)
                )

        if response.status_code >= 400:
            return ToolResult(
                status="FAILED",
                error_code="AC.TOOL.HTTP_ERROR",
                error_message=f"HTTP {response.status_code}: {response.text[:500]}",
            )
        try:
            output = response.json()
        except ValueError:
            output = {"raw": response.text}
        if not isinstance(output, dict):
            output = {"data": output}
        return ToolResult(status="SUCCESS", output=output)
