from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import CurrentTenant, DbSession
from app.core.responses import ok
from app.domain.prompt import repository

router = APIRouter(prefix="/admin/prompts", tags=["prompts"])


class CreateTemplateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    layer: str = Field(default="AGENT", max_length=20)


class CreateVersionRequest(BaseModel):
    content: str = Field(min_length=1)


class TransitionRequest(BaseModel):
    target: str


def _serialize_version(version) -> dict:
    return {
        "id": version.id,
        "templateId": version.template_id,
        "versionNo": version.version_no,
        "content": version.content,
        "variables": version.variables_json,
        "status": version.status,
        "publishedAt": version.published_at.isoformat() if version.published_at else None,
    }


@router.post("")
async def create_template(payload: CreateTemplateRequest, session: DbSession, ctx: CurrentTenant) -> dict:
    template = await repository.create_template(
        session, ctx, code=payload.code, name=payload.name, layer=payload.layer
    )
    return ok({"id": template.id, "code": template.code, "name": template.name, "layer": template.layer})


@router.post("/{template_id}/versions")
async def create_version(
    template_id: int, payload: CreateVersionRequest, session: DbSession, ctx: CurrentTenant
) -> dict:
    version = await repository.create_draft(session, ctx, template_id, content=payload.content)
    return ok(_serialize_version(version))


@router.post("/{template_id}/versions/{version_id}/transition")
async def transition_version(
    template_id: int, version_id: int, payload: TransitionRequest, session: DbSession, ctx: CurrentTenant
) -> dict:
    version = await repository.transition(session, ctx, version_id, payload.target)
    return ok(_serialize_version(version))
