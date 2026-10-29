import json

HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "u1", "X-Roles": "admin"}


def _publish(client, code: str, keywords: list[str]) -> None:
    agent_id = client.post(
        "/api/v1/admin/agents",
        json={"code": code, "name": code, "domain_code": "d1"},
        headers=HEADERS,
    ).json()["data"]["id"]
    version_id = client.post(
        f"/api/v1/admin/agents/{agent_id}/versions",
        json={"role": code, "router_rules": {"keywords": keywords}},
        headers=HEADERS,
    ).json()["data"]["id"]
    client.post(
        f"/api/v1/admin/agents/{agent_id}/publish",
        json={"version_id": version_id},
        headers=HEADERS,
    )


def _events(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        name = None
        data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        if name:
            events.append((name, data))
    return events


def test_uncertain_routing_returns_clarification_stream(client) -> None:
    _publish(client, "agent_a", ["营业执照"])
    _publish(client, "agent_b", ["招投标"])

    session_id = client.post(
        "/api/v1/chat/sessions", json={"channel": "web"}, headers=HEADERS
    ).json()["data"]["sessionId"]

    response = client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"message": "今天天气怎么样"},
        headers=HEADERS,
    )

    assert response.status_code == 200
    events = _events(response.text)
    assert [name for name, _ in events] == ["message.delta", "message.end"]
    assert "请补充" in events[0][1]["content"]
    assert events[-1][1]["finishReason"] == "waiting_user"
