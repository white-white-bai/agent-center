from dataclasses import dataclass, field


@dataclass
class RunContext:
    run_id: str
    tenant_id: str
    user_id: str
    conversation_id: int
    turn_id: int | None
    agent_code: str
    trace_id: str
    user_message: str
    agent_config: dict = field(default_factory=dict)
    model_policy: dict = field(default_factory=dict)
    allowed_tools: list[str] = field(default_factory=list)
    max_steps: int = 8
    token_budget: int = 32000
    timeout_ms: int = 30000
    system_prompt: str | None = None


@dataclass
class RuntimeResult:
    run_id: str
    status: str
    answer: str = ""
    question: str = ""
    steps: int = 0
    tool_calls: int = 0
    token_input: int = 0
    token_output: int = 0
    error_code: str | None = None
    confirmation_id: str | None = None
    confirmation_summary: str = ""
    tool_codes: list[str] = field(default_factory=list)
