from app.runtime.critic import (
    DEFAULT_RISK_KEYWORDS,
    parse_critic_response,
    should_review,
)


def test_risk_mode_matches_keywords() -> None:
    policy = {"enabled": True}
    assert should_review("残疾人补贴怎么申请", "需要...", policy)
    assert not should_review("你好", "您好，有什么可以帮您", policy)


def test_always_mode_and_disabled_mode() -> None:
    assert should_review("你好", "您好", {"enabled": True, "mode": "always"})
    assert not should_review("补贴", "金额", {"enabled": False})


def test_custom_keywords_override_defaults() -> None:
    policy = {"enabled": True, "risk_keywords": ["招标"]}
    assert should_review("招标公告", "见附件", policy)
    assert not should_review("补贴", "金额", policy)
    assert "补贴" in DEFAULT_RISK_KEYWORDS


def test_parse_fenced_response() -> None:
    result = parse_critic_response(
        '```json\n{"verdict":"pass","reason":"与知识一致","revised_answer":""}\n```'
    )
    assert result is not None
    assert result.verdict == "pass"


def test_revise_without_answer_becomes_reject() -> None:
    result = parse_critic_response('{"verdict":"revise","reason":"缺少限定"}')
    assert result is not None
    assert result.verdict == "reject"


def test_invalid_response_returns_none() -> None:
    assert parse_critic_response("我觉得没问题") is None
    assert parse_critic_response('{"verdict":"unknown"}') is None
