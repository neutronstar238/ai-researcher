"""Tests for atomic append, recovery, replay, and fork journal semantics."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from autoresearch.kernel import (
    TERMINAL_EVENT_STATUSES,
    ActorKind,
    ConcurrentWriteError,
    EventActor,
    EventJournal,
    EventStatus,
    ForkPolicyError,
    IdempotencyConflictError,
    JournalAlreadyExistsError,
    JournalCorruptionError,
    JournalError,
    JournalNotFoundError,
    JournalRecoveryRequired,
    RunEvent,
    SensitiveContentError,
    StaleWriterError,
    TerminalJournalError,
    WriterLease,
    calculate_lineage_hash,
)

BASE_TIME = datetime(2026, 7, 28, 7, 0, tzinfo=timezone.utc)


class SimulatedCrash(RuntimeError):
    """Fault injected at a named durability boundary."""


class FailOnce:
    """Raise once when the journal reaches one named fault point."""

    def __init__(self, point: str) -> None:
        self.point = point
        self.triggered = False

    def __call__(self, point: str) -> None:
        if point == self.point and not self.triggered:
            self.triggered = True
            raise SimulatedCrash(point)


def _actor() -> EventActor:
    return EventActor(
        actor_id="policy.journal",
        kind=ActorKind.DETERMINISTIC_POLICY,
        version="1",
    )


def _next_event(
    journal: EventJournal,
    *,
    status: EventStatus = EventStatus.STARTED,
    label: str | None = None,
    payload: dict[str, object] | None = None,
    action: str | None = None,
    idempotency_key: str | None = None,
    event_id: str | None = None,
    run_id: str | None = None,
    sequence: int | None = None,
    parent_event_id: str | None = None,
    parent_event_hash: str | None = None,
    parent_run_id: str | None = None,
) -> RunEvent:
    snapshot = journal.snapshot(require_complete_terminal=False)
    actual_sequence = sequence or len(snapshot.events) + 1
    event_label = label or f"event_{actual_sequence}"
    if snapshot.events:
        parent = snapshot.events[-1]
        default_parent_id = parent.event_id
        default_parent_hash = parent.event_hash
        default_parent_run_id = None
    elif journal.metadata.fork_anchor is not None:
        anchor = journal.metadata.fork_anchor
        default_parent_id = anchor.checkpoint_event_id
        default_parent_hash = anchor.checkpoint_event_hash
        default_parent_run_id = anchor.parent_run_id
    else:
        default_parent_id = None
        default_parent_hash = None
        default_parent_run_id = None

    return RunEvent.create(
        event_id=event_id or f"evt_{journal.metadata.run_id}_{event_label}",
        run_id=run_id or journal.metadata.run_id,
        task_id="262.3",
        sequence=actual_sequence,
        occurred_at=BASE_TIME + timedelta(seconds=actual_sequence),
        actor=_actor(),
        event_type="journal.test",
        status=status,
        action=action or f"Record {event_label}",
        parent_event_id=(
            parent_event_id if parent_event_id is not None else default_parent_id
        ),
        parent_event_hash=(
            parent_event_hash if parent_event_hash is not None else default_parent_hash
        ),
        parent_run_id=parent_run_id if parent_run_id is not None else default_parent_run_id,
        input_artifact_ids=[f"input_{event_label}"],
        output_artifact_ids=[f"output_{event_label}"],
        idempotency_key=idempotency_key or f"{journal.metadata.run_id}:{event_label}",
        payload=payload or {"label": event_label},
    )


def _append_two_event_terminal_run(journal: EventJournal) -> tuple[RunEvent, RunEvent]:
    first = _next_event(journal, label="start")
    journal.append(first)
    terminal = _next_event(
        journal,
        label="complete",
        status=EventStatus.SUCCEEDED,
    )
    journal.append(terminal)
    return first, terminal


def test_create_open_and_empty_lineage_are_deterministic(tmp_path: Path) -> None:
    root = tmp_path / "journal"
    journal = EventJournal.create(root, run_id="run_empty", created_at=BASE_TIME)

    snapshot = journal.snapshot()
    reopened = EventJournal.open(root)

    assert snapshot.events == []
    assert snapshot.seal is None
    assert snapshot.lineage_hash == calculate_lineage_hash("run_empty", [])
    assert reopened.metadata == journal.metadata
    assert reopened.snapshot() == snapshot
    assert (root / "metadata.json").read_text(encoding="utf-8").endswith("\n")


def test_create_rejects_existing_path_and_open_rejects_missing_metadata(
    tmp_path: Path,
) -> None:
    root = tmp_path / "existing"
    EventJournal.create(root, run_id="run_existing", created_at=BASE_TIME)

    with pytest.raises(JournalAlreadyExistsError, match="already exists"):
        EventJournal.create(root, run_id="run_other", created_at=BASE_TIME)

    with pytest.raises(JournalNotFoundError, match="metadata not found"):
        EventJournal.open(tmp_path / "missing")


def test_append_builds_contiguous_chain_and_terminal_seal(tmp_path: Path) -> None:
    journal = EventJournal.create(
        tmp_path / "chain",
        run_id="run_chain",
        created_at=BASE_TIME,
    )
    first = _next_event(journal, label="start")
    first_result = journal.append(
        first,
        expected_lineage_hash=journal.snapshot().lineage_hash,
    )
    terminal = _next_event(
        journal,
        label="negative",
        status=EventStatus.NEGATIVE_RESULT,
    )
    terminal_result = journal.append(
        terminal,
        expected_lineage_hash=first_result.lineage_hash,
    )
    snapshot = journal.snapshot()

    assert first_result.reused is False
    assert terminal_result.sealed is True
    assert [event.sequence for event in snapshot.events] == [1, 2]
    assert snapshot.events[1].parent_event_hash == snapshot.events[0].event_hash
    assert snapshot.seal is not None
    assert snapshot.seal.lineage_hash == snapshot.lineage_hash
    assert snapshot.seal.terminal_status == EventStatus.NEGATIVE_RESULT
    assert sorted(path.name for path in journal.events_dir.iterdir()) == [
        "0000000001.json",
        "0000000002.json",
    ]

    with pytest.raises(TerminalJournalError, match="already terminal"):
        journal.append(_next_event(journal, label="too_late"))


def test_idempotent_retry_reuses_exact_event_and_rejects_changed_content(
    tmp_path: Path,
) -> None:
    journal = EventJournal.create(
        tmp_path / "idempotent",
        run_id="run_idempotent",
        created_at=BASE_TIME,
    )
    event = _next_event(journal, label="start")

    first = journal.append(event)
    retry = journal.append(event, expected_lineage_hash=calculate_lineage_hash("wrong", []))
    changed = RunEvent.create(
        event_id="evt_changed",
        run_id=journal.metadata.run_id,
        task_id="262.3",
        sequence=1,
        occurred_at=BASE_TIME + timedelta(seconds=1),
        actor=_actor(),
        event_type="journal.test",
        status=EventStatus.STARTED,
        action="Changed first event",
        idempotency_key=event.idempotency_key,
        payload={"label": "changed"},
    )

    assert first.reused is False
    assert retry.reused is True
    assert retry.event_count == 1
    with pytest.raises(IdempotencyConflictError, match="already belongs"):
        journal.append(changed)


def test_stale_expected_lineage_and_sequence_are_rejected(tmp_path: Path) -> None:
    journal = EventJournal.create(
        tmp_path / "stale",
        run_id="run_stale",
        created_at=BASE_TIME,
    )
    empty_lineage = journal.snapshot().lineage_hash
    journal.append(_next_event(journal, label="start"))
    second = _next_event(journal, label="second")

    with pytest.raises(StaleWriterError, match="expected lineage"):
        journal.append(second, expected_lineage_hash=empty_lineage)

    skipped = _next_event(
        journal,
        label="skipped",
        sequence=3,
        parent_event_id=journal.snapshot().events[-1].event_id,
        parent_event_hash=journal.snapshot().events[-1].event_hash,
    )
    with pytest.raises(StaleWriterError, match="expected event sequence 2"):
        journal.append(skipped)


def test_append_rejects_wrong_run_parent_and_duplicate_event_id(tmp_path: Path) -> None:
    journal = EventJournal.create(
        tmp_path / "invalid_append",
        run_id="run_append",
        created_at=BASE_TIME,
    )
    first = _next_event(journal, label="start")
    journal.append(first)

    wrong_run = _next_event(journal, label="wrong_run", run_id="run_other")
    with pytest.raises(JournalError, match="does not match journal run"):
        journal.append(wrong_run)

    wrong_parent = _next_event(
        journal,
        label="wrong_parent",
        parent_event_id="evt_missing",
        parent_event_hash="b" * 64,
    )
    with pytest.raises(JournalError, match="parent ID does not match"):
        journal.append(wrong_parent)

    duplicate_id = _next_event(
        journal,
        label="duplicate_id",
        event_id=first.event_id,
    )
    with pytest.raises(JournalError, match="duplicate event_id"):
        journal.append(duplicate_id)


@pytest.mark.parametrize(
    ("payload", "action", "message"),
    [
        ({"api_key": "not-persisted"}, None, "sensitive field"),
        ({"nested": {"email": "person@example.org"}}, None, "sensitive field"),
        ({"note": "Contact person@example.org"}, None, "direct email identifier"),
        ({}, "Use Bearer abcdefghijklmnop", "bearer credential"),
        ({"credential": "sk-proj-abcdefghijklmnop"}, None, "API-key-like"),
        (
            {"credential": "-----BEGIN PRIVATE KEY-----\nvalue"},
            None,
            "private key",
        ),
    ],
)
def test_append_rejects_secrets_and_direct_identifiers(
    tmp_path: Path,
    payload: dict[str, object],
    action: str | None,
    message: str,
) -> None:
    journal = EventJournal.create(
        tmp_path / f"sensitive_{abs(hash(message))}",
        run_id=f"run_sensitive_{abs(hash(message))}",
        created_at=BASE_TIME,
    )
    event = _next_event(journal, payload=payload, action=action)

    with pytest.raises(SensitiveContentError, match=message):
        journal.append(event)
    assert journal.snapshot().events == []


def test_sensitive_scan_covers_the_full_event_envelope(tmp_path: Path) -> None:
    journal = EventJournal.create(
        tmp_path / "sensitive_envelope",
        run_id="run_sensitive_envelope",
        created_at=BASE_TIME,
    )
    event = _next_event(journal, idempotency_key="person@example.org")

    with pytest.raises(SensitiveContentError, match="direct email identifier"):
        journal.append(event)
    assert journal.snapshot().events == []


def test_non_sensitive_token_metrics_are_allowed(tmp_path: Path) -> None:
    journal = EventJournal.create(
        tmp_path / "token_metrics",
        run_id="run_token_metrics",
        created_at=BASE_TIME,
    )
    event = _next_event(
        journal,
        payload={"token_count": 128, "cost": 0.0},
    )

    result = journal.append(event)

    assert result.event.payload["token_count"] == 128


def test_active_writer_lease_blocks_read_write_and_unsafe_break(
    tmp_path: Path,
) -> None:
    journal = EventJournal.create(
        tmp_path / "active_lock",
        run_id="run_active_lock",
        created_at=BASE_TIME,
    )
    lease = WriterLease(
        pid=os.getpid(),
        token="lease_active",
        created_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    journal.lock_path.write_text(lease.canonical_json() + "\n", encoding="utf-8")

    with pytest.raises(ConcurrentWriteError, match="writer lease is active"):
        journal.snapshot()
    with pytest.raises(ConcurrentWriteError, match="writer lease is active"):
        journal.append(_next_event_without_snapshot(journal))
    with pytest.raises(ConcurrentWriteError, match="still alive"):
        journal.break_stale_writer(minimum_age=timedelta(0))


def _next_event_without_snapshot(journal: EventJournal) -> RunEvent:
    return RunEvent.create(
        event_id=f"evt_{journal.metadata.run_id}_manual",
        run_id=journal.metadata.run_id,
        task_id="262.3",
        sequence=1,
        occurred_at=BASE_TIME + timedelta(seconds=1),
        actor=_actor(),
        event_type="journal.test",
        status=EventStatus.STARTED,
        action="Manual first event",
        idempotency_key=f"{journal.metadata.run_id}:manual",
        payload={"label": "manual"},
    )


def test_explicit_recovery_breaks_only_a_dead_old_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = EventJournal.create(
        tmp_path / "stale_lock",
        run_id="run_stale_lock",
        created_at=BASE_TIME,
    )
    lease = WriterLease(
        pid=999999,
        token="lease_stale",
        created_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    journal.lock_path.write_text(lease.canonical_json() + "\n", encoding="utf-8")
    monkeypatch.setattr("autoresearch.kernel.journal._process_is_alive", lambda _pid: False)

    with pytest.raises(ConcurrentWriteError, match="below the recovery threshold"):
        journal.break_stale_writer(minimum_age=timedelta(days=3650))

    recovery = journal.recover(
        break_stale_lock=True,
        minimum_stale_age=timedelta(0),
    )

    assert recovery.snapshot.events == []
    assert not journal.lock_path.exists()


def test_fault_after_pending_write_discards_uncommitted_file_on_retry(
    tmp_path: Path,
) -> None:
    root = tmp_path / "pending_crash"
    journal = EventJournal.create(
        root,
        run_id="run_pending_crash",
        created_at=BASE_TIME,
        fault_injector=FailOnce("after_pending_write"),
    )
    event = _next_event(journal)

    with pytest.raises(SimulatedCrash, match="after_pending_write"):
        journal.append(event)

    assert list(journal.events_dir.iterdir()) == []
    assert len(list(journal.pending_dir.iterdir())) == 1
    assert not journal.lock_path.exists()

    reopened = EventJournal.open(root)
    result = reopened.append(event)

    assert result.reused is False
    assert len(reopened.snapshot().events) == 1
    assert list(reopened.pending_dir.iterdir()) == []


def test_fault_after_event_commit_is_recovered_by_idempotent_retry(
    tmp_path: Path,
) -> None:
    root = tmp_path / "commit_crash"
    journal = EventJournal.create(
        root,
        run_id="run_commit_crash",
        created_at=BASE_TIME,
        fault_injector=FailOnce("after_event_commit"),
    )
    event = _next_event(journal)

    with pytest.raises(SimulatedCrash, match="after_event_commit"):
        journal.append(event)

    reopened = EventJournal.open(root)
    assert reopened.snapshot().events == [event]
    retry = reopened.append(event)

    assert retry.reused is True
    assert retry.event_count == 1


def test_terminal_event_commit_without_seal_requires_and_supports_recovery(
    tmp_path: Path,
) -> None:
    root = tmp_path / "terminal_crash"
    journal = EventJournal.create(
        root,
        run_id="run_terminal_crash",
        created_at=BASE_TIME,
    )
    journal.append(_next_event(journal, label="start"))
    terminal = _next_event(
        journal,
        label="complete",
        status=EventStatus.SUCCEEDED,
    )
    journal.fault_injector = FailOnce("after_event_commit")

    with pytest.raises(SimulatedCrash, match="after_event_commit"):
        journal.append(terminal)

    reopened = EventJournal.open(root)
    with pytest.raises(JournalRecoveryRequired, match="missing its seal"):
        reopened.snapshot()
    assert reopened.snapshot(require_complete_terminal=False).recovery_required is True

    recovery = reopened.recover()
    retry = reopened.append(terminal)

    assert recovery.terminal_seal_rebuilt is True
    assert recovery.snapshot.seal is not None
    assert retry.reused is True
    assert retry.sealed is True


def test_recover_reports_discarded_pending_file(tmp_path: Path) -> None:
    root = tmp_path / "recover_pending"
    journal = EventJournal.create(
        root,
        run_id="run_recover_pending",
        created_at=BASE_TIME,
        fault_injector=FailOnce("after_pending_write"),
    )
    with pytest.raises(SimulatedCrash):
        journal.append(_next_event(journal))

    reopened = EventJournal.open(root)
    recovery = reopened.recover()

    assert recovery.discarded_pending_files == 1
    assert recovery.terminal_seal_rebuilt is False
    assert recovery.snapshot.events == []


@pytest.mark.parametrize("tamper_mode", ["format", "semantic", "partial"])
def test_committed_event_corruption_fails_closed(
    tmp_path: Path,
    tamper_mode: str,
) -> None:
    journal = EventJournal.create(
        tmp_path / f"corrupt_{tamper_mode}",
        run_id=f"run_corrupt_{tamper_mode}",
        created_at=BASE_TIME,
    )
    journal.append(_next_event(journal))
    event_path = journal.events_dir / "0000000001.json"
    original = event_path.read_text(encoding="utf-8")

    if tamper_mode == "format":
        event_path.write_text(" " + original, encoding="utf-8")
    elif tamper_mode == "semantic":
        payload = json.loads(original)
        payload["action"] = "Tampered"
        event_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    else:
        event_path.write_text('{"event_id":', encoding="utf-8")

    with pytest.raises(JournalCorruptionError):
        journal.snapshot()


def test_event_filename_gap_and_unexpected_entry_fail_closed(tmp_path: Path) -> None:
    gap_journal = EventJournal.create(
        tmp_path / "gap",
        run_id="run_gap",
        created_at=BASE_TIME,
    )
    gap_journal.append(_next_event(gap_journal))
    (gap_journal.events_dir / "0000000001.json").rename(
        gap_journal.events_dir / "0000000002.json"
    )
    with pytest.raises(JournalCorruptionError, match="sequence gap"):
        gap_journal.snapshot()

    extra_journal = EventJournal.create(
        tmp_path / "extra",
        run_id="run_extra",
        created_at=BASE_TIME,
    )
    (extra_journal.events_dir / "notes.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(JournalCorruptionError, match="unexpected event filename"):
        extra_journal.snapshot()


def test_metadata_and_terminal_seal_tampering_fail_closed(tmp_path: Path) -> None:
    metadata_journal = EventJournal.create(
        tmp_path / "metadata_tamper",
        run_id="run_metadata_tamper",
        created_at=BASE_TIME,
    )
    metadata_path = metadata_journal.root / "metadata.json"
    metadata_path.write_text(" " + metadata_path.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(JournalCorruptionError, match="not canonical"):
        EventJournal.open(metadata_journal.root)

    seal_journal = EventJournal.create(
        tmp_path / "seal_tamper",
        run_id="run_seal_tamper",
        created_at=BASE_TIME,
    )
    _append_two_event_terminal_run(seal_journal)
    seal_payload = json.loads(seal_journal.seal_path.read_text(encoding="utf-8"))
    seal_payload["event_count"] = 99
    seal_journal.seal_path.write_text(
        json.dumps(seal_payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(JournalCorruptionError, match="invalid terminal-seal"):
        seal_journal.snapshot()


def test_replay_and_checkpoint_use_validated_prefix_lineage(tmp_path: Path) -> None:
    journal = EventJournal.create(
        tmp_path / "replay",
        run_id="run_replay",
        created_at=BASE_TIME,
    )
    journal.append(_next_event(journal, label="start"))
    journal.append(
        _next_event(
            journal,
            label="pause",
            status=EventStatus.PAUSED,
        )
    )
    journal.append(
        _next_event(
            journal,
            label="complete",
            status=EventStatus.SUCCEEDED,
        )
    )

    checkpoint = journal.checkpoint(2)
    labels = journal.replay(
        initial=[],
        reducer=lambda state, event: [*state, str(event.payload["label"])],
        through_sequence=2,
    )
    empty = journal.replay(
        initial=["initial"],
        reducer=lambda state, event: [*state, event.event_id],
        through_sequence=0,
    )

    assert checkpoint.sequence == 2
    assert checkpoint.terminal is False
    assert checkpoint.lineage_hash == calculate_lineage_hash(
        "run_replay",
        journal.snapshot().events[:2],
    )
    assert labels == ["start", "pause"]
    assert empty == ["initial"]
    with pytest.raises(JournalError, match="outside 0..3"):
        journal.replay(initial=[], reducer=lambda state, _event: state, through_sequence=4)
    with pytest.raises(JournalError, match="outside 1..3"):
        journal.checkpoint(0)


def test_terminal_checkpoint_fork_binds_child_first_event_and_preserves_parent(
    tmp_path: Path,
) -> None:
    parent = EventJournal.create(
        tmp_path / "parent",
        run_id="run_parent",
        created_at=BASE_TIME,
    )
    _append_two_event_terminal_run(parent)
    parent_snapshot = parent.snapshot()

    child = EventJournal.fork_from(
        parent,
        tmp_path / "child",
        run_id="run_child",
        checkpoint_sequence=2,
        created_at=BASE_TIME + timedelta(minutes=1),
    )
    child_event = _next_event(child, label="fork_start")
    result = child.append(child_event)

    assert child.metadata.fork_anchor is not None
    assert child.metadata.fork_anchor.parent_run_id == "run_parent"
    assert child_event.parent_event_id == parent_snapshot.events[-1].event_id
    assert child_event.parent_event_hash == parent_snapshot.events[-1].event_hash
    assert result.event_count == 1
    assert parent.snapshot() == parent_snapshot
    assert child.snapshot().lineage_hash != parent_snapshot.lineage_hash


def test_non_terminal_fork_requires_explicit_policy(tmp_path: Path) -> None:
    parent = EventJournal.create(
        tmp_path / "nonterminal_parent",
        run_id="run_nonterminal_parent",
        created_at=BASE_TIME,
    )
    parent.append(_next_event(parent, label="start"))

    with pytest.raises(ForkPolicyError, match="allow_non_terminal=True"):
        EventJournal.fork_from(
            parent,
            tmp_path / "blocked_child",
            run_id="run_blocked_child",
            checkpoint_sequence=1,
        )

    child = EventJournal.fork_from(
        parent,
        tmp_path / "approved_child",
        run_id="run_approved_child",
        checkpoint_sequence=1,
        allow_non_terminal=True,
        created_at=BASE_TIME + timedelta(minutes=1),
    )

    assert child.metadata.fork_anchor is not None
    assert child.metadata.fork_anchor.non_terminal_fork_approved is True
    child.append(_next_event(child, label="approved_fork"))


def test_fork_rejects_first_event_that_does_not_match_anchor(tmp_path: Path) -> None:
    parent = EventJournal.create(
        tmp_path / "anchor_parent",
        run_id="run_anchor_parent",
        created_at=BASE_TIME,
    )
    _append_two_event_terminal_run(parent)
    child = EventJournal.fork_from(
        parent,
        tmp_path / "anchor_child",
        run_id="run_anchor_child",
        checkpoint_sequence=2,
        created_at=BASE_TIME + timedelta(minutes=1),
    )
    anchor = child.metadata.fork_anchor
    assert anchor is not None
    wrong = _next_event(
        child,
        label="wrong_anchor",
        parent_event_id="evt_wrong",
        parent_event_hash="c" * 64,
        parent_run_id=anchor.parent_run_id,
    )

    with pytest.raises(ForkPolicyError, match="parent_event_id"):
        child.append(wrong)
    assert child.snapshot().events == []


def test_fork_target_path_must_be_new(tmp_path: Path) -> None:
    parent = EventJournal.create(
        tmp_path / "target_parent",
        run_id="run_target_parent",
        created_at=BASE_TIME,
    )
    _append_two_event_terminal_run(parent)
    target = tmp_path / "existing_target"
    target.mkdir()

    with pytest.raises(JournalAlreadyExistsError):
        EventJournal.fork_from(
            parent,
            target,
            run_id="run_target_child",
            checkpoint_sequence=2,
        )


def test_fork_requires_a_distinct_child_run_id(tmp_path: Path) -> None:
    parent = EventJournal.create(
        tmp_path / "same_run_parent",
        run_id="run_same",
        created_at=BASE_TIME,
    )
    _append_two_event_terminal_run(parent)

    with pytest.raises(ForkPolicyError, match="must differ"):
        EventJournal.fork_from(
            parent,
            tmp_path / "same_run_child",
            run_id=parent.metadata.run_id,
            checkpoint_sequence=2,
        )


def test_unexpected_pending_entry_fails_recovery(tmp_path: Path) -> None:
    journal = EventJournal.create(
        tmp_path / "pending_entry",
        run_id="run_pending_entry",
        created_at=BASE_TIME,
    )
    (journal.pending_dir / "unexpected.txt").write_text("not a temp event", encoding="utf-8")

    with pytest.raises(JournalCorruptionError, match="unexpected pending entry"):
        journal.recover()


@settings(max_examples=25, deadline=None)
@given(
    statuses=st.lists(
        st.sampled_from(
            [
                EventStatus.STARTED,
                EventStatus.PAUSED,
                EventStatus.APPROVED,
            ]
        ),
        min_size=1,
        max_size=8,
    ),
    terminal_status=st.one_of(
        st.none(),
        st.sampled_from(sorted(TERMINAL_EVENT_STATUSES, key=lambda item: item.value)),
    ),
)
def test_property_append_replay_checkpoint_and_reopen_are_deterministic(
    statuses: list[EventStatus],
    terminal_status: EventStatus | None,
) -> None:
    with TemporaryDirectory() as temp_directory:
        journal = EventJournal.create(
            Path(temp_directory) / "journal",
            run_id="run_property",
            created_at=BASE_TIME,
        )
        appended: list[RunEvent] = []
        for index, status in enumerate(statuses, start=1):
            event = _next_event(
                journal,
                label=f"step_{index}",
                status=status,
            )
            journal.append(event)
            appended.append(event)
        if terminal_status is not None:
            terminal = _next_event(
                journal,
                label="terminal",
                status=terminal_status,
            )
            journal.append(terminal)
            appended.append(terminal)

        retry = journal.append(appended[0])
        reopened = EventJournal.open(journal.root)
        snapshot = reopened.snapshot()
        replayed_ids = reopened.replay(
            initial=(),
            reducer=lambda state, event: (*state, event.event_id),
        )

        assert retry.reused is True
        assert snapshot.events == appended
        assert [event.sequence for event in snapshot.events] == list(
            range(1, len(appended) + 1)
        )
        assert snapshot.lineage_hash == calculate_lineage_hash(
            journal.metadata.run_id,
            appended,
        )
        assert replayed_ids == tuple(event.event_id for event in appended)
        assert (snapshot.seal is not None) is (terminal_status is not None)
        for sequence in range(1, len(appended) + 1):
            checkpoint = reopened.checkpoint(sequence)
            assert checkpoint.event == appended[sequence - 1]
            assert checkpoint.lineage_hash == calculate_lineage_hash(
                journal.metadata.run_id,
                appended[:sequence],
            )
