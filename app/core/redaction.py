import re
from typing import Any

ID_CARD = re.compile(r"\b\d{17}[\dXx]\b")
PHONE = re.compile(r"\b1\d{10}\b")
API_KEY = re.compile(r"\b(sk|ak)-[A-Za-z0-9_-]{8,}\b")
SECRET_KEYS = {"password", "passwd", "token", "secret", "authorization", "api_key", "apikey"}


def redact_text(text: str) -> str:
    text = ID_CARD.sub("[ID_CARD]", text)
    text = PHONE.sub("[PHONE]", text)
    text = API_KEY.sub("[API_KEY]", text)
    return text


def redact(value: Any) -> Any:
    """递归脱敏：敏感字段名整值替换，字符串按模式替换。"""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if str(key).lower() in SECRET_KEYS:
                result[key] = "***"
            else:
                result[key] = redact(item)
        return result
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value
