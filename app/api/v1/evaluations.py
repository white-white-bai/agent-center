from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import CurrentTenant, DbSession, ModelRouterDep
from app.core.responses import ok
from app.core.tenant import require_admin
from app.domain.evaluation import service

router = APIRouter(prefix="/admin", tags=["evaluation"], dependencies=[Depends(require_admin)])


class CreateDatasetRequest(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    domainCode: str | None = None


class CreateCaseRequest(BaseModel):
    question: str = Field(min_length=1)
    expectedAnswer: str | None = None
    expectedDocIds: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class RunEvaluationRequest(BaseModel):
    datasetId: int
    promptVersionId: int | None = None
    agentVersionId: int | None = None
    model: str = Field(default="eval-model", max_length=100)
    passThreshold: float = Field(default=0.5, ge=0, le=1)


@router.post("/eval-datasets")
async def create_dataset(payload: CreateDatasetRequest, session: DbSession, ctx: CurrentTenant) -> dict:
    dataset = await service.create_dataset(
        session, ctx, code=payload.code, name=payload.name, domain_code=payload.domainCode
    )
    return ok({"id": dataset.id, "code": dataset.code, "name": dataset.name})


@router.post("/eval-datasets/{dataset_id}/cases")
async def create_case(
    dataset_id: int, payload: CreateCaseRequest, session: DbSession, ctx: CurrentTenant
) -> dict:
    case = await service.add_case(
        session,
        ctx,
        dataset_id,
        question=payload.question,
        expected_answer=payload.expectedAnswer,
        expected_doc_ids=payload.expectedDocIds,
        tags=payload.tags,
    )
    return ok({"id": case.id, "question": case.question})


class ImportCasesRequest(BaseModel):
    cases: list[CreateCaseRequest] = Field(min_length=1)


@router.post("/eval-datasets/{dataset_id}/cases/import")
async def import_cases(
    dataset_id: int, payload: ImportCasesRequest, session: DbSession, ctx: CurrentTenant
) -> dict:
    from app.domain.evaluation import service as eval_service

    created = []
    for item in payload.cases:
        case = await eval_service.add_case(
            session,
            ctx,
            dataset_id,
            question=item.question,
            expected_answer=item.expectedAnswer,
            expected_doc_ids=item.expectedDocIds,
            tags=item.tags or ["baseline"],
        )
        created.append(case.id)
    return ok({"imported": len(created), "caseIds": created})


@router.post("/evaluations")
async def run_evaluation(
    payload: RunEvaluationRequest, session: DbSession, ctx: CurrentTenant, model_router: ModelRouterDep
) -> dict:
    eval_run = await service.run_evaluation(
        session,
        ctx,
        dataset_id=payload.datasetId,
        router=model_router,
        model=payload.model,
        prompt_version_id=payload.promptVersionId,
        agent_version_id=payload.agentVersionId,
        pass_threshold=payload.passThreshold,
    )
    return ok(
        {
            "id": eval_run.id,
            "status": eval_run.status,
            "metrics": eval_run.metrics_json,
        }
    )


@router.get("/evaluations/{eval_run_id}")
async def get_evaluation(eval_run_id: int, session: DbSession, ctx: CurrentTenant) -> dict:
    from sqlalchemy import select

    from app.domain.evaluation.models import EvalRun

    result = await session.execute(
        select(EvalRun).where(EvalRun.id == eval_run_id, EvalRun.tenant_id == ctx.tenant_id)
    )
    eval_run = result.scalar_one_or_none()
    if eval_run is None:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("评测任务不存在")
    results = await service.list_results(session, ctx, eval_run.id)
    return ok(
        {
            "id": eval_run.id,
            "status": eval_run.status,
            "metrics": eval_run.metrics_json,
            "results": [
                {
                    "caseId": item.case_id,
                    "score": item.score,
                    "passed": item.passed,
                    "actualAnswer": item.actual_answer,
                }
                for item in results
            ],
        }
    )
