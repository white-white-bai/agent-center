from app.domain.knowledge import sync

HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "u1", "X-Roles": "admin"}


async def test_dify_sync_task_run_and_search(async_client, monkeypatch) -> None:
    async def fake_dify(source_ref: str):
        assert source_ref == "ds1"
        return [
            {
                "document_code": "dify:ds1:d1",
                "title": "Dify 营业执照",
                "content": "Dify 迁移内容：营业执照需要身份证。",
            }
        ]

    monkeypatch.setattr(sync, "dify_fetcher", fake_dify)
    space_id = (
        await async_client.post(
            "/api/v1/admin/knowledge-spaces",
            json={"code": "dify_kb", "name": "Dify 知识", "domainCode": "district_service"},
            headers=HEADERS,
        )
    ).json()["data"]["id"]
    created = await async_client.post(
        "/api/v1/admin/knowledge-sync-tasks",
        json={"spaceId": space_id, "sourceType": "DIFY", "sourceRef": "ds1"},
        headers=HEADERS,
    )
    assert created.status_code == 200
    task_id = created.json()["data"]["id"]
    assert created.json()["data"]["status"] == "PENDING"

    run = await async_client.post(
        f"/api/v1/admin/knowledge-sync-tasks/{task_id}/run", headers=HEADERS
    )
    assert run.status_code == 200
    assert run.json()["data"]["status"] == "SUCCESS"
    assert run.json()["data"]["checkpoint"]["processed"] == ["dify:ds1:d1"]

    hits = (
        await async_client.post(
            "/api/v1/knowledge/search",
            json={"query": "Dify 迁移", "topK": 5},
            headers=HEADERS,
        )
    ).json()["data"]
    assert hits
    assert hits[0]["title"] == "Dify 营业执照"

    again = await async_client.post(
        f"/api/v1/admin/knowledge-sync-tasks/{task_id}/run", headers=HEADERS
    )
    assert again.json()["data"]["status"] == "SUCCESS"
