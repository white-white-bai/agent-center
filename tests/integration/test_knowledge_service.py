from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.tenant import TenantContext
from app.domain.knowledge import service as knowledge_service
from app.domain.knowledge.citations import validate_chunk
from app.domain.knowledge.models import KnowledgeChunk, KnowledgeSpace

CTX = TenantContext(tenant_id="t1", user_id="u1")


async def _published_doc(db_session, *, region: str | None = None, effective_to=None, authority: int = 3):
    space = await knowledge_service.create_space(
        db_session, CTX, code="district", name="区级知识", domain_code="district_service"
    )
    document = await knowledge_service.ingest_document(
        db_session,
        CTX,
        space_id=space.id,
        title="营业执照办理指南",
        content="# 申请材料\n\n申请人需要提交身份证和营业执照申请书。\n\n# 办理时限\n\n五个工作日办结。",
        region_code=region,
        authority_level=authority,
        effective_to=effective_to,
    )
    await knowledge_service.publish_document(db_session, CTX, document.id)
    return space, document


async def test_search_only_returns_published_documents(db_session) -> None:
    space = await knowledge_service.create_space(
        db_session, CTX, code="s1", name="空间1", domain_code="district_service"
    )
    await knowledge_service.ingest_document(
        db_session,
        CTX,
        space_id=space.id,
        title="草稿文档",
        content="营业执照办理材料",
    )

    results = await knowledge_service.search(db_session, CTX, query="营业执照")

    assert results == []


async def test_search_returns_relevant_chunks_with_metadata(db_session) -> None:
    await _published_doc(db_session)

    results = await knowledge_service.search(db_session, CTX, query="营业执照材料")

    assert results
    top = results[0]
    assert top["title"] == "营业执照办理指南"
    assert top["section"] == "申请材料"
    assert top["effectiveStatus"] == "active"


async def test_search_filters_by_region(db_session) -> None:
    await _published_doc(db_session, region="320402")

    matching = await knowledge_service.search(db_session, CTX, query="营业执照", region_code="320402")
    other = await knowledge_service.search(db_session, CTX, query="营业执照", region_code="320404")

    assert matching
    assert other == []


async def test_search_excludes_expired_documents(db_session) -> None:
    await _published_doc(db_session, effective_to=datetime.utcnow() - timedelta(days=1))

    assert await knowledge_service.search(db_session, CTX, query="营业执照") == []


async def test_search_is_tenant_isolated(db_session) -> None:
    await _published_doc(db_session)
    other_ctx = TenantContext(tenant_id="t2", user_id="u2")

    assert await knowledge_service.search(db_session, other_ctx, query="营业执照") == []


async def test_citation_rejects_unknown_or_foreign_chunk(db_session) -> None:
    import pytest

    from app.core.exceptions import NotFoundError

    await _published_doc(db_session)
    chunk = (await db_session.execute(select(KnowledgeChunk))).scalars().first()

    assert await validate_chunk(db_session, CTX, chunk.chunk_id)

    with pytest.raises(NotFoundError):
        await validate_chunk(db_session, TenantContext(tenant_id="t2", user_id="u2"), chunk.chunk_id)


async def test_search_respects_route_rule_space_subset(db_session) -> None:
    from app.domain.knowledge.models import KnowledgeRouteRule

    space_a, _ = await _published_doc(db_session)
    space_b = await knowledge_service.create_space(
        db_session, CTX, code="s2", name="空间2", domain_code="district_service"
    )
    document_b = await knowledge_service.ingest_document(
        db_session,
        CTX,
        space_id=space_b.id,
        title="交易指南",
        content="招投标办理流程",
    )
    await knowledge_service.publish_document(db_session, CTX, document_b.id)
    db_session.add(
        KnowledgeRouteRule(
            tenant_id="t1",
            domain_code="district_service",
            intent_keywords_json=["营业执照"],
            space_ids_json=[space_a.id],
            priority=10,
        )
    )
    await db_session.commit()

    results = await knowledge_service.search(db_session, CTX, query="营业执照", domain_code="district_service")

    assert all(result["title"] == "营业执照办理指南" for result in results)
    assert not any(result["title"] == "交易指南" for result in results)
