from fastapi import FastAPI

from app.api.v1 import agents, chat, operations, prompts, tools
from app.core.logging import configure_logging
from app.core.middleware import install_exception_handlers, install_trace_middleware

configure_logging()

app = FastAPI(title="Agent Center", version="0.1.0")
install_trace_middleware(app)
install_exception_handlers(app)

app.include_router(chat.router, prefix="/api/v1")
app.include_router(prompts.router, prefix="/api/v1")
app.include_router(agents.router, prefix="/api/v1")
app.include_router(tools.router, prefix="/api/v1")
app.include_router(operations.router, prefix="/api/v1")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
