from fastapi import FastAPI

from app.core.logging import configure_logging
from app.core.middleware import install_exception_handlers, install_trace_middleware

configure_logging()

app = FastAPI(title="Agent Center", version="0.1.0")
install_trace_middleware(app)
install_exception_handlers(app)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
