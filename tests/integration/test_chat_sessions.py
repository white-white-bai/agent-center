def test_create_and_get_session(client) -> None:
    headers = {"X-Tenant-Id": "t1", "X-User-Id": "u1"}

    created = client.post(
        "/api/v1/chat/sessions",
        json={"channel": "web", "agent_group_code": "district_service", "metadata": {"region_code": "320402"}},
        headers=headers,
    )

    assert created.status_code == 200
    body = created.json()
    assert body["code"] == "0"
    session_id = body["data"]["sessionId"]
    assert body["data"]["status"] == "ACTIVE"

    fetched = client.get(f"/api/v1/chat/sessions/{session_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["data"]["sessionId"] == session_id


def test_session_is_tenant_isolated(client) -> None:
    created = client.post(
        "/api/v1/chat/sessions",
        json={"channel": "web"},
        headers={"X-Tenant-Id": "t1", "X-User-Id": "u1"},
    )

    session_id = created.json()["data"]["sessionId"]
    response = client.get(
        f"/api/v1/chat/sessions/{session_id}",
        headers={"X-Tenant-Id": "t2", "X-User-Id": "u2"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "AC.COMMON.NOT_FOUND"


def test_create_session_requires_identity(client) -> None:
    response = client.post("/api/v1/chat/sessions", json={"channel": "web"})

    assert response.status_code == 401


def test_get_unknown_session_returns_404(client) -> None:
    response = client.get(
        "/api/v1/chat/sessions/999999",
        headers={"X-Tenant-Id": "t1", "X-User-Id": "u1"},
    )

    assert response.status_code == 404
