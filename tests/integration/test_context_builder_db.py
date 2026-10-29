from app.domain.session.models import Conversation, Message
from app.runtime.builder import ContextBuilder


async def _seed(db_session, *, summary: str | None = None) -> Conversation:
    conversation = Conversation(
        tenant_id="t1",
        user_id="u1",
        channel="web",
        status="ACTIVE",
        context_summary=summary,
        session_state_json={"slots": {"matter_type": {"value": "营业执照", "status": "filled"}}},
    )
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)
    for role, content in [("user", "营业执照怎么办理"), ("assistant", "需要提交身份证")]:
        db_session.add(
            Message(tenant_id="t1", conversation_id=conversation.id, role=role, content=content)
        )
    await db_session.commit()
    return conversation


async def test_builder_includes_recent_messages_and_state(db_session) -> None:
    conversation = await _seed(db_session)

    built = await ContextBuilder(db_session).build(
        tenant_id="t1",
        conversation=conversation,
        agent_prompt="你是政务顾问",
        user_message="材料有哪些",
        token_budget=32000,
    )

    assert set(built.names()) == {"safety", "agent", "session_state", "recent_messages", "user_message"}
    prompt = built.to_prompt()
    assert "营业执照怎么办理" in prompt
    assert "材料有哪些" in prompt
    assert "营业执照" in prompt


async def test_builder_drops_low_priority_when_budget_is_tight(db_session) -> None:
    conversation = await _seed(db_session, summary="历史摘要" * 200)

    built = await ContextBuilder(db_session).build(
        tenant_id="t1",
        conversation=conversation,
        agent_prompt="你是政务顾问",
        user_message="材料有哪些",
        token_budget=600,
        knowledge_snippets=["知识" * 500],
        memories=["记忆" * 100],
        profile_summary="用户偏好简洁回答",
    )

    assert "safety" in built.names()
    assert "knowledge" in built.dropped
    assert "summary" in built.dropped
