"""Embedding provider unit tests (deterministic hash embedding)."""

from __future__ import annotations

from app.integrations.embeddings.hash import HashEmbeddingProvider


def _cos(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False))


def test_embedding_is_deterministic_and_normalized() -> None:
    provider = HashEmbeddingProvider()
    v1 = provider.embed("hello world multimodal")
    v2 = provider.embed("hello world multimodal")
    assert v1 == v2
    assert len(v1) == 128
    assert abs(sum(x * x for x in v1) - 1.0) < 1e-6


def test_similar_texts_rank_higher() -> None:
    provider = HashEmbeddingProvider()
    a = provider.embed("multimodal protein ligand interaction")
    b = provider.embed("multimodal protein ligand docking")
    c = provider.embed("graph neural network")
    assert _cos(a, b) > _cos(a, c)


def test_empty_text_is_defined() -> None:
    provider = HashEmbeddingProvider()
    v = provider.embed("")
    assert len(v) == 128


def test_unconfigured_provider_raises() -> None:
    from app.api.errors import ProviderNotConfiguredError
    from app.integrations.embeddings.hash import get_provider

    try:
        get_provider(None)
        raise AssertionError("should have raised")
    except ProviderNotConfiguredError:
        pass
