from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.tenant import TenantContext
from app.domain.knowledge.models import KnowledgeChunk
from app.domain.session.models import Citation


async def validate_chunk(session: AsyncSession, ctx: TenantContext, chunk_id: str) -> KnowledgeChunk:
    result = await session.execute(
        select(KnowledgeChunk).where(
            KnowledgeChunk.chunk_id == chunk_id,
            KnowledgeChunk.tenant_id == ctx.tenant_id,
            KnowledgeChunk.status == "ACTIVE",
        )
    )
    chunk = result.scalar_one_or_none()
    if chunk is None:
        raise NotFoundError(f"引用不可用或无权访问: {chunk_id}")
    return chunk


async def record_citations(
    session: AsyncSession,
    ctx: TenantContext,
    *,
    run_id: str,
    results: list[dict],
    message_id: int | None = None,
    commit: bool = True,
) -> list[Citation]:
    citations: list[Citation] = []
    for result in results:
        chunk = await validate_chunk(session, ctx, result["chunkId"])
        citation = Citation(
            tenant_id=ctx.tenant_id,
            run_id=run_id,
            message_id=message_id,
            document_id=str(chunk.document_id),
            chunk_id=chunk.chunk_id,
            title=chunk.title,
            section=chunk.section,
            source_url=chunk.source_url,
            quote=chunk.content[:200],
            effective_status=result.get("effectiveStatus", "active"),
        )
        session.add(citation)
        citations.append(citation)
    if citations:
        if commit:
            await session.commit()
        else:
            await session.flush()
    return citations


def serialize_citation(citation: Citation) -> dict:
    return {
        "docId": citation.document_id,
        "chunkId": citation.chunk_id,
        "title": citation.title,
        "clause": citation.section,
        "url": citation.source_url,
        "quote": citation.quote,
    }
