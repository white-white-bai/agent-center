from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import AdminContext, CurrentTenant, DbSession
from app.core.responses import ok
from app.domain.knowledge import service

router = APIRouter(tags=["knowledge"])


class CreateSpaceRequest(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    layer: str = Field(default="DOMAIN", max_length=20)
    domainCode: str | None = Field(default=None, max_length=100)


class CreateDocumentRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1)
    regionCode: str | None = Field(default=None, max_length=20)
    authorityLevel: int = Field(default=3, ge=1, le=5)
    effectiveFrom: datetime | None = None
    effectiveTo: datetime | None = None
    sourceUrl: str | None = None
    documentCode: str | None = Field(default=None, max_length=100)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    domainCode: str | None = None
    regionCode: str | None = None
    spaceIds: list[int] | None = None
    topK: int = Field(default=5, ge=1, le=20)


@router.post("/admin/knowledge-spaces")
async def create_space(payload: CreateSpaceRequest, session: DbSession, ctx: AdminContext) -> dict:
    from app.domain.evaluation import audit

    space = await service.create_space(
        session,
        ctx,
        code=payload.code,
        name=payload.name,
        layer=payload.layer,
        domain_code=payload.domainCode,
    )
    await audit.record_audit(
        session,
        ctx,
        action="knowledge.space.create",
        resource_type="knowledge_space",
        resource_id=space.id,
        detail={"code": space.code, "layer": space.layer},
    )
    return ok({"id": space.id, "code": space.code, "name": space.name, "layer": space.layer})


@router.post("/admin/knowledge-spaces/{space_id}/documents")
async def create_document(
    space_id: int, payload: CreateDocumentRequest, session: DbSession, ctx: AdminContext
) -> dict:
    document = await service.ingest_document(
        session,
        ctx,
        space_id=space_id,
        title=payload.title,
        content=payload.content,
        region_code=payload.regionCode,
        authority_level=payload.authorityLevel,
        effective_from=payload.effectiveFrom,
        effective_to=payload.effectiveTo,
        source_url=payload.sourceUrl,
        document_code=payload.documentCode,
    )
    from app.domain.evaluation import audit

    await audit.record_audit(
        session,
        ctx,
        action="knowledge.document.create",
        resource_type="knowledge_document",
        resource_id=document.id,
        detail={"spaceId": space_id, "title": document.title},
    )
    return ok({"id": document.id, "title": document.title, "status": document.status})


@router.post("/admin/knowledge-spaces/{space_id}/documents/{document_id}/publish")
async def publish_document(
    space_id: int, document_id: int, session: DbSession, ctx: AdminContext
) -> dict:
    from app.domain.evaluation import audit

    await service.get_space(session, ctx, space_id)
    document = await service.publish_document(session, ctx, document_id)
    await audit.record_audit(
        session,
        ctx,
        action="knowledge.publish",
        resource_type="knowledge_document",
        resource_id=document.id,
        detail={"spaceId": space_id},
    )
    return ok({"id": document.id, "status": document.status})


class NewVersionRequest(BaseModel):
    content: str = Field(min_length=1)
    title: str | None = Field(default=None, max_length=300)
    regionCode: str | None = Field(default=None, max_length=20)
    authorityLevel: int | None = Field(default=None, ge=1, le=5)
    effectiveFrom: datetime | None = None
    effectiveTo: datetime | None = None
    sourceUrl: str | None = None


@router.post("/admin/knowledge-documents/{document_id}/versions")
async def create_document_version(
    document_id: int, payload: NewVersionRequest, session: DbSession, ctx: AdminContext
) -> dict:
    from app.domain.evaluation import audit

    document = await service.new_version(
        session,
        ctx,
        document_id,
        content=payload.content,
        title=payload.title,
        region_code=payload.regionCode,
        authority_level=payload.authorityLevel,
        effective_from=payload.effectiveFrom,
        effective_to=payload.effectiveTo,
        source_url=payload.sourceUrl,
    )
    await audit.record_audit(
        session,
        ctx,
        action="knowledge.version.create",
        resource_type="knowledge_document",
        resource_id=document.id,
        detail={"previousDocumentId": document_id, "versionNo": document.version_no},
    )
    return ok(
        {
            "id": document.id,
            "documentCode": document.document_code,
            "versionNo": document.version_no,
            "status": document.status,
        }
    )


@router.post("/admin/knowledge-documents/{document_id}/unpublish")
async def unpublish_document(document_id: int, session: DbSession, ctx: AdminContext) -> dict:
    from app.domain.evaluation import audit

    document = await service.unpublish_document(session, ctx, document_id)
    await audit.record_audit(
        session,
        ctx,
        action="knowledge.unpublish",
        resource_type="knowledge_document",
        resource_id=document.id,
    )
    return ok({"id": document.id, "status": document.status})


@router.post("/knowledge/search")
async def search(payload: SearchRequest, session: DbSession, ctx: CurrentTenant) -> dict:
    results = await service.search(
        session,
        ctx,
        query=payload.query,
        domain_code=payload.domainCode,
        region_code=payload.regionCode,
        space_ids=payload.spaceIds,
        top_k=payload.topK,
    )
    return ok(results)
