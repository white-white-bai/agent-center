from app.domain.session.models import Message
from app.domain.session.summarizer import compress_messages


def _message(role: str, content: str, message_id: int | None = None) -> Message:
    message = Message(tenant_id="t1", conversation_id=1, role=role, content=content)
    if message_id is not None:
        message.id = message_id
    return message


def test_compress_returns_empty_for_short_conversation() -> None:
    messages = [_message("user", "你好")]

    assert compress_messages(messages, keep_last=6) == ""


def test_compress_keeps_questions_and_conclusions() -> None:
    messages = []
    for index in range(8):
        messages.append(_message("user", f"问题{index}"))
        messages.append(_message("assistant", f"回答{index}"))

    summary = compress_messages(messages, keep_last=4)

    assert "历史问题" in summary
    assert "历史结论" in summary
    assert "问题1" in summary


def test_compress_limits_length() -> None:
    messages = [_message("user", "很长的问题" * 100), _message("assistant", "很长的回答" * 100)] * 10

    summary = compress_messages(messages, keep_last=2)

    assert len(summary) <= 800
