import hashlib
import re
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.core.tenant import TenantContext
from app.domain.knowledge.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeRouteRule,
    KnowledgeSpace,
)

HEADING_PATTERN = re.compile(r"^(#{1,6}\s+.+|第[一二三四五六七八九十百]+[章节条]\s*.+|[\u4e00-\u9fff]{1,20}、)$")


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def split_text(text: str, *, max_chars: int = 300, overlap: int = 50) -> list[dict]:
    """按段落与标题切分，尽量保持条款完整。"""
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()]
    chunks: list[dict] = []
    current = ""
    section = ""
    section_before = ""
    for paragraph in paragraphs:
        first_line = paragraph.splitlines()[0].strip()
        if HEADING_PATTERN.match(first_line):
            section = first_line.lstrip("#").strip()
            if current:
                chunks.append({"section": section_before, "content": current[:max_chars]})
                current = ""
            section_before = section
            current = paragraph
            continue
        if len(current) + len(paragraph) + 1 <= max_chars:
            current = f"{current}\n{paragraph}".strip()
            continue
        if current:
            chunks.append({"section": section_before, "content": current[:max_chars]})
        tail = current[-overlap:] if current and overlap else ""
        current = f"{tail}\n{paragraph}".strip()
        section_before = section
        while len(current) > max_chars:
            chunks.append({"section": section_before, "content": current[:max_chars]})
            current = current[max_chars - overlap :]
    if current:
        chunks.append({"section": section_before or section, "content": current[:max_chars]})
    return chunks


async def create_space(
    session: AsyncSession,
    ctx: TenantContext,
    *,
    code: str,
    name: str,
    layer: str = "DOMAIN",
    domain_code: str | None = None,
) -> KnowledgeSpace:
    space = KnowledgeSpace(
        tenant_id=ctx.tenant_id,
        code=code,
        name=name,
        layer=layer,
        domain_code=domain_code,
    )
    session.add(space)
    await session.commit()
    await session.refresh(space)
    return space


async def get_space(session: AsyncSession, ctx: TenantContext, space_id: int) -> KnowledgeSpace:
    result = await session.execute(
        select(KnowledgeSpace).where(
            KnowledgeSpace.id == space_id, KnowledgeSpace.tenant_id == ctx.tenant_id
        )
    )
    space = result.scalar_one_or_none()
    if space is None:
        raise NotFoundError("知识空间不存在")
    return space


async def ingest_document(
    session: AsyncSession,
    ctx: TenantContext,
    *,
    space_id: int,
    title: str,
    content: str,
    region_code: str | None = None,
    authority_level: int = 3,
    effective_from: datetime | None = None,
    effective_to: datetime | None = None,
    source_url: str | None = None,
    document_code: str | None = None,
) -> KnowledgeDocument:
    space = await get_space(session, ctx, space_id)
    document = KnowledgeDocument(
        tenant_id=ctx.tenant_id,
        space_id=space.id,
        document_code=document_code or f"doc_{uuid4().hex[:12]}",
        title=title,
        version_no=1,
        status="DRAFT",
        region_code=region_code,
        authority_level=authority_level,
        effective_from=effective_from,
        effective_to=effective_to,
        source_url=source_url,
        content_hash=content_hash(content),
    )
    session.add(document)
    await session.commit()
    await session.refresh(document)

    chunks = split_text(content)
    for index, chunk in enumerate(chunks):
        session.add(
            KnowledgeChunk(
                tenant_id=ctx.tenant_id,
                chunk_id=f"chunk_{document.id}_{index}_{uuid4().hex[:6]}",
                document_id=document.id,
                document_version=document.version_no,
                title=title,
                section=chunk["section"],
                content=chunk["content"],
                domain_code=space.domain_code,
                region_code=region_code,
                effective_from=effective_from,
                effective_to=effective_to,
                authority_level=authority_level,
                source_url=source_url,
                content_hash=content_hash(chunk["content"]),
                status="DRAFT",
            )
        )
    await session.commit()
    await _index_chunks(session, ctx, document.id, chunks)
    return document


async def _index_chunks(session: AsyncSession, ctx: TenantContext, document_id: int, chunks: list[dict]) -> None:
    try:
        from app.integrations.llm.openai_client import build_embedding_client
        from app.infrastructure.vector.store import get_vector_store

        result = await session.execute(
            select(KnowledgeChunk).where(
                KnowledgeChunk.document_id == document_id,
                KnowledgeChunk.tenant_id == ctx.tenant_id,
            )
        )
        rows = list(result.scalars().all())
        if not rows:
            return
        vectors = await build_embedding_client().embed([row.content for row in rows])
        get_vector_store().upsert(
            ctx.tenant_id,
            [
                (
                    row.chunk_id,
                    vector,
                    {
                        "status": "DRAFT",
                        "domain_code": row.domain_code,
                        "region_code": row.region_code,
                    },
                )
                for row, vector in zip(rows, vectors)
            ],
        )
    except Exception:  # noqa: BLE001 - 向量化失败不阻塞入库，检索降级为关键词
        pass


