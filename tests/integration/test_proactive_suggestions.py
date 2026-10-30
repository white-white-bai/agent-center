from app.api.deps import get_model_router
from app.core.tenant import TenantContext
from app.integrations.llm.client import LLMResponse
from app.integrations.llm.router import ModelRouter
from app.main import app

HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "u1"}


class Client:
    def __init__(self, reply: str, *, fail: bool = False) -> None:
        self.reply = reply
        self.fail = fail

    async def complete(self, request):
        if self.fail:
            raise RuntimeError("down")
        return LLMResponse(content=self.reply, model=request.model)

    async def stream(self, request):
        yield ""


async def _seed_profile(async_client, db_session) -> None:
    await async_client.post(
        "/api/v1/profile/tags",
        json={"tags": [{"key": "所在区域", "value": "天宁区"}]},
        headers=HEADERS,
    )
    from app.domain.profile.service import record_event

    await record_event(
        db_session,
        TenantContext(tenant_id="t1", user_id="u1"),
        event_type="matter.active",
        payload={"matter": "营业执照", "status": "受理中"},
    )


async def test_suggestions_use_model_output(async_client, db_session) -> None:
    await _seed_profile(async_client, db_session)
    app.dependency_overrides[get_model_router] = lambda: ModelRouter(
        Client('{"suggestions":["建议一","建议二"],"summary":"模型总结"}')
    )

    response = await async_client.get("/api/v1/profile/suggestions", headers=HEADERS)

    data = response.json()["data"]
    assert data["source"] == "model"
    assert data["suggestions"] == ["建议一", "建议二"]


async def test_suggestions_are_normalized(async_client, db_session) -> None:
    await _seed_profile(async_client, db_session)
    app.dependency_overrides[get_model_router] = lambda: ModelRouter(
        Client(
            '{"suggestions":["重复建议","重复建议","  ","' + "长" * 200 + '"],'
            '"summary":"' + "摘要" * 200 + '"}'
        )
    )

    data = (await async_client.get("/api/v1/profile/suggestions", headers=HEADERS)).json()["data"]

    assert data["source"] == "model"
    assert len(data["suggestions"]) == 2
    assert data["suggestions"][0] == "重复建议"
    assert len(data["suggestions"][1]) <= 120
    assert len(data["summary"]) <= 200


async def test_suggestions_fall_back_to_rules(async_client, db_session) -> None:
    await _seed_profile(async_client, db_session)
    app.dependency_overrides[get_model_router] = lambda: ModelRouter(Client("", fail=True))

    response = await async_client.get("/api/v1/profile/suggestions", headers=HEADERS)

    data = response.json()["data"]
    assert data["source"] == "rule"
    assert any("营业执照" in item for item in data["suggestions"])
