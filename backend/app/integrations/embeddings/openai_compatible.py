"""OpenAI 兼容 Embedding Provider（spec §11.10/§26.3 生产语义嵌入）。

任何 OpenAI 兼容 `/embeddings` 端点（DashScope/OpenAI/Ollama 等）可用：从配置读
base_url/api_key/model。与 hash-dev 不同，这是真实语义嵌入。维度由模型决定
（text-embedding-v3 默认 1024）。
"""

from __future__ import annotations

import httpx

from app.api.errors import ProviderNotConfiguredError
from app.core.config import get_settings


class OpenAICompatibleEmbeddingProvider:
    name = "openai-compatible"
    dimension = 1024  # text-embedding-v3 默认；可被配置覆盖

    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = (settings.llm_base_url or "").rstrip("/")
        self.api_key = settings.llm_api_key
        self.model = settings.embedding_model or "text-embedding-v3"
        if not self.base_url or not self.api_key:
            raise ProviderNotConfiguredError("Embedding 未完整配置（需 LLM_BASE_URL + LLM_API_KEY）")

    def embed(self, text: str) -> list[float]:
        response = httpx.post(
            f"{self.base_url}/embeddings",
            json={"model": self.model, "input": text},
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=60,
        )
        if response.status_code >= 400:
            raise ProviderNotConfiguredError(
                f"Embedding 调用失败 HTTP {response.status_code}: {response.text[:300]}"
            )
        return response.json()["data"][0]["embedding"]