async def get_document(session: AsyncSession, ctx: TenantContext, document_id: int) -> KnowledgeDocument:
    result = await session.execute(
        select(KnowledgeDocument).where(
            KnowledgeDocument.id == document_id, KnowledgeDocument.tenant_id == ctx.tenant_id
        )
    )
    document = result.scalar_one_or_none()
    if document is None:
        raise NotFoundError("知识文档不存在")
    return document


async def _archive_chunks(session: AsyncSession, ctx: TenantContext, document_id: int) -> list[str]:
    result = await session.execute(
        select(KnowledgeChunk).where(
            KnowledgeChunk.document_id == document_id,
            KnowledgeChunk.tenant_id == ctx.tenant_id,
        )
    )
    chunks = list(result.scalars().all())
    for chunk in chunks:
        chunk.status = "ARCHIVED"
    await session.commit()

    chunk_ids = [chunk.chunk_id for chunk in chunks]
    try:
        from app.infrastructure.vector.store import get_vector_store

        get_vector_store().delete(ctx.tenant_id, chunk_ids)
    except Exception:  # noqa: BLE001 - 向量删除失败不影响下架
        pass
    return chunk_ids


async def new_version(
    session: AsyncSession,
    ctx: TenantContext,
    document_id: int,
    *,
    content: str,
    title: str | None = None,
    region_code: str | None = None,
    authority_level: int | None = None,
    effective_from: datetime | None = None,
    effective_to: datetime | None = None,
    source_url: str | None = None,
) -> KnowledgeDocument:
    """基于已有文档创建新版本，旧版本置为 SUPERSEDED 并下架旧切片。"""
    old = await get_document(session, ctx, document_id)
    old.status = "SUPERSEDED"
    await session.commit()
    await _archive_chunks(session, ctx, old.id)

    document = KnowledgeDocument(
        tenant_id=ctx.tenant_id,
        space_id=old.space_id,
        document_code=old.document_code,
        title=title or old.title,
        version_no=old.version_no + 1,
        status="DRAFT",
        region_code=region_code if region_code is not None else old.region_code,
        authority_level=authority_level if authority_level is not None else old.authority_level,
        effective_from=effective_from if effective_from is not None else old.effective_from,
        effective_to=effective_to if effective_to is not None else old.effective_to,
        source_url=source_url if source_url is not None else old.source_url,
        content_hash=content_hash(content),
    )
    session.add(document)
    await session.commit()
    await session.refresh(document)

    chunks = split_text(content)
    for index, chunk in enumerate(chunks):
        session.add(
            KnowledgeChunk(
                tenant_id=ctx.tenant_id,
                chunk_id=f"chunk_{document.id}_{index}_{uuid4().hex[:6]}",
                document_id=document.id,
                document_version=document.version_no,
                title=document.title,
                section=chunk["section"],
                content=chunk["content"],
                domain_code=(await get_space(session, ctx, document.space_id)).domain_code,
                region_code=document.region_code,
                effective_from=document.effective_from,
                effective_to=document.effective_to,
                authority_level=document.authority_level,
                source_url=document.source_url,
                content_hash=content_hash(chunk["content"]),
                status="DRAFT",
            )
        )
    await session.commit()
    await _index_chunks(session, ctx, document.id, chunks)
    return document


async def unpublish_document(
    session: AsyncSession, ctx: TenantContext, document_id: int
) -> KnowledgeDocument:
    document = await get_document(session, ctx, document_id)
    document.status = "ARCHIVED"
    await session.commit()
    await _archive_chunks(session, ctx, document_id)
    await session.refresh(document)
    return document


async def publish_document(session: AsyncSession, ctx: TenantContext, document_id: int) -> KnowledgeDocument:
    result = await session.execute(
        select(KnowledgeDocument).where(
            KnowledgeDocument.id == document_id, KnowledgeDocument.tenant_id == ctx.tenant_id
        )
    )
    document = result.scalar_one_or_none()
    if document is None:
        raise NotFoundError("知识文档不存在")
    if document.status == "PUBLISHED":
        raise ConflictError("文档已发布")

    chunks = await session.execute(
        select(KnowledgeChunk).where(
            KnowledgeChunk.document_id == document.id,
            KnowledgeChunk.tenant_id == ctx.tenant_id,
        )
    )
    chunk_list = list(chunks.scalars().all())
    if not chunk_list:
        raise ConflictError("文档没有可用切片，不能发布")
    for chunk in chunk_list:
        chunk.status = "ACTIVE"
    document.status = "PUBLISHED"
    await session.commit()

    try:
        from app.infrastructure.vector.store import get_vector_store
        from app.integrations.llm.openai_client import build_embedding_client

        vectors = await build_embedding_client().embed([chunk.content for chunk in chunk_list])
        get_vector_store().upsert(
            ctx.tenant_id,
            [
                (chunk.chunk_id, vector, {"status": "ACTIVE"})
                for chunk, vector in zip(chunk_list, vectors)
            ],
        )
    except Exception:  # noqa: BLE001 - 向量化失败时检索降级为关键词
        pass

    await session.refresh(document)
    return document


