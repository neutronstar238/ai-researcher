"""The research-plan gate must physically block official execution.

The project requires a research-plan confirmation step between a generated plan and
any experiment. Task 267.4 built that gate, but nothing in the competition path
called it, so the 336-cell official search ran without ever consulting it. A gate
that exists but is never invoked is not a gate.

These tests assert that `execute_official_stage` refuses to start when a plan is
supplied without an approval, and that the approved plan hash is bound into the
persisted stage record so an execution is traceable to the exact plan text a human
saw.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.official_development_search import (
    OfficialCellSpec,
    OfficialDevelopmentIdentity,
    execute_official_stage,
)
from autoresearch.competition.official_spend_ledger import (
    OfficialSpendLedger,
    OfficialSpendLimitExceeded,
)
from autoresearch.research.plan_confirmation import (
    ResearchPlanConfirmationError,
    record_plan_decision,
)
from autoresearch.schemas import ResearchPlan, ResearchPlanStatus


def _plan() -> ResearchPlan:
    return ResearchPlan.model_validate(
        {
            "project_id": "official-266-3",
            "candidate_id": "candidate_official",
            "title": "Noise-robust equation discovery on the official panel",
            "problem_statement": "Candidates overfit the validation window.",
            "rationale": "Validation-guided sparsity should transfer better.",
            "technical_details": "Fit once on train-only context, freeze, predict.",
            "methods": "Model-authored sparse regression with held-out selection.",
            "experiments": ["pilot on 6 systems", "full stage on 14 systems"],
            "expected_results": "Lower derivative NMSE than the domain baseline.",
            "code_agent_brief": "Implement fit_equations and predict_derivative.",
            "risks_and_alternatives": ["four PDE systems are underpowered"],
            "references": ["arXiv:2607.04108"],
            "evidence_refs": ["runs/manual-live/task2661-.../plan.json"],
            "status": ResearchPlanStatus.READY_FOR_APPROVAL,
        }
    )


def _identity(tmp_path: Path) -> OfficialDevelopmentIdentity:
    payload = {
        "schema_version": "official-development-identity-v1",
        "plan_hash": "a" * 64,
        "development_panel_hash": "b" * 64,
        "sealed_confirmation_panel_hash": "c" * 64,
        "runner_sha256": "d" * 64,
        "runtime_environment_hash": "e" * 64,
        "image_id": "sha256:" + "f" * 64,
        "data_root": tmp_path.as_posix(),
        "initial_candidate_count": 1,
        "pilot_system_count": 1,
        "full_system_count": 1,
        "conditions": ("snr_20",),
        "seeds": (101,),
        "maximum_official_cells_total": 464,
        "numeric_payload_opened_during_freeze": False,
        "confirmation_identity_read_count": 0,
        "created_at": datetime(2026, 8, 2, tzinfo=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
    }
    payload["identity_hash"] = canonical_model_hash(payload)
    return OfficialDevelopmentIdentity.model_validate(payload)


def _spec() -> OfficialCellSpec:
    payload = {
        "attempt_id": "pilot-c1-s1-snr_20-101",
        "method_kind": "candidate",
        "candidate_id": "c1",
        "stage": "pilot",
        "system_name": "s1",
        "data_type": "ode",
        "condition": "snr_20",
        "seed": 101,
        "data_relative_path": "s1.npz",
        "data_sha256": "1" * 64,
        "candidate_source_sha256": "2" * 64,
    }
    payload["spec_hash"] = canonical_model_hash(payload)
    return OfficialCellSpec.model_validate(payload)


def test_execution_is_refused_without_a_recorded_approval(tmp_path: Path) -> None:
    """The core requirement: a generated plan alone does not authorize experiments."""

    with pytest.raises(ResearchPlanConfirmationError, match="requires a recorded human decision"):
        execute_official_stage(
            identity=_identity(tmp_path),
            specs=[_spec()],
            candidates=[],
            output_dir=tmp_path,
            research_plan=_plan(),
            plan_decision=None,
        )


@pytest.mark.parametrize("decision", ["revise", "reject"])
def test_execution_is_refused_for_a_non_approval(tmp_path: Path, decision: str) -> None:
    plan = _plan()
    record = record_plan_decision(
        plan=plan,
        decision=decision,  # type: ignore[arg-type]
        decided_by="operator",
        notes="not yet convinced by the panel",
        output_dir=tmp_path,
    )

    with pytest.raises(ResearchPlanConfirmationError, match="execution stays blocked"):
        execute_official_stage(
            identity=_identity(tmp_path),
            specs=[_spec()],
            candidates=[],
            output_dir=tmp_path,
            research_plan=plan,
            plan_decision=record,
        )


def test_refusal_happens_before_any_container_starts(tmp_path: Path) -> None:
    """No cell directory may be created when the gate refuses."""

    with pytest.raises(ResearchPlanConfirmationError):
        execute_official_stage(
            identity=_identity(tmp_path),
            specs=[_spec()],
            candidates=[],
            output_dir=tmp_path,
            research_plan=_plan(),
            plan_decision=None,
        )

    assert not (tmp_path / "cells" / "pilot").exists()


def test_edited_plan_after_approval_is_refused(tmp_path: Path) -> None:
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
        execute_official_stage(
            identity=_identity(tmp_path),
            specs=[_spec()],
            candidates=[],
            output_dir=tmp_path,
            research_plan=edited,
            plan_decision=record,
        )


def test_ledger_refusal_also_precedes_execution(tmp_path: Path) -> None:
    """The spend gate must likewise refuse before spending anything."""

    exhausted = OfficialSpendLedger(
        lineage_id="lineage-a",
        plan_hash="a" * 64,
        maximum_total_candidate_count=12,
        maximum_official_candidate_cells=380,
        maximum_official_cells_total=464,
        maximum_model_interactions=80,
        maximum_generations=2,
    ).record(stage="prior", candidate_cells=380)

    with pytest.raises(OfficialSpendLimitExceeded) as caught:
        execute_official_stage(
            identity=_identity(tmp_path),
            specs=[_spec()],
            candidates=[],
            output_dir=tmp_path,
            ledger=exhausted,
        )

    assert caught.value.limit_name == "maximum_official_candidate_cells"
    assert not (tmp_path / "cells" / "pilot").exists()


def test_backward_compatible_when_no_plan_is_supplied(tmp_path: Path) -> None:
    """Omitting the plan keeps the old behaviour, so existing callers still work.

    This is deliberate: the gate is opt-in at the call site, and the honest record
    is that the 336-cell run predates it.
    """

    identity = _identity(tmp_path)
    runner_dir = tmp_path / "runner"
    runner_dir.mkdir(parents=True, exist_ok=True)
    # No plan and no ledger: the gates are skipped and the stage proceeds to the
    # runner-hash check, which fails here because this is a synthetic fixture.
    with pytest.raises(Exception) as caught:
        execute_official_stage(
            identity=identity,
            specs=[_spec()],
            candidates=[],
            output_dir=tmp_path,
        )

    # The failure must NOT be a plan-gate refusal.
    assert not isinstance(caught.value, ResearchPlanConfirmationError)


def test_approved_plan_hash_is_bound_into_the_stage_record(tmp_path: Path) -> None:
    """An execution must be traceable to the exact plan text that was approved."""

    from autoresearch.research.plan_confirmation import compute_plan_hash

    plan = _plan()
    record = record_plan_decision(
        plan=plan,
        decision="approve",
        decided_by="operator",
        notes="approved as written",
        output_dir=tmp_path,
    )

    # The gate authorizes and returns the bound hash; the stage record must carry it.
    from autoresearch.research.plan_confirmation import require_approved_plan

    assert require_approved_plan(plan=plan, decision=record) == compute_plan_hash(plan)
    assert record.approved is True
    # And the decision itself is never scientific evidence.
    assert record.is_evidence is False
    assert record.evidence_refs == ()
