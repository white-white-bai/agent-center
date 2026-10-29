from sqlalchemy import select

from app.core.tenant import TenantContext
from app.domain.knowledge import service, sync
from app.domain.knowledge.models import KnowledgeDocument

CTX = TenantContext(tenant_id="t1", user_id="u1")

DOCS = [
    {
        "document_code": "doc_license",
        "title": "营业执照办理指南",
        "content": "# 申请材料\n\n提交身份证和申请书。",
    },
    {
        "document_code": "doc_tax",
        "title": "税务登记指南",
        "content": "# 办理流程\n\n先办理营业执照，再办理税务登记。",
    },
]


async def _space(db_session):
    return await service.create_space(
        db_session, CTX, code="sync_space", name="同步空间", domain_code="district_service"
    )


async def test_sync_task_ingests_and_publishes_documents(db_session) -> None:
    space = await _space(db_session)
    task = await sync.create_sync_task(db_session, CTX, space_id=space.id, source_type="UPLOAD")

    result = await sync.run_sync_task(db_session, CTX, task, documents=DOCS)

    assert result.status == "SUCCESS"
    assert result.checkpoint_json["processed"] == ["doc_license", "doc_tax"]
    documents = (await db_session.execute(select(KnowledgeDocument))).scalars().all()
    assert {document.status for document in documents} == {"PUBLISHED"}
    results = await service.search(db_session, CTX, query="营业执照")
    assert results


async def test_sync_task_skips_existing_documents_idempotently(db_session) -> None:
    space = await _space(db_session)
    first = await sync.create_sync_task(db_session, CTX, space_id=space.id)
    await sync.run_sync_task(db_session, CTX, first, documents=DOCS)

    second = await sync.create_sync_task(db_session, CTX, space_id=space.id)
    await sync.run_sync_task(db_session, CTX, second, documents=DOCS)

    documents = (await db_session.execute(select(KnowledgeDocument))).scalars().all()
    assert len(documents) == 2


async def test_sync_task_records_failure_and_retries(db_session) -> None:
    space = await _space(db_session)
    task = await sync.create_sync_task(db_session, CTX, space_id=space.id, source_ref="http://bad")

    async def failing_fetcher(source_ref: str) -> list[dict]:
        raise RuntimeError("source unavailable")

    result = await sync.run_sync_task(db_session, CTX, task, fetcher=failing_fetcher, max_retries=2)

    assert result.status == "PENDING"
    assert result.retry_count == 1
    assert "source unavailable" in (result.error_message or "")

    result = await sync.run_sync_task(db_session, CTX, result, fetcher=failing_fetcher, max_retries=2)
    assert result.status == "FAILED"
    assert result.retry_count == 2
