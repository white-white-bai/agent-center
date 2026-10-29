import httpx

from app.domain.safety.service import SafetyService, load_words


async def test_local_sensitive_word_blocks_input() -> None:
    service = SafetyService(words=["暴力词"])

    result = await service.check("包含暴力词的内容", "input")

    assert result.allowed is False
    assert result.category == "SENSITIVE_WORD"


async def test_safe_text_passes() -> None:
    result = await SafetyService(words=["暴力词"]).check("正常咨询营业执照", "input")

    assert result.allowed is True


async def test_external_moderation_blocks_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"blocked": True, "reason": "涉政", "category": "POLITICAL"})

    service = SafetyService(
        moderation_url="http://moderation.local/check",
        transport=httpx.MockTransport(handler),
    )

    result = await service.check("任意内容", "output")

    assert result.allowed is False
    assert result.category == "POLITICAL"


async def test_moderation_failure_denies_by_default() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="down")

    service = SafetyService(
        moderation_url="http://moderation.local/check",
        transport=httpx.MockTransport(handler),
    )

    result = await service.check("任意内容", "output")

    assert result.allowed is False
    assert result.category == "MODERATION_UNAVAILABLE"


def test_load_words_supports_chinese_comma() -> None:
    assert load_words("词一，词二, 词三") == ["词一", "词二", "词三"]
