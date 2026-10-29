from app.api.deps import get_model_router
from app.domain.evaluation.service import similarity
from app.integrations.llm.client import LLMResponse
from app.integrations.llm.router import ModelRouter
from app.main import app

HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "u1", "X-Roles": "admin"}


class ScriptedClient:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)

    async def complete(self, request):
        return LLMResponse(content=self.replies.pop(0), model=request.model, token_input=1, token_output=1)

    async def stream(self, request):
        yield (await self.complete(request)).content


def test_similarity_scores_overlap() -> None:
    assert similarity("需要身份证", "需要身份证和申请书") == 1.0
    assert similarity("需要身份证", "办理时限五天") == 0.0
    assert similarity("", "任意回答") == 1.0


async def test_evaluation_run_computes_metrics(async_client) -> None:
    app.dependency_overrides[get_model_router] = lambda: ModelRouter(
        ScriptedClient(["需要身份证和申请书", "不确定"])
    )

    dataset_id = (
        await async_client.post(
            "/api/v1/admin/eval-datasets",
            json={"code": "district_eval", "name": "区级评测集"},
            headers=HEADERS,
        )
    ).json()["data"]["id"]

    await async_client.post(
        f"/api/v1/admin/eval-datasets/{dataset_id}/cases",
        json={"question": "营业执照需要什么材料", "expectedAnswer": "需要身份证和申请书"},
        headers=HEADERS,
    )
    await async_client.post(
        f"/api/v1/admin/eval-datasets/{dataset_id}/cases",
        json={"question": "办理时限", "expectedAnswer": "五个工作日"},
        headers=HEADERS,
    )

    run = await async_client.post(
        "/api/v1/admin/evaluations",
        json={"datasetId": dataset_id},
        headers=HEADERS,
    )

    data = run.json()["data"]
    assert data["status"] == "SUCCESS"
    assert data["metrics"]["total"] == 2
    assert data["metrics"]["passed"] == 1
    assert data["metrics"]["accuracy"] == 0.5

    detail = await async_client.get(
        f"/api/v1/admin/evaluations/{data['id']}", headers=HEADERS
    )
    results = detail.json()["data"]["results"]
    assert len(results) == 2
    assert results[0]["passed"] is True
    assert results[1]["passed"] is False


async def test_evaluation_requires_existing_dataset(async_client) -> None:
    app.dependency_overrides[get_model_router] = lambda: ModelRouter(ScriptedClient([]))

    response = await async_client.post(
        "/api/v1/admin/evaluations", json={"datasetId": 999}, headers=HEADERS
    )

    assert response.status_code == 404
