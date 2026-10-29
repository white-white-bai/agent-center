from app.domain.session.slots import (
    SessionState,
    confirm_slot,
    init_state,
    invalidate_slot,
    merge_slot,
    next_clarification,
    push_topic,
    resume_previous_topic,
    suspend_and_switch,
)


def test_init_state_lists_required_slots_as_missing() -> None:
    state = init_state("matter_status_query", ["matter_type", "application_number"])

    assert state.missing_slots() == ["matter_type", "application_number"]


def test_merge_slot_fills_value() -> None:
    state = init_state("matter_status_query", ["matter_type"])
    slot = merge_slot(state, "matter_type", "营业执照办理", source="user", confidence=0.98)

    assert slot.status == "filled"
    assert state.missing_slots() == []
    assert slot.to_dict()["confidence"] == 0.98


def test_confirmed_slot_is_not_overwritten_by_model_suggestion() -> None:
    state = init_state("matter_status_query", ["matter_type"])
    merge_slot(state, "matter_type", "营业执照办理", source="user")
    confirm_slot(state, "matter_type")

    merge_slot(state, "matter_type", "其他事项", source="model", confidence=0.9)

    assert state.slots["matter_type"].value == "营业执照办理"
    assert state.slots["matter_type"].status == "confirmed"


def test_empty_value_resets_slot_to_missing() -> None:
    state = init_state("q", ["a"])
    merge_slot(state, "a", "x", source="user")
    merge_slot(state, "a", "", source="user")

    assert state.slots["a"].status == "missing"


def test_invalid_slot_reappears_in_missing() -> None:
    state = init_state("q", ["a"])
    merge_slot(state, "a", "123", source="user")
    invalidate_slot(state, "a")

    assert state.missing_slots() == ["a"]


def test_clarification_is_limited_per_slot() -> None:
    state = init_state("q", ["a"])
    questions = {"a": "请提供 A"}

    assert next_clarification(state, questions) == "请提供 A"
    assert next_clarification(state, questions) == "请提供 A"
    assert next_clarification(state, questions) is None
    assert state.slots["a"].clarification_count == 2


def test_topic_stack_switch_and_resume() -> None:
    state = init_state("business_license", [])
    push_topic(state, "business_license")
    suspend_and_switch(state, "service_location_query")

    assert state.active_topic == "service_location_query"
    assert state.topic_stack[-1]["topic"] == "business_license"

    assert resume_previous_topic(state) == "business_license"
    assert state.topic_stack == []


def test_state_round_trip_serialization() -> None:
    state = init_state("intent", ["a"])
    merge_slot(state, "a", "v", source="user", confidence=0.7)

    restored = SessionState.from_dict(state.to_dict())

    assert restored.intent == "intent"
    assert restored.slots["a"].value == "v"
    assert restored.to_dict()["missing_slots"] == []
