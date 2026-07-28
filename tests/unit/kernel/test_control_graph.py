"""Lifecycle, policy, fault, and property coverage for the durable Control Graph."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from autoresearch.kernel import (
    ActorKind,
    ControlGraphRuntime,
    DeterministicLoopExecutor,
    EventJournal,
    EventStatus,
    HoldoutState,
    LoopApproval,
    LoopApprovalDecision,
    LoopBudgetPolicy,
    LoopEdgeKind,
    LoopEdgeSpec,
    LoopGraphProposal,
    LoopGuardKind,
    LoopGuardSpec,
    LoopHoldoutPolicy,
    LoopNodeKind,
    LoopNodeOutcome,
    LoopNodeResult,
    LoopNodeSpec,
    LoopPermissionPolicy,
    LoopReplayError,
    LoopResumeRequest,
    LoopRetryPolicy,
    LoopRunSnapshot,
    LoopRunStatus,
    LoopRuntimeError,
    LoopSpec,
    LoopSpecIntegrityError,
    LoopStartRequest,
    LoopUsage,
    RunEvent,
    always_guard,
)

NOW = datetime(2026, 7, 28, 16, 0, tzinfo=timezone.utc)


class InjectedLoopCrash(RuntimeError):
    """Test-only crash after a side effect and before completion persistence."""


def _budget(
    *,
    max_steps: int = 20,
    max_tokens: int = 100,
    max_cost: float = 10.0,
    max_wall_time: float = 100.0,
    max_tool_calls: int = 10,
    max_retries: int = 2,
    max_failures: int = 3,
    max_interventions: int = 2,
) -> LoopBudgetPolicy:
    return LoopBudgetPolicy(
        policy_id="budget.test",
        version="1",
        max_steps=max_steps,
        max_tokens=max_tokens,
        max_estimated_cost_usd=max_cost,
        max_wall_time_seconds=max_wall_time,
        max_tool_calls=max_tool_calls,
        max_total_retries=max_retries,
        max_failures=max_failures,
        max_human_interventions=max_interventions,
    )


def _permissions(
    *,
    granted: list[str] | None = None,
    approval_required: list[str] | None = None,
) -> LoopPermissionPolicy:
    return LoopPermissionPolicy(
        policy_id="permission.test",
        version="1",
        granted_permission_ids=granted or [],
        approval_required_permission_ids=approval_required or [],
    )


def _holdout(
    *,
    reveal_permission_id: str | None = None,
) -> LoopHoldoutPolicy:
    return LoopHoldoutPolicy(
        policy_id="holdout.test",
        version="1",
        reveal_permission_id=reveal_permission_id,
    )


def _outcome_guard(
    guard_id: str,
    *outcomes: LoopNodeOutcome,
) -> LoopGuardSpec:
    return LoopGuardSpec(
        guard_id=guard_id,
        kind=LoopGuardKind.OUTCOME,
        outcomes=list(outcomes),
    )


def _approval_guard(
    guard_id: str,
    *decisions: LoopApprovalDecision,
) -> LoopGuardSpec:
    return LoopGuardSpec(
        guard_id=guard_id,
        kind=LoopGuardKind.APPROVAL_DECISION,
        approval_decisions=list(decisions),
    )


def _edge(
    edge_id: str,
    source: str,
    target: str,
    *,
    kind: LoopEdgeKind = LoopEdgeKind.NEXT,
    priority: int = 100,
    guards: list[LoopGuardSpec] | None = None,
    cycle_boundary: bool = False,
    max_traversals: int = 1,
) -> LoopEdgeSpec:
    default_guards = (
        [always_guard(f"guard.{edge_id}")]
        if source == "start"
        else [
            _outcome_guard(
                f"guard.{edge_id}.succeeded",
                LoopNodeOutcome.SUCCEEDED,
            )
        ]
    )
    return LoopEdgeSpec(
        edge_id=edge_id,
        version="1",
        kind=kind,
        source_node_id=source,
        target_node_id=target,
        priority=priority,
        guards=guards or default_guards,
        cycle_boundary=cycle_boundary,
        max_traversals=max_traversals,
    )


def _start_node() -> LoopNodeSpec:
    return LoopNodeSpec(
        node_id="start",
        version="1",
        kind=LoopNodeKind.START,
    )


def _terminal(
    node_id: str = "done",
    status: LoopRunStatus = LoopRunStatus.SUCCEEDED,
) -> LoopNodeSpec:
    return LoopNodeSpec(
        node_id=node_id,
        version="1",
        kind=LoopNodeKind.TERMINAL,
        terminal_status=status,
    )


def _action(
    node_id: str,
    *,
    handler_id: str | None = None,
    kind: LoopNodeKind = LoopNodeKind.ACTION,
    minimum_tokens: int = 0,
    retry_policy: LoopRetryPolicy | None = None,
    approval_permission: str | None = None,
    permissions: list[str] | None = None,
    side_effecting: bool = False,
    compensation_node_id: str | None = None,
    adaptive: bool = False,
    may_reveal_holdout: bool = False,
    allowed_after_reveal: bool = False,
    interrupt_after: bool = False,
) -> LoopNodeSpec:
    return LoopNodeSpec(
        node_id=node_id,
        version="1",
        kind=kind,
        handler_id=handler_id or f"handler.{node_id}",
        minimum_usage=LoopUsage(tokens=minimum_tokens),
        retry_policy=retry_policy or LoopRetryPolicy(),
        required_approval_permission_id=approval_permission,
        required_permission_ids=permissions or [],
        side_effecting=side_effecting,
        compensation_node_id=compensation_node_id,
        adaptive=adaptive,
        may_reveal_holdout=may_reveal_holdout,
        allowed_after_holdout_reveal=allowed_after_reveal,
        interrupt_after=interrupt_after,
    )


def _spec(
    *,
    nodes: list[LoopNodeSpec],
    edges: list[LoopEdgeSpec],
    budget: LoopBudgetPolicy | None = None,
    permissions: LoopPermissionPolicy | None = None,
    holdout: LoopHoldoutPolicy | None = None,
    spec_id: str = "loop.test",
    version: str = "1",
) -> LoopSpec:
    return LoopSpec.create(
        spec_id=spec_id,
        version=version,
        graph_version=1,
        task_id="task.test",
        entry_node_id="start",
        nodes=nodes,
        edges=edges,
        budget_policy=budget or _budget(),
        permission_policy=permissions or _permissions(),
        holdout_policy=holdout or _holdout(),
    )


def _journal(tmp_path: Path, run_id: str = "run.test") -> EventJournal:
    return EventJournal.create(
        tmp_path / "journal",
        run_id=run_id,
        created_at=NOW,
    )


def _request(
    *,
    run_id: str = "run.test",
    mechanism_family: str = "baseline_family",
    approvals: list[LoopApproval] | None = None,
) -> LoopStartRequest:
    return LoopStartRequest(
        run_id=run_id,
        task_id="task.test",
        mechanism_family=mechanism_family,
        variables={"fixture": "development"},
        approvals=approvals or [],
    )


def _approval(
    *,
    decision: LoopApprovalDecision,
    permission_id: str = "experiment.execute",
) -> LoopApproval:
    return LoopApproval(
        approval_id=f"approval.{decision.value}",
        permission_id=permission_id,
        decision=decision,
        actor_id="operator.test",
        decided_at=NOW,
    )


def _success(
    summary: str,
    *,
    tokens: int = 0,
    artifacts: list[str] | None = None,
    mechanism_family: str | None = None,
    reveal_holdout: bool = False,
    graph_proposal: LoopGraphProposal | None = None,
    side_effect_committed: bool = False,
) -> LoopNodeResult:
    return LoopNodeResult(
        outcome=LoopNodeOutcome.SUCCEEDED,
        summary=summary,
        usage=LoopUsage(tokens=tokens),
        output_artifact_ids=artifacts or [],
        mechanism_family=mechanism_family,
        reveal_holdout=reveal_holdout,
        graph_proposal=graph_proposal,
        side_effect_committed=side_effect_committed,
    )


def _simple_spec(*, interrupt_after: bool = False) -> LoopSpec:
    return _spec(
        nodes=[
            _start_node(),
            _action("work", interrupt_after=interrupt_after),
            _terminal(),
        ],
        edges=[
            _edge("edge.start.work", "start", "work"),
            _edge("edge.work.done", "work", "done"),
        ],
    )


@given(
    node_order=st.permutations(["start", "work", "done"]),
    edge_order=st.permutations(["edge.start.work", "edge.work.done"]),
)
def test_loop_spec_hash_is_independent_of_input_order(
    node_order: list[str],
    edge_order: list[str],
) -> None:
    nodes = {
        "start": _start_node(),
        "work": _action("work"),
        "done": _terminal(),
    }
    edges = {
        "edge.start.work": _edge("edge.start.work", "start", "work"),
        "edge.work.done": _edge("edge.work.done", "work", "done"),
    }
    ordered = _spec(
        nodes=[nodes[node_id] for node_id in node_order],
        edges=[edges[edge_id] for edge_id in edge_order],
    )
    canonical = _simple_spec()
    assert ordered.spec_hash == canonical.spec_hash
    assert ordered.control_snapshot().content_hash() == (
        canonical.control_snapshot().content_hash()
    )


def test_loop_spec_round_trip_and_nested_tamper_detection() -> None:
    spec = _simple_spec()
    loaded = LoopSpec.model_validate_json(spec.model_dump_json())
    assert loaded == spec
    assert loaded.control_snapshot().plane.value == "control"

    loaded.nodes[0].adaptive = not loaded.nodes[0].adaptive
    with pytest.raises(LoopSpecIntegrityError):
        loaded.verify_integrity()


def test_loop_spec_rejects_unmarked_cycle_and_ambiguous_priorities() -> None:
    nodes = [_start_node(), _action("a"), _action("b"), _terminal()]
    with pytest.raises(ValidationError, match="cycle"):
        _spec(
            nodes=nodes,
            edges=[
                _edge("edge.start.a", "start", "a"),
                _edge("edge.a.b", "a", "b"),
                _edge("edge.b.a", "b", "a"),
                _edge(
                    "edge.b.done",
                    "b",
                    "done",
                    priority=200,
                    guards=[
                        _outcome_guard(
                            "guard.b.done",
                            LoopNodeOutcome.SUCCEEDED,
                        )
                    ],
                ),
            ],
        )

    with pytest.raises(ValidationError, match="priorities"):
        _spec(
            nodes=[_start_node(), _action("work"), _terminal()],
            edges=[
                _edge("edge.start.work", "start", "work"),
                _edge(
                    "edge.work.done.a",
                    "work",
                    "done",
                    priority=10,
                ),
                _edge(
                    "edge.work.done.b",
                    "work",
                    "done",
                    priority=10,
                ),
            ],
        )


def test_model_cannot_define_gate_expand_permission_or_authorize_release() -> None:
    with pytest.raises(ValidationError, match="scientific gates"):
        LoopNodeSpec(
            node_id="model_gate",
            version="1",
            kind=LoopNodeKind.GATE,
            handler_id="model.gate",
            actor_kind=ActorKind.MODEL,
            scientific_gate=True,
        )

    proposal_values: dict[str, object] = {
        "proposal_id": "proposal.test",
        "proposed_by_actor_id": "model.test",
        "proposed_by_kind": ActorKind.MODEL,
        "parent_spec_id": "loop.test",
        "parent_spec_hash": "a" * 64,
        "proposed_version": "2",
        "proposed_spec_hash": "b" * 64,
        "rationale": "Try a separately evaluated graph version.",
    }
    with pytest.raises(ValidationError, match="expand permissions"):
        LoopGraphProposal.model_validate(
            {
                **proposal_values,
                "permission_additions": ["release.public"],
            }
        )
    with pytest.raises(ValidationError, match="scientific gate"):
        LoopGraphProposal.model_validate(
            {
                **proposal_values,
                "scientific_gate_status": "pass",
            }
        )
    with pytest.raises(ValidationError, match="authorize release"):
        LoopGraphProposal.model_validate(
            {
                **proposal_values,
                "authorizes_release": True,
            }
        )


def test_control_graph_success_is_sealed_and_round_trips(tmp_path: Path) -> None:
    spec = _simple_spec()
    executor = DeterministicLoopExecutor(
        {
            "handler.work": [
                _success(
                    "Development fixture completed.",
                    tokens=4,
                    artifacts=["artifact.development"],
                )
            ]
        }
    )
    runtime = ControlGraphRuntime(
        spec=spec,
        journal=_journal(tmp_path),
        executor=executor,
        clock=lambda: NOW,
    )

    snapshot = runtime.start(_request())

    assert snapshot.state.status == LoopRunStatus.SUCCEEDED
    assert snapshot.state.completed_node_ids == ["start", "work"]
    assert snapshot.state.produced_artifact_ids == ["artifact.development"]
    assert snapshot.state.consumed_usage.tokens == 4
    assert snapshot.seal_hash is not None
    assert snapshot.event_count == 6
    snapshot.verify_integrity()
    assert LoopRunSnapshot.model_validate_json(snapshot.model_dump_json()) == snapshot
    assert runtime.start(_request()) == snapshot

    with pytest.raises(LoopRuntimeError, match="different start request"):
        runtime.start(_request(mechanism_family="changed_family"))


def test_crash_after_side_effect_reuses_same_idempotency_key(tmp_path: Path) -> None:
    spec = _simple_spec()
    executor = DeterministicLoopExecutor(
        {
            "handler.work": [
                _success(
                    "One idempotent local side effect completed.",
                    artifacts=["artifact.side_effect"],
                    side_effect_committed=True,
                )
            ]
        }
    )
    crashed = False

    def fault(phase: str, node_id: str) -> None:
        nonlocal crashed
        if phase == "after_node_execute" and node_id == "work" and not crashed:
            crashed = True
            raise InjectedLoopCrash("crash after effect before completion event")

    journal = _journal(tmp_path)
    runtime = ControlGraphRuntime(
        spec=spec,
        journal=journal,
        executor=executor,
        clock=lambda: NOW,
        fault_injector=fault,
    )
    with pytest.raises(InjectedLoopCrash):
        runtime.start(_request())

    in_flight = ControlGraphRuntime(
        spec=spec,
        journal=journal,
        executor=executor,
        clock=lambda: NOW,
    ).snapshot()
    assert in_flight.state.status == LoopRunStatus.RUNNING
    first_key = in_flight.state.inflight_idempotency_key

    recovered = ControlGraphRuntime(
        spec=spec,
        journal=journal,
        executor=executor,
        clock=lambda: NOW,
    ).resume()

    assert recovered.state.status == LoopRunStatus.SUCCEEDED
    assert executor.invocation_count == 2
    assert executor.execution_count == 1
    assert executor.idempotency_keys == [first_key, first_key]
    assert recovered.state.produced_artifact_ids == ["artifact.side_effect"]


def test_retry_requires_repair_and_uses_explicit_cycle_boundary(
    tmp_path: Path,
) -> None:
    retry_policy = LoopRetryPolicy(
        max_attempts=2,
        retryable_outcomes=[LoopNodeOutcome.FAILED],
        require_repair_hypothesis=True,
        require_frozen_dimension=True,
    )
    spec = _spec(
        nodes=[
            _start_node(),
            _action("work", retry_policy=retry_policy),
            _action("repair"),
            _terminal(),
        ],
        edges=[
            _edge("edge.start.work", "start", "work"),
            _edge(
                "edge.work.retry",
                "work",
                "repair",
                kind=LoopEdgeKind.RETRY,
                priority=10,
                guards=[
                    _outcome_guard(
                        "guard.work.failed",
                        LoopNodeOutcome.FAILED,
                    )
                ],
                cycle_boundary=True,
                max_traversals=1,
            ),
            _edge(
                "edge.repair.work",
                "repair",
                "work",
                cycle_boundary=True,
            ),
            _edge(
                "edge.work.done",
                "work",
                "done",
                priority=20,
                guards=[
                    _outcome_guard(
                        "guard.work.succeeded",
                        LoopNodeOutcome.SUCCEEDED,
                    )
                ],
            ),
        ],
        budget=_budget(max_retries=1),
    )
    executor = DeterministicLoopExecutor(
        {
            "handler.work": [
                LoopNodeResult(
                    outcome=LoopNodeOutcome.FAILED,
                    summary="First attempt exposed a fixture defect.",
                    failure_code="fixture_defect",
                    retryable=True,
                    repair_hypothesis="Normalize the bounded fixture.",
                    frozen_dimensions=["dataset", "metric"],
                ),
                _success("Repaired attempt completed."),
            ],
            "handler.repair": [_success("Applied the frozen repair hypothesis.")],
        }
    )

    snapshot = ControlGraphRuntime(
        spec=spec,
        journal=_journal(tmp_path),
        executor=executor,
        clock=lambda: NOW,
    ).start(_request())

    assert snapshot.state.status == LoopRunStatus.SUCCEEDED
    assert snapshot.state.retry_count == 1
    assert snapshot.state.attempts_by_node["work"] == 2
    assert snapshot.state.edge_traversals["edge.work.retry"] == 1
    assert executor.execution_count == 3


def test_retry_without_repair_is_blocked_instead_of_blindly_retried(
    tmp_path: Path,
) -> None:
    spec = _spec(
        nodes=[
            _start_node(),
            _action(
                "work",
                retry_policy=LoopRetryPolicy(
                    max_attempts=2,
                    retryable_outcomes=[LoopNodeOutcome.FAILED],
                    require_repair_hypothesis=True,
                ),
            ),
            _action("repair"),
            _terminal(),
        ],
        edges=[
            _edge("edge.start.work", "start", "work"),
            _edge(
                "edge.work.retry",
                "work",
                "repair",
                kind=LoopEdgeKind.RETRY,
                guards=[
                    _outcome_guard(
                        "guard.work.failed",
                        LoopNodeOutcome.FAILED,
                    )
                ],
                cycle_boundary=True,
            ),
            _edge(
                "edge.repair.work",
                "repair",
                "work",
                cycle_boundary=True,
            ),
            _edge(
                "edge.work.done",
                "work",
                "done",
                priority=200,
                guards=[
                    _outcome_guard(
                        "guard.work.done",
                        LoopNodeOutcome.SUCCEEDED,
                    )
                ],
            ),
        ],
    )
    executor = DeterministicLoopExecutor(
        {
            "handler.work": [
                LoopNodeResult(
                    outcome=LoopNodeOutcome.FAILED,
                    summary="Failure has no repair hypothesis.",
                    failure_code="unexplained_failure",
                    retryable=True,
                )
            ],
            "handler.repair": [_success("Must not run without a repair hypothesis.")],
        }
    )

    snapshot = ControlGraphRuntime(
        spec=spec,
        journal=_journal(tmp_path),
        executor=executor,
        clock=lambda: NOW,
    ).start(_request())

    assert snapshot.state.status == LoopRunStatus.BLOCKED
    assert snapshot.state.terminal_reason == "retry_repair_hypothesis_missing:work"
    assert executor.execution_count == 1


def test_budget_exhaustion_blocks_next_node_and_post_result_overage(
    tmp_path: Path,
) -> None:
    spec = _spec(
        nodes=[
            _start_node(),
            _action("work"),
            _action("next_work", minimum_tokens=1),
            _terminal(),
        ],
        edges=[
            _edge("edge.start.work", "start", "work"),
            _edge("edge.work.next", "work", "next_work"),
            _edge("edge.next.done", "next_work", "done"),
        ],
        budget=_budget(max_tokens=5, max_cost=0.0),
    )
    executor = DeterministicLoopExecutor(
        {
            "handler.work": [_success("Used the remaining budget.", tokens=5)],
            "handler.next_work": [_success("Must not execute.", tokens=1)],
        }
    )

    snapshot = ControlGraphRuntime(
        spec=spec,
        journal=_journal(tmp_path),
        executor=executor,
        clock=lambda: NOW,
    ).start(_request())

    assert snapshot.state.status == LoopRunStatus.BLOCKED
    assert snapshot.state.terminal_reason == "token_budget_exhausted"
    assert snapshot.state.consumed_usage.tokens == 5
    assert executor.execution_count == 1

    overage_spec = _simple_spec()
    overage_spec = LoopSpec.create(
        **{
            **overage_spec.model_dump(mode="json", exclude={"spec_hash"}),
            "budget_policy": _budget(max_tokens=4),
        }
    )
    overage_executor = DeterministicLoopExecutor(
        {"handler.work": [_success("Exceeded budget.", tokens=5)]}
    )
    overage = ControlGraphRuntime(
        spec=overage_spec,
        journal=EventJournal.create(
            tmp_path / "overage-journal",
            run_id="run.overage",
            created_at=NOW,
        ),
        executor=overage_executor,
        clock=lambda: NOW,
    ).start(_request(run_id="run.overage"))
    assert overage.state.status == LoopRunStatus.BLOCKED
    assert overage.state.terminal_reason == "token_budget_exceeded"


def test_missing_approval_pauses_and_human_rejection_is_terminal(
    tmp_path: Path,
) -> None:
    permission_id = "experiment.execute"
    danger = _action(
        "danger",
        approval_permission=permission_id,
        permissions=[permission_id],
    )
    spec = _spec(
        nodes=[
            _start_node(),
            danger,
            _terminal(),
            _terminal("rejected", LoopRunStatus.REJECTED),
        ],
        edges=[
            _edge("edge.start.danger", "start", "danger"),
            _edge(
                "edge.danger.done",
                "danger",
                "done",
                priority=10,
                guards=[
                    _outcome_guard(
                        "guard.danger.succeeded",
                        LoopNodeOutcome.SUCCEEDED,
                    ),
                    _approval_guard(
                        "guard.danger.approved",
                        LoopApprovalDecision.APPROVED,
                    )
                ],
            ),
            _edge(
                "edge.danger.rejected",
                "danger",
                "rejected",
                kind=LoopEdgeKind.REJECT,
                priority=20,
                guards=[
                    _outcome_guard(
                        "guard.danger.blocked",
                        LoopNodeOutcome.BLOCKED,
                    ),
                    _approval_guard(
                        "guard.danger.rejected",
                        LoopApprovalDecision.REJECTED,
                    )
                ],
            ),
        ],
        permissions=_permissions(approval_required=[permission_id]),
        budget=_budget(max_interventions=1),
    )
    executor = DeterministicLoopExecutor(
        {"handler.danger": [_success("Must not run after rejection.")]}
    )
    runtime = ControlGraphRuntime(
        spec=spec,
        journal=_journal(tmp_path),
        executor=executor,
        clock=lambda: NOW,
    )

    paused = runtime.start(_request())
    assert paused.state.status == LoopRunStatus.PAUSED
    assert paused.state.pending_approval_permission_id == permission_id
    assert paused.seal_hash is None
    assert runtime.resume().snapshot_hash == paused.snapshot_hash

    rejected = runtime.resume(
        LoopResumeRequest(
            approvals=[
                _approval(
                    decision=LoopApprovalDecision.REJECTED,
                    permission_id=permission_id,
                )
            ]
        )
    )
    assert rejected.state.status == LoopRunStatus.REJECTED
    assert rejected.state.human_intervention_count == 1
    assert rejected.state.last_failure_code == "human_rejected"
    assert rejected.seal_hash is not None
    assert executor.execution_count == 0


def test_approved_node_executes_and_interrupt_after_resumes(
    tmp_path: Path,
) -> None:
    permission_id = "experiment.execute"
    spec = _spec(
        nodes=[
            _start_node(),
            _action(
                "work",
                approval_permission=permission_id,
                permissions=[permission_id],
                interrupt_after=True,
            ),
            _terminal(),
        ],
        edges=[
            _edge("edge.start.work", "start", "work"),
            _edge("edge.work.done", "work", "done"),
        ],
        permissions=_permissions(approval_required=[permission_id]),
        budget=_budget(max_interventions=1),
    )
    executor = DeterministicLoopExecutor(
        {"handler.work": [_success("Approved work completed.")]}
    )
    runtime = ControlGraphRuntime(
        spec=spec,
        journal=_journal(tmp_path),
        executor=executor,
        clock=lambda: NOW,
    )
    paused = runtime.start(
        _request(
            approvals=[
                _approval(
                    decision=LoopApprovalDecision.APPROVED,
                    permission_id=permission_id,
                )
            ]
        )
    )

    assert paused.state.status == LoopRunStatus.PAUSED
    assert paused.state.pending_interrupt_after_node_id == "work"
    assert executor.execution_count == 1

    resumed = runtime.resume()
    assert resumed.state.status == LoopRunStatus.SUCCEEDED
    assert resumed.state.human_intervention_count == 1


def test_negative_result_pivots_only_after_mechanism_family_changes(
    tmp_path: Path,
) -> None:
    spec = _spec(
        nodes=[
            _start_node(),
            _action("evaluate", kind=LoopNodeKind.GATE),
            _action("pivot", kind=LoopNodeKind.PIVOT),
            _action("alternative"),
            _terminal(),
        ],
        edges=[
            _edge("edge.start.evaluate", "start", "evaluate"),
            _edge(
                "edge.evaluate.pivot",
                "evaluate",
                "pivot",
                kind=LoopEdgeKind.PIVOT,
                guards=[
                    _outcome_guard(
                        "guard.evaluate.negative",
                        LoopNodeOutcome.NEGATIVE_RESULT,
                    )
                ],
            ),
            _edge(
                "edge.pivot.alternative",
                "pivot",
                "alternative",
                guards=[
                    _outcome_guard(
                        "guard.pivot.succeeded",
                        LoopNodeOutcome.SUCCEEDED,
                    ),
                    LoopGuardSpec(
                        guard_id="guard.pivot.changed",
                        kind=LoopGuardKind.MECHANISM_CHANGED,
                    )
                ],
            ),
            _edge("edge.alternative.done", "alternative", "done"),
        ],
    )
    executor = DeterministicLoopExecutor(
        {
            "handler.evaluate": [
                LoopNodeResult(
                    outcome=LoopNodeOutcome.NEGATIVE_RESULT,
                    summary="Frozen evaluation did not pass.",
                )
            ],
            "handler.pivot": [
                _success(
                    "Changed the mechanism family.",
                    mechanism_family="alternative_family",
                )
            ],
            "handler.alternative": [_success("Alternative family completed.")],
        }
    )

    snapshot = ControlGraphRuntime(
        spec=spec,
        journal=_journal(tmp_path),
        executor=executor,
        clock=lambda: NOW,
    ).start(_request())

    assert snapshot.state.status == LoopRunStatus.SUCCEEDED
    assert snapshot.state.mechanism_family == "alternative_family"
    assert snapshot.state.completed_node_ids == [
        "start",
        "evaluate",
        "pivot",
        "alternative",
    ]
    assert snapshot.state.last_outcome == LoopNodeOutcome.SUCCEEDED


def test_revealed_holdout_blocks_adaptive_node(tmp_path: Path) -> None:
    permission_id = "holdout.reveal"
    spec = _spec(
        nodes=[
            _start_node(),
            _action(
                "confirm",
                may_reveal_holdout=True,
                permissions=[permission_id],
            ),
            _action("tune", adaptive=True),
            _terminal(),
        ],
        edges=[
            _edge("edge.start.confirm", "start", "confirm"),
            _edge("edge.confirm.tune", "confirm", "tune"),
            _edge("edge.tune.done", "tune", "done"),
        ],
        permissions=_permissions(granted=[permission_id]),
        holdout=_holdout(reveal_permission_id=permission_id),
    )
    executor = DeterministicLoopExecutor(
        {
            "handler.confirm": [
                _success(
                    "Confirmatory holdout was revealed.",
                    reveal_holdout=True,
                )
            ],
            "handler.tune": [_success("Must not adapt after reveal.")],
        }
    )

    snapshot = ControlGraphRuntime(
        spec=spec,
        journal=_journal(tmp_path),
        executor=executor,
        clock=lambda: NOW,
    ).start(_request())

    assert snapshot.state.status == LoopRunStatus.BLOCKED
    assert snapshot.state.holdout_state == HoldoutState.REVEALED
    assert (
        snapshot.state.terminal_reason
        == "revealed_holdout_adaptation_forbidden"
    )
    assert executor.execution_count == 1


def test_compensation_runs_after_committed_side_effect_failure(
    tmp_path: Path,
) -> None:
    work = _action(
        "work",
        side_effecting=True,
        compensation_node_id="compensate",
    )
    compensate = _action(
        "compensate",
        kind=LoopNodeKind.COMPENSATION,
    )
    spec = _spec(
        nodes=[
            _start_node(),
            work,
            compensate,
            _terminal("failed", LoopRunStatus.FAILED),
        ],
        edges=[
            _edge("edge.start.work", "start", "work"),
            _edge(
                "edge.work.compensate",
                "work",
                "compensate",
                kind=LoopEdgeKind.COMPENSATE,
                priority=10,
                guards=[
                    _outcome_guard(
                        "guard.work.failed",
                        LoopNodeOutcome.FAILED,
                    )
                ],
            ),
            _edge(
                "edge.compensate.failed",
                "compensate",
                "failed",
                kind=LoopEdgeKind.STOP,
            ),
        ],
    )
    executor = DeterministicLoopExecutor(
        {
            "handler.work": [
                LoopNodeResult(
                    outcome=LoopNodeOutcome.FAILED,
                    summary="Side effect failed after partial commit.",
                    failure_code="partial_side_effect",
                    side_effect_committed=True,
                )
            ],
            "handler.compensate": [_success("Compensation completed.")],
        }
    )

    snapshot = ControlGraphRuntime(
        spec=spec,
        journal=_journal(tmp_path),
        executor=executor,
        clock=lambda: NOW,
    ).start(_request())

    assert snapshot.state.status == LoopRunStatus.FAILED
    assert snapshot.state.completed_node_ids == ["start", "work", "compensate"]
    assert executor.execution_count == 2


def test_graph_proposal_is_recorded_but_current_spec_stays_frozen(
    tmp_path: Path,
) -> None:
    spec = _simple_spec()
    proposal = LoopGraphProposal(
        proposal_id="proposal.next",
        proposed_by_actor_id="model.planner",
        proposed_by_kind=ActorKind.MODEL,
        parent_spec_id=spec.spec_id,
        parent_spec_hash=spec.spec_hash,
        proposed_version="2",
        proposed_spec_hash="b" * 64,
        rationale="Evaluate a different graph in a future fork.",
    )
    executor = DeterministicLoopExecutor(
        {
            "handler.work": [
                _success(
                    "Current frozen graph completed.",
                    graph_proposal=proposal,
                )
            ]
        }
    )

    snapshot = ControlGraphRuntime(
        spec=spec,
        journal=_journal(tmp_path),
        executor=executor,
        clock=lambda: NOW,
    ).start(_request())

    assert snapshot.state.status == LoopRunStatus.SUCCEEDED
    assert snapshot.state.spec_hash == spec.spec_hash
    assert snapshot.state.graph_proposals == [proposal]
    assert snapshot.state.current_node_id == "done"


def test_sensitive_executor_output_fails_without_persisting_value(
    tmp_path: Path,
) -> None:
    spec = _simple_spec()
    executor = DeterministicLoopExecutor(
        {
            "handler.work": [
                _success("Contact private.person@example.com for the result.")
            ]
        }
    )
    journal = _journal(tmp_path)

    snapshot = ControlGraphRuntime(
        spec=spec,
        journal=journal,
        executor=executor,
        clock=lambda: NOW,
    ).start(_request())

    assert snapshot.state.status == LoopRunStatus.FAILED
    assert snapshot.state.last_failure_code == "sensitive_node_result"
    committed = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(journal.events_dir.glob("*.json"))
    )
    assert "private.person@example.com" not in committed


def test_replay_rejects_semantically_decreasing_usage(tmp_path: Path) -> None:
    spec = _simple_spec(interrupt_after=True)
    executor = DeterministicLoopExecutor(
        {"handler.work": [_success("Paused after work.", tokens=5)]}
    )
    journal = _journal(tmp_path)
    runtime = ControlGraphRuntime(
        spec=spec,
        journal=journal,
        executor=executor,
        clock=lambda: NOW,
    )
    paused = runtime.start(_request())
    assert paused.state.status == LoopRunStatus.PAUSED

    previous = paused.state
    malicious_state = previous.model_dump(mode="json")
    malicious_state.update(
        {
            "revision": previous.revision + 1,
            "status": LoopRunStatus.READY.value,
            "pending_interrupt_after_node_id": None,
            "consumed_usage": LoopUsage(tokens=0).model_dump(mode="json"),
        }
    )
    journal_snapshot = journal.snapshot()
    parent = journal_snapshot.events[-1]
    malicious = RunEvent.create(
        run_id=previous.run_id,
        task_id=previous.task_id,
        sequence=previous.revision + 1,
        actor=ControlGraphRuntime._ACTOR,
        event_type="loop.resumed",
        status=EventStatus.STARTED,
        action="Inject semantically invalid replay state",
        idempotency_key="loop:malicious:usage",
        occurred_at=NOW,
        parent_event_id=parent.event_id,
        parent_event_hash=parent.event_hash,
        payload={
            "loop_spec_hash": spec.spec_hash,
            "new_approval_count": 0,
            "state": malicious_state,
        },
    )
    journal.append(
        malicious,
        expected_lineage_hash=journal_snapshot.lineage_hash,
    )

    with pytest.raises(LoopReplayError, match="usage decreased"):
        runtime.snapshot()


def test_failed_node_can_escalate_to_explicit_terminal(tmp_path: Path) -> None:
    spec = _spec(
        nodes=[
            _start_node(),
            _action("work"),
            _terminal("escalated", LoopRunStatus.ESCALATED),
        ],
        edges=[
            _edge("edge.start.work", "start", "work"),
            _edge(
                "edge.work.escalated",
                "work",
                "escalated",
                kind=LoopEdgeKind.ESCALATE,
                guards=[
                    _outcome_guard(
                        "guard.work.failed",
                        LoopNodeOutcome.FAILED,
                    )
                ],
            ),
        ],
    )
    journal = _journal(tmp_path)
    runtime = ControlGraphRuntime(
        spec=spec,
        journal=journal,
        executor=DeterministicLoopExecutor(
            {
                "handler.work": [
                    LoopNodeResult(
                        outcome=LoopNodeOutcome.FAILED,
                        summary="Deterministic work needs human escalation.",
                        failure_code="manual_review_required",
                    )
                ]
            }
        ),
        clock=lambda: NOW,
    )

    snapshot = runtime.start(_request())

    assert snapshot.state.status == LoopRunStatus.ESCALATED
    assert snapshot.state.last_failure_code == "manual_review_required"
    assert journal.snapshot().events[-1].status == EventStatus.BLOCKED
    assert journal.snapshot().seal is not None


def test_terminal_event_commit_recovers_missing_seal_on_reopen(
    tmp_path: Path,
) -> None:
    root = tmp_path / "terminal-seal-crash"
    fired = False

    def crash_on_terminal_commit(point: str) -> None:
        nonlocal fired
        event_count = len(list((root / "events").glob("*.json")))
        if point == "after_event_commit" and event_count == 6 and not fired:
            fired = True
            raise InjectedLoopCrash("terminal event committed before seal")

    journal = EventJournal.create(
        root,
        run_id="run.test",
        created_at=NOW,
        fault_injector=crash_on_terminal_commit,
    )
    executor = DeterministicLoopExecutor(
        {"handler.work": [_success("Completed before terminal seal crash.")]}
    )
    runtime = ControlGraphRuntime(
        spec=_simple_spec(),
        journal=journal,
        executor=executor,
        clock=lambda: NOW,
    )

    with pytest.raises(InjectedLoopCrash, match="before seal"):
        runtime.start(_request())

    reopened_journal = EventJournal.open(root)
    recovered = ControlGraphRuntime(
        spec=_simple_spec(),
        journal=reopened_journal,
        executor=DeterministicLoopExecutor({}),
        clock=lambda: NOW,
    ).snapshot()

    assert fired is True
    assert recovered.state.status == LoopRunStatus.SUCCEEDED
    assert recovered.seal_hash is not None
    assert reopened_journal.snapshot().seal is not None
