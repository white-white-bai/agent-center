import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.tenant import TenantContext
from app.domain.evaluation.models import EvalCase, EvalDataset, EvalResult, EvalRun
from app.integrations.llm.client import ChatMessage, LLMRequest
from app.integrations.llm.router import ModelRouter


def _ngrams(text: str, size: int = 2) -> set[str]:
    cleaned = re.sub(r"\s+", "", text or "")
    if len(cleaned) <= size:
        return {cleaned} if cleaned else set()
    return {cleaned[index : index + size] for index in range(len(cleaned) - size + 1)}


def similarity(expected: str, actual: str) -> float:
    expected_tokens = _ngrams(expected)
    actual_tokens = _ngrams(actual)
    if not expected_tokens:
        return 1.0 if actual else 0.0
    return len(expected_tokens & actual_tokens) / len(expected_tokens)


async def create_dataset(
    session: AsyncSession, ctx: TenantContext, *, code: str, name: str, domain_code: str | None = None
) -> EvalDataset:
    dataset = EvalDataset(tenant_id=ctx.tenant_id, code=code, name=name, domain_code=domain_code)
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


async def get_dataset(session: AsyncSession, ctx: TenantContext, dataset_id: int) -> EvalDataset:
    result = await session.execute(
        select(EvalDataset).where(EvalDataset.id == dataset_id, EvalDataset.tenant_id == ctx.tenant_id)
    )
    dataset = result.scalar_one_or_none()
    if dataset is None:
        raise NotFoundError("评测集不存在")
    return dataset


async def add_case(
    session: AsyncSession,
    ctx: TenantContext,
    dataset_id: int,
    *,
    question: str,
    expected_answer: str | None = None,
    expected_doc_ids: list[str] | None = None,
    tags: list[str] | None = None,
) -> EvalCase:
    await get_dataset(session, ctx, dataset_id)
    case = EvalCase(
        tenant_id=ctx.tenant_id,
        dataset_id=dataset_id,
        question=question,
        expected_answer=expected_answer,
        expected_doc_ids_json=expected_doc_ids or [],
        tags_json=tags or [],
    )
    session.add(case)
    await session.commit()
    await session.refresh(case)
    return case


async def list_cases(session: AsyncSession, ctx: TenantContext, dataset_id: int) -> list[EvalCase]:
    result = await session.execute(
        select(EvalCase).where(
            EvalCase.dataset_id == dataset_id, EvalCase.tenant_id == ctx.tenant_id
        )
    )
    return list(result.scalars().all())


async def run_evaluation(
    session: AsyncSession,
    ctx: TenantContext,
    *,
    dataset_id: int,
    router: ModelRouter,
    model: str = "eval-model",
    prompt_version_id: int | None = None,
    agent_version_id: int | None = None,
    pass_threshold: float = 0.5,
) -> EvalRun:
    await get_dataset(session, ctx, dataset_id)
    cases = await list_cases(session, ctx, dataset_id)
    eval_run = EvalRun(
        tenant_id=ctx.tenant_id,
        dataset_id=dataset_id,
        prompt_version_id=prompt_version_id,
        agent_version_id=agent_version_id,
        status="RUNNING",
    )
    session.add(eval_run)
    await session.commit()
    await session.refresh(eval_run)

    passed = 0
    total_score = 0.0
    citation_total = 0
    citation_matched = 0
    for case in cases:
        response = await router.complete(
            session,
            ctx,
            LLMRequest(messages=[ChatMessage(role="user", content=case.question)], model=model),
            primary_model=model,
            max_retries=0,
        )
        score = similarity(case.expected_answer or "", response.content)
        is_passed = score >= pass_threshold
        if is_passed:
            passed += 1
        total_score += score

        detail: dict = {}
        expected_docs = [str(item) for item in (case.expected_doc_ids_json or [])]
        if expected_docs:
            from app.domain.knowledge.service import search as search_knowledge

            results = await search_knowledge(session, ctx, query=case.question, top_k=5)
            retrieved = [str(item["documentId"]) for item in results]
            hit = bool(set(expected_docs) & set(retrieved))
            citation_total += 1
            if hit:
                citation_matched += 1
            detail = {"retrievedDocIds": retrieved, "citationHit": hit}

        session.add(
            EvalResult(
                tenant_id=ctx.tenant_id,
                eval_run_id=eval_run.id,
                case_id=case.id,
                score=round(score, 4),
                passed=is_passed,
                actual_answer=response.content,
                detail_json=detail or None,
            )
        )
    total = len(cases)
    eval_run.metrics_json = {
        "total": total,
        "passed": passed,
        "accuracy": round(passed / total, 4) if total else 0.0,
        "avgScore": round(total_score / total, 4) if total else 0.0,
        "citation": {
            "total": citation_total,
            "matched": citation_matched,
            "accuracy": round(citation_matched / citation_total, 4) if citation_total else None,
        },
    }
    eval_run.status = "SUCCESS"
    eval_run.finished_at = datetime.utcnow()
    await session.commit()
    await session.refresh(eval_run)
    return eval_run


async def list_results(session: AsyncSession, ctx: TenantContext, eval_run_id: int) -> list[EvalResult]:
    result = await session.execute(
        select(EvalResult).where(
            EvalResult.eval_run_id == eval_run_id, EvalResult.tenant_id == ctx.tenant_id
        )
    )
    return list(result.scalars().all())
