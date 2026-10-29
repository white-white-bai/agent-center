import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.core.exceptions import ValidationError

_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


@dataclass
class ToolCallDecision:
    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class FinalDecision:
    answer: str


@dataclass
class ClarifyDecision:
    question: str


@dataclass
class SlotsDecision:
    slots: dict[str, Any] = field(default_factory=dict)


Decision = ToolCallDecision | FinalDecision | ClarifyDecision | SlotsDecision


def parse_decision(content: str) -> Decision:
    text = content.strip()
    block = _JSON_BLOCK.search(text)
    if block:
        text = block.group(1).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"模型决策不是合法 JSON: {text[:200]}") from exc

    decision_type = payload.get("type")
    if decision_type == "tool_call":
        tool = payload.get("tool")
        if not tool:
            raise ValidationError("工具调用缺少 tool 字段")
        return ToolCallDecision(tool=tool, arguments=payload.get("arguments") or {})
    if decision_type == "final":
        return FinalDecision(answer=payload.get("answer") or "")
    if decision_type == "clarify":
        return ClarifyDecision(question=payload.get("question") or "")
    if decision_type == "slots":
        slots = payload.get("slots")
        if not isinstance(slots, dict):
            raise ValidationError("槽位决策缺少 slots 对象")
        return SlotsDecision(slots=slots)
    raise ValidationError(f"未知的决策类型: {decision_type}")
