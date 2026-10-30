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


@dataclass
class HandoffDecision:
    to_agent: str
    reason: str = ""
    pending_slots: list[str] = field(default_factory=list)


@dataclass
class TopicDecision:
    action: str
    topic: str = ""


@dataclass
class FanoutDecision:
    tasks: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PlanDecision:
    steps: list[dict[str, Any]] = field(default_factory=list)


Decision = (
    ToolCallDecision
    | FinalDecision
    | ClarifyDecision
    | SlotsDecision
    | HandoffDecision
    | TopicDecision
    | FanoutDecision
    | PlanDecision
)


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
    if decision_type == "topic":
        action = payload.get("action")
        if action not in {"switch", "resume"}:
            raise ValidationError("话题决策 action 仅支持 switch 或 resume")
        if action == "switch" and not payload.get("topic"):
            raise ValidationError("切换话题缺少 topic 字段")
        return TopicDecision(action=action, topic=payload.get("topic") or "")
    if decision_type == "fanout":
        tasks = payload.get("tasks")
        if not isinstance(tasks, list) or not tasks:
            raise ValidationError("并行决策缺少 tasks 列表")
        for item in tasks:
            if not isinstance(item, dict) or not item.get("tool"):
                raise ValidationError("并行任务缺少 tool 字段")
        return FanoutDecision(tasks=tasks)
    if decision_type == "plan":
        steps = payload.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ValidationError("计划决策缺少 steps 列表")
        if len(steps) > 8:
            raise ValidationError("计划步骤不能超过 8 步")
        for item in steps:
            if not isinstance(item, dict) or not item.get("tool"):
                raise ValidationError("计划步骤缺少 tool 字段")
            if not isinstance(item.get("arguments", {}), dict):
                raise ValidationError("计划步骤 arguments 必须是对象")
        return PlanDecision(steps=steps)
    if decision_type == "handoff":
        target = payload.get("to")
        if not target:
            raise ValidationError("交接决策缺少 to 字段")
        return HandoffDecision(
            to_agent=target,
            reason=payload.get("reason") or "",
            pending_slots=list(payload.get("pending_slots") or []),
        )
    raise ValidationError(f"未知的决策类型: {decision_type}")
