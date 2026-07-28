"""Atomic append-only event journal, integrity replay, and lineage forks."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, TypeVar
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from .contracts import (
    EventStatus,
    KernelContract,
    RunEvent,
    Sha256,
    StableId,
    canonical_json,
    canonical_sha256,
)

_EVENT_FILE_PATTERN = re.compile(r"^(?P<sequence>[0-9]{10})\.json$")
_EMAIL_PATTERN = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_BEARER_PATTERN = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE)
_API_KEY_PATTERN = re.compile(r"\b(?:sk|rk|pk)[-_][A-Za-z0-9_-]{16,}\b")
_PRIVATE_KEY_PATTERN = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
_SENSITIVE_KEYS = {
    "address",
    "api_key",
    "apikey",
    "authorization",
    "bank_account",
    "card_number",
    "client_secret",
    "contact",
    "cookie",
    "credit_card",
    "email",
    "access_token",
    "auth_token",
    "id_token",
    "passport_number",
    "passwd",
    "password",
    "phone",
    "private_key",
    "refresh_token",
    "secret",
    "social_security_number",
    "ssn",
    "telephone",
}

TERMINAL_EVENT_STATUSES = frozenset(
    {
        EventStatus.SUCCEEDED,
        EventStatus.FAILED,
        EventStatus.BLOCKED,
        EventStatus.NEGATIVE_RESULT,
        EventStatus.REJECTED,
        EventStatus.CANCELLED,
    }
)

ReplayState = TypeVar("ReplayState")
ModelT = TypeVar("ModelT", bound=BaseModel)


class JournalError(RuntimeError):
    """Base class for fail-closed event journal errors."""


class JournalAlreadyExistsError(JournalError):
    """Raised when journal creation would reuse an existing path."""


class JournalNotFoundError(JournalError):
    """Raised when the requested journal metadata does not exist."""


class JournalCorruptionError(JournalError):
    """Raised when committed bytes, hashes, filenames, or chains are invalid."""


class ConcurrentWriteError(JournalError):
    """Raised when another writer owns the journal lease."""


class StaleWriterError(JournalError):
    """Raised when a caller's expected lineage no longer matches the journal."""


class IdempotencyConflictError(JournalError):
    """Raised when an idempotency key is reused for different event content."""


class TerminalJournalError(JournalError):
    """Raised when a new event targets a terminally sealed journal."""


class JournalRecoveryRequired(JournalError):
    """Raised when a committed terminal event is missing its terminal seal."""


class ForkPolicyError(JournalError):
    """Raised when a fork violates its frozen checkpoint policy."""


class SensitiveContentError(JournalError):
    """Raised when an event attempts to persist a secret or direct identifier."""


class ForkAnchor(KernelContract):
    """Immutable reference from a new run to one parent checkpoint."""

    parent_run_id: StableId
    checkpoint_sequence: int = Field(ge=1)
    checkpoint_event_id: StableId
    checkpoint_event_hash: Sha256
    checkpoint_lineage_hash: Sha256
    non_terminal_fork_approved: bool = False


class _JournalMetadataContent(KernelContract):
    schema_version: Literal[1] = 1
    run_id: StableId
    created_at: datetime
    fork_anchor: ForkAnchor | None = None

    @model_validator(mode="after")
    def _require_utc(self) -> _JournalMetadataContent:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() != timedelta(0):
            raise ValueError("created_at must be timezone-aware UTC")
        self.created_at = self.created_at.astimezone(timezone.utc)
        return self


class JournalMetadata(_JournalMetadataContent):
    """Content-addressed identity and optional fork origin for one journal."""

    metadata_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> JournalMetadata:
        expected = self.calculated_hash()
        if self.metadata_hash != expected:
            raise ValueError(
                f"metadata_hash mismatch for run {self.run_id}: "
                f"expected {expected}, got {self.metadata_hash}"
            )
        return self

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        created_at: datetime,
        fork_anchor: ForkAnchor | None = None,
    ) -> JournalMetadata:
        content = _JournalMetadataContent(
            run_id=run_id,
            created_at=created_at,
            fork_anchor=fork_anchor,
        )
        payload = content.model_dump(mode="json")
        payload["metadata_hash"] = canonical_sha256(content)
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"metadata_hash"}))


