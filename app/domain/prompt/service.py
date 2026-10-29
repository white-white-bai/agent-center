import re
from typing import Any

from app.core.exceptions import ValidationError

_VAR_PATTERN = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")

STATUS_FLOW: dict[str, set[str]] = {
    "DRAFT": {"TESTING"},
    "TESTING": {"PUBLISHED"},
    "PUBLISHED": {"DEPRECATED"},
    "DEPRECATED": set(),
}


def extract_variables(content: str) -> list[str]:
    return sorted({match.group(1) for match in _VAR_PATTERN.finditer(content)})


def render(content: str, variables: dict[str, Any]) -> str:
    missing = [name for name in extract_variables(content) if name not in variables]

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in variables:
            return match.group(0)
        return str(variables[name])

    if missing:
        raise ValidationError(f"缺少提示词变量: {', '.join(missing)}")
    return _VAR_PATTERN.sub(_replace, content)


def compose_layers(layers: list[str]) -> str:
    """按平台基线 → 域模板 → Agent 模板 → 场景覆盖的顺序拼接。

    安全基线由调用方保证排在首位，且不允许被后续层覆盖同名段落。
    """
    return "\n\n".join(layer.strip() for layer in layers if layer and layer.strip())


def can_transition(current: str, target: str) -> bool:
    return target in STATUS_FLOW.get(current, set())
