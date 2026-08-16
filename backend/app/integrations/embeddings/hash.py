"""Deterministic local embedding (dev/test only).

This is NOT a semantic model — it hashes token n-grams into a fixed L2-normalized
vector so the vector pipeline is exercisable offline. A real embedding provider
(OpenAI/Cohere/local model) must be configured for production (§11.10/§26.3).
"""

from __future__ import annotations

import hashlib
import math
import re

from app.integrations.embeddings.base import EmbeddingProvider


class HashEmbeddingProvider:
    name = "hash-dev"
    dimension = 128

    def embed(self, text: str) -> list[float]:
        tokens = re.findall(r"\w+", (text or "").lower())
        vec = [0.0] * self.dimension
        for token in tokens:
            for gram in (token, f"{token}#"):
                digest = int(hashlib.md5(gram.encode("utf-8")).hexdigest(), 16)
                vec[digest % self.dimension] += 1.0 if (digest >> 8) & 1 else -1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]


PROVIDERS: dict[str, EmbeddingProvider] = {"hash-dev": HashEmbeddingProvider()}


def get_provider(name: str | None) -> EmbeddingProvider:
    from app.api.errors import ProviderNotConfiguredError

    if name is None:
        raise ProviderNotConfiguredError("Embedding Provider 未配置")
    if name in ("openai-compatible", "openai", "dashscope"):
        from app.integrations.embeddings.openai_compatible import OpenAICompatibleEmbeddingProvider

        return OpenAICompatibleEmbeddingProvider()
    provider = PROVIDERS.get(name)
    if provider is None:
        raise ProviderNotConfiguredError(f"Embedding Provider 未配置: {name}")
    return provider
