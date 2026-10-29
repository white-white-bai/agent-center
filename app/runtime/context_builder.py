from dataclasses import dataclass, field

SAFETY_BASELINE = "你必须在政务合规范围内回答，不得编造政策依据，不得泄露个人信息。"

PRIORITY_SAFETY = 0
PRIORITY_AGENT = 1
PRIORITY_STATE = 2
PRIORITY_RECENT = 3
PRIORITY_SUMMARY = 4
PRIORITY_KNOWLEDGE = 5
PRIORITY_PROFILE = 6
PRIORITY_MEMORY = 7


def estimate_tokens(text: str) -> int:
    """粗略估算：中文按 1 字符 1 token，英文按 4 字符 1 token。"""
    if not text:
        return 0
    chinese = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    other = len(text) - chinese
    return chinese + ((other + 3) // 4 if other else 0)


@dataclass
class Section:
    name: str
    priority: int
    content: str

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.content)


@dataclass
class BuiltContext:
    sections: list[Section] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    token_budget: int = 0
    reserved_tokens: int = 0

    @property
    def estimated_tokens(self) -> int:
        return sum(section.tokens for section in self.sections)

    def to_prompt(self) -> str:
        return "\n\n".join(section.content for section in self.sections if section.content)

    def names(self) -> list[str]:
        return [section.name for section in self.sections]


def fit_budget(
    sections: list[Section],
    *,
    token_budget: int,
    reserve_tokens: int = 0,
) -> BuiltContext:
    available = max(0, token_budget - reserve_tokens)
    kept: list[Section] = []
    dropped: list[str] = []
    used = 0
    for section in sorted(sections, key=lambda item: item.priority):
        if used + section.tokens <= available:
            kept.append(section)
            used += section.tokens
        else:
            dropped.append(section.name)
    return BuiltContext(
        sections=kept,
        dropped=dropped,
        token_budget=token_budget,
        reserved_tokens=reserve_tokens,
    )


def default_reserve(token_budget: int) -> int:
    return min(max(int(token_budget * 0.3), 500), 4000)
