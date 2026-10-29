from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import TenantContext
from app.domain.evaluation.models import AuditLog


async def record_audit(
    session: AsyncSession,
    ctx: TenantContext,
    *,
    action: str,
    resource_type: str,
    resource_id: str | int | None = None,
    detail: dict | None = None,
) -> AuditLog:
    entry = AuditLog(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        detail_json=detail or {},
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


async def list_audit_logs(
    session: AsyncSession,
    ctx: TenantContext,
    *,
    action: str | None = None,
    resource_type: str | None = None,
    limit: int = 100,
) -> list[AuditLog]:
    query = select(AuditLog).where(AuditLog.tenant_id == ctx.tenant_id)
    if action:
        query = query.where(AuditLog.action == action)
    if resource_type:
        query = query.where(AuditLog.resource_type == resource_type)
    result = await session.execute(query.order_by(AuditLog.id.desc()).limit(limit))
    return list(result.scalars().all())


def serialize_audit(entry: AuditLog) -> dict:
    return {
        "id": entry.id,
        "userId": entry.user_id,
        "action": entry.action,
        "resourceType": entry.resource_type,
        "resourceId": entry.resource_id,
        "detail": entry.detail_json,
        "createdAt": entry.created_at.isoformat() if entry.created_at else None,
    }
