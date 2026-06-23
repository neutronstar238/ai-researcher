from pathlib import Path

from autoresearch.experiments import (
    StrategyPromotionApproval,
    StrategyPromotionInput,
    StrategyPromotionStatus,
    promote_strategy_to_gray_release,
)
from autoresearch.observability import AuditEventType, AuditLog
from autoresearch.schemas import StrategyCard, ValidationStatus


def test_strategy_promotion_requires_human_approval() -> None:
    decision = promote_strategy_to_gray_release(
        StrategyPromotionInput(
            strategy=_candidate_strategy(),
            golden_test_passed=True,
            baseline_evidence_coverage=0.80,
            candidate_evidence_coverage=0.82,
        )
    )

    assert decision.status is StrategyPromotionStatus.BLOCKED
    assert decision.approved is False
    assert decision.gray_traffic_share == 0.0
    assert decision.strategy.release_status == "shadow"
    assert "human approval is required before gray release" in decision.reasons


def test_strategy_promotion_fails_without_golden_test_pass() -> None:
    strategy = _candidate_strategy(golden_test_status=ValidationStatus.FAILED)

    decision = promote_strategy_to_gray_release(
        StrategyPromotionInput(
            strategy=strategy,
            golden_test_passed=False,
            baseline_evidence_coverage=0.80,
            candidate_evidence_coverage=0.82,
            approval=_approval(strategy.id),
        )
    )

    assert decision.status is StrategyPromotionStatus.BLOCKED
    assert "golden tests must pass before gray release" in decision.reasons


def test_strategy_promotion_blocks_safety_or_evidence_regression() -> None:
    strategy = _candidate_strategy()

    decision = promote_strategy_to_gray_release(
        StrategyPromotionInput(
            strategy=strategy,
            golden_test_passed=True,
            safety_regression=True,
            baseline_evidence_coverage=0.84,
            candidate_evidence_coverage=0.80,
            approval=_approval(strategy.id),
        )
    )

    assert decision.status is StrategyPromotionStatus.BLOCKED
    assert "safety regression blocks gray release" in decision.reasons
    assert "evidence coverage must not decrease" in decision.reasons


def test_strategy_promotion_blocks_loop_metric_regression() -> None:
    strategy = _candidate_strategy()

    decision = promote_strategy_to_gray_release(
        StrategyPromotionInput(
            strategy=strategy,
            golden_test_passed=True,
            baseline_evidence_coverage=0.84,
            candidate_evidence_coverage=0.86,
            baseline_metadata_completeness=0.95,
            candidate_metadata_completeness=0.90,
            baseline_reproduction_delta=0.01,
            candidate_reproduction_delta=0.04,
            approval=_approval(strategy.id),
            audit_review_ref=_audit_review_ref(),
        )
    )

    assert decision.status is StrategyPromotionStatus.BLOCKED
    assert "metadata completeness must not decrease" in decision.reasons
    assert "reproduction delta must not increase" in decision.reasons


def test_strategy_promotion_starts_small_gray_release_with_audit(
    tmp_path: Path,
) -> None:
    strategy = _candidate_strategy()
    audit_log = AuditLog(tmp_path / "audit.jsonl")

    decision = promote_strategy_to_gray_release(
        StrategyPromotionInput(
            strategy=strategy,
            golden_test_passed=True,
            baseline_evidence_coverage=0.80,
            candidate_evidence_coverage=0.83,
            approval=_approval(strategy.id),
            audit_review_ref=_audit_review_ref(),
        ),
        audit_log=audit_log,
        actor="evolution-agent",
    )

    assert decision.status is StrategyPromotionStatus.GRAY_RELEASE
    assert decision.approved is True
    assert decision.gray_traffic_share == 0.05
    assert decision.audit_review_ref == _audit_review_ref()
    assert decision.strategy.release_status == "gray_release"
    assert strategy.release_status == "shadow"

    event = audit_log.read_all()[0]
    assert event.event_type is AuditEventType.APPROVAL_GATE
    assert event.actor == "evolution-agent"
    assert event.approved is True
    assert event.resource == strategy.id
    assert event.metadata["audit_review_ref"] == _audit_review_ref()
    assert event.metadata["gray_traffic_share"] == 0.05
    assert event.metadata["release_status"] == "gray_release"


def _candidate_strategy(
    *,
    golden_test_status: ValidationStatus = ValidationStatus.PASSED,
) -> StrategyCard:
    return StrategyCard(
        id="strategy_retrieval_policy_v2",
        strategy_type="retrieval_policy",
        content="Use evidence-preserving query expansion.",
        parent_strategy_id="strategy_retrieval_policy_v1",
        rollback_target="strategy_retrieval_policy_v1",
        release_status="shadow",
        golden_test_status=golden_test_status,
        shadow_status=ValidationStatus.PASSED,
    )


def _approval(strategy_id: str) -> StrategyPromotionApproval:
    return StrategyPromotionApproval(
        strategy_id=strategy_id,
        approved_by="maintainer",
        notes="Golden suite and shadow evaluation reviewed.",
    )


def _audit_review_ref() -> str:
    return "autoresearch-vault/exploration/reviews/strategy_retrieval_policy_v2"
