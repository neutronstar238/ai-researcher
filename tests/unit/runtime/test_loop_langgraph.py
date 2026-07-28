"""Frozen LangGraph 1.x behavior and canonical Control Graph adapter tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoresearch.kernel import (
    ControlGraphRuntime,
    DeterministicLoopExecutor,
    EventJournal,
    LoopBudgetPolicy,
    LoopEdgeKind,
    LoopEdgeSpec,
    LoopGuardKind,
    LoopGuardSpec,
    LoopHoldoutPolicy,
    LoopNodeKind,
    LoopNodeOutcome,
    LoopNodeResult,
    LoopNodeSpec,
    LoopPermissionPolicy,
    LoopRetryPolicy,
    LoopRunStatus,
    LoopSpec,
    LoopStartRequest,
    always_guard,
)
from autoresearch.runtime import (
    LangGraphCharacterizationReport,
    LangGraphControlAdapter,
    adapter_snapshot,
    characterize_installed_langgraph,
)

NOW = datetime(2026, 7, 28, 17, 0, tzinfo=timezone.utc)
EXPECTED_LANGGRAPH_VERSION = "1.2.10"
EXPECTED_LANGCHAIN_CORE_VERSION = "1.5.2"
EXPECTED_CHARACTERIZATION_HASH = "dd62c3faef638b905755dbc26f6761957e5657175de7a3b641b6e5c718ebebd3"


def _edge(edge_id: str, source: str, target: str) -> LoopEdgeSpec:
    guards = (
        [always_guard(f"guard.{edge_id}")]
        if source == "start"
        else [
            LoopGuardSpec(
                guard_id=f"guard.{edge_id}.succeeded",
                kind=LoopGuardKind.OUTCOME,
                outcomes=[LoopNodeOutcome.SUCCEEDED],
            )
        ]
    )
    return LoopEdgeSpec(
        edge_id=edge_id,
        version="1",
        kind=LoopEdgeKind.NEXT,
        source_node_id=source,
        target_node_id=target,
        guards=guards,
    )


def _spec(*, interrupt_after: bool = False) -> LoopSpec:
    return LoopSpec.create(
        spec_id="loop.langgraph_adapter",
        version="1",
        graph_version=1,
        task_id="task.langgraph_adapter",
        entry_node_id="start",
        nodes=[
            LoopNodeSpec(
                node_id="start",
                version="1",
                kind=LoopNodeKind.START,
            ),
            LoopNodeSpec(
                node_id="work",
                version="1",
                kind=LoopNodeKind.ACTION,
                handler_id="handler.work",
                retry_policy=LoopRetryPolicy(),
                interrupt_after=interrupt_after,
            ),
            LoopNodeSpec(
                node_id="done",
                version="1",
                kind=LoopNodeKind.TERMINAL,
                terminal_status=LoopRunStatus.SUCCEEDED,
            ),
        ],
        edges=[
            _edge("edge.start.work", "start", "work"),
            _edge("edge.work.done", "work", "done"),
        ],
        budget_policy=LoopBudgetPolicy(
            policy_id="budget.langgraph_adapter",
            version="1",
            max_steps=3,
            max_tokens=10,
            max_estimated_cost_usd=0.0,
            max_wall_time_seconds=10.0,
            max_tool_calls=0,
            max_total_retries=0,
            max_failures=1,
            max_human_interventions=0,
        ),
        permission_policy=LoopPermissionPolicy(
            policy_id="permission.langgraph_adapter",
            version="1",
        ),
        holdout_policy=LoopHoldoutPolicy(
            policy_id="holdout.langgraph_adapter",
            version="1",
        ),
    )


def _runtime(
    tmp_path: Path,
    *,
    interrupt_after: bool = False,
    run_id: str = "run.langgraph_adapter",
) -> ControlGraphRuntime:
    return ControlGraphRuntime(
        spec=_spec(interrupt_after=interrupt_after),
        journal=EventJournal.create(
            tmp_path / f"journal-{run_id}",
            run_id=run_id,
            created_at=NOW,
        ),
        executor=DeterministicLoopExecutor(
            {
                "handler.work": [
                    LoopNodeResult(
                        outcome=LoopNodeOutcome.SUCCEEDED,
                        summary="Adapter development fixture completed.",
                    )
                ]
            }
        ),
        clock=lambda: NOW,
    )


def _request(run_id: str = "run.langgraph_adapter") -> LoopStartRequest:
    return LoopStartRequest(
        run_id=run_id,
        task_id="task.langgraph_adapter",
        mechanism_family="adapter_fixture",
    )


def test_installed_langgraph_characterization_is_frozen_and_content_addressed() -> None:
    report = characterize_installed_langgraph()

    assert report.langgraph_version == EXPECTED_LANGGRAPH_VERSION
    assert report.langchain_core_version == EXPECTED_LANGCHAIN_CORE_VERSION
    assert report.report_hash == EXPECTED_CHARACTERIZATION_HASH
    assert report.all_passed is True
    loaded = LangGraphCharacterizationReport.model_validate_json(report.model_dump_json())
    assert loaded == report
    assert loaded.calculated_hash() == loaded.report_hash


def test_adapter_static_interrupt_does_not_run_domain_until_resumed(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    adapter = LangGraphControlAdapter(
        runtime=runtime,
        interrupt_before_drive=True,
    )

    paused = adapter.start(_request(), thread_id="thread.static_interrupt")
    checkpoint = adapter.checkpoint_state(thread_id="thread.static_interrupt")

    assert "loop_snapshot" not in paused
    assert tuple(checkpoint.next) == ("drive",)
    assert runtime.journal.snapshot().events == []

    continued = adapter.continue_from_checkpoint(thread_id="thread.static_interrupt")
    snapshot = adapter_snapshot(continued)
    assert snapshot.state.status == LoopRunStatus.SUCCEEDED
    assert snapshot.seal_hash is not None
    json.loads(json.dumps(dict(checkpoint.values), sort_keys=True))


def test_adapter_submits_domain_resume_without_replacing_journal_state(
    tmp_path: Path,
) -> None:
    run_id = "run.langgraph_resume"
    runtime = _runtime(
        tmp_path,
        interrupt_after=True,
        run_id=run_id,
    )
    adapter = LangGraphControlAdapter(runtime=runtime)

    first = adapter_snapshot(
        adapter.start(
            _request(run_id),
            thread_id="thread.domain_resume",
        )
    )
    assert first.state.status == LoopRunStatus.PAUSED
    assert first.seal_hash is None

    resumed = adapter_snapshot(adapter.resume(thread_id="thread.domain_resume"))
    canonical = runtime.snapshot()
    assert resumed.state.status == LoopRunStatus.SUCCEEDED
    assert resumed.snapshot_hash == canonical.snapshot_hash
    assert resumed.lineage_hash == canonical.lineage_hash


def test_adapter_snapshot_rejects_missing_domain_state() -> None:
    with pytest.raises(ValueError, match="no loop snapshot"):
        adapter_snapshot({"operation": "start"})
