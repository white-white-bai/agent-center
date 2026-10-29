import re

FACT_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"我在(?P<value>[\u4e00-\u9fff]{2,10}(?:区|县|市))"), "所在区域", "lives_in"),
    (re.compile(r"我叫(?P<value>[\u4e00-\u9fff]{2,4})"), "称呼", "prefers_name"),
    (re.compile(r"我(?:喜欢|习惯)(?P<value>[\u4e00-\u9fff]{2,10})"), "交互偏好", "prefers"),
]

SENSITIVE_FRAGMENT = re.compile(r"\d{6,}|密码|验证码")


def extract_candidates(user_messages: list[str]) -> list[dict]:
    """从用户消息中抽取记忆候选，规则保守，宁缺毋滥。"""
    candidates: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for message in user_messages:
        if SENSITIVE_FRAGMENT.search(message):
            continue
        for pattern, subject, predicate in FACT_PATTERNS:
            match = pattern.search(message)
            if not match:
                continue
            value = match.group("value")
            key = (subject, value)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "memory_type": "SEMANTIC",
                    "subject": subject,
                    "predicate": predicate,
                    "object_value": value,
                    "confidence": 0.7,
                    "importance": 0.6,
                }
            )
    return candidates
