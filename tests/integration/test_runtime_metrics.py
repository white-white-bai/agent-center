from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.core import telemetry
from app.domain.tool.executor import function_tool_executor

HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "u1", "X-Roles": "admin"}


async def test_metrics_endpoint_uses_route_template(async_client) -> None:
    await async_client.get("/healthz")
    await async_client.get("/api/v1/chat/sessions/1/nope")

    response = await async_client.get("/metrics")

    assert response.status_code == 200
    assert "openmetrics-text" in response.headers["content-type"]
    text = response.text
    assert 'agent_center_http_requests_total{method="GET",route="/healthz",status="200"}' in text
    assert "agent_center_http_request_duration_seconds_bucket" in text
    assert 'route="unmatched"' in text


async def test_metrics_include_trace_exemplar(async_client) -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    telemetry._tracer = provider.get_tracer("test")
    telemetry._provider = provider
    try:
        await async_client.get("/healthz")
        text = (await async_client.get("/metrics")).text
    finally:
        provider.shutdown()
        telemetry.reset_telemetry()

    assert 'trace_id="' in text


async def test_run_model_tool_metrics_are_recorded(async_client) -> None:
    agent_id = (
        await async_client.post(
            "/api/v1/admin/agents",
            json={"code": "metrics_agent", "name": "指标", "domain_code": "district_service"},
            headers=HEADERS,
        )
    ).json()["data"]["id"]
    version_id = (
        await async_client.post(
            f"/api/v1/admin/agents/{agent_id}/versions",
            json={"role": "顾问", "model_policy": {"primary": "stub-primary", "max_steps": 3}},
            headers=HEADERS,
        )
    ).json()["data"]["id"]
    await async_client.post(
        f"/api/v1/admin/agents/{agent_id}/publish",
        json={"version_id": version_id},
        headers=HEADERS,
    )
    session_id = (
        await async_client.post(
            "/api/v1/chat/sessions", json={"channel": "web"}, headers=HEADERS
        )
    ).json()["data"]["sessionId"]
    await async_client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"message": "你好"},
        headers={**HEADERS, "Accept": "text/event-stream"},
    )

    async def echo(arguments, context):
        return {"ok": True}

    function_tool_executor.register("metrics_echo", echo)
    await async_client.post(
        "/api/v1/admin/tools",
        json={"tool_code": "metrics_echo", "name": "指标回显", "source_type": "FUNCTION"},
        headers=HEADERS,
    )
    await async_client.post(
        "/api/v1/admin/tools/metrics_echo/test",
        json={"arguments": {}},
        headers=HEADERS,
    )

    text = (await async_client.get("/metrics")).text

    assert 'agent_center_runs_total{status="COMPLETED"}' in text
    assert 'agent_center_model_duration_seconds_count{model="stub-primary",status="SUCCESS"}' in text
    assert 'agent_center_model_tokens_total{direction="input",model="stub-primary"}' in text
    assert 'agent_center_tool_calls_total{status="SUCCESS",tool="metrics_echo"}' in text
    assert 'route="/api/v1/chat/sessions/{session_id}/messages"' in text, [
        line for line in text.splitlines() if "sessions" in line
    ]
