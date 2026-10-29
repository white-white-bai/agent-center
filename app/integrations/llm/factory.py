from functools import lru_cache

from app.core.config import get_settings
from app.integrations.llm.client import LLMClient, StubLLMClient
from app.integrations.llm.openai_client import build_llm_client
from app.integrations.llm.router import ModelRouter


@lru_cache
def get_llm_client() -> LLMClient:
    settings = get_settings()
    if settings.model_provider == "litellm":  # pragma: no cover - 需真实模型环境
        from app.integrations.llm.client import LiteLLMClient

        return LiteLLMClient()
    if settings.model_provider == "stub":
        return StubLLMClient(reply=settings.stub_reply)
    return build_llm_client()


def get_model_router() -> ModelRouter:
    return ModelRouter(get_llm_client())
