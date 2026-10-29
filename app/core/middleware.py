import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

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


def install_trace_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def trace_middleware(request: Request, call_next):
        incoming = request.headers.get("X-Trace-Id") or new_trace_id()
        set_trace_id(incoming)
        tenant_token = set_current_tenant(request.headers.get("X-Tenant-Id"))
        try:
            response = await call_next(request)
        finally:
            reset_current_tenant(tenant_token)
        response.headers["X-Trace-Id"] = incoming
        return response
