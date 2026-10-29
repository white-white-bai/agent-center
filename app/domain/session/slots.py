from dataclasses import dataclass, field
from typing import Any

SLOT_STATUSES = {"missing", "filled", "confirmed", "invalid", "conflict"}
MAX_CLARIFICATION_PER_SLOT = 2


@dataclass
class Slot:
    value: Any = None
    status: str = "missing"
    source: str | None = None
    confidence: float = 0.0
    clarification_count: int = 0

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "status": self.status,
            "source": self.source,
            "confidence": self.confidence,
            "clarification_count": self.clarification_count,
        }


@dataclass
class SessionState:
    intent: str | None = None
    slots: dict[str, Slot] = field(default_factory=dict)
    required_slots: list[str] = field(default_factory=list)
    clarification_count: int = 0
    active_topic: str | None = None
    topic_stack: list[dict] = field(default_factory=list)

    def missing_slots(self) -> list[str]:
        return [
            name
            for name in self.required_slots
            if self.slots.get(name, Slot()).status in {"missing", "invalid", "conflict"}
        ]

    def to_dict(self) -> dict:
        return {
            "intent": self.intent,
            "slots": {name: slot.to_dict() for name, slot in self.slots.items()},
            "required_slots": self.required_slots,
            "missing_slots": self.missing_slots(),
            "clarification_count": self.clarification_count,
            "active_topic": self.active_topic,
            "topic_stack": self.topic_stack,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "SessionState":
        slots = {
            name: Slot(
                value=data.get("value"),
                status=data.get("status", "missing"),
                source=data.get("source"),
                confidence=float(data.get("confidence", 0.0)),
                clarification_count=int(data.get("clarification_count", 0)),
            )
            for name, data in (payload.get("slots") or {}).items()
        }
        state = cls(
            intent=payload.get("intent"),
            slots=slots,
            required_slots=list(payload.get("required_slots") or []),
            clarification_count=int(payload.get("clarification_count", 0)),
            active_topic=payload.get("active_topic"),
            topic_stack=list(payload.get("topic_stack") or []),
        )
        return state


def init_state(intent: str | None, required_slots: list[str]) -> SessionState:
    return SessionState(
        intent=intent,
        slots={name: Slot() for name in required_slots},
        required_slots=list(required_slots),
    )


def merge_slot(
    state: SessionState,
    name: str,
    value: Any,
    *,
    source: str,
    confidence: float = 1.0,
) -> Slot:
    """合并槽位值。已确认槽位不会被低可信来源覆盖。"""
    if name not in state.required_slots:
        state.required_slots.append(name)
    slot = state.slots.get(name, Slot())
    if slot.status == "confirmed" and source != "user":
        return slot
    if slot.status == "confirmed" and source == "user" and value == slot.value:
        return slot
    if value is None or value == "":
        slot.status = "missing"
        state.slots[name] = slot
        return slot
    slot.value = value
    slot.status = "filled"
    slot.source = source
    slot.confidence = confidence
    state.slots[name] = slot
    return slot


def confirm_slot(state: SessionState, name: str) -> Slot:
    slot = state.slots.get(name, Slot())
    if slot.status in {"filled", "confirmed"}:
        slot.status = "confirmed"
    state.slots[name] = slot
    return slot


def invalidate_slot(state: SessionState, name: str) -> Slot:
    slot = state.slots.get(name, Slot())
    slot.status = "invalid"
    state.slots[name] = slot
    return slot


def next_clarification(
    state: SessionState,
    questions: dict[str, str],
) -> str | None:
    """返回下一个需要追问的问题；单槽位追问超限时返回 None。"""
    for name in state.missing_slots():
        slot = state.slots.setdefault(name, Slot())
        if slot.clarification_count >= MAX_CLARIFICATION_PER_SLOT:
            continue
        question = questions.get(name)
        if question is None:
            continue
        slot.clarification_count += 1
        state.clarification_count += 1
        return question
    return None


def push_topic(state: SessionState, topic: str) -> None:
    if state.active_topic:
        state.topic_stack.append({"topic": state.active_topic, "status": "suspended"})
    state.active_topic = topic


def suspend_and_switch(state: SessionState, new_topic: str, slots_snapshot_id: str | None = None) -> None:
    if state.active_topic:
        entry = {"topic": state.active_topic, "status": "suspended"}
        if slots_snapshot_id:
            entry["slots_snapshot_id"] = slots_snapshot_id
        state.topic_stack.append(entry)
    state.active_topic = new_topic


def resume_previous_topic(state: SessionState) -> str | None:
    while state.topic_stack:
        entry = state.topic_stack.pop()
        if entry.get("status") == "suspended":
            state.active_topic = entry["topic"]
            return state.active_topic
    return None
