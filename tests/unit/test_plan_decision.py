import pytest

from app.core.exceptions import ValidationError
from app.runtime.decisions import PlanDecision, parse_decision


def test_parse_plan_decision() -> None:
    decision = parse_decision(
        '{"type":"plan","steps":[{"tool":"a","arguments":{"x":1}},{"tool":"b"}]}'
    )
    assert isinstance(decision, PlanDecision)
    assert [step["tool"] for step in decision.steps] == ["a", "b"]


def test_plan_requires_steps() -> None:
    with pytest.raises(ValidationError):
        parse_decision('{"type":"plan","steps":[]}')


def test_plan_rejects_too_many_steps() -> None:
    steps = [{"tool": f"t{i}"} for i in range(9)]
    with pytest.raises(ValidationError):
        parse_decision(f'{{"type":"plan","steps":{__import__("json").dumps(steps)}}}')


def test_plan_rejects_invalid_arguments() -> None:
    with pytest.raises(ValidationError):
        parse_decision('{"type":"plan","steps":[{"tool":"a","arguments":[]}]}')
