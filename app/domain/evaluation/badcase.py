from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.core.tenant import TenantContext
from app.domain.evaluation.models import Badcase, Feedback


async def create_badcase_from_feedback(
    session: AsyncSession, ctx: TenantContext, feedback: Feedback
) -> Badcase:
    badcase = Badcase(
        tenant_id=ctx.tenant_id,
        feedback_id=feedback.id,
        run_id=feedback.run_id,
        status="OPEN",
        description=feedback.comment or feedback.reason or "用户点踩",
    )
    session.add(badcase)
    await session.commit()
    await session.refresh(badcase)
    return badcase


async def list_badcases(session: AsyncSession, ctx: TenantContext, *, status: str | None = None) -> list[Badcase]:
    query = select(Badcase).where(Badcase.tenant_id == ctx.tenant_id)
    if status:
        query = query.where(Badcase.status == status)
    result = await session.execute(query.order_by(Badcase.id.desc()))
    return list(result.scalars().all())


async def get_badcase(session: AsyncSession, ctx: TenantContext, badcase_id: int) -> Badcase:
    result = await session.execute(
        select(Badcase).where(Badcase.id == badcase_id, Badcase.tenant_id == ctx.tenant_id)
    )
    badcase = result.scalar_one_or_none()
    if badcase is None:
        raise NotFoundError("Badcase 不存在")
    return badcase


async def convert_to_eval_case(
    session: AsyncSession,
    ctx: TenantContext,
    badcase_id: int,
    *,
    dataset_id: int,
    question: str,
    expected_answer: str | None = None,
) -> Badcase:
    from app.domain.evaluation.service import add_case

    badcase = await get_badcase(session, ctx, badcase_id)
    if badcase.status != "OPEN":
        raise ConflictError(f"Badcase 当前状态不可转换: {badcase.status}")
    case = await add_case(
        session, ctx, dataset_id, question=question, expected_answer=expected_answer, tags=["badcase"]
    )
    badcase.eval_case_id = case.id
    badcase.status = "CONVERTED"
    await session.commit()
    await session.refresh(badcase)
    return badcase
