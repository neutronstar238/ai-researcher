"""Evidence relation-matrix unit tests (spec §14.2)."""

from __future__ import annotations

from app.core.evidence import (
    is_node_type,
    is_relation,
    relation_allowed,
    self_loop_allowed,
)


def test_relation_matrix_allows_valid_edges() -> None:
    assert relation_allowed("paper", "supports", "hypothesis") is True
    assert relation_allowed("result", "contradicts", "claim") is True
    assert relation_allowed("claim", "derived_from", "evidence") is True
    assert relation_allowed("paper", "cites", "paper") is True
    assert relation_allowed("hypothesis", "tested_by", "experiment") is True
    assert relation_allowed("experiment", "produces", "result") is True
    assert relation_allowed("experiment", "uses", "dataset") is True
    assert relation_allowed("result", "validated_by", "validation") is True


def test_relation_matrix_rejects_invalid_edges() -> None:
    assert relation_allowed("dataset", "contradicts", "claim") is False
    assert relation_allowed("experiment", "cites", "claim") is False
    assert relation_allowed("paper", "produces", "result") is False
    assert relation_allowed("claim", "tested_by", "experiment") is False
    assert relation_allowed("dataset", "supports", "hypothesis") is False


def test_related_to_accepts_any_types() -> None:
    assert relation_allowed("dataset", "related_to", "claim") is True
    assert relation_allowed("method", "related_to", "user_does_not_exist") is False  # 未知类型仍拒绝


def test_self_loop_only_related_to() -> None:
    assert self_loop_allowed("related_to") is True
    assert self_loop_allowed("supports") is False


def test_type_and_relation_predicates() -> None:
    assert is_node_type("hypothesis") is True
    assert is_node_type("nonsense") is False
    assert is_relation("contradicts") is True
    assert is_relation("nonsense") is False
