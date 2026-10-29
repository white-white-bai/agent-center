from typing import Any


def ok(data: Any = None) -> dict[str, Any]:
    from app.core.tracing import get_trace_id

    return {"code": "0", "message": "success", "traceId": get_trace_id(), "data": data}


def fail(code: str, message: str, trace_id: str | None) -> dict[str, Any]:
    return {"code": code, "message": message, "traceId": trace_id, "data": None}
