from app.core.tenant import TenantContext
from app.domain.session import summarizer
from app.domain.session.models import Conversation, Message


async def test_long_conversation_gets_summary(db_session) -> None:
    ctx = TenantContext(tenant_id="t1", user_id="u1")
    conversation = Conversation(tenant_id="t1", user_id="u1", channel="web", status="ACTIVE")
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)

    for index in range(8):
        db_session.add(
            Message(
                tenant_id="t1",
                conversation_id=conversation.id,
                role="user",
                content=f"问题{index}",
            )
        )
        db_session.add(
            Message(
                tenant_id="t1",
                conversation_id=conversation.id,
                role="assistant",
                content=f"回答{index}",
            )
        )
    await db_session.commit()

    assert await summarizer.should_compress(db_session, "t1", conversation.id) is True
    summary = await summarizer.summarize_conversation(db_session, ctx, conversation)

    assert summary is not None
    assert "历史问题" in summary
    await db_session.refresh(conversation)
    assert conversation.context_summary == summary


async def test_short_conversation_has_no_summary(db_session) -> None:
    ctx = TenantContext(tenant_id="t1", user_id="u1")
    conversation = Conversation(tenant_id="t1", user_id="u1", channel="web", status="ACTIVE")
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)
    db_session.add(
        Message(tenant_id="t1", conversation_id=conversation.id, role="user", content="你好")
    )
    await db_session.commit()

    assert await summarizer.should_compress(db_session, "t1", conversation.id) is False
    assert await summarizer.summarize_conversation(db_session, ctx, conversation) is None
