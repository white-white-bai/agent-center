from datetime import datetime, timedelta

HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "admin1", "X-Roles": "admin"}


async def _create(async_client, user: str = "u1", channel: str = "web") -> None:
    await async_client.post(
        "/api/v1/chat/sessions",
        json={"channel": channel},
        headers={**HEADERS, "X-User-Id": user},
    )


async def test_list_sessions_with_filters(async_client) -> None:
    await _create(async_client, user="u1")
    await _create(async_client, user="u2", channel="mini")

    all_items = (await async_client.get("/api/v1/admin/sessions", headers=HEADERS)).json()["data"]
    assert all_items["total"] == 2

    filtered = (
        await async_client.get(
            "/api/v1/admin/sessions", params={"userId": "u1"}, headers=HEADERS
        )
    ).json()["data"]
    assert filtered["total"] == 1
    assert filtered["items"][0]["channel"] == "web"


async def test_list_sessions_pagination(async_client) -> None:
    for _ in range(3):
        await _create(async_client)

    page1 = (
        await async_client.get(
            "/api/v1/admin/sessions", params={"page": 1, "pageSize": 2}, headers=HEADERS
        )
    ).json()["data"]
    page2 = (
        await async_client.get(
            "/api/v1/admin/sessions", params={"page": 2, "pageSize": 2}, headers=HEADERS
        )
    ).json()["data"]

    assert page1["total"] == 3
    assert len(page1["items"]) == 2
    assert len(page2["items"]) == 1
    assert page1["items"][0]["sessionId"] != page2["items"][0]["sessionId"]


async def test_list_sessions_is_tenant_isolated(async_client) -> None:
    await _create(async_client)

    other = (
        await async_client.get(
            "/api/v1/admin/sessions",
            headers={"X-Tenant-Id": "t2", "X-User-Id": "admin2", "X-Roles": "admin"},
        )
    ).json()["data"]

    assert other["total"] == 0


async def test_list_sessions_requires_admin(async_client) -> None:
    response = await async_client.get(
        "/api/v1/admin/sessions",
        headers={"X-Tenant-Id": "t1", "X-User-Id": "u1"},
    )

    assert response.status_code == 403
