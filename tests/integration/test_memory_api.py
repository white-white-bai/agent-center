HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "u1"}


async def test_memory_api_crud(async_client) -> None:
    created = await async_client.post(
        "/api/v1/memory",
        json={"subject": "所在区域", "predicate": "lives_in", "value": "常州天宁区"},
        headers=HEADERS,
    )

    assert created.status_code == 200
    assert created.json()["data"]["stored"] is True
    memory_id = created.json()["data"]["memory"]["id"]

    listed = await async_client.get("/api/v1/memory", headers=HEADERS)
    assert len(listed.json()["data"]) == 1

    searched = await async_client.get("/api/v1/memory/search", params={"q": "天宁区"}, headers=HEADERS)
    assert searched.json()["data"][0]["value"] == "常州天宁区"

    deleted = await async_client.delete(f"/api/v1/memory/{memory_id}", headers=HEADERS)
    assert deleted.json()["data"]["deleted"] is True

    after = await async_client.get("/api/v1/memory", headers=HEADERS)
    assert after.json()["data"] == []


async def test_memory_api_rejects_sensitive_value(async_client) -> None:
    response = await async_client.post(
        "/api/v1/memory",
        json={"subject": "证件", "predicate": "id", "value": "身份证 320402199001011234"},
        headers=HEADERS,
    )

    assert response.json()["data"]["stored"] is False


async def test_delete_unknown_memory_returns_404(async_client) -> None:
    response = await async_client.delete("/api/v1/memory/9999", headers=HEADERS)

    assert response.status_code == 404
