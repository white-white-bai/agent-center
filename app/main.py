from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1 import (
    agents,
    chat,
    evaluations,
    knowledge,
    knowledge_sync,
    memory,
    notifications,
    operations,
    profile,
    prompts,
    routing,
    tools,
)
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.middleware import install_exception_handlers, install_trace_middleware

configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    from app.core.telemetry import configure_telemetry, shutdown_telemetry

    configure_telemetry()
    try:
        if get_settings().auto_create_tables:
            from app.infrastructure.database.registry import create_all
            from app.infrastructure.database.session import engine

            await create_all(engine)
        yield
    finally:
        shutdown_telemetry()


app = FastAPI(title="Agent Center", version="0.1.0", lifespan=lifespan)
install_trace_middleware(app)
install_exception_handlers(app)

app.include_router(chat.router, prefix="/api/v1")
app.include_router(prompts.router, prefix="/api/v1")
app.include_router(agents.router, prefix="/api/v1")
app.include_router(tools.router, prefix="/api/v1")
app.include_router(operations.router, prefix="/api/v1")
app.include_router(memory.router, prefix="/api/v1")
app.include_router(profile.router, prefix="/api/v1")
app.include_router(routing.router, prefix="/api/v1")
app.include_router(knowledge.router, prefix="/api/v1")
app.include_router(knowledge_sync.router, prefix="/api/v1")
app.include_router(evaluations.router, prefix="/api/v1")
app.include_router(notifications.router, prefix="/api/v1")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
