"""Agent system unit tests (spec §16, pure functions)."""

from __future__ import annotations

import pytest

from app.api.errors import ValidationAppError
from app.core.agents import (
    Budget,
    Usage,
    budget_exceeded,
    budget_warning,
    is_allowed_task_transition,
    tool_requires_approval,
    tool_risk_level,
)


def test_tool_risk_levels() -> None:
    assert tool_risk_level("project.read") == "read"
    assert tool_risk_level("evidence.propose") == "write_low"
    assert tool_risk_level("experiment.run") == "write_high"
    assert tool_risk_level("external.send") == "external_side_effect"


def test_tool_approval_requirements() -> None:
    assert tool_requires_approval("project.read") is False
    assert tool_requires_approval("evidence.propose") is False
    assert tool_requires_approval("experiment.run") is True
    assert tool_requires_approval("external.send") is True


def test_unknown_tool_raises() -> None:
    with pytest.raises(ValidationAppError):
        tool_risk_level("does.not.exist")


def test_task_transitions() -> None:
    assert is_allowed_task_transition("queued", "running") is True
    assert is_allowed_task_transition("running", "waiting_approval") is True
    assert is_allowed_task_transition("failed", "queued") is True  # retry
    assert is_allowed_task_transition("succeeded", "cancelled") is False
    assert is_allowed_task_transition("cancelled", "running") is False


def test_budget_exceeded() -> None:
    budget = Budget(max_tokens=1000, max_cost=1.0, max_tool_calls=10)
    assert budget_exceeded(Usage(tokens=999, cost=0.5, tool_calls=9), budget) is False
    assert budget_exceeded(Usage(tokens=1000, cost=0.5, tool_calls=9), budget) is True
    assert budget_exceeded(Usage(tokens=1, cost=1.0, tool_calls=1), budget) is True
    assert budget_exceeded(Usage(tokens=1, cost=0.1, tool_calls=10), budget) is True


def test_budget_warning_at_80_percent() -> None:
    budget = Budget(max_tokens=1000)
    assert budget_warning(Usage(tokens=800), budget) is True
    assert budget_warning(Usage(tokens=500), budget) is False
