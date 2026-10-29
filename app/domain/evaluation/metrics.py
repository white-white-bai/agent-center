from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import TenantContext
from app.domain.evaluation.models import Badcase, Feedback
from app.domain.model.models import ModelUsageLog
from app.domain.session.models import Conversation, Run
from app.domain.tool.models import ToolInvokeLog


async def overview(session: AsyncSession, ctx: TenantContext) -> dict:
    tenant = ctx.tenant_id

    conversations = await session.execute(
        select(
            func.count(Conversation.id),
            func.sum(case((Conversation.status == "ACTIVE", 1), else_=0)),
            func.sum(case((Conversation.status == "WAITING_USER", 1), else_=0)),
            func.sum(case((Conversation.status == "TRANSFERRED", 1), else_=0)),
        ).where(Conversation.tenant_id == tenant)
    )
    conv_total, conv_active, conv_waiting, conv_transferred = conversations.one()

    runs = await session.execute(
        select(Run.status, func.count(Run.id)).where(Run.tenant_id == tenant).group_by(Run.status)
    )
    runs_by_status = {status: count for status, count in runs.all()}

    tokens = await session.execute(
        select(func.coalesce(func.sum(Run.token_input), 0), func.coalesce(func.sum(Run.token_output), 0)).where(
            Run.tenant_id == tenant
        )
    )
    token_input, token_output = tokens.one()

    tools = await session.execute(
        select(
            func.count(ToolInvokeLog.id),
            func.sum(case((ToolInvokeLog.status == "SUCCESS", 1), else_=0)),
        ).where(ToolInvokeLog.tenant_id == tenant)
    )
    tool_total, tool_success = tools.one()

    feedback = await session.execute(
        select(
            func.sum(case((Feedback.rating == "up", 1), else_=0)),
            func.sum(case((Feedback.rating == "down", 1), else_=0)),
        ).where(Feedback.tenant_id == tenant)
    )
    feedback_up, feedback_down = feedback.one()

    badcases = await session.execute(
        select(func.count(Badcase.id)).where(Badcase.tenant_id == tenant, Badcase.status == "OPEN")
    )

    models = await session.execute(
        select(
            func.count(ModelUsageLog.id),
            func.sum(case((ModelUsageLog.status == "SUCCESS", 1), else_=0)),
            func.avg(ModelUsageLog.latency_ms),
        ).where(ModelUsageLog.tenant_id == tenant)
    )
    model_total, model_success, model_avg_latency = models.one()

    return {
        "conversations": {
            "total": conv_total or 0,
            "active": int(conv_active or 0),
            "waitingUser": int(conv_waiting or 0),
            "transferred": int(conv_transferred or 0),
        },
        "runs": {"total": sum(runs_by_status.values()), "byStatus": runs_by_status},
        "tokens": {"input": int(token_input or 0), "output": int(token_output or 0)},
        "tools": {
            "total": tool_total or 0,
            "success": int(tool_success or 0),
            "successRate": round((tool_success or 0) / tool_total, 4) if tool_total else 0.0,
        },
        "feedback": {"up": int(feedback_up or 0), "down": int(feedback_down or 0)},
        "badcases": {"open": int(badcases.scalar_one() or 0)},
        "models": {
            "calls": model_total or 0,
            "success": int(model_success or 0),
            "avgLatencyMs": round(float(model_avg_latency or 0), 2),
        },
    }
