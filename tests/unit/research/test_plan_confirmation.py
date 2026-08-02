"""Task 267.4: experiment execution must be impossible without plan approval.

Before this gate, `generate_research_plan` reached
`ResearchPlanStatus.READY_FOR_APPROVAL` and the loop kept going: the campaign and
competition paths never called `research.approval`, and the autonomous engine set
`approval_required_permission_ids=[]` with `max_human_interventions=0`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autoresearch.research.plan_confirmation import (
    ResearchPlanConfirmationError,
    apply_plan_decision,
    compute_plan_hash,
    load_plan_decision,
    record_plan_decision,
    require_approved_plan,
)
from autoresearch.schemas import ResearchPlan, ResearchPlanStatus


def _plan(**overrides: object) -> ResearchPlan:
    payload: dict[str, object] = {
        "project_id": "noise-robust-discovery",
        "candidate_id": "candidate_abc123",
        "title": "Noise-conditioned ensemble sparse regression",
        "problem_statement": "Noisy derivative estimates destabilize term selection.",
        "rationale": "Set-level selection is more stable than per-term credit.",
        "technical_details": "Fit once on train-only context, freeze equations.",
        "methods": "Dictionary construction plus set-level sparse selection.",
        "experiments": ["development panel sweep", "matched-budget comparison"],
        "expected_results": "Lower derivative NMSE under SNR20.",
        "code_agent_brief": "Implement fit_equations and predict_derivative.",
        "risks_and_alternatives": ["underpowered PDE stratum"],
        "references": ["arXiv:2607.04108"],
        "evidence_refs": ["runs/manual-live/task2661-.../plan.json"],
        "status": ResearchPlanStatus.READY_FOR_APPROVAL,
    }
    payload.update(overrides)
    return ResearchPlan.model_validate(payload)


def test_execution_is_impossible_without_a_recorded_decision() -> None:
    """The core requirement: no decision means no execution."""

    plan = _plan()
    with pytest.raises(ResearchPlanConfirmationError, match="requires a recorded human decision"):
        require_approved_plan(plan=plan, decision=None)


@pytest.mark.parametrize("decision", ["revise", "reject"])
def test_non_approval_blocks_execution(decision: str, tmp_path: Path) -> None:
    """Only an explicit approve authorizes execution."""

    plan = _plan()
    record = record_plan_decision(
        plan=plan,
        decision=decision,  # type: ignore[arg-type]
        decided_by="operator",
        notes="panel is underpowered; narrow the claim",
        output_dir=tmp_path,
    )
    with pytest.raises(ResearchPlanConfirmationError, match="execution stays blocked"):
        require_approved_plan(plan=plan, decision=record)


def test_approval_returns_the_bound_plan_hash(tmp_path: Path) -> None:
    """The approved plan hash must be bindable into downstream execution records."""

    plan = _plan()
    record = record_plan_decision(
        plan=plan,
        decision="approve",
        decided_by="operator",
        notes="scope and baselines look right",
        output_dir=tmp_path,
    )
    bound_hash = require_approved_plan(plan=plan, decision=record)

    assert bound_hash == compute_plan_hash(plan)
    assert record.approved is True


def test_plan_edited_after_approval_requires_reconfirmation(tmp_path: Path) -> None:
    """A human must not be bound to a plan they never saw."""

    plan = _plan()
    record = record_plan_decision(
        plan=plan,
        decision="approve",
        decided_by="operator",
        notes="approved as written",
        output_dir=tmp_path,
    )
    edited = plan.model_copy(update={"methods": "switched to a different mechanism"})

    with pytest.raises(ResearchPlanConfirmationError, match="re-confirmation is required"):
        require_approved_plan(plan=edited, decision=record)


def test_revise_returns_control_to_planning_without_spending_budget(tmp_path: Path) -> None:
    """A revision must not consume the scientific search budget."""

    plan = _plan()
    record = record_plan_decision(
        plan=plan,
        decision="revise",
        decided_by="operator",
        notes="add a PDE-capable baseline",
        output_dir=tmp_path,
    )

    assert record.consumes_scientific_budget is False
    assert apply_plan_decision(plan=plan, decision=record).status is (
        ResearchPlanStatus.NEEDS_REVISION
    )


def test_decision_status_transitions(tmp_path: Path) -> None:
    plan = _plan()
    for decision, expected in (
        ("approve", ResearchPlanStatus.APPROVED),
        ("revise", ResearchPlanStatus.NEEDS_REVISION),
        ("reject", ResearchPlanStatus.BLOCKED),
    ):
        record = record_plan_decision(
            plan=plan,
            decision=decision,  # type: ignore[arg-type]
            decided_by="operator",
            notes="recorded decision",
            output_dir=tmp_path,
        )
        assert apply_plan_decision(plan=plan, decision=record).status is expected


def test_approval_is_never_scientific_evidence(tmp_path: Path) -> None:
    """A scope decision must never be counted toward evidence coverage."""

    record = record_plan_decision(
        plan=_plan(),
        decision="approve",
        decided_by="operator",
        notes="scope approved",
        output_dir=tmp_path,
    )

    assert record.is_evidence is False
    assert record.evidence_refs == ()


def test_audit_blocked_plan_cannot_be_rubber_stamped(tmp_path: Path) -> None:
    """A human must not approve a plan the system's own audit blocked."""

    blocked = _plan(status=ResearchPlanStatus.BLOCKED)
    with pytest.raises(ResearchPlanConfirmationError, match="blocked by its own audit"):
        record_plan_decision(
            plan=blocked,
            decision="approve",
            decided_by="operator",
            notes="override attempt",
            output_dir=tmp_path,
        )


def test_decision_round_trips_from_disk(tmp_path: Path) -> None:
    """The gate must survive a process restart, not live in memory."""

    plan = _plan()
    record = record_plan_decision(
        plan=plan,
        decision="approve",
        decided_by="operator",
        notes="approved as written",
        output_dir=tmp_path,
    )
    loaded = load_plan_decision(project_id=plan.project_id, output_dir=tmp_path)

    assert loaded is not None
    assert loaded.decision_id == record.decision_id
    assert require_approved_plan(plan=plan, decision=loaded) == compute_plan_hash(plan)


def test_missing_decision_file_returns_none(tmp_path: Path) -> None:
    assert load_plan_decision(project_id="never-decided", output_dir=tmp_path) is None


def test_approval_for_another_plan_is_rejected(tmp_path: Path) -> None:
    """An approval must not be reused across research plans."""

    approved = _plan()
    other = _plan(title="A different direction entirely")
    record = record_plan_decision(
        plan=approved,
        decision="approve",
        decided_by="operator",
        notes="approved the first plan only",
        output_dir=tmp_path,
    )

    with pytest.raises(ResearchPlanConfirmationError, match="different research plan"):
        require_approved_plan(plan=other, decision=record)


def test_plan_hash_ignores_volatile_bookkeeping_fields() -> None:
    """Re-serializing an unchanged plan must not invalidate a decision."""

    plan = _plan()
    restamped = plan.model_copy(
        update={
            "status": ResearchPlanStatus.APPROVED,
            "quality_gate": {"passed": True},
        }
    )

    assert compute_plan_hash(plan) == compute_plan_hash(restamped)


def test_plan_hash_changes_when_science_changes() -> None:
    """Any change to scientific content must invalidate the decision."""

    plan = _plan()
    changed = plan.model_copy(update={"experiments": ["a completely different design"]})

    assert compute_plan_hash(plan) != compute_plan_hash(changed)
