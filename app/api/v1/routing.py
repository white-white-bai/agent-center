from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import CurrentTenant, DbSession, ModelRouterDep
from app.core.responses import ok
from app.core.tenant import require_admin
from app.runtime import supervisor

router = APIRouter(prefix="/admin", tags=["routing"], dependencies=[Depends(require_admin)])


class RoutePreviewRequest(BaseModel):
    message: str = Field(min_length=1)
    channel: str | None = None
    region: str | None = None


@router.post("/route-preview")
async def route_preview(
    payload: RoutePreviewRequest,
    session: DbSession,
    ctx: CurrentTenant,
    model_router: ModelRouterDep,
) -> dict:
    result = await supervisor.route(
        session,
        ctx,
        message=payload.message,
        channel=payload.channel,
        region=payload.region,
        router=model_router,
    )
    return ok(result.to_dict())
