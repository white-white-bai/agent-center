from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True)
class LLMRequest:
    messages: list[ChatMessage]
    model: str
    temperature: float = 0.2
    timeout_ms: int = 30000
    response_format: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    content: str
    model: str
    token_input: int = 0
    token_output: int = 0
    finish_reason: str = "completed"
    raw: dict[str, Any] = field(default_factory=dict)


class ModelUnavailable(Exception):
    pass


class LLMClient(Protocol):
    async def complete(self, request: LLMRequest) -> LLMResponse: ...

    def stream(self, request: LLMRequest) -> AsyncIterator[str]: ...


class StubLLMClient:
    """测试与本地开发使用的确定性模型实现。"""

    def __init__(self, reply: str = "这是桩模型回复", *, fail_models: set[str] | None = None) -> None:
        self.reply = reply
        self.fail_models = fail_models or set()
        self.calls: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        if request.model in self.fail_models:
            raise ModelUnavailable(f"stub model unavailable: {request.model}")
        prompt_tokens = sum(len(message.content) for message in request.messages)
        return LLMResponse(
            content=self.reply,
            model=request.model,
            token_input=prompt_tokens,
            token_output=len(self.reply),
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        response = await self.complete(request)
        for char in response.content:
            yield char


class LiteLLMClient:
    """LiteLLM 接入，按需导入，避免未安装时影响其他功能。"""

    async def complete(self, request: LLMRequest) -> LLMResponse:
        try:
            import litellm
        except ImportError as exc:  # pragma: no cover - 依赖可选
            raise ModelUnavailable("未安装 litellm") from exc

        response = await litellm.acompletion(
            model=request.model,
            messages=[{"role": m.role, "content": m.content} for m in request.messages],
            temperature=request.temperature,
            timeout=request.timeout_ms / 1000,
            response_format=request.response_format,
        )
        usage = getattr(response, "usage", None)
        choice = response.choices[0]
        return LLMResponse(
            content=choice.message.content or "",
            model=request.model,
            token_input=getattr(usage, "prompt_tokens", 0) or 0,
            token_output=getattr(usage, "completion_tokens", 0) or 0,
            finish_reason=getattr(choice, "finish_reason", "completed") or "completed",
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        try:
            import litellm
        except ImportError as exc:  # pragma: no cover
            raise ModelUnavailable("未安装 litellm") from exc

        stream = await litellm.acompletion(
            model=request.model,
            messages=[{"role": m.role, "content": m.content} for m in request.messages],
            temperature=request.temperature,
            timeout=request.timeout_ms / 1000,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
