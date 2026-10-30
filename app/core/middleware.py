import logging
import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core import metrics, telemetry
from app.core.exceptions import AppError
from app.core.responses import fail
from app.core.tenant import reset_current_tenant, set_current_tenant
from app.core.tracing import ensure_trace_id, new_trace_id, set_trace_id

logger = logging.getLogger(__name__)


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        body = fail(exc.code, exc.message, ensure_trace_id())
        if exc.detail is not None:
            body["detail"] = exc.detail
        return JSONResponse(status_code=exc.status_code, content=body)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        body = fail("AC.COMMON.VALIDATION_FAILED", "参数校验失败", ensure_trace_id())
        body["detail"] = exc.errors()
        return JSONResponse(status_code=422, content=body)

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error: %s", exc)
        return JSONResponse(
            status_code=500,
            content=fail("AC.COMMON.INTERNAL_ERROR", "服务内部错误", ensure_trace_id()),
        )


def _join_route_path(raw_path: str, route_path: str) -> str:
    """把嵌套路由的相对模板与真实路径前缀拼成完整模板。"""
    raw_parts = [part for part in raw_path.strip("/").split("/") if part]
    route_parts = [part for part in route_path.strip("/").split("/") if part]
    if not route_parts:
        return "/"
    for offset in range(len(raw_parts) - len(route_parts) + 1):
        window = raw_parts[offset : offset + len(route_parts)]
        if all("{" in template or template == actual for template, actual in zip(route_parts, window)):
            return "/" + "/".join(raw_parts[:offset] + route_parts)
    return route_path


def _metric_route(scope: Scope, status_code: int) -> str:
    route_path = getattr(scope.get("route"), "path", None)
    if route_path:
        return _join_route_path(scope.get("path") or "", route_path)
    if status_code == 404:
        return "unmatched"
    return scope.get("path") or "unknown"


class TraceMiddleware:
    """纯 ASGI 中间件，Span 覆盖到流式响应结束。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        incoming = headers.get("x-trace-id") or new_trace_id()
        set_trace_id(incoming)
        tenant_token = set_current_tenant(headers.get("x-tenant-id"))
        status_code = 500
        started = time.perf_counter()
        attributes = {
            "http.request.method": scope.get("method"),
            "url.path": scope.get("path"),
            "url.scheme": scope.get("scheme"),
            "server.address": scope.get("server", (None, None))[0],
            "ac.trace_id": incoming,
            "ac.tenant_id": headers.get("x-tenant-id"),
        }

        with telemetry.span("http.request", attributes) as current:
            # 在 Span 刚开始时捕获，避免内层框架切换上下文后丢失。
            trace_id = telemetry.current_trace_id()

            async def send_wrapper(message: Message) -> None:
                nonlocal status_code
                if message["type"] == "http.response.start":
                    status_code = int(message["status"])
                    MutableHeaders(scope=message)["X-Trace-Id"] = incoming
                await send(message)

            try:
                await self.app(scope, receive, send_wrapper)
            except Exception as exc:  # noqa: BLE001 - 记录后继续抛出
                telemetry.mark_error(current, "AC.UNHANDLED", type(exc).__name__)
                raise
            finally:
                current.set_attribute("http.response.status_code", status_code)
                if status_code >= 500:
                    telemetry.mark_error(current, "HTTP_5XX", str(status_code))
                metric_route = _metric_route(scope, status_code)
                if metric_route != "/metrics":
                    metrics.observe_http(
                        method=scope.get("method") or "UNKNOWN",
                        route=metric_route,
                        status=status_code,
                        duration_seconds=time.perf_counter() - started,
                        trace_id=trace_id,
                    )
                reset_current_tenant(tenant_token)


def install_trace_middleware(app: FastAPI) -> None:
    app.add_middleware(TraceMiddleware)
