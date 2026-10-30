from app.core import telemetry


def test_span_is_noop_when_disabled() -> None:
    telemetry.reset_telemetry()

    with telemetry.span("disabled.span", {"ac.test": 1}) as current:
        current.set_attribute("ac.answer", 42)

    assert telemetry.current_trace_id() is None


def test_span_exports_attributes_and_error() -> None:
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    telemetry._tracer = provider.get_tracer("test")
    telemetry._provider = provider
    try:
        with telemetry.span("unit.span", {"ac.value": 1}) as current:
            current.set_attribute("ac.status", "RUNNING")
            telemetry.mark_error(current, "AC.TEST.ERROR", "boom")
    finally:
        provider.shutdown()
        telemetry.reset_telemetry()

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].attributes["ac.value"] == 1
    assert spans[0].attributes["ac.status"] == "RUNNING"
    assert spans[0].attributes["error.code"] == "AC.TEST.ERROR"
    assert spans[0].status.status_code.name == "ERROR"
