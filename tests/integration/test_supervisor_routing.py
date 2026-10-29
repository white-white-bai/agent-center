HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "admin1", "X-Roles": "admin"}


def _publish_agent(client, code: str, name: str, domain: str, rules: dict) -> None:
    agent_id = client.post(
        "/api/v1/admin/agents",
        json={"code": code, "name": name, "domain_code": domain},
        headers=HEADERS,
    ).json()["data"]["id"]
    version_id = client.post(
        f"/api/v1/admin/agents/{agent_id}/versions",
        json={"role": name, "goal": name, "router_rules": rules},
        headers=HEADERS,
    ).json()["data"]["id"]
    client.post(f"/api/v1/admin/agents/{agent_id}/publish", json={"version_id": version_id}, headers=HEADERS)


def test_route_selects_matching_agent(client) -> None:
    _publish_agent(client, "district_consult", "区级咨询", "district_service", {"keywords": ["营业执照", "社保"]})
    _publish_agent(client, "transaction_agent", "公共资源交易", "transaction", {"keywords": ["招投标", "投标"]})

    response = client.post(
        "/api/v1/admin/route-preview",
        json={"message": "营业执照怎么办理"},
        headers=HEADERS,
    )

    data = response.json()["data"]
    assert data["selectedAgent"] == "district_consult"
    assert data["needClarification"] is False
    assert data["reasonCode"] == "DOMAIN_MATCH"


def test_route_returns_clarification_when_no_match(client) -> None:
    _publish_agent(client, "agent_a", "AgentA", "d1", {"keywords": ["营业执照"]})
    _publish_agent(client, "agent_b", "AgentB", "d2", {"keywords": ["招投标"]})

    response = client.post(
        "/api/v1/admin/route-preview",
        json={"message": "今天天气怎么样"},
        headers=HEADERS,
    )

    data = response.json()["data"]
    assert data["selectedAgent"] is None
    assert data["needClarification"] is True
    assert data["reasonCode"] == "NO_MATCH"


def test_route_marks_ties_as_low_confidence(client) -> None:
    _publish_agent(client, "agent_a", "AgentA", "d1", {"keywords": ["办事"]})
    _publish_agent(client, "agent_b", "AgentB", "d2", {"keywords": ["办事"]})

    response = client.post(
        "/api/v1/admin/route-preview",
        json={"message": "我要办事"},
        headers=HEADERS,
    )

    data = response.json()["data"]
    assert data["needClarification"] is True
    assert data["confidence"] <= 0.5


def test_route_filters_by_channel(client) -> None:
    _publish_agent(client, "web_only", "网页客服", "d1", {"keywords": ["咨询"], "channels": ["web"]})
    _publish_agent(client, "app_only", "小程序客服", "d2", {"keywords": ["咨询"], "channels": ["mini"]})

    response = client.post(
        "/api/v1/admin/route-preview",
        json={"message": "咨询政策", "channel": "web"},
        headers=HEADERS,
    )

    data = response.json()["data"]
    assert data["selectedAgent"] == "web_only"
    assert data["needClarification"] is False


def test_route_with_single_agent_skips_keyword_match(client) -> None:
    _publish_agent(client, "only_agent", "唯一 Agent", "d1", {"keywords": ["营业执照"]})

    response = client.post(
        "/api/v1/admin/route-preview",
        json={"message": "今天天气怎么样"},
        headers=HEADERS,
    )

    data = response.json()["data"]
    assert data["selectedAgent"] == "only_agent"
    assert data["reasonCode"] == "SINGLE_AGENT"
