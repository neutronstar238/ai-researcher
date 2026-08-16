"""Milvus vector-store client (spec §11.10).

Collection ``paper_chunks`` mirrors the business metadata; the PostgreSQL
``paper_chunks`` table remains the authoritative record. Retrieval returns UUIDs
that must be re-authorized against PostgreSQL (§19.2).
"""

from __future__ import annotations

import time

from pymilvus import DataType, MilvusClient

from app.core.config import get_settings


class MilvusVectorStore:
    COLLECTION = "paper_chunks"

    def __init__(self, dimension: int = 128) -> None:
        self.client = MilvusClient(uri=get_settings().milvus_uri)
        self.dimension = dimension

    def ensure_collection(self) -> None:
        # 维度不匹配（如 hash-dev 128 → 真实 embedding 1024）时重建集合
        if self.client.has_collection(self.COLLECTION):
            desc = self.client.describe_collection(self.COLLECTION)
            for field in desc.get("fields", []):
                params = field.get("params") or {}
                if field.get("name") == "vector" and params.get("dim") != self.dimension:
                    self.client.drop_collection(self.COLLECTION)
                    break
        if not self.client.has_collection(self.COLLECTION):
            schema = self.client.create_schema(auto_id=False, enable_dynamic_field=True)
            schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=64)
            schema.add_field("vector", DataType.FLOAT_VECTOR, dim=self.dimension)
            schema.add_field("project_id", DataType.VARCHAR, max_length=64)
            schema.add_field("paper_id", DataType.VARCHAR, max_length=64)
            schema.add_field("embedding_model", DataType.VARCHAR, max_length=128)
            schema.add_field("embedding_version", DataType.VARCHAR, max_length=128)
            schema.add_field("created_at", DataType.INT64)
            self.client.create_collection(self.COLLECTION, schema=schema)
            index_params = self.client.prepare_index_params()
            index_params.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
            self.client.create_index(self.COLLECTION, index_params=index_params)
        # 搜索前必须把 collection 加载进内存（幂等）
        self.client.load_collection(self.COLLECTION)

    def insert(self, chunk_id: str, project_id: str, paper_id: str, vector: list[float], model: str) -> None:
        self.client.insert(
            self.COLLECTION,
            [
                {
                    "id": chunk_id,
                    "vector": vector,
                    "project_id": project_id,
                    "paper_id": paper_id,
                    "embedding_model": model,
                    "embedding_version": "v1",
                    "created_at": int(time.time()),
                }
            ],
        )

    def search(self, vector: list[float], project_id: str, top_k: int = 5) -> list[dict]:
        results = self.client.search(
            self.COLLECTION,
            data=[vector],
            limit=top_k,
            filter=f'project_id == "{project_id}"',
            output_fields=["paper_id", "embedding_model"],
        )
        hits = results[0] if results else []
        return [
            {"id": hit["id"], "paper_id": hit["entity"].get("paper_id"), "score": hit["distance"]}
            for hit in hits
        ]
