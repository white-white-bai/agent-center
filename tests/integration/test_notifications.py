from datetime import datetime, timedelta

HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "u1"}


async def test_schedule_and_list_notification(async_client) -> None:
    created = await async_client.post(
        "/api/v1/notifications",
        json={"type": "matter_reminder", "title": "营业执照年检即将到期", "content": "请及时办理"},
        headers=HEADERS,
    )

    assert created.status_code == 200
    assert created.json()["data"]["status"] == "PENDING"

    listed = await async_client.get("/api/v1/notifications", headers=HEADERS)
    assert [item["title"] for item in listed.json()["data"]] == ["营业执照年检即将到期"]


async def test_dispatch_only_sends_due_notifications(async_client) -> None:
    past = (datetime.utcnow() - timedelta(minutes=1)).isoformat()
    future = (datetime.utcnow() + timedelta(days=1)).isoformat()
    await async_client.post(
        "/api/v1/notifications",
        json={"type": "reminder", "title": "已到期", "scheduledAt": past},
        headers=HEADERS,
    )
    await async_client.post(
        "/api/v1/notifications",
        json={"type": "reminder", "title": "未到期", "scheduledAt": future},
        headers=HEADERS,
    )

    dispatched = await async_client.post(
        "/api/v1/admin/notifications/dispatch-due", headers=HEADERS
    )

    assert dispatched.json()["data"]["dispatched"] == 1
    items = (await async_client.get("/api/v1/notifications", headers=HEADERS)).json()["data"]
    statuses = {item["title"]: item["status"] for item in items}
    assert statuses == {"已到期": "SENT", "未到期": "PENDING"}


async def test_cancel_notification(async_client) -> None:
    notification_id = (
        await async_client.post(
            "/api/v1/notifications",
            json={"type": "reminder", "title": "待取消"},
            headers=HEADERS,
        )
    ).json()["data"]["id"]

    cancelled = await async_client.delete(f"/api/v1/notifications/{notification_id}", headers=HEADERS)
    assert cancelled.json()["data"]["status"] == "CANCELLED"

    listed = (await async_client.get("/api/v1/notifications", headers=HEADERS)).json()["data"]
    assert listed == []


async def test_notifications_are_user_and_tenant_isolated(async_client) -> None:
    await async_client.post(
        "/api/v1/notifications",
        json={"type": "reminder", "title": "我的提醒"},
        headers=HEADERS,
    )

    other_user = (
        await async_client.get("/api/v1/notifications", headers={"X-Tenant-Id": "t1", "X-User-Id": "u2"})
    ).json()["data"]
    other_tenant = (
        await async_client.get("/api/v1/notifications", headers={"X-Tenant-Id": "t2", "X-User-Id": "u1"})
    ).json()["data"]

    assert other_user == []
    assert other_tenant == []
