"""Embedding provider contract (spec §11.10)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    name: str
    dimension: int

    def embed(self, text: str) -> list[float]: ...
