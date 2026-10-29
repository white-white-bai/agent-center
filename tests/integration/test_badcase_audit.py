HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "admin1", "X-Roles": "admin"}


async def _create_dataset(async_client) -> int:
    return (
        await async_client.post(
            "/api/v1/admin/eval-datasets",
            json={"code": "badcase_eval", "name": "Badcase 评测集"},
            headers=HEADERS,
        )
    ).json()["data"]["id"]


async def test_downvote_creates_badcase(async_client) -> None:
    await async_client.post(
        "/api/v1/feedback",
        json={"rating": "down", "reason": "answer_inaccurate", "comment": "口径不一致"},
        headers=HEADERS,
    )

    badcases = (await async_client.get("/api/v1/admin/badcases", headers=HEADERS)).json()["data"]

    assert len(badcases) == 1
    assert badcases[0]["status"] == "OPEN"
    assert badcases[0]["description"] == "口径不一致"


async def test_upvote_does_not_create_badcase(async_client) -> None:
    await async_client.post("/api/v1/feedback", json={"rating": "up"}, headers=HEADERS)

    badcases = (await async_client.get("/api/v1/admin/badcases", headers=HEADERS)).json()["data"]

    assert badcases == []


async def test_convert_badcase_to_eval_case(async_client) -> None:
    dataset_id = await _create_dataset(async_client)
    await async_client.post(
        "/api/v1/feedback", json={"rating": "down", "comment": "回答错误"}, headers=HEADERS
    )
    badcase_id = (await async_client.get("/api/v1/admin/badcases", headers=HEADERS)).json()["data"][0]["id"]

    converted = await async_client.post(
        f"/api/v1/admin/badcases/{badcase_id}/convert",
        json={"datasetId": dataset_id, "question": "营业执照材料", "expectedAnswer": "身份证"},
        headers=HEADERS,
    )

    assert converted.status_code == 200
    data = converted.json()["data"]
    assert data["status"] == "CONVERTED"
    assert data["evalCaseId"] is not None

    again = await async_client.post(
        f"/api/v1/admin/badcases/{badcase_id}/convert",
        json={"datasetId": dataset_id, "question": "重复"},
        headers=HEADERS,
    )
    assert again.status_code == 409


async def test_audit_log_records_sensitive_actions(async_client) -> None:
    agent_id = (
        await async_client.post(
            "/api/v1/admin/agents",
            json={"code": "audit_agent", "name": "审计 Agent", "domain_code": "d1"},
            headers=HEADERS,
        )
    ).json()["data"]["id"]
    version_id = (
        await async_client.post(
            f"/api/v1/admin/agents/{agent_id}/versions", json={"role": "顾问"}, headers=HEADERS
        )
    ).json()["data"]["id"]
    await async_client.post(
        f"/api/v1/admin/agents/{agent_id}/publish",
        json={"version_id": version_id},
        headers=HEADERS,
    )

    logs = (
        await async_client.get(
            "/api/v1/admin/audit-logs", params={"action": "agent.publish"}, headers=HEADERS
        )
    ).json()["data"]

    assert len(logs) == 1
    assert logs[0]["action"] == "agent.publish"
    assert logs[0]["resourceId"] == str(agent_id)
    assert logs[0]["userId"] == "admin1"


async def test_audit_logs_are_filtered_and_tenant_isolated(async_client) -> None:
    await async_client.post(
        "/api/v1/admin/tools",
        json={"tool_code": "tool_a", "name": "工具A"},
        headers=HEADERS,
    )
    agent_id = (
        await async_client.post(
            "/api/v1/admin/agents",
            json={"code": "audit_agent_2", "name": "审计 Agent2", "domain_code": "d1"},
            headers=HEADERS,
        )
    ).json()["data"]["id"]
    version_id = (
        await async_client.post(
            f"/api/v1/admin/agents/{agent_id}/versions", json={"role": "顾问"}, headers=HEADERS
        )
    ).json()["data"]["id"]
    await async_client.post(
        f"/api/v1/admin/agents/{agent_id}/publish",
        json={"version_id": version_id},
        headers=HEADERS,
    )

    filtered = (
        await async_client.get(
            "/api/v1/admin/audit-logs", params={"action": "agent.publish"}, headers=HEADERS
        )
    ).json()["data"]
    assert len(filtered) == 1

    other_tenant = (
        await async_client.get(
            "/api/v1/admin/audit-logs",
            headers={"X-Tenant-Id": "t2", "X-User-Id": "admin2", "X-Roles": "admin"},
        )
    ).json()["data"]
    assert other_tenant == []
