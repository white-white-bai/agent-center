from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.core.tenant import TenantContext
from app.domain.tool.idempotency import arguments_hash
from app.domain.tool.models import ToolConfirmation

CONFIRMATION_TTL = timedelta(minutes=10)


async def create_confirmation(
    session: AsyncSession,
    ctx: TenantContext,
    *,
    run_id: str,
    conversation_id: int,
    tool_code: str,
    arguments: dict,
    summary: str,
) -> ToolConfirmation:
    confirmation = ToolConfirmation(
        tenant_id=ctx.tenant_id,
        confirmation_id=f"cfm_{uuid4().hex}",
        run_id=run_id,
        conversation_id=conversation_id,
        tool_code=tool_code,
        arguments_json=arguments,
        arguments_hash=arguments_hash(arguments),
        summary=summary,
        status="PENDING",
        expires_at=datetime.utcnow() + CONFIRMATION_TTL,
    )
    session.add(confirmation)
    await session.commit()
    await session.refresh(confirmation)
    return confirmation


async def decide(
    session: AsyncSession,
    ctx: TenantContext,
    *,
    confirmation_id: str,
    decision: str,
    arguments: dict | None = None,
) -> tuple[ToolConfirmation, bool]:
    """返回确认记录以及是否允许执行。

    确认请求幂等：重复提交 confirm 返回当前状态而不重复执行。
    """
    if decision not in {"confirm", "reject"}:
        raise ConflictError("decision 仅支持 confirm 或 reject")
    result = await session.execute(
        select(ToolConfirmation).where(
            ToolConfirmation.tenant_id == ctx.tenant_id,
            ToolConfirmation.confirmation_id == confirmation_id,
        )
    )
    confirmation = result.scalar_one_or_none()
    if confirmation is None:
        raise NotFoundError("确认记录不存在")

    if confirmation.status in {"CONFIRMED", "REJECTED"}:
        return confirmation, False
    if confirmation.status != "PENDING":
        raise ConflictError(f"确认记录状态异常: {confirmation.status}")
    if confirmation.expires_at and confirmation.expires_at < datetime.utcnow():
        confirmation.status = "EXPIRED"
        await session.commit()
        raise ConflictError("确认已过期，请重新发起操作")

    if decision == "reject":
        confirmation.status = "REJECTED"
        confirmation.decided_at = datetime.utcnow()
        await session.commit()
        return confirmation, False

    if arguments is not None and arguments_hash(arguments) != confirmation.arguments_hash:
        raise ConflictError("操作参数已发生变化，原确认失效")

    confirmation.status = "CONFIRMED"
    confirmation.decided_at = datetime.utcnow()
    await session.commit()
    return confirmation, True
