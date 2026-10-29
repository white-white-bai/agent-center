from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.middleware import install_exception_handlers, install_trace_middleware
from app.core.tenant import TenantContext, get_tenant_context


def _build_app() -> FastAPI:
    app = FastAPI()
    install_trace_middleware(app)
    install_exception_handlers(app)

    @app.get("/whoami")
    async def whoami(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
        return {"tenant": ctx.tenant_id, "user": ctx.user_id, "roles": ctx.roles}

    return app


def test_tenant_context_helpers() -> None:
    ctx = TenantContext(tenant_id="t1", user_id="u1", roles=["admin"])

    assert ctx.has_role("admin")
    assert ctx.has_permission("anything")


def test_missing_credentials_returns_unified_error() -> None:
    response = TestClient(_build_app()).get("/whoami")

    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "AC.AUTH.UNAUTHORIZED"
    assert body["traceId"] == response.headers["X-Trace-Id"]
    assert body["data"] is None


def test_tenant_context_built_from_headers() -> None:
    response = TestClient(_build_app()).get(
        "/whoami",
        headers={"X-Tenant-Id": "t1", "X-User-Id": "u1", "X-Roles": "admin,ops"},
    )

    assert response.status_code == 200
    assert response.json() == {"tenant": "t1", "user": "u1", "roles": ["admin", "ops"]}


def test_trace_id_from_request_header_is_propagated() -> None:
    response = TestClient(_build_app()).get(
        "/whoami",
        headers={"X-Tenant-Id": "t1", "X-User-Id": "u1", "X-Trace-Id": "trace_fixed"},
    )

    assert response.headers["X-Trace-Id"] == "trace_fixed"
