from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.tenant import TenantContext
from app.domain.evaluation.models import Feedback
from app.domain.session.models import Run, RunStep


async def get_run(
    session: AsyncSession,
    ctx: TenantContext,
    run_id: str,
    *,
    conversation_id: int | None = None,
) -> Run:
    result = await session.execute(
        select(Run).where(Run.id == run_id, Run.tenant_id == ctx.tenant_id)
    )
    run = result.scalar_one_or_none()
    if run is None or (conversation_id is not None and run.conversation_id != conversation_id):
        raise NotFoundError("Run 不存在或无权访问")
    return run


async def list_steps(session: AsyncSession, ctx: TenantContext, run_id: str) -> list[RunStep]:
    result = await session.execute(
        select(RunStep)
        .where(RunStep.run_id == run_id, RunStep.tenant_id == ctx.tenant_id)
        .order_by(RunStep.step_no.asc(), RunStep.id.asc())
    )
    return list(result.scalars().all())


def serialize_run(run: Run) -> dict:
    return {
        "runId": run.id,
        "conversationId": run.conversation_id,
        "turnId": run.turn_id,
        "agentCode": run.agent_code,
        "agentVersionId": run.agent_version_id,
        "traceId": run.trace_id,
        "status": run.status,
        "currentStep": run.current_step,
        "toolCallCount": run.tool_call_count,
        "usage": {"input": run.token_input, "output": run.token_output},
        "startedAt": run.started_at.isoformat() if run.started_at else None,
        "endedAt": run.ended_at.isoformat() if run.ended_at else None,
        "errorCode": run.error_code,
    }


def serialize_step(step: RunStep) -> dict:
    return {
        "stepNo": step.step_no,
        "stepType": step.step_type,
        "status": step.status,
        "inputSummary": step.input_summary,
        "outputSummary": step.output_summary,
        "toolCode": step.tool_code,
        "durationMs": step.duration_ms,
        "tokenInput": step.token_input,
        "tokenOutput": step.token_output,
        "errorCode": step.error_code,
    }


async def submit_feedback(
    session: AsyncSession,
    ctx: TenantContext,
    *,
    rating: str,
    conversation_id: int | None,
    message_id: int | None,
    run_id: str | None,
    reason: str | None,
    comment: str | None,
) -> Feedback:
    feedback = Feedback(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        conversation_id=conversation_id,
        message_id=message_id,
        run_id=run_id,
        rating=rating,
        reason=reason,
        comment=comment,
    )
    session.add(feedback)
    await session.commit()
    await session.refresh(feedback)
    return feedback


def serialize_feedback(feedback: Feedback) -> dict:
    return {
        "id": feedback.id,
        "rating": feedback.rating,
        "runId": feedback.run_id,
        "conversationId": feedback.conversation_id,
        "createdAt": feedback.created_at.isoformat() if feedback.created_at else None,
    }
