"""Milvus collection for agent memories (spec §11.10)."""

from __future__ import annotations

import time

from pymilvus import DataType, MilvusClient

from app.core.config import get_settings


class AgentMemoryVectorStore:
    COLLECTION = "agent_memories"

    def __init__(self, dimension: int = 128) -> None:
        self.client = MilvusClient(uri=get_settings().milvus_uri)
        self.dimension = dimension

    def ensure_collection(self) -> None:
        if self.client.has_collection(self.COLLECTION):
            self.client.load_collection(self.COLLECTION)
            return
        schema = self.client.create_schema(auto_id=False, enable_dynamic_field=True)
        schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=64)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=self.dimension)
        schema.add_field("project_id", DataType.VARCHAR, max_length=64)
        schema.add_field("agent_id", DataType.VARCHAR, max_length=64)
        schema.add_field("embedding_model", DataType.VARCHAR, max_length=128)
        schema.add_field("embedding_version", DataType.VARCHAR, max_length=128)
        schema.add_field("created_at", DataType.INT64)
        self.client.create_collection(self.COLLECTION, schema=schema)
        index_params = self.client.prepare_index_params()
        index_params.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
        self.client.create_index(self.COLLECTION, index_params=index_params)
        self.client.load_collection(self.COLLECTION)

    def insert(self, memory_id: str, project_id: str, agent_id: str, vector: list[float], model: str) -> None:
        self.client.insert(
            self.COLLECTION,
            [
                {
                    "id": memory_id,
                    "vector": vector,
                    "project_id": project_id,
                    "agent_id": agent_id,
                    "embedding_model": model,
                    "embedding_version": "v1",
                    "created_at": int(time.time()),
                }
            ],
        )

    def search(self, vector: list[float], project_id: str, agent_id: str, top_k: int = 5) -> list[dict]:
        results = self.client.search(
            self.COLLECTION,
            data=[vector],
            limit=top_k,
            filter=f'project_id == "{project_id}" && agent_id == "{agent_id}"',
            output_fields=["agent_id"],
        )
        hits = results[0] if results else []
        return [{"id": hit["id"], "score": hit["distance"]} for hit in hits]

    def delete(self, memory_id: str) -> None:
        self.client.delete(self.COLLECTION, ids=[memory_id])
