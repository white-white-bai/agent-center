import json

import httpx
import pytest

from app.domain.safety.service import SafetyService


def _handler(calls: list[dict], *, blocked_marker: str = "BLOCK"):
    def handle(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(
            {"payload": payload, "authorization": request.headers.get("Authorization")}
        )
        blocked = blocked_marker in str(payload.get("text", ""))
        return httpx.Response(
            200,
            json={
                "blocked": blocked,
                "reason": "命中审核规则" if blocked else "",
                "category": "MOCK" if blocked else "",
            },
        )

    return handle


async def test_twenty_blocked_input_and_output_cases() -> None:
    calls: list[dict] = []
    service = SafetyService(
        moderation_url="http://moderation/moderate",
        transport=httpx.MockTransport(_handler(calls)),
    )

    for index in range(20):
        result = await service.check(f"BLOCK_INPUT_{index}", "input")
        assert not result.allowed
        assert result.category == "MOCK"
    for index in range(20):
        result = await service.check(f"BLOCK_OUTPUT_{index}", "output")
        assert not result.allowed
        assert result.category == "MOCK"

    assert len(calls) == 40
    assert calls[0]["payload"] == {"text": "BLOCK_INPUT_0", "stage": "input"}
    assert calls[-1]["payload"] == {"text": "BLOCK_OUTPUT_19", "stage": "output"}


async def test_allowed_and_unavailable_behaviour() -> None:
    calls: list[dict] = []
    service = SafetyService(
        moderation_url="http://moderation/moderate",
        transport=httpx.MockTransport(_handler(calls)),
    )
    allowed = await service.check("正常问题", "input")
    assert allowed.allowed

    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    unavailable = SafetyService(
        moderation_url="http://moderation/moderate",
        transport=httpx.MockTransport(fail),
    )
    result = await unavailable.check("正常问题", "input")
    assert not result.allowed
    assert result.category == "MODERATION_UNAVAILABLE"


async def test_api_key_and_custom_fields() -> None:
    calls: list[dict] = []
    service = SafetyService(
        moderation_url="http://moderation/moderate",
        transport=httpx.MockTransport(_handler(calls)),
        api_key="secret",
        text_field="content",
        blocked_field="blocked",
    )
    await service.check("正常问题", "output")
    assert calls[0]["authorization"] == "Bearer secret"
    assert calls[0]["payload"] == {"content": "正常问题", "stage": "output"}


async def test_local_word_short_circuits_remote() -> None:
    calls: list[dict] = []
    service = SafetyService(
        words=["违禁词"],
        moderation_url="http://moderation/moderate",
        transport=httpx.MockTransport(_handler(calls)),
    )
    result = await service.check("包含违禁词", "input")
    assert not result.allowed
    assert result.category == "SENSITIVE_WORD"
    assert calls == []


async def test_malformed_response_fails_closed() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["not", "an", "object"])

    service = SafetyService(
        moderation_url="http://moderation/moderate",
        transport=httpx.MockTransport(handle),
    )
    result = await service.check("正常问题", "input")
    assert not result.allowed
    assert result.category == "MODERATION_UNAVAILABLE"
