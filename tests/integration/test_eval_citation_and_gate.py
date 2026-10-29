import pytest
from sqlalchemy import select

HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "u1", "X-Roles": "admin"}


async def _publish_doc(async_client) -> str:
    space_id = (
        await async_client.post(
            "/api/v1/admin/knowledge-spaces",
            json={"code": "eval_kb", "name": "评测知识", "domainCode": "district_service"},
            headers=HEADERS,
        )
    ).json()["data"]["id"]
    document_id = (
        await async_client.post(
            f"/api/v1/admin/knowledge-spaces/{space_id}/documents",
            json={"title": "营业执照指南", "content": "营业执照办理需要身份证和申请书。"},
            headers=HEADERS,
        )
    ).json()["data"]["id"]
    await async_client.post(
        f"/api/v1/admin/knowledge-spaces/{space_id}/documents/{document_id}/publish",
        headers=HEADERS,
    )
    return str(document_id)


class Client:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    async def complete(self, request):
        from app.integrations.llm.client import LLMResponse

        return LLMResponse(content=self.reply, model=request.model)

    async def stream(self, request):
        yield ""


def _override_router(reply: str) -> None:
    from app.api.deps import get_model_router
    from app.integrations.llm.router import ModelRouter
    from app.main import app

    app.dependency_overrides[get_model_router] = lambda: ModelRouter(Client(reply))


async def test_evaluation_reports_citation_accuracy(async_client) -> None:
    document_id = await _publish_doc(async_client)
    _override_router("营业执照需要身份证和申请书")

    dataset_id = (
        await async_client.post(
            "/api/v1/admin/eval-datasets",
            json={"code": "citation_eval", "name": "引用评测"},
            headers=HEADERS,
        )
    ).json()["data"]["id"]
    await async_client.post(
        f"/api/v1/admin/eval-datasets/{dataset_id}/cases",
        json={
            "question": "营业执照需要什么材料",
            "expectedAnswer": "营业执照需要身份证和申请书",
            "expectedDocIds": [document_id],
        },
        headers=HEADERS,
    )

    run = await async_client.post(
        "/api/v1/admin/evaluations", json={"datasetId": dataset_id}, headers=HEADERS
    )

    metrics = run.json()["data"]["metrics"]
    assert metrics["citation"]["total"] == 1
    assert metrics["citation"]["matched"] == 1
    assert metrics["citation"]["accuracy"] == 1.0

    detail = (
        await async_client.get(
            f"/api/v1/admin/evaluations/{run.json()['data']['id']}", headers=HEADERS
        )
    ).json()["data"]
    assert detail["results"][0]["passed"] is True


async def test_publish_gate_requires_successful_evaluation(async_client, monkeypatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "publish_require_eval", True)
    _override_router("身份证")

    template_id = (
        await async_client.post(
            "/api/v1/admin/prompts", json={"code": "gated", "name": "门禁模板"}, headers=HEADERS
        )
    ).json()["data"]["id"]
    version_id = (
        await async_client.post(
            f"/api/v1/admin/prompts/{template_id}/versions",
            json={"content": "回答：{{question}}"},
            headers=HEADERS,
        )
    ).json()["data"]["id"]
    await async_client.post(
        f"/api/v1/admin/prompts/{template_id}/versions/{version_id}/transition",
        json={"target": "TESTING"},
        headers=HEADERS,
    )

    blocked = await async_client.post(
        f"/api/v1/admin/prompts/{template_id}/versions/{version_id}/transition",
        json={"target": "PUBLISHED"},
        headers=HEADERS,
    )
    assert blocked.status_code == 409

    dataset_id = (
        await async_client.post(
            "/api/v1/admin/eval-datasets",
            json={"code": "gate_eval", "name": "门禁评测"},
            headers=HEADERS,
        )
    ).json()["data"]["id"]
    await async_client.post(
        f"/api/v1/admin/eval-datasets/{dataset_id}/cases",
        json={"question": "材料", "expectedAnswer": "身份证"},
        headers=HEADERS,
    )
    await async_client.post(
        "/api/v1/admin/evaluations",
        json={"datasetId": dataset_id, "promptVersionId": version_id},
        headers=HEADERS,
    )

    published = await async_client.post(
        f"/api/v1/admin/prompts/{template_id}/versions/{version_id}/transition",
        json={"target": "PUBLISHED"},
        headers=HEADERS,
    )
    assert published.status_code == 200
    assert published.json()["data"]["status"] == "PUBLISHED"
