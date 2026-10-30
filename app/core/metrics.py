from prometheus_client import Counter, Gauge, Histogram, REGISTRY
from prometheus_client.openmetrics.exposition import CONTENT_TYPE_LATEST, generate_latest

HTTP_REQUESTS = Counter(
    "agent_center_http_requests_total",
    "HTTP requests handled by Agent Center",
    ["method", "route", "status"],
)
HTTP_DURATION = Histogram(
    "agent_center_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
)

RUNS = Counter(
    "agent_center_runs_total",
    "Agent runs by final status",
    ["status"],
)
RUN_DURATION = Histogram(
    "agent_center_run_duration_seconds",
    "Agent run duration in seconds",
    ["status"],
    buckets=(0.1, 0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300),
)
FIRST_TOKEN_DURATION = Histogram(
    "agent_center_first_token_duration_seconds",
    "Time from request start to first SSE message delta",
    buckets=(0.1, 0.25, 0.5, 1, 2, 3, 5, 8, 10, 20, 30, 60),
)
RUNS_IN_PROGRESS = Gauge(
    "agent_center_runs_in_progress",
    "Agent runs currently executing",
)

MODEL_DURATION = Histogram(
    "agent_center_model_duration_seconds",
    "Model call duration in seconds",
    ["model", "status"],
    buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30, 60, 120),
)
MODEL_TOKENS = Counter(
    "agent_center_model_tokens_total",
    "Model tokens consumed",
    ["model", "direction"],
)

TOOL_CALLS = Counter(
    "agent_center_tool_calls_total",
    "Tool calls by status",
    ["tool", "status"],
)
TOOL_DURATION = Histogram(
    "agent_center_tool_duration_seconds",
    "Tool call duration in seconds",
    ["tool"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
)
SSE_CONNECTIONS = Counter(
    "agent_center_sse_connections_total",
    "SSE connections by stream and end result",
    ["stream", "result"],
)
SSE_ACTIVE = Gauge(
    "agent_center_sse_connections_active",
    "Currently open SSE connections",
    ["stream"],
)


def _exemplar(trace_id: str | None) -> dict[str, str] | None:
    return {"trace_id": trace_id} if trace_id else None


def observe_http(
    method: str,
    route: str,
    status: int,
    duration_seconds: float,
    trace_id: str | None = None,
) -> None:
    HTTP_REQUESTS.labels(method=method, route=route, status=str(status)).inc()
    try:
        HTTP_DURATION.labels(method=method, route=route).observe(
            duration_seconds, exemplar=_exemplar(trace_id)
        )
    except Exception:  # noqa: BLE001 - 指标上报失败不得影响请求
        pass


def run_started() -> None:
    RUNS_IN_PROGRESS.inc()


def observe_run(status: str, duration_seconds: float, trace_id: str | None = None) -> None:
    RUNS.labels(status=status).inc()
    RUNS_IN_PROGRESS.dec()
    try:
        RUN_DURATION.labels(status=status).observe(
            duration_seconds, exemplar=_exemplar(trace_id)
        )
    except Exception:  # noqa: BLE001
        pass


def observe_first_token(duration_seconds: float, trace_id: str | None = None) -> None:
    try:
        FIRST_TOKEN_DURATION.observe(duration_seconds, exemplar=_exemplar(trace_id))
    except Exception:  # noqa: BLE001
        pass


def observe_model(
    model: str,
    status: str,
    duration_seconds: float,
    *,
    token_input: int = 0,
    token_output: int = 0,
    trace_id: str | None = None,
) -> None:
    MODEL_TOKENS.labels(model=model, direction="input").inc(token_input)
    MODEL_TOKENS.labels(model=model, direction="output").inc(token_output)
    try:
        MODEL_DURATION.labels(model=model, status=status).observe(
            duration_seconds, exemplar=_exemplar(trace_id)
        )
    except Exception:  # noqa: BLE001
        pass


def sse_opened(stream: str) -> None:
    SSE_ACTIVE.labels(stream=stream).inc()


def sse_closed(stream: str, *, disconnected: bool) -> None:
    SSE_ACTIVE.labels(stream=stream).dec()
    SSE_CONNECTIONS.labels(
        stream=stream, result="disconnected" if disconnected else "closed"
    ).inc()


def observe_tool(
    tool: str, status: str, duration_seconds: float, trace_id: str | None = None
) -> None:
    TOOL_CALLS.labels(tool=tool, status=status).inc()
    try:
        TOOL_DURATION.labels(tool=tool).observe(
            duration_seconds, exemplar=_exemplar(trace_id)
        )
    except Exception:  # noqa: BLE001
        pass


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
