HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "u1", "X-Roles": "admin"}


async def test_bulk_import_eval_cases(async_client) -> None:
    dataset_id = (
        await async_client.post(
            "/api/v1/admin/eval-datasets",
            json={"code": "baseline", "name": "chatflow 基线"},
            headers=HEADERS,
        )
    ).json()["data"]["id"]

    response = await async_client.post(
        f"/api/v1/admin/eval-datasets/{dataset_id}/cases/import",
        json={
            "cases": [
                {"question": "营业执照材料", "expectedAnswer": "身份证"},
                {"question": "办理时限", "expectedAnswer": "五个工作日"},
            ]
        },
        headers=HEADERS,
    )

    data = response.json()["data"]
    assert data["imported"] == 2
    assert len(data["caseIds"]) == 2


async def test_bulk_import_requires_cases(async_client) -> None:
    dataset_id = (
        await async_client.post(
            "/api/v1/admin/eval-datasets",
            json={"code": "baseline2", "name": "基线2"},
            headers=HEADERS,
        )
    ).json()["data"]["id"]

    response = await async_client.post(
        f"/api/v1/admin/eval-datasets/{dataset_id}/cases/import",
        json={"cases": []},
        headers=HEADERS,
    )

    assert response.status_code == 422
