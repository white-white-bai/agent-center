from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import CurrentTenant, DbSession, ModelRouterDep
from app.core.responses import ok
from app.domain.profile import service

router = APIRouter(prefix="/profile", tags=["profile"])


class TagItem(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=300)
    source: str | None = None
    confidence: float = Field(default=0.5, ge=0, le=1)


class MergeTagsRequest(BaseModel):
    tags: list[TagItem] = Field(min_length=1)


@router.get("/summary")
async def profile_summary(session: DbSession, ctx: CurrentTenant) -> dict:
    summary = await service.get_profile_summary(session, ctx)
    matters = await service.get_active_matters(session, ctx)
    return ok({"summary": summary, "activeMatters": matters})


@router.get("/suggestions")
async def suggestions(session: DbSession, ctx: CurrentTenant, model_router: ModelRouterDep) -> dict:
    from app.domain.profile.proactive import generate_suggestions

    return ok(await generate_suggestions(session, ctx, router=model_router))


@router.get("/tags")
async def list_tags(session: DbSession, ctx: CurrentTenant) -> dict:
    tags = await service.list_tags(session, ctx)
    return ok(
        [
            {
                "key": tag.tag_key,
                "value": tag.tag_value,
                "source": tag.source,
                "confidence": tag.confidence,
            }
            for tag in tags
        ]
    )


@router.post("/tags")
async def merge_tags(payload: MergeTagsRequest, session: DbSession, ctx: CurrentTenant) -> dict:
    stored = await service.merge_tags(
        session, ctx, [tag.model_dump() for tag in payload.tags]
    )
    return ok([{"key": tag.tag_key, "value": tag.tag_value} for tag in stored])
