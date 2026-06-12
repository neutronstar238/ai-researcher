from pathlib import Path

from autoresearch.experiments import (
    StrategyRollbackInput,
    StrategyRollbackStatus,
    evaluate_strategy_rollback,
)
from autoresearch.observability import AuditEventType, AuditLog
from autoresearch.schemas import StrategyCard, ValidationStatus


def test_repeated_negative_reward_triggers_rollback_event(tmp_path: Path) -> None:
    strategy = _gray_strategy()
    audit_log = AuditLog(tmp_path / "audit.jsonl")

    decision = evaluate_strategy_rollback(
        StrategyRollbackInput(
            strategy=strategy,
            recent_rewards=(0.12, -0.08, -0.11),
        ),
        audit_log=audit_log,
        actor="evolution-agent",
        run_id="run_strategy_reward",
        task_id="29.2",
    )

    assert decision.status is StrategyRollbackStatus.ROLLBACK_REQUIRED
    assert decision.rollback_required is True
    assert decision.rollback_target == "strategy_retrieval_policy_v1"
    assert decision.strategy_family_id == "strategy_retrieval_policy_v1"
    assert decision.family_frozen is True
    assert decision.review_required is True
    assert decision.strategy.release_status == "rolled_back"
    assert strategy.release_status == "gray_release"
    assert "repeated negative strategy reward" in decision.reasons

    event = audit_log.read_all()[0]
    assert event.event_type is AuditEventType.ROLLBACK
    assert event.actor == "evolution-agent"
    assert event.resource == strategy.id
    assert event.run_id == "run_strategy_reward"
    assert event.task_id == "29.2"
    assert event.metadata["rollback"] is True
    assert event.metadata["family_frozen"] is True
    assert event.metadata["rollback_target"] == "strategy_retrieval_policy_v1"
    assert event.metadata["release_status"] == "rolled_back"


def test_single_negative_reward_does_not_rollback(tmp_path: Path) -> None:
    audit_log = AuditLog(tmp_path / "audit.jsonl")

    decision = evaluate_strategy_rollback(
        StrategyRollbackInput(
            strategy=_gray_strategy(),
            recent_rewards=(0.10, -0.05),
        ),
        audit_log=audit_log,
    )

    assert decision.status is StrategyRollbackStatus.NO_ACTION
    assert decision.rollback_required is False
    assert decision.family_frozen is False
    assert decision.review_required is False
    assert decision.strategy.release_status == "gray_release"
    assert audit_log.read_all() == []


def test_safety_incident_triggers_rollback_and_freezes_family() -> None:
    decision = evaluate_strategy_rollback(
        StrategyRollbackInput(
            strategy=_gray_strategy(),
            recent_rewards=(0.10,),
            safety_incident=True,
        )
    )

    assert decision.status is StrategyRollbackStatus.ROLLBACK_REQUIRED
    assert decision.family_frozen is True
    assert decision.review_required is True
    assert decision.reasons == ("safety incident",)


def _gray_strategy() -> StrategyCard:
    return StrategyCard(
        id="strategy_retrieval_policy_v2",
        strategy_type="retrieval_policy",
        content="Use evidence-preserving query expansion.",
        parent_strategy_id="strategy_retrieval_policy_v1",
        rollback_target="strategy_retrieval_policy_v1",
        release_status="gray_release",
        golden_test_status=ValidationStatus.PASSED,
        shadow_status=ValidationStatus.PASSED,
    )
