from datetime import datetime, timedelta

from app.core.tenant import TenantContext
from app.domain.memory import service as memory_service
from app.domain.session import summarizer
from app.domain.session.models import Conversation, Message
from app.integrations.llm.client import LLMResponse

CTX = TenantContext(tenant_id="t1", user_id="u1")


class Client:
    def __init__(self, reply: str, *, fail: bool = False) -> None:
        self.reply = reply
        self.fail = fail

    async def complete(self, request):
        if self.fail:
            raise RuntimeError("model down")
        return LLMResponse(content=self.reply, model=request.model)

    async def stream(self, request):
        yield ""


async def _seed_long_conversation(db_session) -> Conversation:
    conversation = Conversation(tenant_id="t1", user_id="u1", channel="web", status="ACTIVE")
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)
    for index in range(8):
        db_session.add(
            Message(tenant_id="t1", conversation_id=conversation.id, role="user", content=f"问题{index}")
        )
        db_session.add(
            Message(tenant_id="t1", conversation_id=conversation.id, role="assistant", content=f"回答{index}")
        )
    await db_session.commit()
    return conversation


async def test_model_summary_is_used_when_available(db_session) -> None:
    from app.integrations.llm.router import ModelRouter

    conversation = await _seed_long_conversation(db_session)
    router = ModelRouter(Client('{"summary":"模型生成的摘要"}'))

    summary = await summarizer.summarize_conversation(db_session, CTX, conversation, router=router)

    assert summary == "模型生成的摘要"


async def test_model_summary_is_truncated(db_session) -> None:
    from app.integrations.llm.router import ModelRouter

    conversation = await _seed_long_conversation(db_session)
    router = ModelRouter(Client('{"summary":"' + "摘" * 2000 + '"}'))

    summary = await summarizer.summarize_conversation(db_session, CTX, conversation, router=router)

    assert summary is not None
    assert len(summary) == 800


async def test_model_summary_falls_back_to_rules_on_failure(db_session) -> None:
    from app.integrations.llm.router import ModelRouter

    conversation = await _seed_long_conversation(db_session)
    router = ModelRouter(Client("", fail=True))

    summary = await summarizer.summarize_conversation(db_session, CTX, conversation, router=router)

    assert summary is not None
    assert "历史问题" in summary


async def test_memory_default_ttl_by_type(db_session) -> None:
    semantic = await memory_service.add_memory(
        db_session, CTX, memory_type="SEMANTIC", subject="区域", predicate="lives_in", object_value="天宁区"
    )
    episodic = await memory_service.add_memory(
        db_session, CTX, memory_type="EPISODIC", subject="事项", predicate="done", object_value="办证"
    )

    now = datetime.utcnow()
    assert semantic.expires_at is not None
    assert abs((semantic.expires_at - now).days - 365) <= 1
    assert episodic.expires_at is not None
    assert abs((episodic.expires_at - now).days - 180) <= 1
