import re
from dataclasses import dataclass

import httpx

from app.core.config import get_settings

PROMPT_INJECTION_PATTERN = re.compile(
    r"(忽略|无视|忘记|跳过).{0,10}(之前|以上|上面|所有|前面|系统).{0,10}(指令|提示|规则|设定)"
    r"|ignore\s+(all\s+)?(previous|above|system)\s+(instructions|prompts|rules)"
    r"|(system|developer)\s*prompt|系统提示词|系统提示|开发者模式|越狱模式|jailbreak"
    r"|你现在(是|扮演).{0,12}(不受限制|无限制|开发者)",
    re.IGNORECASE,
)


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
        api_key: str = "",
        auth_header: str = "Authorization",
        auth_scheme: str = "Bearer",
        text_field: str = "text",
        stage_field: str = "stage",
        blocked_field: str = "blocked",
        reason_field: str = "reason",
        category_field: str = "category",
    ) -> None:
        self.words = words or []
        self.moderation_url = moderation_url
        self.timeout_ms = timeout_ms
        self._transport = transport
        self.api_key = api_key
        self.auth_header = auth_header
        self.auth_scheme = auth_scheme
        self.text_field = text_field
        self.stage_field = stage_field
        self.blocked_field = blocked_field
        self.reason_field = reason_field
        self.category_field = category_field

    def check_local(self, text: str, stage: str) -> SafetyResult:
        if stage == "input" and PROMPT_INJECTION_PATTERN.search(text):
            return SafetyResult(
                allowed=False,
                stage=stage,
                reason="检测到提示词注入或系统提示套取尝试",
                category="PROMPT_INJECTION",
            )
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
        headers = {}
        if self.api_key:
            headers[self.auth_header] = f"{self.auth_scheme} {self.api_key}".strip()
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_ms / 1000, transport=self._transport
            ) as client:
                response = await client.post(
                    self.moderation_url,
                    json={self.text_field: text, self.stage_field: stage},
                    headers=headers,
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError):
            return SafetyResult(
                allowed=False,
                stage=stage,
                reason="审核服务不可用，已按安全策略拒绝",
                category="MODERATION_UNAVAILABLE",
            )
        if not isinstance(payload, dict):
            return SafetyResult(
                allowed=False,
                stage=stage,
                reason="审核服务返回格式异常，已按安全策略拒绝",
                category="MODERATION_UNAVAILABLE",
            )
        if payload.get(self.blocked_field):
            return SafetyResult(
                allowed=False,
                stage=stage,
                reason=payload.get(self.reason_field) or "内容未通过审核",
                category=payload.get(self.category_field) or "MODERATION_BLOCKED",
            )
        return local


def get_safety_service() -> SafetyService:
    settings = get_settings()
    return SafetyService(
        words=load_words(settings.sensitive_words),
        moderation_url=settings.moderation_url,
        timeout_ms=settings.moderation_timeout_ms,
        api_key=settings.moderation_api_key,
        auth_header=settings.moderation_auth_header,
        auth_scheme=settings.moderation_auth_scheme,
        text_field=settings.moderation_text_field,
        stage_field=settings.moderation_stage_field,
        blocked_field=settings.moderation_blocked_field,
        reason_field=settings.moderation_reason_field,
        category_field=settings.moderation_category_field,
    )


REFUSAL_MESSAGE = "抱歉，该内容不符合平台使用规范，我无法继续处理。如有疑问请联系人工客服。"
