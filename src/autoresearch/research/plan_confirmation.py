"""Task 267.4: blocking human research-plan confirmation gate.

Before this module, `generate_research_plan` could reach
`ResearchPlanStatus.READY_FOR_APPROVAL` and the loop would keep going: the
campaign and competition paths never called `research.approval`, and the
autonomous engine wired `approval_required_permission_ids=[]` with
`max_human_interventions=0`.  A plan was therefore generated and consumed
autonomously with no confirmation step.

This gate makes plan approval a physical precondition for experiment execution:

    generate plan -> record human decision -> execute (approve only)

Boundaries that must not erode:

* Approval is a SCOPE decision, never scientific evidence.  `is_evidence` is
  permanently False and `evidence_refs` is always empty, so an approval can
  never be counted toward evidence coverage or a publication claim.
* A `revise` or `reject` decision returns control to plan generation and does
  not consume the scientific search budget.
* The approved plan hash is bound into every downstream execution record, so an
  execution can be traced to the exact plan text a human actually saw.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from autoresearch.schemas import ResearchPlan, ResearchPlanStatus, data_hash

PlanDecision = Literal["approve", "revise", "reject"]

_DECISION_FILENAME = "research-plan-decision.json"


class ResearchPlanConfirmationError(PermissionError):
    """Raised when experiment execution is attempted without plan approval."""


class ResearchPlanDecisionRecord(BaseModel):
    """One recorded human decision about a generated research plan.

    This is process metadata about scope and direction.  It is never scientific
    evidence, and it never proves a result, a metric, novelty, or publication
    readiness.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_id: str = Field(default_factory=lambda: f"plan_decision_{uuid4().hex}")
    plan_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    plan_hash: str = Field(min_length=1)
    decision: PlanDecision
    decided_by: str = Field(min_length=1)
    decided_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    notes: str = Field(min_length=1)
    # Permanent boundary: an approval is a scope decision, not evidence.
    is_evidence: Literal[False] = False
    evidence_refs: tuple[str, ...] = ()
    consumes_scientific_budget: bool = False

    @model_validator(mode="after")
    def _validate_boundaries(self) -> ResearchPlanDecisionRecord:
        if self.evidence_refs:
            raise ValueError("a plan decision must never carry evidence references")
        # Only an approval authorizes execution; revise/reject must return
        # control to planning without spending the scientific search budget.
        if self.decision != "approve" and self.consumes_scientific_budget:
            raise ValueError("a rejected or revised plan must not consume the budget")
        return self

    @property
    def approved(self) -> bool:
        """Return True only for an explicit approval."""

        return self.decision == "approve"

    def to_dict(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        payload["approved"] = self.approved
        return payload


def compute_plan_hash(plan: ResearchPlan) -> str:
    """Return a stable hash of the plan content a human is asked to confirm.

    The hash excludes volatile bookkeeping fields so that re-serializing an
    unchanged plan does not invalidate a recorded decision, while any change to
    the scientific content does.
    """

    payload = plan.model_dump(mode="json")
    for volatile in ("updated_at", "status", "validation_status", "quality_gate"):
        payload.pop(volatile, None)
    return data_hash(payload)


def record_plan_decision(
    *,
    plan: ResearchPlan,
    decision: PlanDecision,
    decided_by: str,
    notes: str,
    output_dir: Path | str = Path("outputs"),
) -> ResearchPlanDecisionRecord:
    """Persist a human decision next to the plan artifacts.

    Refuses to record a decision for a plan that failed its own automated audit,
    so a human cannot rubber-stamp a plan the system already blocked.
    """

    if plan.status is ResearchPlanStatus.BLOCKED:
        raise ResearchPlanConfirmationError(
            "cannot record a decision for a plan blocked by its own audit"
        )

    record = ResearchPlanDecisionRecord(
        plan_id=plan.id,
        project_id=plan.project_id,
        plan_hash=compute_plan_hash(plan),
        decision=decision,
        decided_by=decided_by,
        notes=notes,
    )
    decision_path = _decision_path(output_dir, plan.project_id)
    decision_path.parent.mkdir(parents=True, exist_ok=True)
    decision_path.write_text(
        json.dumps(record.to_dict(), indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return record


def load_plan_decision(
    *,
    project_id: str,
    output_dir: Path | str = Path("outputs"),
) -> ResearchPlanDecisionRecord | None:
    """Load a persisted decision, or None when no human has decided yet."""

    decision_path = _decision_path(output_dir, project_id)
    if not decision_path.is_file():
        return None
    payload = json.loads(decision_path.read_text(encoding="utf-8"))
    payload.pop("approved", None)
    return ResearchPlanDecisionRecord.model_validate(payload)


def apply_plan_decision(
    *,
    plan: ResearchPlan,
    decision: ResearchPlanDecisionRecord,
) -> ResearchPlan:
    """Return the plan with its status advanced by the recorded decision."""

    if decision.plan_id != plan.id:
        raise ValueError("plan decision does not belong to this plan")
    if decision.plan_hash != compute_plan_hash(plan):
        raise ResearchPlanConfirmationError(
            "plan content changed after the human decision was recorded"
        )
    status = {
        "approve": ResearchPlanStatus.APPROVED,
        "revise": ResearchPlanStatus.NEEDS_REVISION,
        "reject": ResearchPlanStatus.BLOCKED,
    }[decision.decision]
    return plan.model_copy(update={"status": status})


def require_approved_plan(
    *,
    plan: ResearchPlan,
    decision: ResearchPlanDecisionRecord | None,
) -> str:
    """Authorize experiment execution and return the bound plan hash.

    This is the physical gate.  Every experiment-execution entry point must call
    it and record the returned hash, so an execution without a matching human
    approval is impossible rather than merely discouraged.
    """

    if decision is None:
        raise ResearchPlanConfirmationError(
            "research plan requires a recorded human decision before execution"
        )
    if not decision.approved:
        raise ResearchPlanConfirmationError(
            f"research plan decision is '{decision.decision}', not 'approve'; "
            "execution stays blocked and control returns to plan generation"
        )
    if decision.plan_id != plan.id:
        raise ResearchPlanConfirmationError(
            "recorded approval belongs to a different research plan"
        )
    expected_hash = compute_plan_hash(plan)
    if decision.plan_hash != expected_hash:
        raise ResearchPlanConfirmationError(
            "research plan changed after approval; re-confirmation is required"
        )
    return expected_hash


def _decision_path(output_dir: Path | str, project_id: str) -> Path:
    return Path(output_dir) / project_id / "research-plan" / _DECISION_FILENAME