class _JournalSealContent(KernelContract):
    schema_version: Literal[1] = 1
    run_id: StableId
    terminal_event_id: StableId
    terminal_event_hash: Sha256
    terminal_status: EventStatus
    event_count: int = Field(ge=1)
    lineage_hash: Sha256
    sealed_at: datetime

    @model_validator(mode="after")
    def _validate_terminal(self) -> _JournalSealContent:
        if self.terminal_status not in TERMINAL_EVENT_STATUSES:
            raise ValueError(f"{self.terminal_status.value} is not a terminal event status")
        if self.sealed_at.tzinfo is None or self.sealed_at.utcoffset() != timedelta(0):
            raise ValueError("sealed_at must be timezone-aware UTC")
        self.sealed_at = self.sealed_at.astimezone(timezone.utc)
        return self


class JournalSeal(_JournalSealContent):
    """Content-addressed terminal seal over one validated event lineage."""

    seal_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> JournalSeal:
        expected = self.calculated_hash()
        if self.seal_hash != expected:
            raise ValueError(
                f"seal_hash mismatch for run {self.run_id}: "
                f"expected {expected}, got {self.seal_hash}"
            )
        return self

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        terminal_event: RunEvent,
        event_count: int,
        lineage_hash: str,
    ) -> JournalSeal:
        content = _JournalSealContent(
            run_id=run_id,
            terminal_event_id=terminal_event.event_id,
            terminal_event_hash=terminal_event.event_hash,
            terminal_status=terminal_event.status,
            event_count=event_count,
            lineage_hash=lineage_hash,
            sealed_at=terminal_event.occurred_at,
        )
        payload = content.model_dump(mode="json")
        payload["seal_hash"] = canonical_sha256(content)
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"seal_hash"}))


class WriterLease(KernelContract):
    """Transient exclusive-writer identity used for crash-safe arbitration."""

    pid: int = Field(ge=1)
    token: StableId
    created_at: datetime

    @model_validator(mode="after")
    def _require_utc(self) -> WriterLease:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() != timedelta(0):
            raise ValueError("created_at must be timezone-aware UTC")
        self.created_at = self.created_at.astimezone(timezone.utc)
        return self


class JournalSnapshot(KernelContract):
    """Validated point-in-time view over committed event files and terminal seal."""

    metadata: JournalMetadata
    events: list[RunEvent] = Field(default_factory=list)
    lineage_hash: Sha256
    seal: JournalSeal | None = None

    @model_validator(mode="after")
    def _validate_snapshot(self) -> JournalSnapshot:
        _validate_event_chain(metadata=self.metadata, events=self.events)
        expected_lineage = calculate_lineage_hash(self.metadata.run_id, self.events)
        if self.lineage_hash != expected_lineage:
            raise ValueError(
                f"lineage_hash mismatch: expected {expected_lineage}, got {self.lineage_hash}"
            )
        _validate_terminal_seal(
            run_id=self.metadata.run_id,
            events=self.events,
            lineage_hash=self.lineage_hash,
            seal=self.seal,
        )
        return self

    @property
    def recovery_required(self) -> bool:
        """Whether a committed terminal event still needs its deterministic seal."""

        return bool(
            self.events
            and self.events[-1].status in TERMINAL_EVENT_STATUSES
            and self.seal is None
        )

    @property
    def is_terminal(self) -> bool:
        """Whether the event lineage has reached a terminal status."""

        return bool(self.events and self.events[-1].status in TERMINAL_EVENT_STATUSES)


class JournalCheckpoint(KernelContract):
    """Stable checkpoint identity for replay or a child-run fork."""

    run_id: StableId
    sequence: int = Field(ge=1)
    event: RunEvent
    lineage_hash: Sha256
    terminal: bool


class AppendResult(KernelContract):
    """Outcome of an append or idempotent append retry."""

    event: RunEvent
    reused: bool
    event_count: int = Field(ge=1)
    lineage_hash: Sha256
    sealed: bool


class RecoveryResult(KernelContract):
    """Actions and final state produced by an explicit journal recovery."""

    discarded_pending_files: int = Field(ge=0)
    terminal_seal_rebuilt: bool
    snapshot: JournalSnapshot


