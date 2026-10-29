HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "u1"}


async def test_merge_tags_and_summary(async_client) -> None:
    merged = await async_client.post(
        "/api/v1/profile/tags",
        json={"tags": [{"key": "回答风格", "value": "简洁", "confidence": 0.8}]},
        headers=HEADERS,
    )
    assert merged.status_code == 200

    summary = await async_client.get("/api/v1/profile/summary", headers=HEADERS)
    data = summary.json()["data"]
    assert "回答风格：简洁" in data["summary"]


async def test_merge_tags_updates_existing_key(async_client) -> None:
    await async_client.post(
        "/api/v1/profile/tags",
        json={"tags": [{"key": "所在区域", "value": "天宁区"}]},
        headers=HEADERS,
    )
    await async_client.post(
        "/api/v1/profile/tags",
        json={"tags": [{"key": "所在区域", "value": "钟楼区"}]},
        headers=HEADERS,
    )

    tags = (await async_client.get("/api/v1/profile/tags", headers=HEADERS)).json()["data"]

    assert len(tags) == 1
    assert tags[0]["value"] == "钟楼区"


async def test_profile_is_user_isolated(async_client) -> None:
    await async_client.post(
        "/api/v1/profile/tags",
        json={"tags": [{"key": "k", "value": "v"}]},
        headers=HEADERS,
    )

    other = await async_client.get(
        "/api/v1/profile/tags",
        headers={"X-Tenant-Id": "t1", "X-User-Id": "u2"},
    )

    assert other.json()["data"] == []


async def test_active_matters_are_returned(async_client, db_session) -> None:
    from app.core.tenant import TenantContext
    from app.domain.profile import service

    ctx = TenantContext(tenant_id="t1", user_id="u1")
    await service.record_event(
        db_session, ctx, event_type="matter.active", payload={"matter": "营业执照", "status": "受理中"}
    )

    summary = await async_client.get("/api/v1/profile/summary", headers=HEADERS)

    assert summary.json()["data"]["activeMatters"] == [{"matter": "营业执照", "status": "受理中"}]
