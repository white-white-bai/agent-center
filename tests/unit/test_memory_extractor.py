from app.domain.memory.extractor import extract_candidates
from app.domain.memory.service import contains_sensitive


def test_extract_region_and_preference() -> None:
    candidates = extract_candidates(["我在常州天宁区，想办营业执照", "我习惯看办事指南"])

    subjects = {(item["subject"], item["object_value"]) for item in candidates}
    assert ("所在区域", "常州天宁区") in subjects


def test_extract_deduplicates_repeated_facts() -> None:
    candidates = extract_candidates(["我在天宁区", "我就在天宁区呀"])

    assert len([c for c in candidates if c["subject"] == "所在区域"]) == 1


def test_extract_skips_messages_with_sensitive_fragments() -> None:
    candidates = extract_candidates(["我在天宁区，身份证 320402199001011234"])

    assert candidates == []


def test_contains_sensitive_detects_id_card_and_phone() -> None:
    assert contains_sensitive("身份证 320402199001011234")
    assert contains_sensitive("电话 13800138000")
    assert contains_sensitive("我的密码是 abc")
    assert not contains_sensitive("我住在天宁区")
