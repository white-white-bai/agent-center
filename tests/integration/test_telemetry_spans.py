from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.core import telemetry
from app.domain.tool.executor import function_tool_executor

HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "u1", "X-Roles": "admin"}


async def _prepare_agent(client) -> None:
    agent_id = (
        await client.post(
            "/api/v1/admin/agents",
            json={"code": "span_agent", "name": "链路测试", "domain_code": "district_service"},
            headers=HEADERS,
        )
    ).json()["data"]["id"]
    version_id = (
        await client.post(
            f"/api/v1/admin/agents/{agent_id}/versions",
            json={"role": "顾问", "model_policy": {"primary": "stub-primary", "max_steps": 3}},
            headers=HEADERS,
        )
    ).json()["data"]["id"]
    await client.post(
        f"/api/v1/admin/agents/{agent_id}/publish",
        json={"version_id": version_id},
        headers=HEADERS,
    )


async def test_chat_and_tool_spans_share_trace(async_client) -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    telemetry._tracer = provider.get_tracer("test")
    telemetry._provider = provider

    async def echo(arguments, context):
        return {"echo": arguments}

    function_tool_executor.register("span_echo", echo)
    try:
        await _prepare_agent(async_client)
        session_id = (
            await async_client.post(
                "/api/v1/chat/sessions", json={"channel": "web"}, headers=HEADERS
            )
        ).json()["data"]["sessionId"]
        response = await async_client.post(
            f"/api/v1/chat/sessions/{session_id}/messages",
            json={"message": "你好"},
            headers={**HEADERS, "Accept": "text/event-stream"},
        )
        assert response.status_code == 200

        await async_client.post(
            "/api/v1/admin/tools",
            json={"tool_code": "span_echo", "name": "链路回显", "source_type": "FUNCTION"},
            headers=HEADERS,
        )
        tool_response = await async_client.post(
            "/api/v1/admin/tools/span_echo/test",
            json={"arguments": {"q": "x"}},
            headers=HEADERS,
        )
        assert tool_response.status_code == 200
    finally:
        provider.shutdown()
        telemetry.reset_telemetry()

    spans = exporter.get_finished_spans()
    by_name = {}
    for span in spans:
        by_name.setdefault(span.name, []).append(span)

    assert "http.request" in by_name
    assert "agent.run" in by_name
    assert "model.complete" in by_name
    assert "tool.execute" in by_name

    chat_http_span = next(
        span
        for span in by_name["http.request"]
        if span.attributes.get("url.path", "").endswith("/messages")
    )
    tool_http_span = next(
        span
        for span in by_name["http.request"]
        if span.attributes.get("url.path", "").endswith("/test")
    )
    run_span = by_name["agent.run"][0]
    model_span = by_name["model.complete"][0]
    tool_span = by_name["tool.execute"][0]

    assert chat_http_span.attributes["http.request.method"] == "POST"
    assert chat_http_span.attributes["ac.tenant_id"] == "t1"
    assert run_span.attributes["ac.agent_code"] == "span_agent"
    assert run_span.attributes["ac.run.status"] == "COMPLETED"
    assert model_span.attributes["gen_ai.request.model"] == "stub-primary"
    assert model_span.attributes["gen_ai.usage.input_tokens"] >= 0
    assert tool_span.attributes["ac.tool.code"] == "span_echo"
    assert tool_span.attributes["ac.tool.status"] == "SUCCESS"

    assert run_span.context.trace_id == chat_http_span.context.trace_id
    assert model_span.context.trace_id == run_span.context.trace_id
    assert tool_span.context.trace_id == tool_http_span.context.trace_id
    assert run_span.parent.span_id == chat_http_span.context.span_id
    assert model_span.parent.span_id == run_span.context.span_id
