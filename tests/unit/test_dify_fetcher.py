import json

import httpx

from app.domain.knowledge.sync import dify_fetcher


def _handler(request: httpx.Request) -> httpx.Response:
    assert request.headers["Authorization"] == "Bearer dify-key"
    path = request.url.path
    page = int(request.url.params.get("page", "1"))
    if path.endswith("/documents"):
        if page == 1:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "d1", "name": "营业执照指南"},
                        {"id": "d2", "name": "空文档"},
                    ],
                    "has_more": True,
                },
            )
        return httpx.Response(
            200, json={"data": [{"id": "d3", "name": "补贴政策"}], "has_more": False}
        )
    if path.endswith("/segments"):
        document_id = path.split("/")[-2]
        if document_id == "d2":
            return httpx.Response(200, json={"data": [], "has_more": False})
        if page == 1 and document_id == "d1":
            return httpx.Response(
                200,
                json={"data": [{"content": "第一段"}], "has_more": True},
            )
        return httpx.Response(
            200,
            json={"data": [{"content": f"{document_id}-第二段"}], "has_more": False},
        )
    return httpx.Response(404)


async def test_dify_fetcher_maps_documents_and_segments() -> None:
    documents = await dify_fetcher(
        "ds1",
        base_url="https://dify.local",
        api_key="dify-key",
        page_size=2,
        transport=httpx.MockTransport(_handler),
    )

    assert [doc["document_code"] for doc in documents] == ["dify:ds1:d1", "dify:ds1:d3"]
    assert documents[0]["title"] == "营业执照指南"
    assert documents[0]["content"] == "第一段\n\nd1-第二段"
    assert documents[1]["content"] == "d3-第二段"


async def test_dify_fetcher_requires_configuration() -> None:
    import pytest

    with pytest.raises(ValueError):
        await dify_fetcher("ds1", base_url="", api_key="")