def _ngrams(text: str, size: int = 2) -> set[str]:
    cleaned = re.sub(r"\s+", "", text)
    if len(cleaned) <= size:
        return {cleaned} if cleaned else set()
    return {cleaned[index : index + size] for index in range(len(cleaned) - size + 1)}


async def _resolve_space_ids(
    session: AsyncSession,
    ctx: TenantContext,
    *,
    query: str,
    domain_code: str | None,
    space_ids: list[int] | None,
) -> list[int] | None:
    if space_ids:
        return space_ids
    result = await session.execute(
        select(KnowledgeRouteRule)
        .where(KnowledgeRouteRule.tenant_id == ctx.tenant_id)
        .order_by(KnowledgeRouteRule.priority.desc())
    )
    for rule in result.scalars().all():
        if domain_code and rule.domain_code != domain_code:
            continue
        if any(keyword and keyword in query for keyword in (rule.intent_keywords_json or [])):
            return list(rule.space_ids_json or [])
    if domain_code:
        spaces = await session.execute(
            select(KnowledgeSpace.id).where(
                KnowledgeSpace.tenant_id == ctx.tenant_id,
                KnowledgeSpace.domain_code == domain_code,
            )
        )
        return list(spaces.scalars().all())
    return None


async def search(
    session: AsyncSession,
    ctx: TenantContext,
    *,
    query: str,
    domain_code: str | None = None,
    region_code: str | None = None,
    space_ids: list[int] | None = None,
    top_k: int = 5,
) -> list[dict]:
    """混合检索首期实现：关键词 n-gram 打分 + 地域/有效期/权限过滤 + 权威度排序。"""
    now = datetime.utcnow()
    resolved_space_ids = await _resolve_space_ids(
        session, ctx, query=query, domain_code=domain_code, space_ids=space_ids
    )
    if resolved_space_ids == []:
        return []
    query_stmt = select(KnowledgeChunk, KnowledgeDocument).join(
        KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id
    ).where(
        KnowledgeChunk.tenant_id == ctx.tenant_id,
        KnowledgeChunk.status == "ACTIVE",
        KnowledgeDocument.status == "PUBLISHED",
    )
    if resolved_space_ids is not None:
        query_stmt = query_stmt.where(KnowledgeDocument.space_id.in_(resolved_space_ids))
    if region_code:
        query_stmt = query_stmt.where(
            (KnowledgeChunk.region_code.is_(None)) | (KnowledgeChunk.region_code == region_code)
        )
    if domain_code:
        query_stmt = query_stmt.where(
            (KnowledgeChunk.domain_code.is_(None)) | (KnowledgeChunk.domain_code == domain_code)
        )

    rows = (await session.execute(query_stmt)).all()
    if not rows:
        return []
    tokens = _ngrams(query)

    vector_hits: dict[str, float] = {}
    try:
        from app.core.config import get_settings
        from app.infrastructure.vector.store import get_vector_store
        from app.integrations.llm.openai_client import build_embedding_client

        query_vector = (await build_embedding_client().embed([query]))[0]
        vector_hits = dict(
            get_vector_store().search(
                ctx.tenant_id, query_vector, top_k=get_settings().vector_top_k
            )
        )
    except Exception:  # noqa: BLE001 - 向量检索不可用时退化为关键词
        vector_hits = {}

    scored: list[tuple[float, KnowledgeChunk, KnowledgeDocument]] = []
    for chunk, document in rows:
        if chunk.effective_from and chunk.effective_from > now:
            continue
        if chunk.effective_to and chunk.effective_to < now:
            continue
        searchable = f"{chunk.title} {chunk.section or ''} {chunk.content}"
        content_tokens = _ngrams(searchable)
        matched = len(tokens & content_tokens)
        keyword_score = matched / max(len(tokens), 1)
        vector_score = max(0.0, vector_hits.get(chunk.chunk_id, 0.0))
        if keyword_score == 0 and vector_score < 0.3:
            continue
        score = 0.4 * keyword_score + 0.6 * vector_score + document.authority_level / 100
        scored.append((score, chunk, document))

    scored.sort(key=lambda item: (item[0], item[2].authority_level), reverse=True)
    results: list[dict] = []
    for score, chunk, document in scored[:top_k]:
        results.append(
            {
                "chunkId": chunk.chunk_id,
                "documentId": str(document.id),
                "documentVersion": chunk.document_version,
                "title": chunk.title,
                "section": chunk.section,
                "content": chunk.content,
                "sourceUrl": chunk.source_url,
                "regionCode": chunk.region_code,
                "authorityLevel": document.authority_level,
                "score": round(score, 4),
                "effectiveStatus": "active",
            }
        )
    return results
