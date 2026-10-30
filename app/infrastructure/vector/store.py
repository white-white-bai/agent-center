import logging
import math
import time
from typing import Protocol

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class VectorStore(Protocol):
    def upsert(self, tenant_id: str, items: list[tuple[str, list[float], dict]]) -> None: ...

    def search(self, tenant_id: str, vector: list[float], top_k: int) -> list[tuple[str, float]]: ...

    def delete(self, tenant_id: str, ids: list[str]) -> None: ...


class InMemoryVectorStore:
    """测试与降级使用：按租户隔离的内存向量索引。"""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, tuple[list[float], dict]]] = {}

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        if not left or not right:
            return 0.0
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(a * a for a in left)) or 1.0
        right_norm = math.sqrt(sum(b * b for b in right)) or 1.0
        return dot / (left_norm * right_norm)

    def upsert(self, tenant_id: str, items: list[tuple[str, list[float], dict]]) -> None:
        bucket = self._data.setdefault(tenant_id, {})
        for item_id, vector, metadata in items:
            bucket[item_id] = (vector, metadata)

    def search(self, tenant_id: str, vector: list[float], top_k: int) -> list[tuple[str, float]]:
        bucket = self._data.get(tenant_id, {})
        scored = [
            (item_id, self._cosine(vector, stored[0]))
            for item_id, stored in bucket.items()
            if stored[1].get("status") == "ACTIVE"
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]

    def delete(self, tenant_id: str, ids: list[str]) -> None:
        bucket = self._data.get(tenant_id, {})
        for item_id in ids:
            bucket.pop(item_id, None)


class MilvusVectorStore:
    """Milvus 适配器，按需导入 pymilvus；支持 Milvus Lite 本地文件。"""

    def __init__(self, uri: str, collection: str, dim: int) -> None:
        from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility

        self._dim = dim
        self._collection_name = collection
        connections.connect(alias="default", uri=uri)
        if not utility.has_collection(collection):
            schema = CollectionSchema(
                fields=[
                    FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=128),
                    FieldSchema(name="tenant_id", dtype=DataType.VARCHAR, max_length=64),
                    FieldSchema(name="status", dtype=DataType.VARCHAR, max_length=20),
                    FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=dim),
                ]
            )
            collection_obj = Collection(collection, schema=schema)
            collection_obj.create_index(
                field_name="vector",
                index_params={"index_type": "AUTOINDEX", "metric_type": "COSINE"},
            )
        self._collection = Collection(collection)

    def upsert(self, tenant_id: str, items: list[tuple[str, list[float], dict]]) -> None:
        if not items:
            return
        self._collection.upsert(
            [
                [item_id for item_id, _, _ in items],
                [tenant_id for _ in items],
                [metadata.get("status", "ACTIVE") for _, _, metadata in items],
                [vector for _, vector, _ in items],
            ]
        )
        self._collection.flush()

    def search(self, tenant_id: str, vector: list[float], top_k: int) -> list[tuple[str, float]]:
        self._collection.load()
        results = self._collection.search(
            data=[vector],
            anns_field="vector",
            param={"metric_type": "COSINE"},
            limit=top_k,
            expr=f'tenant_id == "{tenant_id}" and status == "ACTIVE"',
            output_fields=["id"],
        )
        hits: list[tuple[str, float]] = []
        for hit in results[0]:
            hits.append((hit.id, float(hit.score)))
        return hits

    def delete(self, tenant_id: str, ids: list[str]) -> None:
        if not ids:
            return
        quoted = ", ".join(f'"{item_id}"' for item_id in ids)
        self._collection.delete(f"tenant_id == \"{tenant_id}\" and id in [{quoted}]")


_store: VectorStore | None = None
_store_fallback = False
_last_attempt = 0.0
RETRY_INTERVAL_SECONDS = 30.0


def get_vector_store() -> VectorStore:
    global _store, _store_fallback, _last_attempt
    settings = get_settings()
    if _store is not None:
        if not _store_fallback or not settings.milvus_uri:
            return _store
        if time.monotonic() - _last_attempt < RETRY_INTERVAL_SECONDS:
            return _store
    if settings.milvus_uri:
        _last_attempt = time.monotonic()
        try:
            _store = MilvusVectorStore(
                settings.milvus_uri, settings.milvus_collection, settings.embedding_dim
            )
            _store_fallback = False
            return _store
        except Exception as exc:  # noqa: BLE001 - Milvus 不可用时降级，并定期重试
            logger.warning("Milvus 不可用，降级内存向量库: %s", exc)
            _store = InMemoryVectorStore()
            _store_fallback = True
            return _store
    _store = InMemoryVectorStore()
    _store_fallback = False
    return _store


def reset_vector_store(store: VectorStore | None = None) -> None:
    global _store, _store_fallback, _last_attempt
    _store = store
    _store_fallback = False
    _last_attempt = 0.0
