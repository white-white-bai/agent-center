from typing import Any

import httpx

from app.core.config import get_settings
from app.domain.tool.executor import ToolContext, function_tool_executor

CHATFLOW_TOOL_CODE = "dify.chatflow.invoke"
CHATFLOW_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "用户问题"},
        "inputs": {"type": "object", "description": "Dify 应用输入变量"},
        "conversation_id": {"type": "string", "description": "Dify 会话 ID，可选"},
        "user": {"type": "string", "description": "Dify 用户标识，可选"},
    },
    "required": ["query"],
}


class DifyError(Exception):
    pass


async def invoke_chatflow(
    query: str,
    *,
    inputs: dict[str, Any] | None = None,
    conversation_id: str | None = None,
    user: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    timeout_ms: int | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    base = (base_url or settings.dify_base_url).rstrip("/")
    key = api_key or settings.dify_chatflow_api_key
    timeout = (timeout_ms or settings.dify_chatflow_timeout_ms) / 1000
    if not query:
        raise DifyError("缺少 query")
    if not base or not key:
        raise DifyError("未配置 Dify 地址或 Chatflow API Key")

    payload = {
        "inputs": inputs or {},
        "query": query,
        "response_mode": "blocking",
        "conversation_id": conversation_id or "",
        "user": user or "agent-center",
    }
    async with httpx.AsyncClient(
        base_url=base,
        headers={"Authorization": f"Bearer {key}"},
        timeout=timeout,
        transport=transport,
    ) as client:
        response = await client.post("/v1/chat-messages", json=payload)
        response.raise_for_status()
        body = response.json()
    if not isinstance(body, dict):
        raise DifyError("Dify 返回格式异常")
    return {
        "answer": body.get("answer") or "",
        "conversationId": body.get("conversation_id"),
        "messageId": body.get("message_id"),
        "metadata": body.get("metadata") or {},
    }


async def _chatflow_handler(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    return await invoke_chatflow(
        str(arguments.get("query") or ""),
        inputs=arguments.get("inputs") if isinstance(arguments.get("inputs"), dict) else {},
        conversation_id=arguments.get("conversation_id"),
        user=arguments.get("user") or context.user_id,
    )


def register_dify_tool() -> None:
    function_tool_executor.register(CHATFLOW_TOOL_CODE, _chatflow_handler)
