HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "admin1", "X-Roles": "admin"}


async def _actions(async_client) -> set[str]:
    logs = (
        await async_client.get("/api/v1/admin/audit-logs", params={"limit": 100}, headers=HEADERS)
    ).json()["data"]
    return {item["action"] for item in logs}


async def test_audit_covers_management_writes(async_client) -> None:
    agent_id = (
        await async_client.post(
            "/api/v1/admin/agents",
            json={"code": "cov_agent", "name": "覆盖", "domain_code": "d1"},
            headers=HEADERS,
        )
    ).json()["data"]["id"]
    await async_client.post(
        f"/api/v1/admin/agents/{agent_id}/versions", json={"role": "顾问"}, headers=HEADERS
    )

    template_id = (
        await async_client.post(
            "/api/v1/admin/prompts", json={"code": "cov_prompt", "name": "覆盖"}, headers=HEADERS
        )
    ).json()["data"]["id"]
    await async_client.post(
        f"/api/v1/admin/prompts/{template_id}/versions", json={"content": "hi"}, headers=HEADERS
    )

    await async_client.post(
        "/api/v1/admin/tools/matter.submit/credentials",
        json={"name": "api_key", "value": "sk-test"},
        headers=HEADERS,
    )

    space_id = (
        await async_client.post(
            "/api/v1/admin/knowledge-spaces",
            json={"code": "cov_kb", "name": "覆盖", "domainCode": "district_service"},
            headers=HEADERS,
        )
    ).json()["data"]["id"]
    await async_client.post(
        f"/api/v1/admin/knowledge-spaces/{space_id}/documents",
        json={"title": "指南", "content": "内容"},
        headers=HEADERS,
    )

    dataset_id = (
        await async_client.post(
            "/api/v1/admin/eval-datasets", json={"code": "cov_eval", "name": "覆盖"}, headers=HEADERS
        )
    ).json()["data"]["id"]
    await async_client.post(
        f"/api/v1/admin/eval-datasets/{dataset_id}/cases",
        json={"question": "q", "expectedAnswer": "a"},
        headers=HEADERS,
    )
    await async_client.post(
        f"/api/v1/admin/eval-datasets/{dataset_id}/cases/import",
        json={"cases": [{"question": "q2", "expectedAnswer": "a2"}]},
        headers=HEADERS,
    )

    actions = await _actions(async_client)

    assert {
        "agent.create",
        "agent.version.create",
        "prompt.create",
        "prompt.version.create",
        "tool.credential.save",
        "knowledge.space.create",
        "knowledge.document.create",
        "eval.dataset.create",
        "eval.case.create",
        "eval.cases.import",
    } <= actions


async def test_audit_records_eval_run_and_purge(async_client) -> None:
    from app.api.deps import get_model_router
    from app.integrations.llm.client import LLMResponse
    from app.integrations.llm.router import ModelRouter
    from app.main import app

    class Client:
        async def complete(self, request):
            return LLMResponse(content="a", model=request.model)

        async def stream(self, request):
            yield ""

    app.dependency_overrides[get_model_router] = lambda: ModelRouter(Client())
    dataset_id = (
        await async_client.post(
            "/api/v1/admin/eval-datasets", json={"code": "run_eval", "name": "执行"}, headers=HEADERS
        )
    ).json()["data"]["id"]
    await async_client.post(
        f"/api/v1/admin/eval-datasets/{dataset_id}/cases",
        json={"question": "q", "expectedAnswer": "a"},
        headers=HEADERS,
    )
    await async_client.post(
        "/api/v1/admin/evaluations", json={"datasetId": dataset_id}, headers=HEADERS
    )
    await async_client.post(
        "/api/v1/admin/maintenance/purge-trace", json={"days": 90}, headers=HEADERS
    )

    actions = await _actions(async_client)

    assert "eval.run" in actions
    assert "maintenance.purge_trace" in actions
