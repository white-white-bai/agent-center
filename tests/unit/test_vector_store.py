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


def test_cosine_handles_zero_vectors() -> None:
    store = InMemoryVectorStore()
    assert store._cosine([], [1.0]) == 0.0
    assert math.isclose(store._cosine([1.0, 0.0], [1.0, 0.0]), 1.0)
