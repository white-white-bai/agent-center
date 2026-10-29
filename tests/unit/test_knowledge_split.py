from app.domain.knowledge.service import split_text


def test_split_text_keeps_paragraphs_and_sections() -> None:
    text = "# 申请材料\n\n申请人需要提交身份证。\n\n# 办理时限\n\n五个工作日办结。"

    chunks = split_text(text, max_chars=100)

    assert len(chunks) >= 2
    assert chunks[0]["section"] == "申请材料"
    assert "身份证" in chunks[0]["content"]
    assert chunks[-1]["section"] == "办理时限"


def test_split_text_respects_max_chars() -> None:
    text = "很长的段落。" * 200

    chunks = split_text(text, max_chars=120, overlap=20)

    assert chunks
    assert all(len(chunk["content"]) <= 120 for chunk in chunks)


def test_split_text_returns_empty_for_blank_input() -> None:
    assert split_text("   ") == []
