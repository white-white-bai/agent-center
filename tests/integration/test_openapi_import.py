HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "admin1", "X-Roles": "admin"}

SPEC = {
    "paths": {
        "/matters/status": {
            "get": {
                "operationId": "matter.status.query",
                "summary": "查询办理进度",
                "parameters": [
                    {
                        "name": "application_number",
                        "in": "query",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
            }
        },
        "/matters/submit": {
            "post": {
                "summary": "提交申请",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["matter_type"],
                                "properties": {"matter_type": {"type": "string"}},
                            }
                        }
                    }
                },
            }
        },
    }
}


async def test_openapi_import_preview_only(async_client) -> None:
    response = await async_client.post(
        "/api/v1/admin/tools/import-openapi",
        json={"spec": SPEC, "auto_register": False},
        headers=HEADERS,
    )

    data = response.json()["data"]
    assert data["total"] == 2
    assert data["created"] == []
    assert {item["method"] for item in data["preview"]} == {"GET", "POST"}


async def test_openapi_import_registers_and_skips_duplicates(async_client) -> None:
    first = await async_client.post(
        "/api/v1/admin/tools/import-openapi",
        json={"spec": SPEC, "auto_register": True, "base_url": "http://biz.local"},
        headers=HEADERS,
    )
    data = first.json()["data"]
    assert data["total"] == 2
    assert set(data["created"]) == {"matter.status.query", "post.matters.submit"}

    second = await async_client.post(
        "/api/v1/admin/tools/import-openapi",
        json={"spec": SPEC, "auto_register": True, "base_url": "http://biz.local"},
        headers=HEADERS,
    )
    assert second.json()["data"]["created"] == []
    assert set(second.json()["data"]["skipped"]) == {"matter.status.query", "post.matters.submit"}


async def test_openapi_import_rejects_unknown_spec(async_client) -> None:
    response = await async_client.post(
        "/api/v1/admin/tools/import-openapi",
        json={"spec": {}, "auto_register": True},
        headers=HEADERS,
    )

    assert response.json()["data"]["total"] == 0
