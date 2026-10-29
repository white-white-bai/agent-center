from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import TenantContext
from app.domain.model.models import ModelUsageLog
from app.domain.session.events import RunEvent
from app.domain.session.models import RunStep
from app.domain.tool.models import ToolInvokeLog


async def purge_trace(
    session: AsyncSession,
    ctx: TenantContext,
    *,
    days: int | None = None,
    now: datetime | None = None,
) -> dict:
    """清理超过保留期的运行轨迹数据，返回各表删除行数。"""
    from app.core.config import get_settings

    retention = days if days is not None else get_settings().trace_retention_days
    cutoff = (now or datetime.utcnow()) - timedelta(days=retention)

    counts: dict[str, int] = {}
    for name, model in (
        ("run_step", RunStep),
        ("run_event", RunEvent),
        ("model_usage_log", ModelUsageLog),
        ("tool_invoke_log", ToolInvokeLog),
    ):
        result = await session.execute(
            delete(model).where(
                model.tenant_id == ctx.tenant_id,
                model.created_at < cutoff,
            )
        )
        counts[name] = result.rowcount or 0
    await session.commit()
    return {"retentionDays": retention, "cutoff": cutoff.isoformat(), "deleted": counts}
