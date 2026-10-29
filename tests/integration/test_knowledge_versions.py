from sqlalchemy import select

HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "admin1", "X-Roles": "admin"}


async def _create_space(async_client) -> int:
    return (
        await async_client.post(
            "/api/v1/admin/knowledge-spaces",
            json={"code": "version_kb", "name": "版本知识", "domainCode": "district_service"},
            headers=HEADERS,
        )
    ).json()["data"]["id"]


async def _create_and_publish(async_client, space_id: int, content: str, title: str = "指南") -> int:
    document_id = (
        await async_client.post(
            f"/api/v1/admin/knowledge-spaces/{space_id}/documents",
            json={"title": title, "content": content},
            headers=HEADERS,
        )
    ).json()["data"]["id"]
    await async_client.post(
        f"/api/v1/admin/knowledge-spaces/{space_id}/documents/{document_id}/publish",
        headers=HEADERS,
    )
    return document_id


async def test_new_version_supersedes_old_and_search_returns_latest(async_client, db_session) -> None:
    from app.domain.knowledge.models import KnowledgeChunk, KnowledgeDocument

    space_id = await _create_space(async_client)
    v1_id = await _create_and_publish(async_client, space_id, "办理营业执照需要身份证。")

    version = await async_client.post(
        f"/api/v1/admin/knowledge-documents/{v1_id}/versions",
        json={"content": "办理营业执照需要身份证和场地证明。"},
        headers=HEADERS,
    )
    v2_id = version.json()["data"]["id"]
    assert version.json()["data"]["versionNo"] == 2

    published = await async_client.post(
        f"/api/v1/admin/knowledge-spaces/{space_id}/documents/{v2_id}/publish",
        headers=HEADERS,
    )
    assert published.json()["data"]["status"] == "PUBLISHED"

    old = await db_session.get(KnowledgeDocument, v1_id)
    assert old.status == "SUPERSEDED"
    old_chunks = (
        await db_session.execute(
            select(KnowledgeChunk).where(KnowledgeChunk.document_id == v1_id)
        )
    ).scalars().all()
    assert {chunk.status for chunk in old_chunks} == {"ARCHIVED"}

    results = (
        await async_client.post(
            "/api/v1/knowledge/search",
            json={"query": "场地证明", "topK": 5},
            headers=HEADERS,
        )
    ).json()["data"]
    assert results
    assert results[0]["documentId"] == str(v2_id)


async def test_unpublish_removes_document_from_search(async_client) -> None:
    space_id = await _create_space(async_client)
    document_id = await _create_and_publish(async_client, space_id, "公共资源交易需要投标保证金。")

    before = (
        await async_client.post(
            "/api/v1/knowledge/search",
            json={"query": "投标保证金", "topK": 5},
            headers=HEADERS,
        )
    ).json()["data"]
    assert before

    await async_client.post(
        f"/api/v1/admin/knowledge-documents/{document_id}/unpublish", headers=HEADERS
    )
    after = (
        await async_client.post(
            "/api/v1/knowledge/search",
            json={"query": "投标保证金", "topK": 5},
            headers=HEADERS,
        )
    ).json()["data"]
    assert after == []


async def test_new_version_is_tenant_isolated(async_client) -> None:
    space_id = await _create_space(async_client)
    document_id = await _create_and_publish(async_client, space_id, "内容")

    response = await async_client.post(
        f"/api/v1/admin/knowledge-documents/{document_id}/versions",
        json={"content": "新内容"},
        headers={"X-Tenant-Id": "t2", "X-User-Id": "admin2", "X-Roles": "admin"},
    )

    assert response.status_code == 404
