ADMIN = {"X-Tenant-Id": "t1", "X-User-Id": "admin1", "X-Roles": "admin"}


def _create_agent(client, code: str = "district_consult") -> int:
    response = client.post(
        "/api/v1/admin/agents",
        json={"code": code, "name": "区级咨询", "domain_code": "district_service"},
        headers=ADMIN,
    )
    assert response.status_code == 200
    return response.json()["data"]["id"]


def _create_version(client, agent_id: int) -> int:
    response = client.post(
        f"/api/v1/admin/agents/{agent_id}/versions",
        json={"role": "政务顾问", "goal": "解答办事政策", "tools": ["knowledge.search"]},
        headers=ADMIN,
    )
    assert response.status_code == 200
    return response.json()["data"]["id"]


def test_publish_agent_version(client) -> None:
    agent_id = _create_agent(client)
    version_id = _create_version(client, agent_id)

    published = client.post(
        f"/api/v1/admin/agents/{agent_id}/publish",
        json={"version_id": version_id},
        headers=ADMIN,
    )

    assert published.status_code == 200
    data = published.json()["data"]
    assert data["status"] == "PUBLISHED"
    assert data["publishedAt"] is not None

    agents = client.get("/api/v1/admin/agents", headers=ADMIN).json()["data"]
    assert agents[0]["lifecycle"] == "PUBLISHED"
    assert agents[0]["currentVersionId"] == version_id


def test_duplicate_agent_code_is_rejected(client) -> None:
    _create_agent(client, "dup_agent")

    response = client.post(
        "/api/v1/admin/agents",
        json={"code": "dup_agent", "name": "重复", "domain_code": "d"},
        headers=ADMIN,
    )

    assert response.status_code == 409


def test_publishing_new_version_deprecates_previous_and_allows_rollback(client) -> None:
    agent_id = _create_agent(client, "multi_version")
    first = _create_version(client, agent_id)
    client.post(f"/api/v1/admin/agents/{agent_id}/publish", json={"version_id": first}, headers=ADMIN)
    second = _create_version(client, agent_id)

    client.post(f"/api/v1/admin/agents/{agent_id}/publish", json={"version_id": second}, headers=ADMIN)
    rollback = client.post(
        f"/api/v1/admin/agents/{agent_id}/publish",
        json={"version_id": first},
        headers=ADMIN,
    )

    assert rollback.status_code == 200
    assert rollback.json()["data"]["id"] == first
    agents = client.get("/api/v1/admin/agents", headers=ADMIN).json()["data"]
    assert agents[0]["currentVersionId"] == first


def test_republishing_same_version_is_rejected(client) -> None:
    agent_id = _create_agent(client, "same_version")
    version_id = _create_version(client, agent_id)
    client.post(f"/api/v1/admin/agents/{agent_id}/publish", json={"version_id": version_id}, headers=ADMIN)

    response = client.post(
        f"/api/v1/admin/agents/{agent_id}/publish",
        json={"version_id": version_id},
        headers=ADMIN,
    )

    assert response.status_code == 409


def test_agent_is_tenant_isolated(client) -> None:
    agent_id = _create_agent(client, "isolated_agent")
    version_id = _create_version(client, agent_id)

    response = client.post(
        f"/api/v1/admin/agents/{agent_id}/publish",
        json={"version_id": version_id},
        headers={"X-Tenant-Id": "t2", "X-User-Id": "other"},
    )

    assert response.status_code == 404
