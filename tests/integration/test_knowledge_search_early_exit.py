import pytest

from app.core.tenant import TenantContext
from app.domain.knowledge import service


async def test_search_skips_embedding_when_tenant_has_no_spaces(db_session, monkeypatch) -> None:
    def fail_client():
        raise AssertionError("无知识空间时不应构建 embedding 客户端")

    monkeypatch.setattr(
        "app.integrations.llm.openai_client.build_embedding_client", fail_client
    )

    results = await service.search(
        db_session,
        TenantContext(tenant_id="empty_tenant", user_id="u1"),
        query="营业执照",
        domain_code="district_service",
    )

    assert results == []


async def test_search_skips_embedding_when_no_candidate_chunks(db_session, monkeypatch) -> None:
    space = await service.create_space(
        db_session,
        TenantContext(tenant_id="t1", user_id="u1"),
        code="empty_kb",
        name="空知识库",
        domain_code="district_service",
    )

    def fail_client():
        raise AssertionError("无候选切片时不应构建 embedding 客户端")

    monkeypatch.setattr(
        "app.integrations.llm.openai_client.build_embedding_client", fail_client
    )

    results = await service.search(
        db_session,
        TenantContext(tenant_id="t1", user_id="u1"),
        query="营业执照",
        domain_code="district_service",
    )

    assert results == []
    assert space.id > 0
