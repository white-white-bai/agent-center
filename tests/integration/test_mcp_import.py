from app.integrations.mcp.client import MCPClient

HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "u1", "X-Roles": "admin"}


class _FakeMCPClient:
    def __init__(self, config: dict, timeout: float = 10.0) -> None:
        self.config = config

    async def list_tools(self) -> list[dict]:
        return [
            {
                "name": "echo",
                "description": "回显文本",
                "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}},
                "annotations": {"readOnlyHint": True},
            }
        ]

    async def call_tool(self, name: str, arguments: dict) -> dict:
        return {"content": [{"type": "text", "text": arguments.get("q", "")}]}

    async def close(self) -> None:
        return None


def _patch(monkeypatch) -> None:
    monkeypatch.setattr(
        MCPClient,
        "from_config",
        classmethod(lambda cls, config, timeout=10.0: _FakeMCPClient(config, timeout)),
    )


def test_import_mcp_preview_and_register(client, monkeypatch) -> None:
    _patch(monkeypatch)

    response = client.post(
        "/api/v1/admin/tools/import-mcp",
        json={
            "transport": "sse",
            "url": "http://mcp.local/sse",
            "tool_prefix": "mcp.",
            "auto_register": True,
        },
        headers=HEADERS,
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 1
    assert data["created"] == ["mcp.echo"]
    assert data["preview"][0]["writeOperation"] is False

    again = client.post(
        "/api/v1/admin/tools/import-mcp",
        json={
            "transport": "sse",
            "url": "http://mcp.local/sse",
            "tool_prefix": "mcp.",
            "auto_register": True,
        },
        headers=HEADERS,
    ).json()["data"]
    assert again["skipped"] == ["mcp.echo"]


def test_import_mcp_rejects_invalid_config(client) -> None:
    response = client.post(
        "/api/v1/admin/tools/import-mcp",
        json={"transport": "sse"},
        headers=HEADERS,
    )
    assert response.status_code == 422

    response = client.post(
        "/api/v1/admin/tools/import-mcp",
        json={"transport": "stdio"},
        headers=HEADERS,
    )
    assert response.status_code == 422


def test_mcp_tool_executes_through_tool_service(client, monkeypatch) -> None:
    _patch(monkeypatch)
    client.post(
        "/api/v1/admin/tools/import-mcp",
        json={
            "transport": "stdio",
            "command": ["fake-mcp"],
            "auto_register": True,
        },
        headers=HEADERS,
    )

    response = client.post(
        "/api/v1/admin/tools/echo/test",
        json={"arguments": {"q": "你好"}},
        headers=HEADERS,
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "SUCCESS"
    assert data["output"]["content"][0]["text"] == "你好"