class EventJournal:
    """Directory-backed immutable event journal with one atomic file per event."""

    METADATA_FILE = "metadata.json"
    SEAL_FILE = "terminal-seal.json"
    LOCK_FILE = ".writer.lock"
    EVENTS_DIR = "events"
    PENDING_DIR = ".pending"

    def __init__(
        self,
        root: Path,
        metadata: JournalMetadata,
        *,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        self.root = root
        self.metadata = metadata
        self.fault_injector = fault_injector

    @classmethod
    def create(
        cls,
        root: str | Path,
        *,
        run_id: str,
        created_at: datetime | None = None,
        fault_injector: Callable[[str], None] | None = None,
    ) -> EventJournal:
        """Create a new journal without reusing or deleting an existing path."""

        return cls._create(
            root,
            run_id=run_id,
            created_at=created_at,
            fork_anchor=None,
            fault_injector=fault_injector,
        )

    @classmethod
    def _create(
        cls,
        root: str | Path,
        *,
        run_id: str,
        created_at: datetime | None,
        fork_anchor: ForkAnchor | None,
        fault_injector: Callable[[str], None] | None,
    ) -> EventJournal:
        root_path = Path(root)
        try:
            root_path.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise JournalAlreadyExistsError(f"journal path already exists: {root_path}") from exc

        events_dir = root_path / cls.EVENTS_DIR
        pending_dir = root_path / cls.PENDING_DIR
        events_dir.mkdir()
        pending_dir.mkdir()
        metadata = JournalMetadata.create(
            run_id=run_id,
            created_at=created_at or datetime.now(timezone.utc),
            fork_anchor=fork_anchor,
        )
        _atomic_write_text(
            root_path / cls.METADATA_FILE,
            metadata.canonical_json() + "\n",
        )
        return cls(root_path, metadata, fault_injector=fault_injector)

    @classmethod
    def open(
        cls,
        root: str | Path,
        *,
        fault_injector: Callable[[str], None] | None = None,
    ) -> EventJournal:
        """Open an existing journal after validating canonical metadata bytes."""

        root_path = Path(root)
        metadata_path = root_path / cls.METADATA_FILE
        if not metadata_path.is_file():
            raise JournalNotFoundError(f"journal metadata not found: {metadata_path}")
        metadata = _read_canonical_model(metadata_path, JournalMetadata)
        return cls(root_path, metadata, fault_injector=fault_injector)

    @classmethod
    def fork_from(
        cls,
        parent: EventJournal,
        root: str | Path,
        *,
        run_id: str,
        checkpoint_sequence: int,
        allow_non_terminal: bool = False,
        created_at: datetime | None = None,
        fault_injector: Callable[[str], None] | None = None,
    ) -> EventJournal:
        """Create an empty child journal anchored to one immutable parent checkpoint."""

        if run_id == parent.metadata.run_id:
            raise ForkPolicyError("child run_id must differ from the parent run_id")
        checkpoint = parent.checkpoint(checkpoint_sequence)
        if not checkpoint.terminal and not allow_non_terminal:
            raise ForkPolicyError(
                "non-terminal checkpoints require allow_non_terminal=True"
            )
        anchor = ForkAnchor(
            parent_run_id=checkpoint.run_id,
            checkpoint_sequence=checkpoint.sequence,
            checkpoint_event_id=checkpoint.event.event_id,
            checkpoint_event_hash=checkpoint.event.event_hash,
            checkpoint_lineage_hash=checkpoint.lineage_hash,
            non_terminal_fork_approved=allow_non_terminal,
        )
        return cls._create(
            root,
            run_id=run_id,
            created_at=created_at,
            fork_anchor=anchor,
            fault_injector=fault_injector,
        )

    def snapshot(self, *, require_complete_terminal: bool = True) -> JournalSnapshot:
        """Load and validate one consistent committed snapshot."""

        if self.lock_path.exists():
            raise ConcurrentWriteError(f"journal writer lease is active: {self.lock_path}")
        return self._load_snapshot(require_complete_terminal=require_complete_terminal)

    def append(
        self,
        event: RunEvent,
        *,
        expected_lineage_hash: str | None = None,
    ) -> AppendResult:
        """Atomically append one event or return its prior idempotent result."""

        _reject_sensitive_event(event)
        with self._writer_lease():
            self._discard_pending_files()
            self._recover_terminal_seal_if_needed()
            snapshot = self._load_snapshot(require_complete_terminal=True)

            existing_by_key = {item.idempotency_key: item for item in snapshot.events}
            existing = existing_by_key.get(event.idempotency_key)
            if existing is not None:
                if existing.event_hash != event.event_hash:
                    raise IdempotencyConflictError(
                        f"idempotency key {event.idempotency_key} already belongs to "
                        f"event {existing.event_id}"
                    )
                return AppendResult(
                    event=existing,
                    reused=True,
                    event_count=len(snapshot.events),
                    lineage_hash=snapshot.lineage_hash,
                    sealed=snapshot.seal is not None,
                )

            if expected_lineage_hash is not None and (
                expected_lineage_hash != snapshot.lineage_hash
            ):
                raise StaleWriterError(
                    f"expected lineage {expected_lineage_hash}, "
                    f"found {snapshot.lineage_hash}"
                )
            if snapshot.is_terminal:
                raise TerminalJournalError(
                    f"run {self.metadata.run_id} is already terminal"
                )

            self._validate_append(event=event, snapshot=snapshot)
            pending_path = self.pending_dir / f"{event.sequence:010d}-{uuid4().hex}.tmp"
            _write_new_file(pending_path, event.canonical_json() + "\n")
            self._fault("after_pending_write")

            final_path = self._event_path(event.sequence)
            if final_path.exists():
                raise StaleWriterError(f"event sequence already exists: {event.sequence}")
            os.replace(pending_path, final_path)
            _fsync_directory(self.events_dir)
            self._fault("after_event_commit")

            events = [*snapshot.events, event]
            lineage_hash = calculate_lineage_hash(self.metadata.run_id, events)
            seal: JournalSeal | None = None
            if event.status in TERMINAL_EVENT_STATUSES:
                seal = JournalSeal.create(
                    run_id=self.metadata.run_id,
                    terminal_event=event,
                    event_count=len(events),
                    lineage_hash=lineage_hash,
                )
                _atomic_write_text(self.seal_path, seal.canonical_json() + "\n")
                self._fault("after_seal_commit")

            return AppendResult(
                event=event,
                reused=False,
                event_count=len(events),
                lineage_hash=lineage_hash,
                sealed=seal is not None,
            )

    def recover(
        self,
        *,
        break_stale_lock: bool = False,
        minimum_stale_age: timedelta = timedelta(seconds=30),
    ) -> RecoveryResult:
        """Discard uncommitted temp files and rebuild a missing deterministic seal."""

        if self.lock_path.exists():
            if not break_stale_lock:
                raise ConcurrentWriteError(f"journal writer lease is active: {self.lock_path}")
            self.break_stale_writer(minimum_age=minimum_stale_age)

        with self._writer_lease():
            discarded = self._discard_pending_files()
            rebuilt = self._recover_terminal_seal_if_needed()
            snapshot = self._load_snapshot(require_complete_terminal=True)
        return RecoveryResult(
            discarded_pending_files=discarded,
            terminal_seal_rebuilt=rebuilt,
            snapshot=snapshot,
        )

    def break_stale_writer(self, *, minimum_age: timedelta) -> WriterLease:
        """Remove a dead writer's old lease only after explicit, fail-closed checks."""

        if minimum_age < timedelta(0):
            raise ValueError("minimum_age must be non-negative")
        if not self.lock_path.is_file():
            raise ConcurrentWriteError("no writer lease exists")

        lease = _read_canonical_model(self.lock_path, WriterLease)
        age = datetime.now(timezone.utc) - lease.created_at
        if age < minimum_age:
            raise ConcurrentWriteError(
                f"writer lease age {age.total_seconds():.3f}s is below the recovery threshold"
            )
        if _process_is_alive(lease.pid):
            raise ConcurrentWriteError(f"writer process {lease.pid} is still alive")

        current = _read_canonical_model(self.lock_path, WriterLease)
        if current.token != lease.token:
            raise ConcurrentWriteError("writer lease changed during stale-lock inspection")
        self.lock_path.unlink()
        _fsync_directory(self.root)
        return lease

    def checkpoint(self, sequence: int) -> JournalCheckpoint:
        """Resolve one committed sequence to an immutable lineage checkpoint."""

        snapshot = self.snapshot()
        if sequence < 1 or sequence > len(snapshot.events):
            raise JournalError(
                f"checkpoint sequence {sequence} is outside 1..{len(snapshot.events)}"
            )
        events = snapshot.events[:sequence]
        event = events[-1]
        return JournalCheckpoint(
            run_id=self.metadata.run_id,
            sequence=sequence,
            event=event,
            lineage_hash=calculate_lineage_hash(self.metadata.run_id, events),
            terminal=event.status in TERMINAL_EVENT_STATUSES,
        )

    def replay(
        self,
        *,
        initial: ReplayState,
        reducer: Callable[[ReplayState, RunEvent], ReplayState],
        through_sequence: int | None = None,
    ) -> ReplayState:
        """Replay validated events through a caller-provided deterministic reducer."""

        snapshot = self.snapshot()
        if through_sequence is None:
            events = snapshot.events
        else:
            if through_sequence < 0 or through_sequence > len(snapshot.events):
                raise JournalError(
                    f"replay sequence {through_sequence} is outside 0..{len(snapshot.events)}"
                )
            events = snapshot.events[:through_sequence]

        state = initial
        for event in events:
            state = reducer(state, event)
        return state

    @property
    def events_dir(self) -> Path:
        return self.root / self.EVENTS_DIR

    @property
    def pending_dir(self) -> Path:
        return self.root / self.PENDING_DIR

    @property
    def lock_path(self) -> Path:
        return self.root / self.LOCK_FILE

    @property
    def seal_path(self) -> Path:
        return self.root / self.SEAL_FILE

    def _load_snapshot(self, *, require_complete_terminal: bool) -> JournalSnapshot:
        metadata = _read_canonical_model(self.root / self.METADATA_FILE, JournalMetadata)
        if metadata != self.metadata:
            raise JournalCorruptionError("journal metadata changed after open")
        events = self._read_events()
        seal = (
            _read_canonical_model(self.seal_path, JournalSeal)
            if self.seal_path.exists()
            else None
        )
        try:
            snapshot = JournalSnapshot(
                metadata=metadata,
                events=events,
                lineage_hash=calculate_lineage_hash(metadata.run_id, events),
                seal=seal,
            )
        except ValueError as exc:
            raise JournalCorruptionError(f"invalid journal snapshot: {exc}") from exc
        if require_complete_terminal and snapshot.recovery_required:
            raise JournalRecoveryRequired(
                f"terminal event {snapshot.events[-1].event_id} is missing its seal"
            )
        return snapshot

    def _read_events(self) -> list[RunEvent]:
        if not self.events_dir.is_dir():
            raise JournalCorruptionError(f"events directory missing: {self.events_dir}")
        paths = sorted(self.events_dir.iterdir(), key=lambda path: path.name)
        events: list[RunEvent] = []
        for expected_sequence, path in enumerate(paths, start=1):
            if not path.is_file():
                raise JournalCorruptionError(f"unexpected events entry: {path}")
            match = _EVENT_FILE_PATTERN.fullmatch(path.name)
            if match is None:
                raise JournalCorruptionError(f"unexpected event filename: {path.name}")
            filename_sequence = int(match.group("sequence"))
            if filename_sequence != expected_sequence:
                raise JournalCorruptionError(
                    f"event filename sequence gap: expected {expected_sequence}, "
                    f"found {filename_sequence}"
                )
            event = _read_canonical_model(path, RunEvent)
            if event.sequence != filename_sequence:
                raise JournalCorruptionError(
                    f"event {event.event_id} sequence {event.sequence} "
                    f"does not match filename {path.name}"
                )
            events.append(event)
        return events

    def _validate_append(self, *, event: RunEvent, snapshot: JournalSnapshot) -> None:
        if event.run_id != self.metadata.run_id:
            raise JournalError(
                f"event run {event.run_id} does not match journal run {self.metadata.run_id}"
            )
        expected_sequence = len(snapshot.events) + 1
        if event.sequence != expected_sequence:
            raise StaleWriterError(
                f"expected event sequence {expected_sequence}, got {event.sequence}"
            )
        if any(existing.event_id == event.event_id for existing in snapshot.events):
            raise JournalError(f"duplicate event_id: {event.event_id}")

        if not snapshot.events:
            self._validate_first_event(event)
            return

        previous = snapshot.events[-1]
        if event.parent_event_id != previous.event_id:
            raise JournalError(
                f"event {event.event_id} parent ID does not match {previous.event_id}"
            )
        if event.parent_event_hash != previous.event_hash:
            raise JournalError(
                f"event {event.event_id} parent hash does not match {previous.event_hash}"
            )
        if event.parent_run_id not in (None, self.metadata.run_id):
            raise JournalError("non-initial events cannot change parent run")

    def _validate_first_event(self, event: RunEvent) -> None:
        anchor = self.metadata.fork_anchor
        if anchor is None:
            if (
                event.parent_event_id is not None
                or event.parent_event_hash is not None
                or event.parent_run_id is not None
            ):
                raise ForkPolicyError("non-fork journals cannot start from a parent event")
            return

        if event.parent_run_id != anchor.parent_run_id:
            raise ForkPolicyError("fork event parent_run_id does not match the frozen anchor")
        if event.parent_event_id != anchor.checkpoint_event_id:
            raise ForkPolicyError("fork event parent_event_id does not match the frozen anchor")
        if event.parent_event_hash != anchor.checkpoint_event_hash:
            raise ForkPolicyError("fork event parent hash does not match the frozen anchor")

    def _recover_terminal_seal_if_needed(self) -> bool:
        snapshot = self._load_snapshot(require_complete_terminal=False)
        if not snapshot.recovery_required:
            return False
        terminal_event = snapshot.events[-1]
        seal = JournalSeal.create(
            run_id=self.metadata.run_id,
            terminal_event=terminal_event,
            event_count=len(snapshot.events),
            lineage_hash=snapshot.lineage_hash,
        )
        _atomic_write_text(self.seal_path, seal.canonical_json() + "\n")
        return True

    def _discard_pending_files(self) -> int:
        if not self.pending_dir.is_dir():
            raise JournalCorruptionError(f"pending directory missing: {self.pending_dir}")
        discarded = 0
        for path in self.pending_dir.iterdir():
            if not path.is_file() or path.suffix != ".tmp":
                raise JournalCorruptionError(f"unexpected pending entry: {path}")
            if path.parent.resolve() != self.pending_dir.resolve():
                raise JournalCorruptionError(f"pending path escapes journal: {path}")
            path.unlink()
            discarded += 1
        if discarded:
            _fsync_directory(self.pending_dir)
        return discarded

    def _event_path(self, sequence: int) -> Path:
        return self.events_dir / f"{sequence:010d}.json"

    def _fault(self, point: str) -> None:
        if self.fault_injector is not None:
            self.fault_injector(point)

    @contextmanager
    def _writer_lease(self) -> Iterator[WriterLease]:
        lease = WriterLease(
            pid=os.getpid(),
            token=f"lease_{uuid4().hex}",
            created_at=datetime.now(timezone.utc),
        )
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            descriptor = os.open(self.lock_path, flags)
        except FileExistsError as exc:
            raise ConcurrentWriteError(
                f"journal writer lease is active: {self.lock_path}"
            ) from exc

        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(lease.canonical_json())
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            _fsync_directory(self.root)
            yield lease
        finally:
            if self.lock_path.exists():
                current: WriterLease | None
                try:
                    current = _read_canonical_model(self.lock_path, WriterLease)
                except JournalCorruptionError:
                    current = None
                if current is not None and current.token == lease.token:
                    self.lock_path.unlink()
                    _fsync_directory(self.root)


def calculate_lineage_hash(run_id: str, events: list[RunEvent]) -> str:
    """Fold ordered event hashes into a deterministic run-specific lineage hash."""

    lineage_hash = canonical_sha256(
        {"schema_version": 1, "run_id": run_id, "kind": "event_journal_genesis"}
    )
    for event in events:
        lineage_hash = canonical_sha256(
            {
                "previous_lineage_hash": lineage_hash,
                "sequence": event.sequence,
                "event_hash": event.event_hash,
            }
        )
    return lineage_hash


def _validate_event_chain(*, metadata: JournalMetadata, events: list[RunEvent]) -> None:
    event_ids: set[str] = set()
    idempotency_keys: set[str] = set()
    for index, event in enumerate(events, start=1):
        if event.run_id != metadata.run_id:
            raise ValueError(
                f"event {event.event_id} run {event.run_id} "
                f"does not match journal run {metadata.run_id}"
            )
        if event.sequence != index:
            raise ValueError(
                f"event {event.event_id} sequence {event.sequence}, expected {index}"
            )
        if event.event_id in event_ids:
            raise ValueError(f"duplicate event_id: {event.event_id}")
        if event.idempotency_key in idempotency_keys:
            raise ValueError(f"duplicate idempotency key: {event.idempotency_key}")
        event_ids.add(event.event_id)
        idempotency_keys.add(event.idempotency_key)

        if index == 1:
            _validate_first_chain_event(metadata=metadata, event=event)
        else:
            previous = events[index - 2]
            if event.parent_event_id != previous.event_id:
                raise ValueError(
                    f"event {event.event_id} parent ID does not match {previous.event_id}"
                )
            if event.parent_event_hash != previous.event_hash:
                raise ValueError(
                    f"event {event.event_id} parent hash does not match "
                    f"{previous.event_hash}"
                )
        if event.status in TERMINAL_EVENT_STATUSES and index != len(events):
            raise ValueError(f"terminal event {event.event_id} is not the final event")


def _validate_first_chain_event(*, metadata: JournalMetadata, event: RunEvent) -> None:
    anchor = metadata.fork_anchor
    if anchor is None:
        if (
            event.parent_event_id is not None
            or event.parent_event_hash is not None
            or event.parent_run_id is not None
        ):
            raise ValueError("non-fork journal starts from a parent event")
        return
    if (
        event.parent_run_id != anchor.parent_run_id
        or event.parent_event_id != anchor.checkpoint_event_id
        or event.parent_event_hash != anchor.checkpoint_event_hash
    ):
        raise ValueError("first fork event does not match its frozen anchor")


def _validate_terminal_seal(
    *,
    run_id: str,
    events: list[RunEvent],
    lineage_hash: str,
    seal: JournalSeal | None,
) -> None:
    if seal is None:
        return
    if not events:
        raise ValueError("empty journal cannot have a terminal seal")
    terminal_event = events[-1]
    if terminal_event.status not in TERMINAL_EVENT_STATUSES:
        raise ValueError("terminal seal exists but final event is not terminal")
    if seal.run_id != run_id:
        raise ValueError("terminal seal run_id mismatch")
    if seal.terminal_event_id != terminal_event.event_id:
        raise ValueError("terminal seal event ID mismatch")
    if seal.terminal_event_hash != terminal_event.event_hash:
        raise ValueError("terminal seal event hash mismatch")
    if seal.terminal_status != terminal_event.status:
        raise ValueError("terminal seal status mismatch")
    if seal.event_count != len(events):
        raise ValueError("terminal seal event count mismatch")
    if seal.lineage_hash != lineage_hash:
        raise ValueError("terminal seal lineage hash mismatch")


def _reject_sensitive_event(event: RunEvent) -> None:
    validate_persistable_content(
        event.model_dump(mode="json", exclude={"event_hash"}),
    )


def validate_persistable_content(value: object) -> None:
    """Reject secret-like values and direct identifiers before local persistence."""

    _scan_sensitive_value(value, path="$")


def _scan_sensitive_value(value: object, *, path: str) -> None:
    if value is None or isinstance(value, bool | int | float):
        return
    if isinstance(value, str):
        if _EMAIL_PATTERN.search(value):
            raise SensitiveContentError(f"{path} contains a direct email identifier")
        if _BEARER_PATTERN.search(value):
            raise SensitiveContentError(f"{path} contains a bearer credential")
        if _API_KEY_PATTERN.search(value):
            raise SensitiveContentError(f"{path} contains an API-key-like credential")
        if _PRIVATE_KEY_PATTERN.search(value):
            raise SensitiveContentError(f"{path} contains a private key")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _scan_sensitive_value(item, path=f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
            if normalized in _SENSITIVE_KEYS:
                raise SensitiveContentError(f"{path}.{key} is a sensitive field")
            _scan_sensitive_value(item, path=f"{path}.{key}")
        return
    raise SensitiveContentError(f"{path} contains unsupported sensitive-scan content")


def _read_canonical_model(path: Path, model_type: type[ModelT]) -> ModelT:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise JournalCorruptionError(f"cannot read {path}: {exc}") from exc
    try:
        model = model_type.model_validate_json(text)
    except ValueError as exc:
        raise JournalCorruptionError(f"invalid {path.name}: {exc}") from exc
    expected = canonical_json(model) + "\n"
    if text != expected:
        raise JournalCorruptionError(f"{path.name} is not canonical JSON")
    return model


def _atomic_write_text(path: Path, text: str) -> None:
    temp_path = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    try:
        _write_new_file(temp_path, text)
        os.replace(temp_path, path)
        _fsync_directory(path.parent)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _write_new_file(path: Path, text: str) -> None:
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _process_is_alive(pid: int) -> bool:
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True
