from app.api.deps import get_model_router
from app.core.config import get_settings
from app.integrations.llm.client import LLMResponse
from app.integrations.llm.router import ModelRouter
from app.main import app

HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "admin1", "X-Roles": "admin"}


class Client:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    async def complete(self, request):
        if self.fail:
            raise RuntimeError("Invalid 'Authorization' header or token.")
        return LLMResponse(content="正常", model=request.model, token_input=10, token_output=2)

    async def stream(self, request):
        yield ""


async def test_model_health_reports_success(async_client, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "llm_api_key", "user_test_key")
    app.dependency_overrides[get_model_router] = lambda: ModelRouter(Client())

    response = await async_client.get("/api/v1/admin/model/health", headers=HEADERS)

    data = response.json()["data"]
    assert data["configured"] is True
    assert data["ok"] is True
    assert data["content"] == "正常"


async def test_model_health_reports_auth_failure(async_client, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "llm_api_key", "user_expired_key")
    app.dependency_overrides[get_model_router] = lambda: ModelRouter(Client(fail=True))

    response = await async_client.get("/api/v1/admin/model/health", headers=HEADERS)

    data = response.json()["data"]
    assert data["configured"] is True
    assert data["ok"] is False
    assert "Authorization" in data["message"]
    assert "Studio" in data["hint"]


async def test_model_health_without_key(async_client, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "llm_api_key", "")

    response = await async_client.get("/api/v1/admin/model/health", headers=HEADERS)

    data = response.json()["data"]
    assert data["configured"] is False
    assert "桩模型" in data["message"]
