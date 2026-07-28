"""Strangler migration adapter for the legacy Competition research cycle.

The legacy service remains the scientific execution engine and compatibility
artifact writer.  In ``shadow`` mode this module records an immutable vNext
event lineage and compares a projection with the legacy terminal state.  After
two distinct equivalent formal runs, ``vnext`` mode may make the verified
projection the lifecycle return authority while retaining the legacy files for
one compatibility window.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from autoresearch.kernel import (
    ActorKind,
    ControlCyclePolicy,
    EventActor,
    EventJournal,
    EventStatus,
    GraphEdge,
    GraphNode,
    GraphPlane,
    GraphSnapshot,
    RunEvent,
    canonical_sha256,
)

from .manifest import load_cycle_manifest
from .models import (
    CycleManifest,
    CycleOutcome,
    CycleResult,
    EvidenceGateReport,
)

COMPETITION_MIGRATION_MODE_ENV = "AUTORESEARCH_COMPETITION_MIGRATION_MODE"
COMPETITION_FORMAL_RUN_ENV = "AUTORESEARCH_COMPETITION_FORMAL_RUN_ID"
COMPETITION_MIGRATION_SCHEMA_VERSION = 1
COMPETITION_MIGRATION_TASK_ID = "262.8.1"
MINIMUM_FORMAL_RUNS = 2


class CompetitionMigrationError(RuntimeError):
    """Base error for Competition lifecycle migration failures."""


class CompetitionCutoverNotReadyError(CompetitionMigrationError):
    """Raised before execution when vNext authority has not earned promotion."""


class CompetitionParityError(CompetitionMigrationError):
    """Raised when the vNext projection is not equivalent to the legacy state."""


class CompetitionMigrationMode(str, Enum):
    """Reversible Competition lifecycle authority feature flag."""

    LEGACY = "legacy"
    SHADOW = "shadow"
    VNEXT = "vnext"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CompetitionArtifactBinding(_FrozenModel):
    """Path-safe logical artifact identity and observed content digest."""

    role: str = Field(min_length=1)
    logical_path: str = Field(min_length=1)
    exists: bool
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    size_bytes: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _validate_presence(self) -> CompetitionArtifactBinding:
        if self.exists != (self.sha256 is not None and self.size_bytes is not None):
            raise ValueError("existing artifacts require sha256 and size_bytes")
        return self


class CompetitionGateSemantics(_FrozenModel):
    """Normalized evidence-gate meaning, independent of its file layout."""

    emitted: bool
    passed: bool | None = None
    release_allowed: bool | None = None
    failure_count: int = Field(default=0, ge=0)
    warning_count: int = Field(default=0, ge=0)
    checked_attempt_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _validate_emission(self) -> CompetitionGateSemantics:
        values = (self.passed, self.release_allowed)
        if self.emitted and any(value is None for value in values):
            raise ValueError("an emitted gate requires passed and release_allowed")
        if not self.emitted and any(value is not None for value in values):
            raise ValueError("a missing gate cannot report a gate decision")
        return self


class CompetitionFailureSemantics(_FrozenModel):
    """Redacted legacy exception identity without persisting exception text."""

    category: Literal["legacy_exception"]
    error_type: str = Field(min_length=1)
    message_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    persisted_stage: str = Field(min_length=1)
    persisted_outcome: str = Field(min_length=1)


class CompetitionLifecycleSnapshot(_FrozenModel):
    """Comparable legacy or vNext lifecycle endpoint."""

    schema_version: Literal[1] = 1
    service: Literal["competition"] = "competition"
    run_id: str = Field(min_length=1)
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    stage: str = Field(min_length=1)
    outcome: str = Field(min_length=1)
    terminal_status: EventStatus
    scientific_endpoint: str = Field(min_length=1)
    gate: CompetitionGateSemantics
    artifacts: tuple[CompetitionArtifactBinding, ...]
    failure: CompetitionFailureSemantics | None = None
    attempt_count: int = Field(ge=0)
    access_request_count: int = Field(ge=0)
    human_intervention_count: int = Field(ge=0)
    release_eligible: bool

    @model_validator(mode="after")
    def _validate_terminal_meaning(self) -> CompetitionLifecycleSnapshot:
        if self.failure is not None and self.terminal_status is not EventStatus.FAILED:
            raise ValueError("legacy exceptions must project to failed")
        if (
            self.outcome == CycleOutcome.ACCESS_REQUIRED.value
            and self.terminal_status is not EventStatus.BLOCKED
        ):
            raise ValueError("access_required must project to blocked")
        return self


class CompetitionParityCheck(_FrozenModel):
    """One named old/new equivalence check."""

    name: Literal[
        "events",
        "terminal_state",
        "scientific_endpoint",
        "gate",
        "artifacts",
        "failure_semantics",
        "intervention_counts",
    ]
    passed: bool
    legacy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    projected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CompetitionParityReport(_FrozenModel):
    """Immutable comparison for one unique legacy terminal observation."""

    schema_version: Literal[1] = 1
    service: Literal["competition"] = "competition"
    migration_task_id: Literal["262.8.1"] = "262.8.1"
    invocation_index: int = Field(ge=1)
    invocation_kind: Literal["run", "resume"]
    migration_mode: CompetitionMigrationMode
    lifecycle_authority: Literal["legacy", "vnext"]
    source_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    formal_run_id: str | None = None
    legacy: CompetitionLifecycleSnapshot
    projected: CompetitionLifecycleSnapshot
    expected_event_semantics_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    projected_event_semantics_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    checks: tuple[CompetitionParityCheck, ...]
    equivalent: bool
    journal_path: str = Field(min_length=1)
    control_projection_path: str = Field(min_length=1)
    journal_event_count: int = Field(ge=1)
    journal_lineage_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    journal_seal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    legacy_compatibility_files_retained: bool = True

    @model_validator(mode="after")
    def _validate_equivalence(self) -> CompetitionParityReport:
        actual = all(check.passed for check in self.checks)
        if self.equivalent != actual:
            raise ValueError("equivalent must equal the conjunction of parity checks")
        if self.lifecycle_authority == "vnext" and (
            self.migration_mode is not CompetitionMigrationMode.VNEXT
        ):
            raise ValueError("vnext authority requires vnext migration mode")
        return self


class CompetitionFormalRunRecord(_FrozenModel):
    """One distinct full vertical accepted toward cutover eligibility."""

    formal_run_id: str = Field(min_length=1)
    legacy_run_id: str = Field(min_length=1)
    source_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    parity_report_path: str = Field(min_length=1)
    parity_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    journal_seal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    scientific_endpoint: Literal["development_smoke_passed"]
    equivalent: Literal[True] = True


class CompetitionPromotionLedger(_FrozenModel):
    """Cross-run evidence required before the vNext authority flag is accepted."""

    schema_version: Literal[1] = 1
    service: Literal["competition"] = "competition"
    required_equivalent_formal_runs: Literal[2] = 2
    formal_runs: tuple[CompetitionFormalRunRecord, ...] = ()
    cutover_eligible: bool = False
    legacy_compatibility_writer_retained: bool = True
    compatibility_reader_window: Literal["vnext-plus-one-release"] = (
        "vnext-plus-one-release"
    )

    @model_validator(mode="after")
    def _validate_eligibility(self) -> CompetitionPromotionLedger:
        ids = [record.formal_run_id for record in self.formal_runs]
        run_ids = [record.legacy_run_id for record in self.formal_runs]
        if len(ids) != len(set(ids)):
            raise ValueError("formal_run_id values must be unique")
        if len(run_ids) != len(set(run_ids)):
            raise ValueError("formal runs must use distinct legacy run IDs")
        expected = len(self.formal_runs) >= MINIMUM_FORMAL_RUNS
        if self.cutover_eligible != expected:
            raise ValueError("cutover_eligible does not match formal run evidence")
        return self


class CompetitionTerminalIdempotencyReport(_FrozenModel):
    """Evidence that an unchanged terminal legacy state did not create events."""

    schema_version: Literal[1] = 1
    service: Literal["competition"] = "competition"
    run_id: str = Field(min_length=1)
    source_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    requested_invocation_kind: Literal["run", "resume"]
    requested_migration_mode: CompetitionMigrationMode
    original_invocation_index: int = Field(ge=1)
    original_event_count: int = Field(ge=1)
    observed_event_count: int = Field(ge=1)
    new_invocation_created: Literal[False] = False
    manifest_hash_unchanged: bool
    lineage_hash_unchanged: bool
    passed: bool

    @model_validator(mode="after")
    def _validate_result(self) -> CompetitionTerminalIdempotencyReport:
        expected = (
            self.original_event_count == self.observed_event_count
            and self.manifest_hash_unchanged
            and self.lineage_hash_unchanged
        )
        if self.passed != expected:
            raise ValueError("idempotency passed does not match observed invariants")
        return self


class CompetitionRollbackReport(_FrozenModel):
    """Read-after-cutover proof that the legacy feature flag remains viable."""

    schema_version: Literal[1] = 1
    service: Literal["competition"] = "competition"
    run_id: str = Field(min_length=1)
    from_mode: Literal["vnext"] = "vnext"
    to_mode: Literal["legacy"] = "legacy"
    feature_flag: Literal["AUTORESEARCH_COMPETITION_MIGRATION_MODE"] = (
        "AUTORESEARCH_COMPETITION_MIGRATION_MODE"
    )
    parity_report_path: str = Field(min_length=1)
    legacy_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    vnext_lineage_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    vnext_seal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    compatibility_files_preserved: bool
    lifecycle_result_equal: bool
    projection_equal: bool
    journal_unchanged: bool
    passed: bool

    @model_validator(mode="after")
    def _validate_result(self) -> CompetitionRollbackReport:
        expected = all(
            (
                self.compatibility_files_preserved,
                self.lifecycle_result_equal,
                self.projection_equal,
                self.journal_unchanged,
            )
        )
        if self.passed != expected:
            raise ValueError("rollback passed does not match rollback invariants")
        return self


def resolve_competition_migration_mode(
    value: CompetitionMigrationMode | str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> CompetitionMigrationMode:
    """Resolve the reversible flag, defaulting to behavior-identical legacy mode."""

    if isinstance(value, CompetitionMigrationMode):
        return value
    raw = value
    if raw is None:
        source = os.environ if env is None else env
        raw = source.get(COMPETITION_MIGRATION_MODE_ENV, "")
    normalized = str(raw or CompetitionMigrationMode.LEGACY.value).strip().lower()
    try:
        return CompetitionMigrationMode(normalized)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in CompetitionMigrationMode)
        raise CompetitionMigrationError(
            f"{COMPETITION_MIGRATION_MODE_ENV} must be one of: {allowed}"
        ) from exc


def resolve_competition_formal_run_id(
    value: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> str | None:
    """Resolve an optional explicit formal-run identity without inventing one."""

    raw = value
    if raw is None:
        source = os.environ if env is None else env
        raw = source.get(COMPETITION_FORMAL_RUN_ENV)
    normalized = str(raw).strip() if raw is not None else ""
    if not normalized:
        return None
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", normalized):
        raise CompetitionMigrationError(
            f"{COMPETITION_FORMAL_RUN_ENV} must be a path-safe identifier"
        )
    return normalized


class CompetitionMigrationCoordinator:
    """Persist, compare, and promote one Competition lifecycle at a time."""

    def __init__(
        self,
        *,
        root: Path | str,
        mode: CompetitionMigrationMode | str,
        formal_run_id: str | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.mode = resolve_competition_migration_mode(mode)
        self.formal_run_id = resolve_competition_formal_run_id(formal_run_id)
        if self.mode is CompetitionMigrationMode.LEGACY:
            raise CompetitionMigrationError(
                "the migration coordinator is unnecessary in legacy mode"
            )

    @property
    def promotion_ledger_path(self) -> Path:
        return self.root / "promotion-ledger.json"

    def assert_mode_allowed(self) -> None:
        """Reject a premature vNext cutover before any scientific work starts."""

        if self.mode is not CompetitionMigrationMode.VNEXT:
            return
        ledger = self.load_promotion_ledger()
        if not ledger.cutover_eligible:
            raise CompetitionCutoverNotReadyError(
                "Competition vNext authority requires two distinct equivalent formal runs"
            )

    def load_promotion_ledger(self) -> CompetitionPromotionLedger:
        if not self.promotion_ledger_path.is_file():
            return CompetitionPromotionLedger()
        ledger = CompetitionPromotionLedger.model_validate_json(
            self.promotion_ledger_path.read_text(encoding="utf-8")
        )
        for record in ledger.formal_runs:
            report_path = _resolve_under_root(self.root, record.parity_report_path)
            if not report_path.is_file():
                raise CompetitionMigrationError(
                    f"formal parity report is missing: {record.parity_report_path}"
                )
            if _sha256_file(report_path) != record.parity_report_sha256:
                raise CompetitionMigrationError(
                    f"formal parity report hash changed: {record.formal_run_id}"
                )
            report = CompetitionParityReport.model_validate_json(
                report_path.read_text(encoding="utf-8")
            )
            expected = (
                report.formal_run_id == record.formal_run_id
                and report.legacy.run_id == record.legacy_run_id
                and report.source_fingerprint == record.source_fingerprint
                and report.journal_seal_hash == record.journal_seal_hash
                and report.equivalent
                and report.migration_mode is CompetitionMigrationMode.SHADOW
                and report.lifecycle_authority == "legacy"
                and report.legacy.scientific_endpoint
                == CycleOutcome.DEVELOPMENT_SMOKE_PASSED.value
            )
            if not expected:
                raise CompetitionMigrationError(
                    f"formal parity evidence is inconsistent: {record.formal_run_id}"
                )
            cycle_root = self.root / "cycles" / record.legacy_run_id
            validated = _find_existing_report(cycle_root, record.source_fingerprint)
            if validated != report:
                raise CompetitionMigrationError(
                    f"formal parity report is not the validated cycle report: "
                    f"{record.formal_run_id}"
                )
        return ledger

    def record_result(
        self,
        *,
        cycle_dir: Path | str,
        result: CycleResult,
        invocation_kind: Literal["run", "resume"],
    ) -> CycleResult:
        """Record one successful legacy invocation and return its active authority."""

        report, _ = self._record(
            cycle_dir=Path(cycle_dir),
            run_id=Path(cycle_dir).name,
            invocation_kind=invocation_kind,
            error=None,
        )
        if not report.equivalent:
            raise CompetitionParityError(
                f"Competition lifecycle parity failed for {report.legacy.run_id}"
            )
        if self.mode is CompetitionMigrationMode.SHADOW:
            return result
        projected = _cycle_result_from_projection(Path(cycle_dir), report.projected)
        if projected.model_dump(mode="json") != result.model_dump(mode="json"):
            raise CompetitionParityError(
                "vNext Competition return object differs from the legacy endpoint"
            )
        return projected

    def record_failure(
        self,
        *,
        cycle_dir: Path | str,
        run_id: str,
        invocation_kind: Literal["run", "resume"],
        error: Exception,
    ) -> CompetitionParityReport:
        """Persist a redacted failed terminal event before re-raising the legacy error."""

        report, _ = self._record(
            cycle_dir=Path(cycle_dir),
            run_id=run_id,
            invocation_kind=invocation_kind,
            error=error,
        )
        if not report.equivalent:
            raise CompetitionParityError(
                f"Competition failure parity failed for {report.legacy.run_id}"
            )
        return report

    def _record(
        self,
        *,
        cycle_dir: Path,
        run_id: str,
        invocation_kind: Literal["run", "resume"],
        error: Exception | None,
    ) -> tuple[CompetitionParityReport, bool]:
        resolved_cycle = cycle_dir.resolve()
        manifest = load_cycle_manifest(resolved_cycle / "cycle-manifest.json")
        if manifest.run_id != run_id:
            run_id = manifest.run_id
        legacy = _legacy_snapshot(
            cycle_dir=resolved_cycle,
            manifest=manifest,
            error=error,
        )
        source_fingerprint = _source_fingerprint(legacy)
        cycle_migration_root = self.root / "cycles" / manifest.run_id
        existing = _find_existing_report(cycle_migration_root, source_fingerprint)
        if existing is not None:
            if self.formal_run_id not in (None, existing.formal_run_id):
                raise CompetitionMigrationError(
                    "an existing terminal observation cannot be relabeled as a formal run"
                )
            _write_terminal_idempotency_report(
                cycle_migration_root=cycle_migration_root,
                existing=existing,
                requested_invocation_kind=invocation_kind,
                requested_mode=self.mode,
            )
            return existing, True

        reports = _load_reports(cycle_migration_root)
        invocation_index = len(reports) + 1
        invocation_root = (
            cycle_migration_root / "invocations" / f"{invocation_index:06d}"
        )
        journal_root = invocation_root / "journal"
        previous_report = reports[-1] if reports else None
        journal = _create_invocation_journal(
            journal_root=journal_root,
            migration_root=self.root,
            legacy_run_id=manifest.run_id,
            invocation_index=invocation_index,
            previous_report=previous_report,
            created_at=manifest.updated_at,
        )
        expected_semantics = _expected_event_semantics(
            legacy,
            invocation_kind=invocation_kind,
            migration_mode=self.mode,
            formal_run_id=self.formal_run_id,
        )
        _append_event_semantics(
            journal=journal,
            semantics=expected_semantics,
            occurred_at=manifest.updated_at,
            source_fingerprint=source_fingerprint,
        )
        journal_snapshot = journal.snapshot()
        projected_semantics = _event_semantics_from_journal(journal_snapshot.events)
        projected = _projection_from_journal(journal_snapshot.events)
        control_projection = _control_projection(
            legacy_run_id=manifest.run_id,
            invocation_index=invocation_index,
            events=journal_snapshot.events,
        )
        control_path = invocation_root / "control-graph.json"
        _write_model(control_path, control_projection)
        checks = _parity_checks(
            legacy=legacy,
            projected=projected,
            expected_event_semantics=expected_semantics,
            projected_event_semantics=projected_semantics,
        )
        seal = journal_snapshot.seal
        if seal is None:
            raise CompetitionMigrationError("Competition invocation journal is not sealed")
        report = CompetitionParityReport(
            invocation_index=invocation_index,
            invocation_kind=invocation_kind,
            migration_mode=self.mode,
            lifecycle_authority=(
                "vnext"
                if self.mode is CompetitionMigrationMode.VNEXT
                else "legacy"
            ),
            source_fingerprint=source_fingerprint,
            formal_run_id=self.formal_run_id,
            legacy=legacy,
            projected=projected,
            expected_event_semantics_sha256=_json_sha256(expected_semantics),
            projected_event_semantics_sha256=_json_sha256(projected_semantics),
            checks=checks,
            equivalent=all(check.passed for check in checks),
            journal_path=_relative_posix(journal_root, self.root),
            control_projection_path=_relative_posix(control_path, self.root),
            journal_event_count=len(journal_snapshot.events),
            journal_lineage_hash=journal_snapshot.lineage_hash,
            journal_seal_hash=seal.seal_hash,
        )
        report_path = invocation_root / "parity-report.json"
        _write_model(report_path, report)
        if not report.equivalent:
            raise CompetitionParityError(
                f"Competition parity mismatch: {_failed_check_names(report)}"
            )
        if self.formal_run_id is not None:
            self._record_formal_run(report_path=report_path, report=report)
        return report, False

    def _record_formal_run(
        self,
        *,
        report_path: Path,
        report: CompetitionParityReport,
    ) -> None:
        if self.mode is not CompetitionMigrationMode.SHADOW:
            raise CompetitionMigrationError(
                "formal parity runs must execute with legacy authority in shadow mode"
            )
        if report.legacy.scientific_endpoint != CycleOutcome.DEVELOPMENT_SMOKE_PASSED.value:
            raise CompetitionMigrationError(
                "formal promotion evidence requires a complete development vertical"
            )
        if report.legacy.failure is not None:
            raise CompetitionMigrationError("failed invocations cannot count as formal runs")
        if self.formal_run_id is None:
            raise CompetitionMigrationError("formal_run_id is required")

        ledger = self.load_promotion_ledger()
        existing = next(
            (
                record
                for record in ledger.formal_runs
                if record.formal_run_id == self.formal_run_id
            ),
            None,
        )
        report_sha256 = _sha256_file(report_path)
        candidate = CompetitionFormalRunRecord(
            formal_run_id=self.formal_run_id,
            legacy_run_id=report.legacy.run_id,
            source_fingerprint=report.source_fingerprint,
            parity_report_path=_relative_posix(report_path, self.root),
            parity_report_sha256=report_sha256,
            journal_seal_hash=report.journal_seal_hash,
            scientific_endpoint=CycleOutcome.DEVELOPMENT_SMOKE_PASSED.value,
        )
        if existing is not None:
            if existing != candidate:
                raise CompetitionMigrationError(
                    f"formal run ID {self.formal_run_id} already binds different evidence"
                )
            return
        records = tuple(
            sorted((*ledger.formal_runs, candidate), key=lambda item: item.formal_run_id)
        )
        updated = ledger.model_copy(
            update={
                "formal_runs": records,
                "cutover_eligible": len(records) >= MINIMUM_FORMAL_RUNS,
            }
        )
        _write_model(self.promotion_ledger_path, updated)


def rehearse_competition_rollback(
    *,
    cycle_dir: Path | str,
    migration_root: Path | str,
    vnext_result: CycleResult,
    legacy_result: CycleResult,
) -> CompetitionRollbackReport:
    """Verify that the reversible flag can return to the retained legacy reader."""

    resolved_cycle = Path(cycle_dir).resolve()
    resolved_root = Path(migration_root).resolve()
    manifest = load_cycle_manifest(resolved_cycle / "cycle-manifest.json")
    cycle_root = resolved_root / "cycles" / manifest.run_id
    vnext_reports = [
        report
        for report in _load_reports(cycle_root)
        if report.migration_mode is CompetitionMigrationMode.VNEXT
    ]
    if not vnext_reports:
        raise CompetitionMigrationError(
            "rollback rehearsal requires a prior vnext-authority invocation"
        )
    report = vnext_reports[-1]
    journal = EventJournal.open(resolved_root / report.journal_path)
    before = journal.snapshot()
    current = _legacy_snapshot(cycle_dir=resolved_cycle, manifest=manifest, error=None)
    projection_equal = current == report.projected
    after = journal.snapshot()
    required_files = {
        resolved_cycle / "competition-run-spec.json",
        resolved_cycle / "cycle-manifest.json",
    }
    required_files.update(
        Path(path) for path in manifest.artifact_paths.values() if Path(path).is_file()
    )
    compatibility_files_preserved = all(path.is_file() for path in required_files)
    rollback = CompetitionRollbackReport(
        run_id=manifest.run_id,
        parity_report_path=_report_path_for(report),
        legacy_manifest_hash=manifest.manifest_hash or "",
        vnext_lineage_hash=before.lineage_hash,
        vnext_seal_hash=before.seal.seal_hash if before.seal is not None else "",
        compatibility_files_preserved=compatibility_files_preserved,
        lifecycle_result_equal=(
            vnext_result.model_dump(mode="json") == legacy_result.model_dump(mode="json")
        ),
        projection_equal=projection_equal,
        journal_unchanged=before == after,
        passed=all(
            (
                compatibility_files_preserved,
                vnext_result.model_dump(mode="json")
                == legacy_result.model_dump(mode="json"),
                projection_equal,
                before == after,
            )
        ),
    )
    output = (
        resolved_root
        / "rollback-rehearsals"
        / f"{manifest.run_id}-{report.source_fingerprint[:12]}.json"
    )
    _write_model(output, rollback)
    return rollback


def _legacy_snapshot(
    *,
    cycle_dir: Path,
    manifest: CycleManifest,
    error: Exception | None,
) -> CompetitionLifecycleSnapshot:
    gate = _gate_semantics(cycle_dir)
    failure = None
    if error is not None:
        failure = CompetitionFailureSemantics(
            category="legacy_exception",
            error_type=type(error).__name__,
            message_sha256=_sha256_text(str(error)),
            persisted_stage=manifest.stage.value,
            persisted_outcome=manifest.outcome.value,
        )
    terminal_status = _terminal_status(manifest.outcome, error=error)
    endpoint = (
        f"failed:{type(error).__name__}"
        if error is not None
        else manifest.outcome.value
    )
    return CompetitionLifecycleSnapshot(
        run_id=manifest.run_id,
        manifest_hash=manifest.manifest_hash or "",
        stage=manifest.stage.value,
        outcome=manifest.outcome.value,
        terminal_status=terminal_status,
        scientific_endpoint=endpoint,
        gate=gate,
        artifacts=_artifact_bindings(cycle_dir=cycle_dir, manifest=manifest),
        failure=failure,
        attempt_count=len(manifest.attempts),
        access_request_count=len(manifest.access_request_ids),
        human_intervention_count=manifest.human_intervention_count,
        release_eligible=manifest.release_eligible,
    )


def _gate_semantics(cycle_dir: Path) -> CompetitionGateSemantics:
    path = cycle_dir / "evidence-gate.json"
    if not path.is_file():
        return CompetitionGateSemantics(emitted=False)
    gate = EvidenceGateReport.model_validate_json(path.read_text(encoding="utf-8"))
    return CompetitionGateSemantics(
        emitted=True,
        passed=gate.passed,
        release_allowed=gate.release_allowed,
        failure_count=len(gate.failures),
        warning_count=len(gate.warnings),
        checked_attempt_count=len(gate.checked_attempt_ids),
    )


def _terminal_status(
    outcome: CycleOutcome,
    *,
    error: Exception | None,
) -> EventStatus:
    if error is not None or outcome is CycleOutcome.FAILED:
        return EventStatus.FAILED
    if outcome is CycleOutcome.ACCESS_REQUIRED:
        return EventStatus.BLOCKED
    if outcome is CycleOutcome.NEGATIVE_RESULT:
        return EventStatus.NEGATIVE_RESULT
    if outcome is CycleOutcome.DEVELOPMENT_SMOKE_PASSED:
        return EventStatus.SUCCEEDED
    return EventStatus.PAUSED


def _artifact_bindings(
    *,
    cycle_dir: Path,
    manifest: CycleManifest,
) -> tuple[CompetitionArtifactBinding, ...]:
    raw: dict[str, Path] = {
        role: Path(path) for role, path in manifest.artifact_paths.items()
    }
    raw["cycle_manifest"] = cycle_dir / "cycle-manifest.json"
    negative = cycle_dir / "negative-result.md"
    if negative.is_file():
        raw["negative_result"] = negative
    bindings: list[CompetitionArtifactBinding] = []
    for role, path in sorted(raw.items()):
        resolved = path.resolve()
        exists = resolved.is_file()
        logical_path = _logical_artifact_path(
            cycle_dir=cycle_dir,
            role=role,
            path=resolved,
        )
        bindings.append(
            CompetitionArtifactBinding(
                role=role,
                logical_path=logical_path,
                exists=exists,
                sha256=_sha256_file(resolved) if exists else None,
                size_bytes=resolved.stat().st_size if exists else None,
            )
        )
    return tuple(bindings)


def _logical_artifact_path(*, cycle_dir: Path, role: str, path: Path) -> str:
    try:
        return path.relative_to(cycle_dir.resolve()).as_posix()
    except ValueError:
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", path.name).strip("-")
        return f"external/{_safe_component(role)}/{safe_name or 'artifact'}"


def _source_fingerprint(snapshot: CompetitionLifecycleSnapshot) -> str:
    payload: dict[str, Any] = {
        "service": snapshot.service,
        "run_id": snapshot.run_id,
        "manifest_hash": snapshot.manifest_hash,
        "failure": (
            snapshot.failure.model_dump(mode="json")
            if snapshot.failure is not None
            else None
        ),
    }
    return canonical_sha256(payload)


def _expected_event_semantics(
    snapshot: CompetitionLifecycleSnapshot,
    *,
    invocation_kind: Literal["run", "resume"],
    migration_mode: CompetitionMigrationMode,
    formal_run_id: str | None,
) -> tuple[dict[str, Any], ...]:
    artifacts_by_role = {item.role: item for item in snapshot.artifacts}
    semantics: list[dict[str, Any]] = [
        {
            "event_type": "competition.lifecycle.started",
            "status": EventStatus.STARTED.value,
            "action": "Observe legacy Competition lifecycle",
            "artifact_roles": _existing_roles(artifacts_by_role, ("run_spec",)),
            "payload": {
                "formal_run_id": formal_run_id,
                "invocation_kind": invocation_kind,
                "legacy_run_id": snapshot.run_id,
                "lifecycle_authority": (
                    "vnext"
                    if migration_mode is CompetitionMigrationMode.VNEXT
                    else "legacy"
                ),
                "migration_mode": migration_mode.value,
                "observed_stage": snapshot.stage,
            },
        }
    ]
    stage_specs = (
        (
            "topic_selection",
            "competition.topic.selection_observed",
            "Observe deterministic competition topic selection",
        ),
        (
            "selected_topic",
            "competition.topic.selected",
            "Observe selected competition topic",
        ),
        (
            "hypothesis",
            "competition.hypothesis.defined",
            "Observe bound competition hypothesis",
        ),
        (
            "experiment_protocol",
            "competition.plan.compiled",
            "Observe frozen competition protocol",
        ),
    )
    for role, event_type, action in stage_specs:
        if role in artifacts_by_role and artifacts_by_role[role].exists:
            semantics.append(
                {
                    "event_type": event_type,
                    "status": EventStatus.STARTED.value,
                    "action": action,
                    "artifact_roles": [role],
                    "payload": {"artifact_role": role},
                }
            )
    attempt_roles = sorted(
        role for role in artifacts_by_role if role.startswith("attempt_seed_")
    )
    for role in attempt_roles:
        semantics.append(
            {
                "event_type": "competition.attempt.observed",
                "status": EventStatus.STARTED.value,
                "action": "Observe persisted competition attempt",
                "artifact_roles": [role],
                "payload": {"artifact_role": role},
            }
        )
    if snapshot.gate.emitted:
        semantics.append(
            {
                "event_type": "competition.evidence_gate.observed",
                "status": EventStatus.STARTED.value,
                "action": "Observe deterministic competition evidence gate",
                "artifact_roles": _existing_roles(
                    artifacts_by_role,
                    ("evidence_gate",),
                ),
                "payload": snapshot.gate.model_dump(mode="json"),
            }
        )
    semantics.append(
        {
            "event_type": "competition.lifecycle.terminal",
            "status": snapshot.terminal_status.value,
            "action": "Seal Competition lifecycle observation",
            "artifact_roles": sorted(
                role for role, binding in artifacts_by_role.items() if binding.exists
            ),
            "payload": {"snapshot": snapshot.model_dump(mode="json")},
        }
    )
    return tuple(semantics)


def _create_invocation_journal(
    *,
    journal_root: Path,
    migration_root: Path,
    legacy_run_id: str,
    invocation_index: int,
    previous_report: CompetitionParityReport | None,
    created_at: datetime,
) -> EventJournal:
    journal_run_id = (
        f"competition.{_safe_component(legacy_run_id)}.vnext.{invocation_index:06d}"
    )
    if previous_report is None:
        return EventJournal.create(
            journal_root,
            run_id=journal_run_id,
            created_at=created_at,
        )
    parent = EventJournal.open(migration_root / previous_report.journal_path)
    parent_snapshot = parent.snapshot()
    return EventJournal.fork_from(
        parent,
        journal_root,
        run_id=journal_run_id,
        checkpoint_sequence=len(parent_snapshot.events),
        created_at=created_at,
    )

def _append_event_semantics(
    *,
    journal: EventJournal,
    semantics: tuple[dict[str, Any], ...],
    occurred_at: datetime,
    source_fingerprint: str,
) -> None:
    actor = EventActor(
        actor_id="service_competition_legacy_v1",
        kind=ActorKind.SYSTEM,
        version="competition-migration-v1",
    )
    for index, item in enumerate(semantics, start=1):
        current = journal.snapshot(require_complete_terminal=False)
        if current.events:
            parent_event = current.events[-1]
            parent_event_id = parent_event.event_id
            parent_event_hash = parent_event.event_hash
            parent_run_id = None
        elif journal.metadata.fork_anchor is not None:
            anchor = journal.metadata.fork_anchor
            parent_event_id = anchor.checkpoint_event_id
            parent_event_hash = anchor.checkpoint_event_hash
            parent_run_id = anchor.parent_run_id
        else:
            parent_event_id = None
            parent_event_hash = None
            parent_run_id = None
        artifact_roles = list(item["artifact_roles"])
        output_ids = sorted(
            {
                f"artifact_{_safe_component(role)}_{source_fingerprint[:16]}"
                for role in artifact_roles
            }
        )
        event = RunEvent.create(
            event_id=(
                f"evt_competition_{source_fingerprint[:16]}_{index:04d}"
            ),
            run_id=journal.metadata.run_id,
            task_id=COMPETITION_MIGRATION_TASK_ID,
            sequence=index,
            occurred_at=occurred_at + timedelta(microseconds=index),
            actor=actor,
            event_type=str(item["event_type"]),
            status=EventStatus(str(item["status"])),
            action=str(item["action"]),
            parent_event_id=parent_event_id,
            parent_event_hash=parent_event_hash,
            parent_run_id=parent_run_id,
            output_artifact_ids=output_ids,
            idempotency_key=(
                f"{journal.metadata.run_id}:{source_fingerprint[:16]}:{index:04d}"
            ),
            payload=dict(item["payload"]),
        )
        journal.append(event, expected_lineage_hash=current.lineage_hash)


def _event_semantics_from_journal(
    events: list[RunEvent],
) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "event_type": event.event_type,
            "status": event.status.value,
            "action": event.action,
            "artifact_roles": _artifact_roles_from_event(event),
            "payload": event.payload,
        }
        for event in events
    )


def _artifact_roles_from_event(event: RunEvent) -> list[str]:
    terminal_snapshot = event.payload.get("snapshot")
    if isinstance(terminal_snapshot, dict):
        raw_artifacts = terminal_snapshot.get("artifacts", [])
        if isinstance(raw_artifacts, list):
            return sorted(
                str(item.get("role"))
                for item in raw_artifacts
                if isinstance(item, dict) and item.get("exists") is True
            )
    role = event.payload.get("artifact_role")
    if isinstance(role, str):
        return [role]
    if event.event_type == "competition.lifecycle.started":
        return ["run_spec"] if event.output_artifact_ids else []
    if event.event_type == "competition.evidence_gate.observed":
        return ["evidence_gate"] if event.output_artifact_ids else []
    return []


def _projection_from_journal(events: list[RunEvent]) -> CompetitionLifecycleSnapshot:
    if not events:
        raise CompetitionMigrationError("cannot project an empty Competition journal")
    terminal = events[-1]
    if terminal.event_type != "competition.lifecycle.terminal":
        raise CompetitionMigrationError("Competition journal lacks a terminal lifecycle event")
    payload = terminal.payload.get("snapshot")
    if not isinstance(payload, dict):
        raise CompetitionMigrationError("terminal lifecycle event lacks a snapshot")
    return CompetitionLifecycleSnapshot.model_validate(payload)


def _control_projection(
    *,
    legacy_run_id: str,
    invocation_index: int,
    events: list[RunEvent],
) -> GraphSnapshot:
    nodes = [
        GraphNode(
            node_id=f"node_{event.event_id}",
            plane=GraphPlane.CONTROL,
            node_type="competition.event",
            label=event.event_type,
            attributes={
                "sequence": event.sequence,
                "status": event.status.value,
                "event_hash": event.event_hash,
            },
        )
        for event in events
    ]
    edges = [
        GraphEdge(
            edge_id=f"edge_competition_{invocation_index:06d}_{index:04d}",
            plane=GraphPlane.CONTROL,
            edge_type="competition.precedes",
            source_id=nodes[index - 1].node_id,
            target_id=nodes[index].node_id,
        )
        for index in range(1, len(nodes))
    ]
    return GraphSnapshot(
        graph_id=f"graph_competition_{_safe_component(legacy_run_id)}",
        version=invocation_index,
        plane=GraphPlane.CONTROL,
        control_cycle_policy=ControlCyclePolicy.ACYCLIC,
        nodes=nodes,
        edges=edges,
        metadata={
            "service": "competition",
            "migration_task_id": COMPETITION_MIGRATION_TASK_ID,
            "legacy_run_id": legacy_run_id,
        },
    )


def _parity_checks(
    *,
    legacy: CompetitionLifecycleSnapshot,
    projected: CompetitionLifecycleSnapshot,
    expected_event_semantics: tuple[dict[str, Any], ...],
    projected_event_semantics: tuple[dict[str, Any], ...],
) -> tuple[CompetitionParityCheck, ...]:
    values: tuple[tuple[str, Any, Any], ...] = (
        ("events", expected_event_semantics, projected_event_semantics),
        (
            "terminal_state",
            {
                "stage": legacy.stage,
                "outcome": legacy.outcome,
                "terminal_status": legacy.terminal_status.value,
            },
            {
                "stage": projected.stage,
                "outcome": projected.outcome,
                "terminal_status": projected.terminal_status.value,
            },
        ),
        (
            "scientific_endpoint",
            {
                "scientific_endpoint": legacy.scientific_endpoint,
                "attempt_count": legacy.attempt_count,
                "release_eligible": legacy.release_eligible,
            },
            {
                "scientific_endpoint": projected.scientific_endpoint,
                "attempt_count": projected.attempt_count,
                "release_eligible": projected.release_eligible,
            },
        ),
        (
            "gate",
            legacy.gate.model_dump(mode="json"),
            projected.gate.model_dump(mode="json"),
        ),
        (
            "artifacts",
            [item.model_dump(mode="json") for item in legacy.artifacts],
            [item.model_dump(mode="json") for item in projected.artifacts],
        ),
        (
            "failure_semantics",
            legacy.failure.model_dump(mode="json") if legacy.failure else None,
            projected.failure.model_dump(mode="json") if projected.failure else None,
        ),
        (
            "intervention_counts",
            {
                "human_intervention_count": legacy.human_intervention_count,
                "access_request_count": legacy.access_request_count,
            },
            {
                "human_intervention_count": projected.human_intervention_count,
                "access_request_count": projected.access_request_count,
            },
        ),
    )
    return tuple(
        CompetitionParityCheck(
            name=name,  # type: ignore[arg-type]
            passed=_json_sha256(old) == _json_sha256(new),
            legacy_sha256=_json_sha256(old),
            projected_sha256=_json_sha256(new),
        )
        for name, old, new in values
    )


def _cycle_result_from_projection(
    cycle_dir: Path,
    projection: CompetitionLifecycleSnapshot,
) -> CycleResult:
    manifest = load_cycle_manifest(cycle_dir / "cycle-manifest.json")
    return CycleResult(
        cycle_dir=cycle_dir.resolve().as_posix(),
        manifest_path=(cycle_dir.resolve() / "cycle-manifest.json").as_posix(),
        evidence_gate_path=manifest.artifact_paths.get("evidence_gate"),
        outcome=CycleOutcome(projection.outcome),
        release_eligible=projection.release_eligible,
        human_intervention_count=projection.human_intervention_count,
        access_request_count=projection.access_request_count,
    )


def _find_existing_report(
    cycle_migration_root: Path,
    source_fingerprint: str,
) -> CompetitionParityReport | None:
    return next(
        (
            report
            for report in _load_reports(cycle_migration_root)
            if report.source_fingerprint == source_fingerprint
        ),
        None,
    )


def _load_reports(cycle_migration_root: Path) -> list[CompetitionParityReport]:
    invocations = cycle_migration_root / "invocations"
    if not invocations.is_dir():
        return []
    reports: list[CompetitionParityReport] = []
    for path in sorted(invocations.glob("*/parity-report.json")):
        report = CompetitionParityReport.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        root = _root_for_cycle(cycle_migration_root)
        journal_path = _resolve_under_root(root, report.journal_path)
        journal = EventJournal.open(journal_path)
        snapshot = journal.snapshot()
        if len(snapshot.events) != report.journal_event_count:
            raise CompetitionMigrationError(
                f"journal event count changed for invocation {report.invocation_index}"
            )
        if snapshot.lineage_hash != report.journal_lineage_hash:
            raise CompetitionMigrationError(
                f"journal lineage changed for invocation {report.invocation_index}"
            )
        if snapshot.seal is None or snapshot.seal.seal_hash != report.journal_seal_hash:
            raise CompetitionMigrationError(
                f"journal seal changed for invocation {report.invocation_index}"
            )
        projected = _projection_from_journal(snapshot.events)
        projected_semantics = _event_semantics_from_journal(snapshot.events)
        expected_semantics = _expected_event_semantics(
            report.legacy,
            invocation_kind=report.invocation_kind,
            migration_mode=report.migration_mode,
            formal_run_id=report.formal_run_id,
        )
        checks = _parity_checks(
            legacy=report.legacy,
            projected=projected,
            expected_event_semantics=expected_semantics,
            projected_event_semantics=projected_semantics,
        )
        if (
            projected != report.projected
            or checks != report.checks
            or _json_sha256(expected_semantics)
            != report.expected_event_semantics_sha256
            or _json_sha256(projected_semantics)
            != report.projected_event_semantics_sha256
            or _source_fingerprint(report.legacy) != report.source_fingerprint
        ):
            raise CompetitionMigrationError(
                f"parity report changed for invocation {report.invocation_index}"
            )
        control_path = _resolve_under_root(root, report.control_projection_path)
        control = GraphSnapshot.model_validate_json(
            control_path.read_text(encoding="utf-8")
        )
        expected_control = _control_projection(
            legacy_run_id=report.legacy.run_id,
            invocation_index=report.invocation_index,
            events=snapshot.events,
        )
        if control != expected_control:
            raise CompetitionMigrationError(
                f"control projection changed for invocation {report.invocation_index}"
            )
        reports.append(report)
    expected = list(range(1, len(reports) + 1))
    actual = [report.invocation_index for report in reports]
    if actual != expected:
        raise CompetitionMigrationError("Competition invocation index sequence is invalid")
    return reports


def _root_for_cycle(cycle_migration_root: Path) -> Path:
    if cycle_migration_root.parent.name != "cycles":
        raise CompetitionMigrationError("invalid Competition migration cycle path")
    return cycle_migration_root.parent.parent


def _write_terminal_idempotency_report(
    *,
    cycle_migration_root: Path,
    existing: CompetitionParityReport,
    requested_invocation_kind: Literal["run", "resume"],
    requested_mode: CompetitionMigrationMode,
) -> Path:
    root = _root_for_cycle(cycle_migration_root)
    journal = EventJournal.open(root / existing.journal_path)
    first = journal.snapshot()
    second = journal.snapshot()
    report = CompetitionTerminalIdempotencyReport(
        run_id=existing.legacy.run_id,
        source_fingerprint=existing.source_fingerprint,
        requested_invocation_kind=requested_invocation_kind,
        requested_migration_mode=requested_mode,
        original_invocation_index=existing.invocation_index,
        original_event_count=existing.journal_event_count,
        observed_event_count=len(second.events),
        manifest_hash_unchanged=(
            existing.legacy.manifest_hash == existing.projected.manifest_hash
        ),
        lineage_hash_unchanged=(
            first.lineage_hash
            == second.lineage_hash
            == existing.journal_lineage_hash
        ),
        passed=(
            existing.journal_event_count == len(second.events)
            and existing.legacy.manifest_hash == existing.projected.manifest_hash
            and first.lineage_hash
            == second.lineage_hash
            == existing.journal_lineage_hash
        ),
    )
    path = (
        cycle_migration_root
        / "terminal-idempotency"
        / f"{existing.source_fingerprint[:16]}.json"
    )
    _write_model(path, report)
    return path


def _write_model(path: Path, model: BaseModel) -> None:
    _write_json(path, model.model_dump(mode="json"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_sha256(value: Any) -> str:
    normalized = json.loads(json.dumps(value, sort_keys=True))
    return canonical_sha256(normalized)


def _safe_component(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._-")
    return normalized[:96] or "item"


def _relative_posix(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _resolve_under_root(root: Path, relative_path: str) -> Path:
    root_resolved = root.resolve()
    candidate = (root_resolved / relative_path).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise CompetitionMigrationError(
            f"migration artifact path escapes root: {relative_path}"
        ) from exc
    return candidate


def _existing_roles(
    artifacts: Mapping[str, CompetitionArtifactBinding],
    roles: tuple[str, ...],
) -> list[str]:
    return [role for role in roles if role in artifacts and artifacts[role].exists]


def _failed_check_names(report: CompetitionParityReport) -> str:
    return ", ".join(check.name for check in report.checks if not check.passed)


def _report_path_for(report: CompetitionParityReport) -> str:
    return (Path(report.journal_path).parent / "parity-report.json").as_posix()


__all__ = [
    "COMPETITION_FORMAL_RUN_ENV",
    "COMPETITION_MIGRATION_MODE_ENV",
    "CompetitionArtifactBinding",
    "CompetitionCutoverNotReadyError",
    "CompetitionFailureSemantics",
    "CompetitionFormalRunRecord",
    "CompetitionGateSemantics",
    "CompetitionLifecycleSnapshot",
    "CompetitionMigrationCoordinator",
    "CompetitionMigrationError",
    "CompetitionMigrationMode",
    "CompetitionParityCheck",
    "CompetitionParityError",
    "CompetitionParityReport",
    "CompetitionPromotionLedger",
    "CompetitionRollbackReport",
    "CompetitionTerminalIdempotencyReport",
    "rehearse_competition_rollback",
    "resolve_competition_formal_run_id",
    "resolve_competition_migration_mode",
]
