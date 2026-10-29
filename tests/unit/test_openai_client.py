import json

import httpx

from app.integrations.llm.client import ChatMessage, LLMRequest
from app.integrations.llm.openai_client import HashEmbeddingClient, OpenAICompatibleClient


def _sse(lines: list[str]) -> bytes:
    return ("\n".join(lines) + "\n").encode()


async def test_openai_client_complete_parses_response() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "deepseek-test",
                "choices": [{"message": {"content": "你好"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            },
        )

    client = OpenAICompatibleClient(
        base_url="https://llm.local/v1",
        api_key="sk-test",
        transport=httpx.MockTransport(handler),
    )
    response = await client.complete(
        LLMRequest(messages=[ChatMessage(role="user", content="hi")], model="deepseek-test")
    )

    assert response.content == "你好"
    assert response.token_input == 12
    assert captured["url"] == "https://llm.local/v1/chat/completions"
    assert captured["auth"] == "Bearer sk-test"
    assert captured["body"]["model"] == "deepseek-test"


async def test_openai_client_stream_yields_deltas() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse(
                [
                    'data: {"choices":[{"delta":{"content":"你"}}]}',
                    'data: {"choices":[{"delta":{"content":"好"}}]}',
                    "data: [DONE]",
                ]
            ),
        )

    client = OpenAICompatibleClient(
        base_url="https://llm.local/v1", api_key="sk-test", transport=httpx.MockTransport(handler)
    )
    chunks = [
        chunk
        async for chunk in client.stream(
            LLMRequest(messages=[ChatMessage(role="user", content="hi")], model="m")
        )
    ]

    assert "".join(chunks) == "你好"


async def test_openai_client_maps_http_error() -> None:
    import pytest

    from app.integrations.llm.client import ModelUnavailable

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = OpenAICompatibleClient(
        base_url="https://llm.local/v1", api_key="sk-test", transport=httpx.MockTransport(handler)
    )

    with pytest.raises(ModelUnavailable):
        await client.complete(LLMRequest(messages=[], model="m"))


async def test_hash_embedding_is_normalized_and_deterministic() -> None:
    client = HashEmbeddingClient(dim=16)
    first = (await client.embed(["营业执照办理"]))[0]
    second = (await client.embed(["营业执照办理"]))[0]

    assert first == second
    assert abs(sum(value * value for value in first) ** 0.5 - 1.0) < 1e-6
