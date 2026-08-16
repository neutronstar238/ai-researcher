"""Lifecycle state-machine unit tests (spec §12.2, pure functions)."""

from __future__ import annotations

from app.core.lifecycle import (
    STAGE_ORDER,
    gate_missing,
    is_allowed_transition,
    next_stage,
    ordinal_of,
)


def test_stage_order_is_eight() -> None:
    assert len(STAGE_ORDER) == 8
    assert STAGE_ORDER[0] == "topic"
    assert STAGE_ORDER[-1] == "evolution"


def test_ordinal_mapping() -> None:
    assert ordinal_of("topic") == 1
    assert ordinal_of("evolution") == 8


def test_next_stage_chaining() -> None:
    assert next_stage("topic") == "literature"
    assert next_stage("reflection") == "evolution"
    assert next_stage("evolution") is None


def test_legal_transitions() -> None:
    assert is_allowed_transition("pending", "ready") is True
    assert is_allowed_transition("ready", "running") is True
    assert is_allowed_transition("running", "completed") is True
    assert is_allowed_transition("running", "blocked") is True
    assert is_allowed_transition("blocked", "running") is True
    assert is_allowed_transition("completed", "running") is True  # 显式重开
    assert is_allowed_transition("waiting_approval", "completed") is True


def test_illegal_transitions() -> None:
    assert is_allowed_transition("pending", "running") is False
    assert is_allowed_transition("pending", "completed") is False
    assert is_allowed_transition("completed", "completed") is False
    assert is_allowed_transition("cancelled", "running") is False
    assert is_allowed_transition("ready", "completed") is False
    assert is_allowed_transition("completed", "blocked") is False


def test_gate_requires_evidence_for_literature() -> None:
    assert gate_missing("literature", 0) == [
        {"code": "MIN_EVIDENCE_NOT_MET", "threshold": 1, "actual": 0}
    ]
    assert gate_missing("literature", 5) == []


def test_gate_topic_has_no_requirement() -> None:
    assert gate_missing("topic", 0) == []
