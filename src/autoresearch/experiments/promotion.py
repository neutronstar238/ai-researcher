"""Promotion gates for controlled strategy gray release."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from autoresearch.observability import AuditEvent, AuditEventType, AuditLog
from autoresearch.schemas import StrategyCard, ValidationStatus


class StrategyPromotionStatus(str, Enum):
    """Outcome of a strategy promotion gate."""

    BLOCKED = "blocked"
    GRAY_RELEASE = "gray_release"


class StrategyPromotionApproval(BaseModel):
    """Human approval record for a strategy gray release."""

    model_config = ConfigDict(extra="forbid")

    approval_id: str = Field(default_factory=lambda: f"approval_{uuid4().hex}")
    strategy_id: str
    approved_by: str = Field(min_length=1)
    approved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    notes: str = Field(min_length=1)
    approved: bool = True


class StrategyPromotionInput(BaseModel):
    """Inputs required before a strategy can enter gray release."""

    model_config = ConfigDict(extra="forbid")

    strategy: StrategyCard
    golden_test_passed: bool
    safety_regression: bool = False
    baseline_evidence_coverage: float = Field(ge=0.0, le=1.0)
    candidate_evidence_coverage: float = Field(ge=0.0, le=1.0)
    approval: StrategyPromotionApproval | None = None
    audit_review_ref: str | None = Field(default=None, min_length=1)
    gray_traffic_share: float = Field(default=0.05, gt=0.0, le=0.10)


class StrategyPromotionDecision(BaseModel):
    """Auditable strategy promotion decision."""

    model_config = ConfigDict(extra="forbid")

    strategy: StrategyCard
    status: StrategyPromotionStatus
    approved: bool
    gray_traffic_share: float = Field(ge=0.0, le=0.10)
    audit_review_ref: str | None = None
    reasons: tuple[str, ...]


def promote_strategy_to_gray_release(
    promotion: StrategyPromotionInput,
    *,
    audit_log: AuditLog | None = None,
    actor: str = "strategy-promotion",
) -> StrategyPromotionDecision:
    """Promote a strategy to gray release only after all release gates pass."""

    reasons = _blocking_reasons(promotion)
    approved = not reasons
    strategy = (
        promotion.strategy.model_copy(update={"release_status": "gray_release"})
        if approved
        else promotion.strategy
    )
    decision = StrategyPromotionDecision(
        strategy=strategy,
        status=StrategyPromotionStatus.GRAY_RELEASE
        if approved
        else StrategyPromotionStatus.BLOCKED,
        approved=approved,
        gray_traffic_share=promotion.gray_traffic_share if approved else 0.0,
        audit_review_ref=promotion.audit_review_ref,
        reasons=tuple(reasons) if reasons else ("all promotion gates passed",),
    )
    if audit_log is not None:
        audit_log.append(_audit_event(promotion, decision, actor))
    return decision


def _blocking_reasons(promotion: StrategyPromotionInput) -> list[str]:
    reasons: list[str] = []
    approval = promotion.approval
    if approval is None:
        reasons.append("human approval is required before gray release")
    elif not approval.approved:
        reasons.append("human approval record is not approved")
    elif approval.strategy_id != promotion.strategy.id:
        reasons.append("human approval strategy_id does not match strategy")

    if promotion.audit_review_ref is None:
        reasons.append("audit review link is required before gray release")

    if (
        not promotion.golden_test_passed
        or promotion.strategy.golden_test_status is not ValidationStatus.PASSED
    ):
        reasons.append("golden tests must pass before gray release")

    if promotion.safety_regression:
        reasons.append("safety regression blocks gray release")

    if (
        promotion.candidate_evidence_coverage
        < promotion.baseline_evidence_coverage
    ):
        reasons.append("evidence coverage must not decrease")

    return reasons


def _audit_event(
    promotion: StrategyPromotionInput,
    decision: StrategyPromotionDecision,
    actor: str,
) -> AuditEvent:
    approval = promotion.approval
    return AuditEvent(
        event_type=AuditEventType.APPROVAL_GATE,
        actor=actor,
        action=f"strategy promotion {decision.status.value}",
        resource=promotion.strategy.id,
        approved=decision.approved,
        metadata={
            "approval_id": approval.approval_id if approval is not None else None,
            "audit_review_ref": decision.audit_review_ref,
            "release_status": decision.strategy.release_status,
            "gray_traffic_share": decision.gray_traffic_share,
            "reasons": list(decision.reasons),
            "golden_test_passed": promotion.golden_test_passed,
            "strategy_golden_test_status": promotion.strategy.golden_test_status.value,
            "safety_regression": promotion.safety_regression,
            "baseline_evidence_coverage": promotion.baseline_evidence_coverage,
            "candidate_evidence_coverage": promotion.candidate_evidence_coverage,
        },
    )
