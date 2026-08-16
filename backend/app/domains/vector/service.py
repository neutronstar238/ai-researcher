"""Vector application service (embed + store + search)."""

from __future__ import annotations

import uuid

from app.core.config import get_settings
from app.integrations.embeddings.hash import get_provider
from app.integrations.vector_store.milvus import MilvusVectorStore


class VectorService:
    def __init__(self) -> None:
        self.vector_store = MilvusVectorStore()
        self.vector_store.ensure_collection()

    def embed(self, text: str):
        settings = get_settings()
        provider = get_provider(settings.embedding_provider)
        return provider.embed(text), provider

    def store(self, project_id: uuid.UUID, text: str, paper_id: str | None) -> dict:
        vector, provider = self.embed(text)
        chunk_id = uuid.uuid4().hex
        self.vector_store.insert(chunk_id, str(project_id), paper_id or "", vector, provider.name)
        return {"chunk_id": chunk_id, "embedding_model": provider.name, "dimension": provider.dimension}

    def search(self, project_id: uuid.UUID, query: str, top_k: int) -> list[dict]:
        vector, _ = self.embed(query)
        return self.vector_store.search(vector, str(project_id), top_k)
