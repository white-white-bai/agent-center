import math

from app.infrastructure.vector.store import InMemoryVectorStore


def test_in_memory_vector_store_ranks_by_cosine() -> None:
    store = InMemoryVectorStore()
    store.upsert(
        "t1",
        [
            ("a", [1.0, 0.0], {"status": "ACTIVE"}),
            ("b", [0.0, 1.0], {"status": "ACTIVE"}),
            ("c", [1.0, 1.0], {"status": "DRAFT"}),
        ],
    )

    hits = store.search("t1", [0.9, 0.1], top_k=5)

    assert [item_id for item_id, _ in hits] == ["a", "b"]
    assert hits[0][1] > hits[1][1]


def test_in_memory_vector_store_is_tenant_isolated() -> None:
    store = InMemoryVectorStore()
    store.upsert("t1", [("a", [1.0, 0.0], {"status": "ACTIVE"})])

    assert store.search("t2", [1.0, 0.0], top_k=5) == []


def test_in_memory_vector_store_delete() -> None:
    store = InMemoryVectorStore()
    store.upsert("t1", [("a", [1.0], {"status": "ACTIVE"})])
    store.delete("t1", ["a"])

    assert store.search("t1", [1.0], top_k=5) == []


def test_milvus_fallback_retries_after_startup(monkeypatch) -> None:
    from types import SimpleNamespace

    from app.infrastructure.vector import store as vector_store

    class FakeMilvus:
        attempts = 0

        def __init__(self, *args, **kwargs) -> None:
            FakeMilvus.attempts += 1
            if FakeMilvus.attempts == 1:
                raise RuntimeError("not ready")

    monkeypatch.setattr(
        vector_store,
        "get_settings",
        lambda: SimpleNamespace(
            milvus_uri="http://milvus:19530",
            milvus_collection="c",
            embedding_dim=4,
        ),
    )
    monkeypatch.setattr(vector_store, "MilvusVectorStore", FakeMilvus)
    vector_store.reset_vector_store()

    first = vector_store.get_vector_store()
    assert isinstance(first, InMemoryVectorStore)
    assert FakeMilvus.attempts == 1

    vector_store._last_attempt = 0.0
    second = vector_store.get_vector_store()
    assert isinstance(second, FakeMilvus)
    assert FakeMilvus.attempts == 2
    vector_store.reset_vector_store()


def test_cosine_handles_zero_vectors() -> None:
    store = InMemoryVectorStore()
    assert store._cosine([], [1.0]) == 0.0
    assert math.isclose(store._cosine([1.0, 0.0], [1.0, 0.0]), 1.0)
