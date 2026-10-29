import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.tenant import TenantContext
from app.domain.memory.extractor import extract_candidates
from app.domain.memory.models import MemoryItem
from app.domain.memory.service import add_memory
from app.infrastructure.database.session import SessionFactory

logger = logging.getLogger(__name__)


async def extract_from_messages(
    session: AsyncSession, ctx: TenantContext, messages: list[str]
) -> list[MemoryItem]:
    stored: list[MemoryItem] = []
    for candidate in extract_candidates(messages):
        item = await add_memory(session, ctx, **candidate)
        if item is not None:
            stored.append(item)
    return stored


async def _run(tenant_id: str, user_id: str, messages: list[str]) -> None:
    ctx = TenantContext(tenant_id=tenant_id, user_id=user_id)
    try:
        async with SessionFactory() as session:
            await extract_from_messages(session, ctx, messages)
    except Exception:  # noqa: BLE001 - 记忆抽取失败不得影响对话
        logger.exception("记忆抽取失败 tenant=%s user=%s", tenant_id, user_id)


def schedule_memory_extraction(tenant_id: str, user_id: str, messages: list[str]) -> None:
    """异步抽取记忆；关闭时直接跳过。"""
    if not get_settings().memory_extraction_enabled:
        return
    asyncio.create_task(_run(tenant_id, user_id, messages))
