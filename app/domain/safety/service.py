from dataclasses import dataclass

import httpx

from app.core.config import get_settings


@dataclass
class SafetyResult:
    allowed: bool
    stage: str
    reason: str = ""
    category: str = ""

    @classmethod
    def pass_(cls, stage: str) -> "SafetyResult":
        return cls(allowed=True, stage=stage)


def load_words(raw: str) -> list[str]:
    return [word.strip() for word in raw.replace("，", ",").split(",") if word.strip()]


class SafetyService:
    """内容安全检查：本地词表优先，可选外部审核服务。

    审核服务不可用时按既定策略降级：拒绝放行，避免未审核内容输出。
    """

    def __init__(
        self,
        *,
        words: list[str] | None = None,
        moderation_url: str | None = None,
        timeout_ms: int = 2000,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.words = words or []
        self.moderation_url = moderation_url
        self.timeout_ms = timeout_ms
        self._transport = transport

    def check_local(self, text: str, stage: str) -> SafetyResult:
        for word in self.words:
            if word and word in text:
                return SafetyResult(
                    allowed=False, stage=stage, reason=f"命中敏感词：{word}", category="SENSITIVE_WORD"
                )
        return SafetyResult.pass_(stage)

    async def check(self, text: str, stage: str) -> SafetyResult:
        local = self.check_local(text, stage)
        if not local.allowed:
            return local
        if not self.moderation_url:
            return local
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_ms / 1000, transport=self._transport
            ) as client:
                response = await client.post(
                    self.moderation_url, json={"text": text, "stage": stage}
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError:
            return SafetyResult(
                allowed=False,
                stage=stage,
                reason="审核服务不可用，已按安全策略拒绝",
                category="MODERATION_UNAVAILABLE",
            )
        if payload.get("blocked"):
            return SafetyResult(
                allowed=False,
                stage=stage,
                reason=payload.get("reason") or "内容未通过审核",
                category=payload.get("category") or "MODERATION_BLOCKED",
            )
        return local


def get_safety_service() -> SafetyService:
    settings = get_settings()
    return SafetyService(
        words=load_words(settings.sensitive_words),
        moderation_url=settings.moderation_url,
        timeout_ms=settings.moderation_timeout_ms,
    )


REFUSAL_MESSAGE = "抱歉，该内容不符合平台使用规范，我无法继续处理。如有疑问请联系人工客服。"
