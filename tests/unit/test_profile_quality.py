from app.domain.profile.proactive import normalize_suggestions


def test_normalize_suggestions_dedupes_and_limits() -> None:
    result = normalize_suggestions(
        ["  建议一  ", "建议一", "", "建议二", "建议三", "建议四"],
        max_items=3,
        max_chars=120,
    )
    assert result == ["建议一", "建议二", "建议三"]


def test_normalize_suggestions_truncates_items() -> None:
    result = normalize_suggestions(["很长" * 100], max_items=3, max_chars=10)
    assert len(result[0]) == 10
