from contextvars import ContextVar
from uuid import uuid4

_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)


def new_trace_id() -> str:
    return f"trace_{uuid4().hex}"


def set_trace_id(trace_id: str) -> None:
    _trace_id.set(trace_id)


def get_trace_id() -> str | None:
    return _trace_id.get()


def ensure_trace_id() -> str:
    trace_id = get_trace_id()
    if trace_id is None:
        trace_id = new_trace_id()
        set_trace_id(trace_id)
    return trace_id
