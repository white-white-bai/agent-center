import json

import httpx
import pytest

from app.integrations.dify import DifyError, invoke_chatflow


async def test_chatflow_invocation_payload_and_mapping() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        seen["path"] = request.url.path
        seen["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "answer": "Dify 回答",
                "conversation_id": "conv-1",
                "message_id": "msg-1",
                "metadata": {"usage": 3},
            },
        )

    result = await invoke_chatflow(
        "你好",
        inputs={"city": "常州"},
        conversation_id="conv-1",
        user="u1",
        base_url="https://dify.local",
        api_key="app-key",
        transport=httpx.MockTransport(handler),
    )

    assert result["answer"] == "Dify 回答"
    assert result["conversationId"] == "conv-1"
    assert result["messageId"] == "msg-1"
    assert seen["auth"] == "Bearer app-key"
    assert seen["path"] == "/v1/chat-messages"
    assert seen["payload"]["query"] == "你好"
    assert seen["payload"]["inputs"] == {"city": "常州"}
    assert seen["payload"]["response_mode"] == "blocking"


async def test_chatflow_requires_query_and_configuration() -> None:
    with pytest.raises(DifyError):
        await invoke_chatflow("", base_url="https://dify.local", api_key="k")
    with pytest.raises(DifyError):
        await invoke_chatflow("你好", base_url="", api_key="")


async def test_chatflow_http_error_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "boom"})

    with pytest.raises(httpx.HTTPError):
        await invoke_chatflow(
            "你好",
            base_url="https://dify.local",
            api_key="k",
            transport=httpx.MockTransport(handler),
        )
