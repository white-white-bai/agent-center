from app.api.deps import get_model_router
from app.integrations.llm.client import LLMResponse
from app.integrations.llm.router import ModelRouter
from app.main import app

HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "admin1", "X-Roles": "admin"}


def _publish_agent(client, code: str, domain: str, keywords: list[str]) -> None:
    agent_id = client.post(
        "/api/v1/admin/agents",
        json={"code": code, "name": code, "domain_code": domain},
        headers=HEADERS,
    ).json()["data"]["id"]
    version_id = client.post(
        f"/api/v1/admin/agents/{agent_id}/versions",
        json={"role": code, "router_rules": {"keywords": keywords}},
        headers=HEADERS,
    ).json()["data"]["id"]
    client.post(
        f"/api/v1/admin/agents/{agent_id}/publish",
        json={"version_id": version_id},
        headers=HEADERS,
    )


class ScriptedClient:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    async def complete(self, request):
        return LLMResponse(content=self.reply, model=request.model)

    async def stream(self, request):
        yield ""


def test_model_selection_can_override_rule_score(client) -> None:
    _publish_agent(client, "agent_a", "d1", ["办事"])
    _publish_agent(client, "agent_b", "d2", ["办事"])
    app.dependency_overrides[get_model_router] = lambda: ModelRouter(
        ScriptedClient('{"agent":"agent_b","confidence":0.9,"reason":"语义更接近"}')
    )

    response = client.post(
        "/api/v1/admin/route-preview", json={"message": "我要办事"}, headers=HEADERS
    )

    data = response.json()["data"]
    assert data["selectedAgent"] == "agent_b"
    assert data["reasonCode"] == "MODEL_SELECT"
    assert data["confidence"] == 0.9


def test_invalid_model_choice_falls_back_to_rules(client) -> None:
    _publish_agent(client, "agent_a", "d1", ["办事"])
    _publish_agent(client, "agent_b", "d2", ["办事"])
    app.dependency_overrides[get_model_router] = lambda: ModelRouter(
        ScriptedClient('{"agent":"not_allowed","confidence":0.99}')
    )

    response = client.post(
        "/api/v1/admin/route-preview", json={"message": "我要办事"}, headers=HEADERS
    )

    data = response.json()["data"]
    assert data["reasonCode"] == "DOMAIN_MATCH"
    assert data["needClarification"] is True
