"""The system must GENERATE a plan that satisfies the audit, not just consume one.

`execute_official_stage` enforces the research-plan gate, but nothing in the
competition path generated a plan, so the loop could never reach an approvable state:
the gate would refuse forever because no plan existed. This closes that half.

Every field is derived from persisted frozen evidence -- the 266.1 plan, the frozen
panel, the baseline registry, the frozen estimand -- so the plan describes the search
that will actually run rather than a template.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autoresearch.competition.official_plan_generation import (
    OfficialPlanGenerationError,
    build_official_research_plan,
    write_official_research_plan,
)
from autoresearch.research.plan_confirmation import (
    ResearchPlanConfirmationError,
    compute_plan_hash,
    record_plan_decision,
    require_approved_plan,
)
from autoresearch.research.plans import audit_research_plan
from autoresearch.schemas import ResearchPlanStatus

ROOT = Path(__file__).resolve().parents[3]
FROZEN_PLAN = (
    ROOT / "runs" / "manual-live"
    / "task2661-scientific-contract-recovery-plan-v1"
    / "scientific-contract-recovery-plan.json"
)
AUTONOMOUS_PLAN = (
    ROOT / "runs" / "manual-live"
    / "task2651-autonomous-recovery-plan-v1"
    / "autonomous-research-plan.json"
)
DATA_ROOT = (
    ROOT / "runs" / "manual-live" / "task259-mdbench-official-v1"
    / "data" / "prepared" / "processed-9fe483c64ad6"
)


def _plan():
    return build_official_research_plan(
        plan_path=FROZEN_PLAN,
        autonomous_plan_path=AUTONOMOUS_PLAN,
        data_root=DATA_ROOT,
    )


def test_generated_plan_passes_the_audit_rubric() -> None:
    """The whole point: the system's own plan must clear the quality gate."""

    plan = _plan()
    audit = audit_research_plan(plan)

    assert audit.passed, f"issues: {list(audit.issues)}"
    assert audit.score == pytest.approx(1.0)
    assert plan.status is ResearchPlanStatus.READY_FOR_APPROVAL


def test_plan_identifies_both_a_source_and_a_holdout_route() -> None:
    """The rubric requires both, and a hold-out route is what makes it testable."""

    plan = _plan()

    assert "MDBench" in plan.datasets["source"]
    assert "held-out" in plan.datasets["target"]
    # The sealed confirmation panel must stay out of the development route.
    assert "unread" in plan.datasets["target"]


def test_plan_names_the_domain_valid_baselines_from_the_frozen_registry() -> None:
    """Baselines are read out of the frozen plan, not invented."""

    frozen = json.loads(FROZEN_PLAN.read_text(encoding="utf-8"))
    expected = {item["baseline_id"] for item in frozen["baselines"]}
    plan = _plan()

    for baseline_id in expected:
        assert baseline_id in plan.methods


def test_plan_states_the_real_metric_and_aggregation() -> None:
    plan = _plan()

    assert "derivative NMSE" in plan.methods
    assert "median" in plan.methods


def test_plan_derives_the_panel_size_from_the_frozen_panel() -> None:
    autonomous = json.loads(AUTONOMOUS_PLAN.read_text(encoding="utf-8"))
    count = len(autonomous["development_panel"]["systems"])
    plan = _plan()

    assert str(count) in " ".join(plan.experiments)


def test_expected_results_is_an_expectation_not_a_claim() -> None:
    """The audit rejects unsupported result claims; a negative must stay allowed."""

    plan = _plan()
    text = plan.expected_results.casefold()

    assert "expected" in text
    assert "not yet observed" in text
    assert "negative outcome is a valid result" in text


def test_plan_carries_a_command_oriented_brief() -> None:
    plan = _plan()

    assert "python" in plan.code_agent_brief
    assert "pytest" in plan.code_agent_brief


def test_plan_records_the_underpowered_pde_stratum_as_a_risk() -> None:
    """An honest plan must state its own power limitation up front."""

    risks = " ".join(plan_risk for plan_risk in _plan().risks_and_alternatives)

    assert "underpowered" in risks
    assert "directional" in risks


def test_plan_records_the_unpaired_baseline_risk() -> None:
    """P-20260802-065 must be a stated risk, not a surprise."""

    risks = " ".join(_plan().risks_and_alternatives).casefold()

    assert "unpaired" in risks
    assert "coverage gap" in risks


def test_plan_evidence_refs_point_at_real_artifacts() -> None:
    plan = _plan()

    assert plan.evidence_refs
    for reference in plan.evidence_refs:
        assert Path(reference).exists(), reference


def test_generated_plan_flows_through_the_gate(tmp_path: Path) -> None:
    """Generate, refuse without approval, approve, then refuse an edited plan."""

    plan = _plan()

    with pytest.raises(ResearchPlanConfirmationError):
        require_approved_plan(plan=plan, decision=None)

    record = record_plan_decision(
        plan=plan,
        decision="approve",
        decided_by="operator",
        notes="panel, baselines and stop rules reviewed",
        output_dir=tmp_path,
    )
    assert require_approved_plan(plan=plan, decision=record) == compute_plan_hash(plan)

    edited = plan.model_copy(update={"methods": "a different mechanism entirely"})
    with pytest.raises(ResearchPlanConfirmationError, match="re-confirmation"):
        require_approved_plan(plan=edited, decision=record)


def test_plan_is_persisted_where_the_cli_can_read_it(tmp_path: Path) -> None:
    written = write_official_research_plan(plan=_plan(), output_dir=tmp_path)

    path = Path(written["plan_path"])
    assert path.is_file()
    reloaded = json.loads(path.read_text(encoding="utf-8"))
    assert reloaded["title"]
    assert reloaded["datasets"]["source"]


def test_a_panel_without_both_domains_is_refused(tmp_path: Path) -> None:
    """A plan must not claim ODE and PDE coverage the panel does not have."""

    autonomous = json.loads(AUTONOMOUS_PLAN.read_text(encoding="utf-8"))
    autonomous["development_panel"]["systems"] = [
        item for item in autonomous["development_panel"]["systems"]
        if item["data_type"] == "ode"
    ]
    broken = tmp_path / "ode-only.json"
    broken.write_text(json.dumps(autonomous), encoding="utf-8")

    with pytest.raises(OfficialPlanGenerationError, match="both ODE and PDE"):
        build_official_research_plan(
            plan_path=FROZEN_PLAN,
            autonomous_plan_path=broken,
            data_root=DATA_ROOT,
        )
