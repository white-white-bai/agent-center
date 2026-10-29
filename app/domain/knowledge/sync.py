from collections.abc import Awaitable, Callable
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.tenant import TenantContext
from app.domain.knowledge.models import KnowledgeDocument, KnowledgeSyncTask
from app.domain.knowledge.service import ingest_document, publish_document

DocumentFetcher = Callable[[str], Awaitable[list[dict]]]


async def http_fetcher(source_ref: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(source_ref)
        response.raise_for_status()
        payload = response.json()
    if isinstance(payload, dict):
        payload = payload.get("documents") or []
    return list(payload)


async def create_sync_task(
    session: AsyncSession,
    ctx: TenantContext,
    *,
    space_id: int,
    source_type: str = "UPLOAD",
    source_ref: str | None = None,
) -> KnowledgeSyncTask:
    task = KnowledgeSyncTask(
        tenant_id=ctx.tenant_id,
        space_id=space_id,
        source_type=source_type,
        source_ref=source_ref,
        status="PENDING",
        checkpoint_json={"processed": []},
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def get_task(session: AsyncSession, ctx: TenantContext, task_id: int) -> KnowledgeSyncTask:
    result = await session.execute(
        select(KnowledgeSyncTask).where(
            KnowledgeSyncTask.id == task_id, KnowledgeSyncTask.tenant_id == ctx.tenant_id
        )
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise NotFoundError("同步任务不存在")
    return task


async def _upsert_document(session: AsyncSession, ctx: TenantContext, space_id: int, payload: dict) -> None:
    code = payload.get("document_code") or payload.get("id")
    existing = await session.execute(
        select(KnowledgeDocument).where(
            KnowledgeDocument.tenant_id == ctx.tenant_id,
            KnowledgeDocument.document_code == code,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return
    document = await ingest_document(
        session,
        ctx,
        space_id=space_id,
        title=payload["title"],
        content=payload["content"],
        region_code=payload.get("region_code"),
        authority_level=int(payload.get("authority_level", 3)),
        source_url=payload.get("source_url"),
        document_code=code,
    )
    await publish_document(session, ctx, document.id)


async def run_sync_task(
    session: AsyncSession,
    ctx: TenantContext,
    task: KnowledgeSyncTask,
    *,
    documents: list[dict] | None = None,
    fetcher: DocumentFetcher | None = None,
    max_retries: int = 3,
) -> KnowledgeSyncTask:
    """执行同步任务，支持幂等跳过、断点续跑与有限重试。"""
    if task.status == "SUCCESS":
        return task
    task.status = "RUNNING"
    await session.commit()

    processed = list((task.checkpoint_json or {}).get("processed") or [])
    try:
        if documents is None:
            if fetcher is None:
                if not task.source_ref:
                    raise ValueError("缺少同步来源")
                fetcher = http_fetcher
            documents = await fetcher(task.source_ref or "")
        for payload in documents:
            code = payload.get("document_code") or payload.get("id")
            if code in processed:
                continue
            await _upsert_document(session, ctx, task.space_id, payload)
            processed.append(code)
            task.checkpoint_json = {"processed": list(processed)}
            await session.commit()
        task.status = "SUCCESS"
        task.finished_at = datetime.utcnow()
    except Exception as exc:  # noqa: BLE001 - 同步失败需要记录并可重试
        task.retry_count += 1
        task.error_message = str(exc)
        task.status = "FAILED" if task.retry_count >= max_retries else "PENDING"
    await session.commit()
    await session.refresh(task)
    return task
