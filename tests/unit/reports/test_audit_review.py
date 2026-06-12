from pathlib import Path

from autoresearch.experiments import (
    StrategyPromotionApproval,
    StrategyPromotionInput,
    StrategyPromotionStatus,
    promote_strategy_to_gray_release,
)
from autoresearch.observability import AuditEventType, AuditLog
from autoresearch.reports import (
    StrategyPromotionAuditReviewContext,
    generate_strategy_promotion_audit_review,
)
from autoresearch.schemas import StrategyCard, ValidationStatus


def test_promotion_workflow_links_to_audit_review(tmp_path: Path) -> None:
    review = generate_strategy_promotion_audit_review(
        StrategyPromotionAuditReviewContext(
            strategy_id="strategy_retrieval_policy_v2",
            strategy_card_ref=(
                "autoresearch-vault/exploration/strategy_cards/"
                "strategy_retrieval_policy_v2.md"
            ),
            gate_summary=(
                "Golden suite passed.",
                "Evidence coverage did not decrease.",
                "Human approval is still required.",
            ),
            evidence_summary="Shadow run and golden suite evidence were reviewed.",
            reward_summary="Reward delta is positive after cost and risk penalties.",
            risk_summary="Main risk is higher retrieval cost during gray release.",
            rollback_plan="Rollback target is strategy_retrieval_policy_v1.",
            recommendation="Approve 5 percent gray release.",
        ),
        output_dir=tmp_path,
    )
    audit_log = AuditLog(tmp_path / "audit.jsonl")
    strategy = _candidate_strategy()

    decision = promote_strategy_to_gray_release(
        StrategyPromotionInput(
            strategy=strategy,
            golden_test_passed=True,
            baseline_evidence_coverage=0.80,
            candidate_evidence_coverage=0.84,
            approval=_approval(strategy.id),
            audit_review_ref=review.review_ref,
        ),
        audit_log=audit_log,
        actor="evolution-agent",
    )

    markdown = Path(review.markdown_path or "").read_text(encoding="utf-8")
    assert "# Strategy Promotion Audit Review" in markdown
    assert (
        "[[autoresearch-vault/exploration/strategy_cards/strategy_retrieval_policy_v2]]"
        in markdown
    )
    assert "## Gate Summary" in markdown
    assert review.review_ref == (tmp_path / "strategy-promotion-audit-review.md").as_posix()

    assert decision.status is StrategyPromotionStatus.GRAY_RELEASE
    assert decision.audit_review_ref == review.review_ref

    event = audit_log.read_all()[0]
    assert event.event_type is AuditEventType.APPROVAL_GATE
    assert event.metadata["audit_review_ref"] == review.review_ref


def _candidate_strategy() -> StrategyCard:
    return StrategyCard(
        id="strategy_retrieval_policy_v2",
        strategy_type="retrieval_policy",
        content="Use evidence-preserving query expansion.",
        parent_strategy_id="strategy_retrieval_policy_v1",
        rollback_target="strategy_retrieval_policy_v1",
        release_status="shadow",
        golden_test_status=ValidationStatus.PASSED,
        shadow_status=ValidationStatus.PASSED,
    )


def _approval(strategy_id: str) -> StrategyPromotionApproval:
    return StrategyPromotionApproval(
        strategy_id=strategy_id,
        approved_by="maintainer",
        notes="Audit review and release gates reviewed.",
    )
