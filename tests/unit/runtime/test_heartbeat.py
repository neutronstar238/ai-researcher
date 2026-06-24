import json
from datetime import datetime, timezone
from pathlib import Path

from autoresearch.runtime import (
    HEARTBEAT_EVIDENCE_POLICY,
    RuntimeHeartbeatAction,
    RuntimeHeartbeatStatus,
    evaluate_runtime_heartbeats,
    load_runtime_heartbeats,
    write_runtime_heartbeat,
    write_runtime_heartbeat_report,
)


def test_runtime_heartbeat_detects_stale_and_stalled_progress(tmp_path: Path) -> None:
    state = tmp_path / ".airesearcher" / "runtime-heartbeats.json"
    base = datetime(2026, 6, 23, 0, 0, 0, tzinfo=timezone.utc)

    for minute in range(3):
        write_runtime_heartbeat(
            state_path=state,
            run_id="cycle-1",
            stage="research-plan",
            progress="same-plan-draft",
            emitted_at=base.replace(minute=minute),
            message=f"draft attempt {minute}",
            artifact_refs=["runs/cycle-1/research-plan.md"],
        )
    write_runtime_heartbeat(
        state_path=state,
        run_id="cycle-1",
        stage="experiment",
        progress="started-baseline",
        emitted_at=base,
    )

    report = evaluate_runtime_heartbeats(
        state_path=state,
        checked_at=base.replace(minute=5),
        stale_after_seconds=240,
        stall_repetition_threshold=3,
    )

    by_stage = {stage.stage: stage for stage in report.stages}
    assert report.passed is False
    assert by_stage["research_plan"].status is RuntimeHeartbeatStatus.STALLED
    assert by_stage["research_plan"].action is RuntimeHeartbeatAction.REPAIR_OR_PIVOT
    assert by_stage["research_plan"].repeated_progress_count == 3
    assert by_stage["experiment"].status is RuntimeHeartbeatStatus.STALE
    assert by_stage["experiment"].action is RuntimeHeartbeatAction.INSPECT
    assert "cannot support scientific results" in report.evidence_policy


def test_runtime_heartbeat_history_is_bounded_and_report_is_json(
    tmp_path: Path,
) -> None:
    state = tmp_path / ".airesearcher" / "runtime-heartbeats.json"
    report_path = tmp_path / "reports" / "runtime-heartbeat-report.json"
    base = datetime(2026, 6, 23, 0, 0, 0, tzinfo=timezone.utc)

    for minute in range(3):
        write_runtime_heartbeat(
            state_path=state,
            run_id="cycle-1",
            stage="literature",
            progress=f"query-batch-{minute}",
            emitted_at=base.replace(minute=minute),
            history_limit=2,
        )

    events = load_runtime_heartbeats(state)
    report = evaluate_runtime_heartbeats(
        state_path=state,
        checked_at=base.replace(minute=3),
        stale_after_seconds=999,
    )
    written = write_runtime_heartbeat_report(report, report_path)
    payload = json.loads(written.read_text(encoding="utf-8"))

    assert len(events) == 2
    assert [event.progress_signature for event in events] == ["query-batch-1", "query-batch-2"]
    assert report.passed is True
    assert payload["passed"] is True
    assert payload["evidence_policy"] == HEARTBEAT_EVIDENCE_POLICY


def test_runtime_heartbeat_check_can_filter_one_run_id(tmp_path: Path) -> None:
    state = tmp_path / ".airesearcher" / "runtime-heartbeats.json"
    base = datetime(2026, 6, 23, 0, 0, 0, tzinfo=timezone.utc)

    write_runtime_heartbeat(
        state_path=state,
        run_id="cycle-old",
        stage="literature",
        progress="old-progress",
        emitted_at=base,
    )
    write_runtime_heartbeat(
        state_path=state,
        run_id="cycle-current",
        stage="literature",
        progress="fresh-progress",
        emitted_at=base.replace(minute=9, second=30),
    )

    all_runs = evaluate_runtime_heartbeats(
        state_path=state,
        checked_at=base.replace(minute=10),
        stale_after_seconds=60,
    )
    current_only = evaluate_runtime_heartbeats(
        state_path=state,
        run_id="cycle-current",
        checked_at=base.replace(minute=10),
        stale_after_seconds=60,
    )

    assert all_runs.passed is False
    assert all_runs.stale_count == 1
    assert current_only.passed is True
    assert current_only.event_count == 1
    assert current_only.stage_count == 1
    assert current_only.stages[0].run_id == "cycle-current"
