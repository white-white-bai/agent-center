import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.core.tenant import TenantContext
from app.domain.tool.models import ToolIdempotencyRecord


def normalize_arguments(arguments: dict[str, Any]) -> str:
    return json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def arguments_hash(arguments: dict[str, Any]) -> str:
    return hashlib.sha256(normalize_arguments(arguments).encode("utf-8")).hexdigest()


def build_idempotency_key(run_id: str | None, tool_code: str, arguments: dict[str, Any]) -> str:
    raw = f"{run_id or ''}:{tool_code}:{arguments_hash(arguments)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def begin(
    session: AsyncSession,
    ctx: TenantContext,
    *,
    tool_code: str,
    idempotency_key: str,
    arguments: dict[str, Any],
) -> ToolIdempotencyRecord | None:
    """返回已完成记录表示可复用结果；返回 None 表示首次执行，已创建 EXECUTING 记录。"""
    result = await session.execute(
        select(ToolIdempotencyRecord).where(
            ToolIdempotencyRecord.tenant_id == ctx.tenant_id,
            ToolIdempotencyRecord.tool_code == tool_code,
            ToolIdempotencyRecord.idempotency_key == idempotency_key,
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        record = ToolIdempotencyRecord(
            tenant_id=ctx.tenant_id,
            tool_code=tool_code,
            idempotency_key=idempotency_key,
            arguments_hash=arguments_hash(arguments),
            status="EXECUTING",
        )
        session.add(record)
        await session.commit()
        return None

    if record.arguments_hash != arguments_hash(arguments):
        raise ConflictError("幂等键相同但请求参数不一致，拒绝执行")
    if record.status == "SUCCESS":
        return record
    if record.status == "EXECUTING":
        raise ConflictError("相同幂等键的请求正在执行中")
    raise ConflictError(f"幂等记录状态异常: {record.status}")


async def complete(
    session: AsyncSession,
    record: ToolIdempotencyRecord,
    *,
    response: dict[str, Any],
) -> None:
    record.status = "SUCCESS"
    record.response_json = response
    await session.commit()


async def fail(session: AsyncSession, ctx: TenantContext, *, tool_code: str, idempotency_key: str) -> None:
    result = await session.execute(
        select(ToolIdempotencyRecord).where(
            ToolIdempotencyRecord.tenant_id == ctx.tenant_id,
            ToolIdempotencyRecord.tool_code == tool_code,
            ToolIdempotencyRecord.idempotency_key == idempotency_key,
        )
    )
    record = result.scalar_one_or_none()
    if record is not None and record.status == "EXECUTING":
        record.status = "FAILED"
        await session.commit()
