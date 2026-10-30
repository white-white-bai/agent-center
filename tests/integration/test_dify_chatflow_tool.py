from app.integrations import dify
from app.integrations.dify import CHATFLOW_TOOL_CODE

HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "u1", "X-Roles": "admin"}


async def test_import_and_invoke_dify_chatflow_tool(async_client, monkeypatch) -> None:
    created = await async_client.post(
        "/api/v1/admin/tools/import-dify-chatflow", headers=HEADERS
    )
    assert created.status_code == 200
    assert created.json()["data"] == {"created": True, "toolCode": CHATFLOW_TOOL_CODE}

    again = await async_client.post(
        "/api/v1/admin/tools/import-dify-chatflow", headers=HEADERS
    )
    assert again.json()["data"]["created"] is False

    calls = []

    async def fake_invoke(query, **kwargs):
        calls.append({"query": query, "kwargs": kwargs})
        return {"answer": "来自 Dify", "conversationId": "c1", "messageId": "m1"}

    monkeypatch.setattr(dify, "invoke_chatflow", fake_invoke)

    response = await async_client.post(
        f"/api/v1/admin/tools/{CHATFLOW_TOOL_CODE}/test",
        json={"arguments": {"query": "你好", "inputs": {"city": "常州"}}},
        headers=HEADERS,
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "SUCCESS"
    assert data["output"]["answer"] == "来自 Dify"
    assert calls[0]["query"] == "你好"
    assert calls[0]["kwargs"]["inputs"] == {"city": "常州"}
