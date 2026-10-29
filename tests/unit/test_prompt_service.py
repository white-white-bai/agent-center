import pytest

from app.core.exceptions import ValidationError
from app.domain.prompt.service import can_transition, compose_layers, extract_variables, render


def test_extract_variables_in_order() -> None:
    content = "你是{{ agent.role }}，目标：{{goal}}，再次强调 {{ goal }}"

    assert extract_variables(content) == ["agent.role", "goal"]


def test_render_replaces_variables() -> None:
    rendered = render("你好 {{ user.name }}，今天是 {{day}}", {"user.name": "张三", "day": "周一"})

    assert rendered == "你好 张三，今天是 周一"


def test_render_raises_on_missing_variable() -> None:
    with pytest.raises(ValidationError) as exc:
        render("{{a}} and {{b}}", {"a": 1})

    assert "b" in str(exc.value)


def test_compose_layers_keeps_order() -> None:
    assert compose_layers(["base", "", "agent"]) == "base\n\nagent"


def test_status_flow() -> None:
    assert can_transition("DRAFT", "TESTING")
    assert can_transition("TESTING", "PUBLISHED")
    assert can_transition("PUBLISHED", "DEPRECATED")
    assert not can_transition("DRAFT", "PUBLISHED")
    assert not can_transition("DEPRECATED", "DRAFT")
