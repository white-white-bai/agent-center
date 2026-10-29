from app.runtime.context_builder import (
    PRIORITY_AGENT,
    PRIORITY_KNOWLEDGE,
    PRIORITY_MEMORY,
    PRIORITY_PROFILE,
    PRIORITY_RECENT,
    PRIORITY_SAFETY,
    PRIORITY_SUMMARY,
    Section,
    default_reserve,
    estimate_tokens,
    fit_budget,
)


def test_estimate_tokens_counts_chinese_and_english() -> None:
    assert estimate_tokens("你好") == 2
    assert estimate_tokens("abcdefgh") == 2
    assert estimate_tokens("") == 0


def test_fit_budget_keeps_high_priority_sections() -> None:
    sections = [
        Section(name="safety", priority=PRIORITY_SAFETY, content="安全" * 10),
        Section(name="knowledge", priority=PRIORITY_KNOWLEDGE, content="知识" * 1000),
    ]

    built = fit_budget(sections, token_budget=100, reserve_tokens=0)

    assert built.names() == ["safety"]
    assert built.dropped == ["knowledge"]


def test_fit_budget_drops_lowest_priority_first() -> None:
    sections = [
        Section(name="safety", priority=PRIORITY_SAFETY, content="s" * 4),
        Section(name="agent", priority=PRIORITY_AGENT, content="a" * 40),
        Section(name="summary", priority=PRIORITY_SUMMARY, content="m" * 40),
        Section(name="profile", priority=PRIORITY_PROFILE, content="p" * 40),
        Section(name="memory", priority=PRIORITY_MEMORY, content="x" * 40),
        Section(name="knowledge", priority=PRIORITY_KNOWLEDGE, content="k" * 40),
    ]

    built = fit_budget(sections, token_budget=12, reserve_tokens=0)

    assert built.names() == ["safety", "agent"]
    assert set(built.dropped) == {"summary", "profile", "memory", "knowledge"}


def test_fit_budget_never_exceeds_available() -> None:
    sections = [Section(name=f"s{i}", priority=i, content="内" * 20) for i in range(10)]

    built = fit_budget(sections, token_budget=100, reserve_tokens=20)

    assert built.estimated_tokens <= 80


def test_default_reserve_is_bounded() -> None:
    assert default_reserve(1000) == 500
    assert default_reserve(100000) == 4000


def test_built_context_prompt_joins_sections() -> None:
    built = fit_budget(
        [
            Section(name="a", priority=PRIORITY_SAFETY, content="第一段"),
            Section(name="b", priority=PRIORITY_RECENT, content="第二段"),
        ],
        token_budget=1000,
    )

    assert built.to_prompt() == "第一段\n\n第二段"
