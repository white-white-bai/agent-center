from app.core.tenant import TenantContext
from app.domain.knowledge import service

CTX = TenantContext(tenant_id="t1", user_id="u1")


async def test_search_matches_document_title(db_session) -> None:
    space = await service.create_space(
        db_session, CTX, code="title_kb", name="标题检索", domain_code="district_service"
    )
    document = await service.ingest_document(
        db_session,
        CTX,
        space_id=space.id,
        title="新生儿落户指南",
        content="所需材料：出生医学证明、父母双方身份证、结婚证。",
    )
    await service.publish_document(db_session, CTX, document.id)

    results = await service.search(db_session, CTX, query="新生儿落户")

    assert results
    assert results[0]["title"] == "新生儿落户指南"
