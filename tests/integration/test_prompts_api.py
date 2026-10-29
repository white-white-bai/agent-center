HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "admin1", "X-Roles": "admin"}


def test_prompt_version_lifecycle(client) -> None:
    created_template = client.post(
        "/api/v1/admin/prompts",
        json={"code": "district_consult", "name": "区级咨询模板"},
        headers=HEADERS,
    )
    assert created_template.status_code == 200
    template_id = created_template.json()["data"]["id"]

    draft = client.post(
        f"/api/v1/admin/prompts/{template_id}/versions",
        json={"content": "你是{{agent.role}}，请回答{{question}}"},
        headers=HEADERS,
    )
    assert draft.status_code == 200
    draft_data = draft.json()["data"]
    assert draft_data["status"] == "DRAFT"
    assert draft_data["variables"] == ["agent.role", "question"]
    version_id = draft_data["id"]

    testing = client.post(
        f"/api/v1/admin/prompts/{template_id}/versions/{version_id}/transition",
        json={"target": "TESTING"},
        headers=HEADERS,
    )
    assert testing.json()["data"]["status"] == "TESTING"

    published = client.post(
        f"/api/v1/admin/prompts/{template_id}/versions/{version_id}/transition",
        json={"target": "PUBLISHED"},
        headers=HEADERS,
    )
    assert published.json()["data"]["status"] == "PUBLISHED"
    assert published.json()["data"]["publishedAt"] is not None


def test_prompt_version_cannot_skip_status(client) -> None:
    template_id = client.post(
        "/api/v1/admin/prompts",
        json={"code": "p1", "name": "模板1"},
        headers=HEADERS,
    ).json()["data"]["id"]
    version_id = client.post(
        f"/api/v1/admin/prompts/{template_id}/versions",
        json={"content": "hi"},
        headers=HEADERS,
    ).json()["data"]["id"]

    response = client.post(
        f"/api/v1/admin/prompts/{template_id}/versions/{version_id}/transition",
        json={"target": "PUBLISHED"},
        headers=HEADERS,
    )

    assert response.status_code == 409
    assert response.json()["code"] == "AC.COMMON.CONFLICT"


def test_prompt_template_is_tenant_isolated(client) -> None:
    template_id = client.post(
        "/api/v1/admin/prompts",
        json={"code": "p2", "name": "模板2"},
        headers=HEADERS,
    ).json()["data"]["id"]

    response = client.post(
        f"/api/v1/admin/prompts/{template_id}/versions",
        json={"content": "hi"},
        headers={"X-Tenant-Id": "t2", "X-User-Id": "admin2", "X-Roles": "admin"},
    )

    assert response.status_code == 404
