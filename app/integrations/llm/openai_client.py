from collections.abc import AsyncIterator

import httpx

from app.core.config import get_settings
from app.integrations.llm.client import (
    ChatMessage,
    LLMClient,
    LLMRequest,
    LLMResponse,
    ModelUnavailable,
)


class OpenAICompatibleClient:
    """OpenAI 兼容 /chat/completions 客户端，支持流式与用量。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not base_url:
            raise ValueError("缺少 LLM base_url")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._transport = transport
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @staticmethod
    def _payload(request: LLMRequest, *, stream: bool) -> dict:
        payload: dict = {
            "model": request.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "temperature": request.temperature,
            "stream": stream,
        }
        if request.response_format:
            payload["response_format"] = request.response_format
        return payload

    async def complete(self, request: LLMRequest) -> LLMResponse:
        async with httpx.AsyncClient(
            base_url=self.base_url, headers=self._headers(), transport=self._transport
        ) as client:
            try:
                response = await client.post(
                    "/chat/completions",
                    json=self._payload(request, stream=False),
                    timeout=request.timeout_ms / 1000 or self._timeout,
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise ModelUnavailable(f"模型调用失败: {exc}") from exc
            body = response.json()

        choice = (body.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        usage = body.get("usage") or {}
        return LLMResponse(
            content=message.get("content") or "",
            model=body.get("model") or request.model,
            token_input=int(usage.get("prompt_tokens") or 0),
            token_output=int(usage.get("completion_tokens") or 0),
            finish_reason=choice.get("finish_reason") or "completed",
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        async with httpx.AsyncClient(
            base_url=self.base_url, headers=self._headers(), transport=self._transport
        ) as client:
            try:
                async with client.stream(
                    "POST",
                    "/chat/completions",
                    json=self._payload(request, stream=True),
                    timeout=request.timeout_ms / 1000 or self._timeout,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        chunk = line[len("data: ") :].strip()
                        if chunk == "[DONE]":
                            break
                        import json

                        payload = json.loads(chunk)
                        delta = ((payload.get("choices") or [{}])[0].get("delta") or {}).get("content")
                        if delta:
                            yield delta
            except httpx.HTTPError as exc:
                raise ModelUnavailable(f"模型流式调用失败: {exc}") from exc

    async def embed(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        settings = get_settings()
        async with httpx.AsyncClient(
            base_url=self.base_url, headers=self._headers(), transport=self._transport
        ) as client:
            try:
                response = await client.post(
                    "/embeddings",
                    json={"model": model or settings.embedding_model, "input": texts},
                    timeout=self._timeout,
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise ModelUnavailable(f"Embedding 调用失败: {exc}") from exc
            body = response.json()
        return [item["embedding"] for item in body.get("data") or []]


class HashEmbeddingClient:
    """离线兜底：基于字符哈希的确定性向量，仅用于测试与无 Embedding 环境。"""

    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim

    def embed_sync(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for index, char in enumerate(text):
            slot = (ord(char) + index) % self.dim
            vector[slot] += 1.0
        norm = sum(value * value for value in vector) ** 0.5 or 1.0
        return [value / norm for value in vector]

    async def embed(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        return [self.embed_sync(text) for text in texts]


def build_llm_client() -> LLMClient:
    """按配置构建模型客户端：配置了 base_url 与密钥则走 OpenAI 兼容接口。"""
    settings = get_settings()
    if settings.llm_base_url and settings.llm_api_key:
        return OpenAICompatibleClient(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            timeout=settings.llm_timeout_ms / 1000,
        )
    from app.integrations.llm.client import StubLLMClient

    return StubLLMClient(reply=settings.stub_reply)


def build_embedding_client():
    settings = get_settings()
    if settings.llm_base_url and settings.llm_api_key and settings.embedding_model:
        return OpenAICompatibleClient(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            timeout=settings.llm_timeout_ms / 1000,
        )
    return HashEmbeddingClient(dim=settings.embedding_dim)
