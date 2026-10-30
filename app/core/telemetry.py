import logging
from contextlib import contextmanager
from typing import Any, Iterator

from app.core.config import get_settings

logger = logging.getLogger(__name__)

try:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
    from opentelemetry.trace import Status, StatusCode

    OTEL_AVAILABLE = True
except ImportError:  # pragma: no cover - 依赖未安装时整体降级
    trace = None
    Status = None
    StatusCode = None
    OTEL_AVAILABLE = False

_tracer = None
_provider = None


class NoopSpan:
    def set_attribute(self, key: str, value: Any) -> None:
        return None

    def set_attributes(self, attributes: dict[str, Any]) -> None:
        return None

    def set_status(self, status: Any) -> None:
        return None

    def record_exception(self, exception: BaseException) -> None:
        return None


NOOP_SPAN = NoopSpan()


def _clean_attributes(attributes: dict[str, Any] | None) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in (attributes or {}).items():
        if value is None:
            continue
        if isinstance(value, (bool, str, int, float)):
            cleaned[key] = value
        elif isinstance(value, (list, tuple)) and all(
            isinstance(item, (bool, str, int, float)) for item in value
        ):
            cleaned[key] = list(value)
        else:
            cleaned[key] = str(value)
    return cleaned


def configure_telemetry(settings=None) -> bool:
    global _provider, _tracer
    settings = settings or get_settings()
    if not settings.otel_enabled:
        return False
    if not OTEL_AVAILABLE:
        logger.warning("AC_OTEL_ENABLED=true 但未安装 opentelemetry 依赖，Span 已禁用")
        return False
    if _provider is not None:
        return True

    ratio = min(max(float(settings.otel_sample_ratio), 0.0), 1.0)
    provider = TracerProvider(
        resource=Resource.create(
            {"service.name": settings.otel_service_name, "service.version": "0.1.0"}
        ),
        sampler=ParentBased(TraceIdRatioBased(ratio)),
    )
    if settings.otel_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter(
            endpoint=settings.otel_endpoint,
            timeout=settings.otel_timeout_ms / 1000,
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
    else:
        logger.warning("AC_OTEL_ENABLED=true 但未配置 AC_OTEL_ENDPOINT，Span 不会导出")

    trace.set_tracer_provider(provider)
    _provider = provider
    _tracer = provider.get_tracer("agent-center")
    return True


def shutdown_telemetry() -> None:
    global _provider, _tracer
    if _provider is not None:
        try:
            _provider.shutdown()
        except Exception:  # noqa: BLE001 - 关闭失败不影响进程退出
            pass
    _provider = None
    _tracer = None


def reset_telemetry() -> None:
    """测试或热重载时清除全局状态。"""
    global _provider, _tracer
    _provider = None
    _tracer = None


@contextmanager
def span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
    if not OTEL_AVAILABLE or _tracer is None:
        yield NOOP_SPAN
        return
    with _tracer.start_as_current_span(
        name,
        attributes=_clean_attributes(attributes),
        record_exception=True,
        set_status_on_exception=True,
    ) as current:
        yield current


def mark_error(current: Any, code: str, message: str | None = None) -> None:
    if not OTEL_AVAILABLE or current is NOOP_SPAN:
        return
    try:
        current.set_attribute("error.code", code)
        current.set_status(Status(StatusCode.ERROR, message or code))
    except Exception:  # noqa: BLE001 - 埋点失败不得影响业务
        pass


def current_trace_id() -> str | None:
    if not OTEL_AVAILABLE or _tracer is None:
        return None
    try:
        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            return format(span_context.trace_id, "032x")
    except Exception:  # noqa: BLE001
        return None
    return None
