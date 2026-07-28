"""Strangler migration adapter for the bounded autonomous Sprint service.

The Sprint executor and its compatibility files remain authoritative in
``shadow`` mode.  This module projects one immutable vNext event lineage per
distinct logical observation, proves parity, and permits ``vnext`` lifecycle
return authority only after two different complete formal Sprints have passed
the same checks.  Scientific negative results remain completed Sprints; they
are never rewritten as execution failures.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

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

if TYPE_CHECKING:
    from .sprint import (
        AutonomyLedger,
        SprintManifest,
        SprintResult,
        SprintSpec,
    )

SPRINT_MIGRATION_MODE_ENV = "AUTORESEARCH_SPRINT_MIGRATION_MODE"
SPRINT_FORMAL_RUN_ENV = "AUTORESEARCH_SPRINT_FORMAL_RUN_ID"
SPRINT_MIGRATION_SCHEMA_VERSION = 1
SPRINT_MIGRATION_TASK_ID = "262.8.3"
MINIMUM_FORMAL_RUNS = 2


class SprintMigrationError(RuntimeError):
    """Base error for Sprint lifecycle migration failures."""


class SprintCutoverNotReadyError(SprintMigrationError):
    """Raised before work when vNext authority has not earned promotion."""


class SprintParityError(SprintMigrationError):
    """Raised when a vNext Sprint projection differs from legacy meaning."""


class SprintMigrationMode(str, Enum):
    """Reversible Sprint lifecycle-authority flag."""

    LEGACY = "legacy"
    SHADOW = "shadow"
    VNEXT = "vnext"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SprintArtifactBinding(_FrozenModel):
    """Logical artifact identity without persisting an absolute private path."""

    role: str = Field(min_length=1)
    logical_path: str = Field(min_length=1)
    exists: bool
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    size_bytes: int | None = Field(default=None, ge=0)
    expected_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    matches_expected: bool | None = None

    @model_validator(mode="after")
    def _validate_presence(self) -> SprintArtifactBinding:
        if self.exists != (self.sha256 is not None and self.size_bytes is not None):
            raise ValueError("existing Sprint artifacts require sha256 and size")
        if self.expected_sha256 is None and self.matches_expected is not None:
            raise ValueError("match status requires an expected digest")
        if self.expected_sha256 is not None:
            expected_match = self.exists and self.sha256 == self.expected_sha256
            if self.matches_expected != expected_match:
                raise ValueError("artifact match status is inconsistent")
        return self


class SprintGateSemantics(_FrozenModel):
    """Task-level, paper, autonomy, and release-gate meaning."""

    endpoint_emitted: bool
    endpoint_passed: bool | None = None
    endpoint_failure_count: int = Field(default=0, ge=0)
    endpoint_warning_count: int = Field(default=0, ge=0)
    independent_unit_count: int = Field(default=0, ge=0)
    paper_emitted: bool
    paper_status: str | None = None
    paper_quality_passed: bool | None = None
    paper_quality_failure_count: int = Field(default=0, ge=0)
    audit_emitted: bool
    autonomy_level: str | None = None
    autonomy_checks_passed: bool | None = None
    autonomy_check_failure_count: int = Field(default=0, ge=0)
    external_submission_authorized: bool = False

    @model_validator(mode="after")
    def _validate_emission(self) -> SprintGateSemantics:
        if self.endpoint_emitted != (self.endpoint_passed is not None):
            raise ValueError("Sprint endpoint emission and decision are inconsistent")
        if not self.endpoint_emitted and (
            self.endpoint_failure_count
            or self.endpoint_warning_count
            or self.independent_unit_count
        ):
            raise ValueError("missing endpoint cannot report endpoint counts")
        if self.paper_emitted != (
            self.paper_status is not None and self.paper_quality_passed is not None
        ):
            raise ValueError("Sprint paper emission and quality are inconsistent")
        if not self.paper_emitted and self.paper_quality_failure_count:
            raise ValueError("missing paper cannot report quality failures")
        if self.audit_emitted != (
            self.autonomy_level is not None
            and self.autonomy_checks_passed is not None
        ):
            raise ValueError("Sprint audit emission and decision are inconsistent")
        if not self.audit_emitted and self.autonomy_check_failure_count:
            raise ValueError("missing audit cannot report failed checks")
        if self.external_submission_authorized:
            raise ValueError("Sprint migration cannot authorize external submission")
        return self


class SprintFailureSemantics(_FrozenModel):
    """Digest-only blocked or failed legacy meaning."""

    category: Literal["legacy_block", "legacy_exception"]
    error_type: str = Field(min_length=1)
    message_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    persisted_stage: str = Field(min_length=1)
    persisted_outcome: str = Field(min_length=1)


class SprintInterventionSemantics(_FrozenModel):
    """Human, fallback, and decision counts derived from persisted evidence."""

    legacy_event_count: int = Field(ge=0)
    research_decision_event_count: int = Field(ge=0)
    prelaunch_operator_research_decisions: int = Field(ge=0)
    post_start_manual_research_decisions: int = Field(ge=0)
    local_model_fallback_count: int = Field(ge=0)
    access_request_count: Literal[0] = 0


class SprintResultPathSemantics(_FrozenModel):
    """Enough path shape to reconstruct the legacy result without private roots."""

    manuscript_kind: Literal["none", "root_relative", "relative"]
    manuscript_value: str | None = None
    paper_pdf_kind: Literal["none", "root_relative", "relative"]
    paper_pdf_value: str | None = None

    @model_validator(mode="after")
    def _validate_paths(self) -> SprintResultPathSemantics:
        for kind, value in (
            (self.manuscript_kind, self.manuscript_value),
            (self.paper_pdf_kind, self.paper_pdf_value),
        ):
            if (kind == "none") != (value is None):
                raise ValueError("Sprint result path kind and value are inconsistent")
            if value is not None:
                path = Path(value)
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError("Sprint result path semantics must remain path-safe")
        return self


class SprintLifecycleSnapshot(_FrozenModel):
    """Comparable legacy or vNext Sprint endpoint."""

    schema_version: Literal[1] = 1
    service: Literal["sprint"] = "sprint"
    sprint_id: str = Field(min_length=1)
    manifest_semantics_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    autonomy_ledger_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stage: str = Field(min_length=1)
    outcome: str = Field(min_length=1)
    terminal_status: EventStatus
    scientific_endpoint: str = Field(min_length=1)
    selected_candidate_id: str | None = None
    selected_program_id: str | None = None
    gate: SprintGateSemantics
    artifacts: tuple[SprintArtifactBinding, ...]
    failure: SprintFailureSemantics | None = None
    interventions: SprintInterventionSemantics
    result_paths: SprintResultPathSemantics
    external_submission_authorized: bool = False

    @model_validator(mode="after")
    def _validate_terminal_meaning(self) -> SprintLifecycleSnapshot:
        if self.external_submission_authorized:
            raise ValueError("Sprint projection cannot authorize external submission")
        if self.failure is not None:
            expected = (
                EventStatus.BLOCKED
                if self.failure.category == "legacy_block"
                else EventStatus.FAILED
            )
            if self.terminal_status is not expected:
                raise ValueError("Sprint failure category and terminal status differ")
        if self.outcome == "completed":
            if not (
                self.gate.endpoint_emitted
                and self.gate.paper_emitted
                and self.gate.audit_emitted
            ):
                raise ValueError("completed Sprint lacks endpoint, paper, or audit gate")
            expected = (
                EventStatus.SUCCEEDED
                if self.gate.endpoint_passed
                else EventStatus.NEGATIVE_RESULT
            )
            if self.terminal_status is not expected:
                raise ValueError("completed Sprint has the wrong scientific status")
        if (
            self.outcome == "blocked"
            and (
                self.failure is None
                or self.failure.category == "legacy_block"
            )
            and self.terminal_status is not EventStatus.BLOCKED
        ):
            raise ValueError("blocked Sprint must project to blocked")
        return self


class SprintParityCheck(_FrozenModel):
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


class SprintParityReport(_FrozenModel):
    """Immutable comparison for one logical Sprint observation."""

    schema_version: Literal[1] = 1
    service: Literal["sprint"] = "sprint"
    migration_task_id: Literal["262.8.3"] = "262.8.3"
    invocation_index: int = Field(ge=1)
    invocation_kind: Literal["run", "resume"]
    migration_mode: SprintMigrationMode
    lifecycle_authority: Literal["legacy", "vnext"]
    source_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    formal_run_id: str | None = None
    legacy: SprintLifecycleSnapshot
    projected: SprintLifecycleSnapshot
    expected_event_semantics: tuple[dict[str, Any], ...]
    expected_event_semantics_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    projected_event_semantics_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    checks: tuple[SprintParityCheck, ...]
    equivalent: bool
    journal_path: str = Field(min_length=1)
    control_projection_path: str = Field(min_length=1)
    journal_event_count: int = Field(ge=1)
    journal_lineage_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    journal_seal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    legacy_compatibility_files_retained: bool

    @model_validator(mode="after")
    def _validate_equivalence(self) -> SprintParityReport:
        if self.equivalent != all(check.passed for check in self.checks):
            raise ValueError("equivalent must equal the Sprint parity conjunction")
        if self.lifecycle_authority == "vnext" and (
            self.migration_mode is not SprintMigrationMode.VNEXT
        ):
            raise ValueError("vnext authority requires vnext Sprint mode")
        return self


class SprintFormalRunRecord(_FrozenModel):
    """One complete Sprint accepted toward cutover eligibility."""

    formal_run_id: str = Field(min_length=1)
    legacy_sprint_id: str = Field(min_length=1)
    source_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    parity_report_path: str = Field(min_length=1)
    parity_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    journal_seal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    scientific_endpoint: Literal["task_level_gate_passed", "negative_result"]
    equivalent: Literal[True] = True


class SprintPromotionLedger(_FrozenModel):
    """Cross-Sprint evidence required before vNext authority can run."""

    schema_version: Literal[1] = 1
    service: Literal["sprint"] = "sprint"
    migration_task_id: Literal["262.8.3"] = "262.8.3"
    required_equivalent_formal_runs: Literal[2] = 2
    formal_runs: tuple[SprintFormalRunRecord, ...] = ()
    cutover_eligible: bool = False
    legacy_writer_retained: Literal[True] = True

    @model_validator(mode="after")
    def _validate_promotion(self) -> SprintPromotionLedger:
        formal_ids = [item.formal_run_id for item in self.formal_runs]
        sprint_ids = [item.legacy_sprint_id for item in self.formal_runs]
        if len(formal_ids) != len(set(formal_ids)):
            raise ValueError("formal Sprint run IDs must be unique")
        if len(sprint_ids) != len(set(sprint_ids)):
            raise ValueError("formal runs must use different Sprint IDs")
        if self.cutover_eligible != (
            len(self.formal_runs) >= MINIMUM_FORMAL_RUNS
        ):
            raise ValueError("Sprint cutover eligibility contradicts formal evidence")
        return self


class SprintTerminalIdempotencyReport(_FrozenModel):
    """Proof that an unchanged terminal observation did not append a run."""

    schema_version: Literal[1] = 1
    service: Literal["sprint"] = "sprint"
    sprint_id: str
    source_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    requested_invocation_kind: Literal["run", "resume"]
    requested_migration_mode: SprintMigrationMode
    original_invocation_index: int = Field(ge=1)
    original_event_count: int = Field(ge=1)
    observed_event_count: int = Field(ge=1)
    semantic_manifest_unchanged: bool
    autonomy_ledger_unchanged: bool
    journal_unchanged: bool
    passed: bool


class SprintRollbackReport(_FrozenModel):
    """Evidence that lifecycle authority can return to legacy."""

    schema_version: Literal[1] = 1
    service: Literal["sprint"] = "sprint"
    sprint_id: str
    feature_flag: Literal["AUTORESEARCH_SPRINT_MIGRATION_MODE"] = (
        "AUTORESEARCH_SPRINT_MIGRATION_MODE"
    )
    requested_mode: Literal["legacy"] = "legacy"
    parity_report_path: str
    legacy_manifest_semantics_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    vnext_lineage_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    vnext_seal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    compatibility_files_preserved: bool
    lifecycle_result_equal: bool
    projection_equal: bool
    journal_unchanged: bool
    passed: bool

    @model_validator(mode="after")
    def _validate_passed(self) -> SprintRollbackReport:
        actual = all(
            (
                self.compatibility_files_preserved,
                self.lifecycle_result_equal,
                self.projection_equal,
                self.journal_unchanged,
            )
        )
        if self.passed != actual:
            raise ValueError("Sprint rollback status contradicts its invariants")
        return self


def resolve_sprint_migration_mode(
    value: SprintMigrationMode | str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> SprintMigrationMode:
    """Resolve a default-off, case-insensitive Sprint authority mode."""

    raw: SprintMigrationMode | str | None = value
    if raw is None:
        source = os.environ if env is None else env
        raw = source.get(SPRINT_MIGRATION_MODE_ENV, SprintMigrationMode.LEGACY.value)
    if isinstance(raw, SprintMigrationMode):
        return raw
    try:
        return SprintMigrationMode(str(raw).strip().lower())
    except ValueError as exc:
        choices = ", ".join(item.value for item in SprintMigrationMode)
        raise SprintMigrationError(
            f"{SPRINT_MIGRATION_MODE_ENV} must be one of: {choices}"
        ) from exc


def resolve_sprint_formal_run_id(
    value: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> str | None:
    """Resolve an explicit formal identity without inventing one."""

    raw = value
    if raw is None:
        source = os.environ if env is None else env
        raw = source.get(SPRINT_FORMAL_RUN_ENV)
    normalized = str(raw).strip() if raw is not None else ""
    if not normalized:
        return None
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", normalized):
        raise SprintMigrationError(
            f"{SPRINT_FORMAL_RUN_ENV} must be a path-safe identifier"
        )
    return normalized


class SprintMigrationCoordinator:
    """Persist, compare, and promote one Sprint lifecycle at a time."""

    def __init__(
        self,
        *,
        root: Path | str,
        mode: SprintMigrationMode | str,
        formal_run_id: str | None = None,
        vault_root: Path | str = Path("autoresearch-vault"),
    ) -> None:
        self.root = Path(root).resolve()
        self.mode = resolve_sprint_migration_mode(mode)
        self.formal_run_id = resolve_sprint_formal_run_id(formal_run_id)
        self.vault_root = Path(vault_root).resolve()
        if self.mode is SprintMigrationMode.LEGACY:
            raise SprintMigrationError(
                "the Sprint migration coordinator is unnecessary in legacy mode"
            )

    @property
    def promotion_ledger_path(self) -> Path:
        return self.root / "promotion-ledger.json"

    def assert_mode_allowed(self) -> None:
        """Reject premature vNext authority before Sprint work starts."""

        if self.mode is not SprintMigrationMode.VNEXT:
            return
        if not self.load_promotion_ledger().cutover_eligible:
            raise SprintCutoverNotReadyError(
                "Sprint vNext authority requires two distinct equivalent formal runs"
            )

    def load_promotion_ledger(self) -> SprintPromotionLedger:
        """Load and independently revalidate every formal report."""

        if not self.promotion_ledger_path.is_file():
            return SprintPromotionLedger()
        ledger = SprintPromotionLedger.model_validate_json(
            self.promotion_ledger_path.read_text(encoding="utf-8")
        )
        for record in ledger.formal_runs:
            report_path = _resolve_under_root(self.root, record.parity_report_path)
            if not report_path.is_file():
                raise SprintMigrationError(
                    f"formal Sprint parity report is missing: "
                    f"{record.parity_report_path}"
                )
            if _sha256_file(report_path) != record.parity_report_sha256:
                raise SprintMigrationError(
                    f"formal Sprint parity report changed: {record.formal_run_id}"
                )
            report = SprintParityReport.model_validate_json(
                report_path.read_text(encoding="utf-8")
            )
            complete_vertical = (
                report.formal_run_id == record.formal_run_id
                and report.legacy.sprint_id == record.legacy_sprint_id
                and report.source_fingerprint == record.source_fingerprint
                and report.journal_seal_hash == record.journal_seal_hash
                and report.legacy.scientific_endpoint
                == record.scientific_endpoint
                and report.equivalent
                and report.migration_mode is SprintMigrationMode.SHADOW
                and report.lifecycle_authority == "legacy"
                and report.legacy.outcome == "completed"
                and report.legacy.stage == "complete"
                and report.legacy.failure is None
                and _formal_gate_ready(report.legacy)
                and _formal_artifacts_ready(report.legacy)
                and report.legacy.interventions.post_start_manual_research_decisions
                == 0
                and report.legacy.interventions.local_model_fallback_count == 0
                and report.legacy_compatibility_files_retained
            )
            if not complete_vertical:
                raise SprintMigrationError(
                    f"formal Sprint parity evidence is inconsistent: "
                    f"{record.formal_run_id}"
                )
            sprint_root = self.root / "sprints" / record.legacy_sprint_id
            if _find_existing_report(sprint_root, record.source_fingerprint) != report:
                raise SprintMigrationError(
                    "formal report is not the validated Sprint observation: "
                    f"{record.formal_run_id}"
                )
        return ledger

    def record_result(
        self,
        *,
        sprint_dir: Path | str,
        result: SprintResult,
        invocation_kind: Literal["run", "resume"],
    ) -> SprintResult:
        """Record one returned legacy result and apply active authority."""

        report, _ = self._record(
            sprint_dir=Path(sprint_dir),
            sprint_id=Path(sprint_dir).name,
            invocation_kind=invocation_kind,
            error=None,
        )
        if not report.equivalent:
            raise SprintParityError(
                f"Sprint lifecycle parity failed for {report.legacy.sprint_id}"
            )
        if self.mode is SprintMigrationMode.SHADOW:
            return result
        projected = _sprint_result_from_projection(
            Path(sprint_dir),
            report.projected,
        )
        if projected.model_dump(mode="json") != result.model_dump(mode="json"):
            raise SprintParityError(
                "vNext Sprint return object differs from the legacy endpoint"
            )
        return projected

    def record_failure(
        self,
        *,
        sprint_dir: Path | str,
        sprint_id: str,
        invocation_kind: Literal["run", "resume"],
        error: Exception,
    ) -> SprintParityReport:
        """Persist a redacted failed event before the legacy exception escapes."""

        report, _ = self._record(
            sprint_dir=Path(sprint_dir),
            sprint_id=sprint_id,
            invocation_kind=invocation_kind,
            error=error,
        )
        if not report.equivalent:
            raise SprintParityError(
                f"Sprint failure parity failed for {report.legacy.sprint_id}"
            )
        return report

    def _record(
        self,
        *,
        sprint_dir: Path,
        sprint_id: str,
        invocation_kind: Literal["run", "resume"],
        error: Exception | None,
    ) -> tuple[SprintParityReport, bool]:
        resolved_sprint = sprint_dir.resolve()
        spec, manifest, ledger = _validated_sprint(resolved_sprint)
        if manifest.sprint_id != sprint_id:
            sprint_id = manifest.sprint_id
        legacy = _legacy_snapshot(
            sprint_dir=resolved_sprint,
            vault_root=self.vault_root,
            spec=spec,
            manifest=manifest,
            ledger=ledger,
            error=error,
        )
        source_fingerprint = _source_fingerprint(legacy)
        sprint_migration_root = self.root / "sprints" / sprint_id
        existing = _find_existing_report(
            sprint_migration_root,
            source_fingerprint,
        )
        if existing is not None:
            if self.formal_run_id not in (None, existing.formal_run_id):
                raise SprintMigrationError(
                    "an existing Sprint observation cannot be relabeled as formal"
                )
            _write_terminal_idempotency_report(
                sprint_migration_root=sprint_migration_root,
                existing=existing,
                requested_invocation_kind=invocation_kind,
                requested_mode=self.mode,
                observed=legacy,
            )
            return existing, True

        reports = _load_reports(sprint_migration_root)
        invocation_index = len(reports) + 1
        invocation_root = (
            sprint_migration_root / "invocations" / f"{invocation_index:06d}"
        )
        journal_root = invocation_root / "journal"
        previous_report = reports[-1] if reports else None
        journal = _create_invocation_journal(
            journal_root=journal_root,
            migration_root=self.root,
            sprint_id=sprint_id,
            invocation_index=invocation_index,
            previous_report=previous_report,
            created_at=_utc(manifest.updated_at),
        )
        expected_semantics = _expected_event_semantics(
            legacy,
            ledger=ledger,
            invocation_kind=invocation_kind,
            migration_mode=self.mode,
            formal_run_id=self.formal_run_id,
        )
        _append_event_semantics(
            journal=journal,
            semantics=expected_semantics,
            occurred_at=_utc(manifest.updated_at),
            source_fingerprint=source_fingerprint,
        )
        journal_snapshot = journal.snapshot()
        projected_semantics = _event_semantics_from_journal(
            journal_snapshot.events
        )
        projected = _projection_from_journal(journal_snapshot.events)
        control_projection = _control_projection(
            sprint_id=sprint_id,
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
            raise SprintMigrationError("Sprint invocation journal is not sealed")
        compatibility_retained = _compatibility_files_retained(resolved_sprint)
        report = SprintParityReport(
            invocation_index=invocation_index,
            invocation_kind=invocation_kind,
            migration_mode=self.mode,
            lifecycle_authority=(
                "vnext" if self.mode is SprintMigrationMode.VNEXT else "legacy"
            ),
            source_fingerprint=source_fingerprint,
            formal_run_id=self.formal_run_id,
            legacy=legacy,
            projected=projected,
            expected_event_semantics=expected_semantics,
            expected_event_semantics_sha256=_json_sha256(expected_semantics),
            projected_event_semantics_sha256=_json_sha256(projected_semantics),
            checks=checks,
            equivalent=all(check.passed for check in checks),
            journal_path=_relative_posix(journal_root, self.root),
            control_projection_path=_relative_posix(control_path, self.root),
            journal_event_count=len(journal_snapshot.events),
            journal_lineage_hash=journal_snapshot.lineage_hash,
            journal_seal_hash=seal.seal_hash,
            legacy_compatibility_files_retained=compatibility_retained,
        )
        report_path = invocation_root / "parity-report.json"
        _write_model(report_path, report)
        if not report.equivalent:
            raise SprintParityError(
                f"Sprint parity mismatch: {_failed_check_names(report)}"
            )
        if not compatibility_retained:
            raise SprintMigrationError("Sprint compatibility files are missing")
        if self.formal_run_id is not None:
            self._record_formal_run(report_path=report_path, report=report)
        return report, False

    def _record_formal_run(
        self,
        *,
        report_path: Path,
        report: SprintParityReport,
    ) -> None:
        if self.mode is not SprintMigrationMode.SHADOW:
            raise SprintMigrationError(
                "formal Sprint runs require legacy authority in shadow mode"
            )
        if (
            report.legacy.outcome != "completed"
            or report.legacy.stage != "complete"
            or report.legacy.failure is not None
            or not _formal_gate_ready(report.legacy)
            or not _formal_artifacts_ready(report.legacy)
            or report.legacy.interventions.post_start_manual_research_decisions
            != 0
            or report.legacy.interventions.local_model_fallback_count != 0
        ):
            raise SprintMigrationError(
                "formal promotion requires a complete, verified, human-free Sprint"
            )
        if self.formal_run_id is None:
            raise SprintMigrationError("formal Sprint run ID is required")
        endpoint = report.legacy.scientific_endpoint
        if endpoint not in ("task_level_gate_passed", "negative_result"):
            raise SprintMigrationError("formal Sprint lacks a scientific endpoint")
        formal_endpoint = cast(
            Literal["task_level_gate_passed", "negative_result"],
            endpoint,
        )

        ledger = self.load_promotion_ledger()
        existing = next(
            (
                item
                for item in ledger.formal_runs
                if item.formal_run_id == self.formal_run_id
            ),
            None,
        )
        candidate = SprintFormalRunRecord(
            formal_run_id=self.formal_run_id,
            legacy_sprint_id=report.legacy.sprint_id,
            source_fingerprint=report.source_fingerprint,
            parity_report_path=_relative_posix(report_path, self.root),
            parity_report_sha256=_sha256_file(report_path),
            journal_seal_hash=report.journal_seal_hash,
            scientific_endpoint=formal_endpoint,
        )
        if existing is not None:
            if existing != candidate:
                raise SprintMigrationError(
                    f"formal Sprint ID {self.formal_run_id} binds other evidence"
                )
            return
        records = tuple(
            sorted(
                (*ledger.formal_runs, candidate),
                key=lambda item: item.formal_run_id,
            )
        )
        updated = ledger.model_copy(
            update={
                "formal_runs": records,
                "cutover_eligible": len(records) >= MINIMUM_FORMAL_RUNS,
            }
        )
        _write_model(self.promotion_ledger_path, updated)


def rehearse_sprint_rollback(
    *,
    sprint_dir: Path | str,
    migration_root: Path | str,
    vault_root: Path | str,
    vnext_result: SprintResult,
    legacy_result: SprintResult,
) -> SprintRollbackReport:
    """Verify a switch from vNext lifecycle authority back to legacy."""

    resolved_sprint = Path(sprint_dir).resolve()
    resolved_root = Path(migration_root).resolve()
    resolved_vault = Path(vault_root).resolve()
    spec, manifest, ledger = _validated_sprint(resolved_sprint)
    sprint_root = resolved_root / "sprints" / manifest.sprint_id
    vnext_reports = [
        report
        for report in _load_reports(sprint_root)
        if report.migration_mode is SprintMigrationMode.VNEXT
    ]
    if not vnext_reports:
        raise SprintMigrationError(
            "rollback requires a prior vNext-authority Sprint invocation"
        )
    report = vnext_reports[-1]
    journal = EventJournal.open(resolved_root / report.journal_path)
    before = journal.snapshot()
    current = _legacy_snapshot(
        sprint_dir=resolved_sprint,
        vault_root=resolved_vault,
        spec=spec,
        manifest=manifest,
        ledger=ledger,
        error=None,
    )
    after = journal.snapshot()
    compatibility_preserved = _compatibility_files_retained(resolved_sprint)
    result_equal = (
        vnext_result.model_dump(mode="json")
        == legacy_result.model_dump(mode="json")
    )
    rollback = SprintRollbackReport(
        sprint_id=manifest.sprint_id,
        parity_report_path=_report_path_for(report),
        legacy_manifest_semantics_sha256=current.manifest_semantics_sha256,
        vnext_lineage_hash=before.lineage_hash,
        vnext_seal_hash=before.seal.seal_hash if before.seal is not None else "",
        compatibility_files_preserved=compatibility_preserved,
        lifecycle_result_equal=result_equal,
        projection_equal=current == report.projected,
        journal_unchanged=before == after,
        passed=all(
            (
                compatibility_preserved,
                result_equal,
                current == report.projected,
                before == after,
            )
        ),
    )
    output = (
        resolved_root
        / "rollback-rehearsals"
        / f"{manifest.sprint_id}-{report.source_fingerprint[:12]}.json"
    )
    _write_model(output, rollback)
    return rollback


def _validated_sprint(
    sprint_dir: Path,
) -> tuple[SprintSpec, SprintManifest, AutonomyLedger]:
    # Imported lazily because the legacy Sprint imports this migration adapter.
    from .sprint import (
        _load_and_verify_spec,
        _load_ledger,
        _load_manifest,
        _verify_manifest_artifacts,
    )

    spec = _load_and_verify_spec(sprint_dir)
    manifest = _load_manifest(sprint_dir / "sprint-manifest.json", spec=spec)
    ledger = _load_ledger(
        sprint_dir / "autonomy-ledger.json",
        sprint_id=spec.sprint_id,
    )
    _verify_manifest_artifacts(manifest)
    return spec, manifest, ledger


def _legacy_snapshot(
    *,
    sprint_dir: Path,
    vault_root: Path,
    spec: SprintSpec,
    manifest: SprintManifest,
    ledger: AutonomyLedger,
    error: Exception | None,
) -> SprintLifecycleSnapshot:
    gate = _gate_semantics(sprint_dir=sprint_dir, manifest=manifest)
    failure = _failure_semantics(manifest=manifest, error=error)
    endpoint = _scientific_endpoint(
        outcome=manifest.outcome.value,
        endpoint_passed=gate.endpoint_passed,
        error=error,
    )
    return SprintLifecycleSnapshot(
        sprint_id=manifest.sprint_id,
        manifest_semantics_sha256=_manifest_semantics_sha256(manifest),
        autonomy_ledger_sha256=ledger.ledger_hash or "",
        stage=manifest.stage.value,
        outcome=manifest.outcome.value,
        terminal_status=_terminal_status(
            outcome=manifest.outcome.value,
            endpoint_passed=gate.endpoint_passed,
            error=error,
        ),
        scientific_endpoint=endpoint,
        selected_candidate_id=manifest.selected_candidate_id,
        selected_program_id=manifest.selected_program_id,
        gate=gate,
        artifacts=_artifact_bindings(
            sprint_dir=sprint_dir,
            vault_root=vault_root,
            spec=spec,
            manifest=manifest,
        ),
        failure=failure,
        interventions=_intervention_semantics(
            sprint_dir=sprint_dir,
            manifest=manifest,
            ledger=ledger,
        ),
        result_paths=_result_path_semantics(
            sprint_dir=sprint_dir,
            manifest=manifest,
        ),
    )


def _manifest_semantics_sha256(manifest: SprintManifest) -> str:
    payload = manifest.model_dump(
        mode="json",
        exclude={"updated_at", "manifest_hash", "failure"},
    )
    return canonical_sha256(payload)


def _failure_semantics(
    *,
    manifest: SprintManifest,
    error: Exception | None,
) -> SprintFailureSemantics | None:
    if error is not None:
        return SprintFailureSemantics(
            category="legacy_exception",
            error_type=type(error).__name__,
            message_sha256=_sha256_text(str(error)),
            persisted_stage=manifest.stage.value,
            persisted_outcome=manifest.outcome.value,
        )
    if manifest.outcome.value != "blocked":
        return None
    raw = manifest.failure or "blocked without a persisted reason"
    prefix, separator, remainder = raw.partition(":")
    error_type = prefix.strip() if separator and prefix.strip() else "Blocked"
    message = remainder.strip() if separator else raw
    return SprintFailureSemantics(
        category="legacy_block",
        error_type=error_type,
        message_sha256=_sha256_text(message),
        persisted_stage=manifest.stage.value,
        persisted_outcome=manifest.outcome.value,
    )


def _terminal_status(
    *,
    outcome: str,
    endpoint_passed: bool | None,
    error: Exception | None,
) -> EventStatus:
    if error is not None:
        return EventStatus.FAILED
    if outcome == "blocked":
        return EventStatus.BLOCKED
    if outcome == "completed":
        return (
            EventStatus.SUCCEEDED
            if endpoint_passed is True
            else EventStatus.NEGATIVE_RESULT
        )
    return EventStatus.PAUSED


def _scientific_endpoint(
    *,
    outcome: str,
    endpoint_passed: bool | None,
    error: Exception | None,
) -> str:
    if error is not None:
        return f"failed:{type(error).__name__}"
    if outcome == "blocked":
        return "blocked"
    if outcome == "completed":
        return (
            "task_level_gate_passed"
            if endpoint_passed is True
            else "negative_result"
        )
    return "incomplete"


def _gate_semantics(
    *,
    sprint_dir: Path,
    manifest: SprintManifest,
) -> SprintGateSemantics:
    from .sprint import (
        SprintAutonomyAudit,
        TaskLevelEndpointResult,
        _load_stamped_model,
    )

    endpoint = None
    endpoint_path = _manifest_artifact_path(
        sprint_dir,
        manifest,
        "task_level_endpoint",
    )
    if endpoint_path is not None and endpoint_path.is_file():
        endpoint = _load_stamped_model(
            endpoint_path,
            TaskLevelEndpointResult,
            "endpoint_hash",
        )

    paper_payload: dict[str, Any] | None = None
    paper_path = _manifest_artifact_path(
        sprint_dir,
        manifest,
        "paper_build",
    )
    if paper_path is not None and paper_path.is_file():
        raw_payload = json.loads(paper_path.read_text(encoding="utf-8"))
        if not isinstance(raw_payload, dict):
            raise SprintMigrationError("Sprint paper build payload is not an object")
        paper_payload = raw_payload
    paper_quality = (
        paper_payload.get("paper_quality") if paper_payload is not None else None
    )
    if paper_quality is not None and not isinstance(paper_quality, dict):
        raise SprintMigrationError("Sprint paper quality payload is not an object")
    paper_failures = (
        paper_quality.get("failures", ())
        if isinstance(paper_quality, dict)
        else ()
    )
    if not isinstance(paper_failures, list | tuple):
        raise SprintMigrationError("Sprint paper failures are malformed")

    audit = None
    audit_path = _manifest_artifact_path(
        sprint_dir,
        manifest,
        "autonomy_audit",
    )
    if audit_path is not None and audit_path.is_file():
        audit = _load_stamped_model(
            audit_path,
            SprintAutonomyAudit,
            "audit_hash",
        )
    bounded_audit_checks = (
        "live_local_model_selected_topic",
        "multiple_executable_programs_considered",
        "selected_topic_controls_primary_analysis",
        "independent_statistical_unit_is_task",
        "experiment_executed_inside_sprint",
        "paper_prose_generated_by_live_local_model",
        "paper_build_automatic_in_same_ledger",
        "paper_pdf_exists",
        "post_start_manual_research_decisions_zero",
        "external_submission_blocked",
    )
    audit_failures = (
        sum(not audit.checks.get(name, False) for name in bounded_audit_checks)
        if audit is not None
        else 0
    )
    return SprintGateSemantics(
        endpoint_emitted=endpoint is not None,
        endpoint_passed=endpoint.passed if endpoint is not None else None,
        endpoint_failure_count=len(endpoint.failures) if endpoint is not None else 0,
        endpoint_warning_count=len(endpoint.warnings) if endpoint is not None else 0,
        independent_unit_count=(
            endpoint.independent_unit_count if endpoint is not None else 0
        ),
        paper_emitted=paper_payload is not None,
        paper_status=(
            str(paper_payload.get("status"))
            if paper_payload is not None
            else None
        ),
        paper_quality_passed=(
            bool(paper_quality.get("passed"))
            if isinstance(paper_quality, dict)
            else None
        ),
        paper_quality_failure_count=len(paper_failures),
        audit_emitted=audit is not None,
        autonomy_level=(
            audit.autonomy_level.value if audit is not None else None
        ),
        autonomy_checks_passed=(
            audit_failures == 0 if audit is not None else None
        ),
        autonomy_check_failure_count=audit_failures,
        external_submission_authorized=manifest.external_submission_authorized,
    )


def _intervention_semantics(
    *,
    sprint_dir: Path,
    manifest: SprintManifest,
    ledger: AutonomyLedger,
) -> SprintInterventionSemantics:
    from .sprint import DecisionOrigin, SprintAutonomyAudit, _load_stamped_model

    research_decisions = sum(event.research_decision for event in ledger.events)
    prelaunch = sum(
        event.research_decision
        and event.pre_start
        and event.origin is DecisionOrigin.OPERATOR_PRELAUNCH
        for event in ledger.events
    )
    post_manual = sum(
        event.research_decision
        and not event.pre_start
        and event.origin is DecisionOrigin.MANUAL_RUNTIME
        for event in ledger.events
    )
    fallback_counts = [sum(event.fallback_used for event in ledger.events)]

    systems_path = _manifest_artifact_path(sprint_dir, manifest, "systems_result")
    if systems_path is not None and systems_path.is_file():
        systems_payload = json.loads(systems_path.read_text(encoding="utf-8"))
        raw_fallbacks = (
            systems_payload.get("local_model_fallback_count")
            if isinstance(systems_payload, dict)
            else None
        )
        if isinstance(raw_fallbacks, int) and raw_fallbacks >= 0:
            fallback_counts.append(raw_fallbacks)

    audit_path = _manifest_artifact_path(sprint_dir, manifest, "autonomy_audit")
    if audit_path is not None and audit_path.is_file():
        audit = _load_stamped_model(
            audit_path,
            SprintAutonomyAudit,
            "audit_hash",
        )
        fallback_counts.append(audit.local_model_fallback_count)
        post_manual = max(
            post_manual,
            audit.post_start_manual_research_decisions,
        )
        prelaunch = max(
            prelaunch,
            audit.prelaunch_operator_research_decisions,
        )

    return SprintInterventionSemantics(
        legacy_event_count=len(ledger.events),
        research_decision_event_count=research_decisions,
        prelaunch_operator_research_decisions=prelaunch,
        post_start_manual_research_decisions=post_manual,
        local_model_fallback_count=max(fallback_counts, default=0),
    )


def _artifact_bindings(
    *,
    sprint_dir: Path,
    vault_root: Path,
    spec: SprintSpec,
    manifest: SprintManifest,
) -> tuple[SprintArtifactBinding, ...]:
    raw: dict[str, tuple[Path, str | None]] = {
        "spec": (
            sprint_dir / "sprint-spec.json",
            manifest.artifact_sha256.get("spec"),
        ),
        "autonomy_ledger": (sprint_dir / "autonomy-ledger.json", None),
        "route_a_manifest": (
            Path(spec.route_a_campaign_path) / "campaign-manifest.json",
            spec.route_a_manifest_sha256,
        ),
        "llm_config": (Path(spec.llm_config_path), spec.llm_config_sha256),
        "sprint_vault_report": (
            vault_root
            / "projects"
            / spec.project_id
            / "campaign"
            / spec.sprint_id
            / "sprint-report.md",
            None,
        ),
    }
    for role, raw_path in manifest.artifact_paths.items():
        raw.setdefault(
            _safe_component(role),
            (
                _resolve_legacy_artifact(sprint_dir, raw_path),
                manifest.artifact_sha256.get(role),
            ),
        )

    bindings: list[SprintArtifactBinding] = []
    for role, (artifact_path, expected) in sorted(raw.items()):
        resolved = artifact_path.resolve()
        exists = resolved.is_file()
        digest = _sha256_file(resolved) if exists else None
        bindings.append(
            SprintArtifactBinding(
                role=role,
                logical_path=_logical_artifact_path(
                    sprint_dir=sprint_dir,
                    role=role,
                    path=resolved,
                ),
                exists=exists,
                sha256=digest,
                size_bytes=resolved.stat().st_size if exists else None,
                expected_sha256=expected,
                matches_expected=(
                    exists and digest == expected if expected is not None else None
                ),
            )
        )
    return tuple(bindings)


def _result_path_semantics(
    *,
    sprint_dir: Path,
    manifest: SprintManifest,
) -> SprintResultPathSemantics:
    manuscript_kind, manuscript_value = _reference_semantics(
        sprint_dir,
        manifest.artifact_paths.get("manuscript"),
    )
    paper_pdf: str | None = None
    paper_path = _manifest_artifact_path(sprint_dir, manifest, "paper_build")
    if paper_path is not None and paper_path.is_file():
        payload = json.loads(paper_path.read_text(encoding="utf-8"))
        raw_pdf = payload.get("pdf_path") if isinstance(payload, dict) else None
        paper_pdf = str(raw_pdf) if isinstance(raw_pdf, str) else None
    pdf_kind, pdf_value = _reference_semantics(sprint_dir, paper_pdf)
    return SprintResultPathSemantics(
        manuscript_kind=manuscript_kind,
        manuscript_value=manuscript_value,
        paper_pdf_kind=pdf_kind,
        paper_pdf_value=pdf_value,
    )


def _reference_semantics(
    sprint_dir: Path,
    raw: str | None,
) -> tuple[Literal["none", "root_relative", "relative"], str | None]:
    if raw is None:
        return "none", None
    path = Path(raw)
    if path.is_absolute():
        try:
            relative = path.resolve().relative_to(sprint_dir.resolve()).as_posix()
        except ValueError as exc:
            raise SprintMigrationError(
                "Sprint result path escapes its root and cannot be projected safely"
            ) from exc
        return "root_relative", relative
    if ".." in path.parts:
        raise SprintMigrationError("relative Sprint result path escapes its root")
    return "relative", raw


def _manifest_artifact_path(
    sprint_dir: Path,
    manifest: SprintManifest,
    role: str,
) -> Path | None:
    raw = manifest.artifact_paths.get(role)
    return _resolve_legacy_artifact(sprint_dir, raw) if raw is not None else None


def _resolve_legacy_artifact(sprint_dir: Path, raw: str) -> Path:
    path = Path(raw)
    return path.resolve() if path.is_absolute() else (sprint_dir / path).resolve()


def _logical_artifact_path(*, sprint_dir: Path, role: str, path: Path) -> str:
    try:
        return path.relative_to(sprint_dir.resolve()).as_posix()
    except ValueError:
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", path.name).strip("-")
        return f"external/{_safe_component(role)}/{safe_name or 'artifact'}"


def _source_fingerprint(snapshot: SprintLifecycleSnapshot) -> str:
    return canonical_sha256(snapshot.model_dump(mode="json"))


def _expected_event_semantics(
    snapshot: SprintLifecycleSnapshot,
    *,
    ledger: AutonomyLedger,
    invocation_kind: Literal["run", "resume"],
    migration_mode: SprintMigrationMode,
    formal_run_id: str | None,
) -> tuple[dict[str, Any], ...]:
    artifacts = {item.role: item for item in snapshot.artifacts}
    start_roles = _existing_roles(artifacts, ("spec", "autonomy_ledger"))
    semantics: list[dict[str, Any]] = [
        {
            "event_type": "sprint.lifecycle.started",
            "status": EventStatus.STARTED.value,
            "action": "Observe legacy Sprint lifecycle",
            "artifact_roles": start_roles,
            "payload": {
                "artifact_roles": start_roles,
                "formal_run_id": formal_run_id,
                "invocation_kind": invocation_kind,
                "lifecycle_authority": (
                    "vnext"
                    if migration_mode is SprintMigrationMode.VNEXT
                    else "legacy"
                ),
                "migration_mode": migration_mode.value,
                "observed_stage": snapshot.stage,
                "sprint_id": snapshot.sprint_id,
            },
        }
    ]
    for legacy_event in ledger.events:
        roles = _legacy_event_artifact_roles(
            artifacts=artifacts,
            output_hashes=legacy_event.output_hashes,
        )
        semantics.append(
            {
                "event_type": (
                    f"sprint.stage.{legacy_event.stage.value}.observed"
                ),
                "status": EventStatus.STARTED.value,
                "action": legacy_event.action,
                "artifact_roles": roles,
                "payload": {
                    "artifact_roles": roles,
                    "fallback_used": legacy_event.fallback_used,
                    "input_hashes": dict(sorted(legacy_event.input_hashes.items())),
                    "legacy_event_hash": legacy_event.event_hash,
                    "legacy_sequence": legacy_event.sequence,
                    "note_sha256": _sha256_text(legacy_event.note),
                    "origin": legacy_event.origin.value,
                    "output_hashes": dict(
                        sorted(legacy_event.output_hashes.items())
                    ),
                    "pre_start": legacy_event.pre_start,
                    "research_decision": legacy_event.research_decision,
                    "stage": legacy_event.stage.value,
                },
            }
        )
    terminal_roles = sorted(
        role for role, binding in artifacts.items() if binding.exists
    )
    semantics.append(
        {
            "event_type": "sprint.lifecycle.terminal",
            "status": snapshot.terminal_status.value,
            "action": "Seal Sprint lifecycle observation",
            "artifact_roles": terminal_roles,
            "payload": {"snapshot": snapshot.model_dump(mode="json")},
        }
    )
    return tuple(semantics)


def _legacy_event_artifact_roles(
    *,
    artifacts: Mapping[str, SprintArtifactBinding],
    output_hashes: Mapping[str, str],
) -> list[str]:
    aliases = {
        "generation_evidence": "manuscript_generation",
        "endpoint": "task_level_endpoint",
        "literature": "literature_snapshot",
        "paper_pdf": "paper_pdf",
        "program_catalog": "program_catalog",
    }
    candidates = {
        aliases.get(role, role)
        for role in output_hashes
    }
    return sorted(
        role
        for role in candidates
        if role in artifacts and artifacts[role].exists
    )


def _create_invocation_journal(
    *,
    journal_root: Path,
    migration_root: Path,
    sprint_id: str,
    invocation_index: int,
    previous_report: SprintParityReport | None,
    created_at: datetime,
) -> EventJournal:
    journal_run_id = (
        f"sprint.{_safe_component(sprint_id)}.vnext.{invocation_index:06d}"
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
        actor_id="service_sprint_legacy_v1",
        kind=ActorKind.SYSTEM,
        version="sprint-migration-v1",
    )
    for index, item in enumerate(semantics, start=1):
        current = journal.snapshot(require_complete_terminal=False)
        if current.events:
            parent = current.events[-1]
            parent_event_id = parent.event_id
            parent_event_hash = parent.event_hash
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
            event_id=f"evt_sprint_{source_fingerprint[:16]}_{index:04d}",
            run_id=journal.metadata.run_id,
            task_id=SPRINT_MIGRATION_TASK_ID,
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
    snapshot = event.payload.get("snapshot")
    if isinstance(snapshot, dict):
        raw_artifacts = snapshot.get("artifacts", [])
        if isinstance(raw_artifacts, list):
            return sorted(
                str(item.get("role"))
                for item in raw_artifacts
                if isinstance(item, dict) and item.get("exists") is True
            )
    raw_roles = event.payload.get("artifact_roles")
    if isinstance(raw_roles, list):
        return sorted(str(item) for item in raw_roles)
    return []


def _projection_from_journal(
    events: list[RunEvent],
) -> SprintLifecycleSnapshot:
    if not events:
        raise SprintMigrationError("cannot project an empty Sprint journal")
    terminal = events[-1]
    if terminal.event_type != "sprint.lifecycle.terminal":
        raise SprintMigrationError("Sprint journal lacks a terminal event")
    payload = terminal.payload.get("snapshot")
    if not isinstance(payload, dict):
        raise SprintMigrationError("Sprint terminal event lacks a snapshot")
    return SprintLifecycleSnapshot.model_validate(payload)


def _control_projection(
    *,
    sprint_id: str,
    invocation_index: int,
    events: list[RunEvent],
) -> GraphSnapshot:
    nodes = [
        GraphNode(
            node_id=f"node_{event.event_id}",
            plane=GraphPlane.CONTROL,
            node_type="sprint.event",
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
            edge_id=f"edge_sprint_{invocation_index:06d}_{index:04d}",
            plane=GraphPlane.CONTROL,
            edge_type="sprint.precedes",
            source_id=nodes[index - 1].node_id,
            target_id=nodes[index].node_id,
        )
        for index in range(1, len(nodes))
    ]
    return GraphSnapshot(
        graph_id=f"graph_sprint_{_safe_component(sprint_id)}",
        version=invocation_index,
        plane=GraphPlane.CONTROL,
        control_cycle_policy=ControlCyclePolicy.ACYCLIC,
        nodes=nodes,
        edges=edges,
        metadata={
            "service": "sprint",
            "migration_task_id": SPRINT_MIGRATION_TASK_ID,
            "legacy_sprint_id": sprint_id,
        },
    )


def _parity_checks(
    *,
    legacy: SprintLifecycleSnapshot,
    projected: SprintLifecycleSnapshot,
    expected_event_semantics: tuple[dict[str, Any], ...],
    projected_event_semantics: tuple[dict[str, Any], ...],
) -> tuple[SprintParityCheck, ...]:
    values: tuple[tuple[str, Any, Any], ...] = (
        ("events", expected_event_semantics, projected_event_semantics),
        (
            "terminal_state",
            {
                "stage": legacy.stage,
                "outcome": legacy.outcome,
                "terminal_status": legacy.terminal_status.value,
                "selected_candidate_id": legacy.selected_candidate_id,
                "selected_program_id": legacy.selected_program_id,
            },
            {
                "stage": projected.stage,
                "outcome": projected.outcome,
                "terminal_status": projected.terminal_status.value,
                "selected_candidate_id": projected.selected_candidate_id,
                "selected_program_id": projected.selected_program_id,
            },
        ),
        (
            "scientific_endpoint",
            {
                "scientific_endpoint": legacy.scientific_endpoint,
                "manifest_semantics_sha256": legacy.manifest_semantics_sha256,
                "autonomy_ledger_sha256": legacy.autonomy_ledger_sha256,
                "result_paths": legacy.result_paths.model_dump(mode="json"),
            },
            {
                "scientific_endpoint": projected.scientific_endpoint,
                "manifest_semantics_sha256": projected.manifest_semantics_sha256,
                "autonomy_ledger_sha256": projected.autonomy_ledger_sha256,
                "result_paths": projected.result_paths.model_dump(mode="json"),
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
            (
                projected.failure.model_dump(mode="json")
                if projected.failure
                else None
            ),
        ),
        (
            "intervention_counts",
            legacy.interventions.model_dump(mode="json"),
            projected.interventions.model_dump(mode="json"),
        ),
    )
    return tuple(
        SprintParityCheck(
            name=name,  # type: ignore[arg-type]
            passed=_json_sha256(old) == _json_sha256(new),
            legacy_sha256=_json_sha256(old),
            projected_sha256=_json_sha256(new),
        )
        for name, old, new in values
    )


def _sprint_result_from_projection(
    sprint_dir: Path,
    projection: SprintLifecycleSnapshot,
) -> SprintResult:
    from .sprint import AutonomyLevel, SprintOutcome, SprintResult, SprintStage

    resolved = sprint_dir.resolve()
    return SprintResult(
        sprint_dir=resolved.as_posix(),
        outcome=SprintOutcome(projection.outcome),
        stage=SprintStage(projection.stage),
        selected_candidate_id=projection.selected_candidate_id,
        selected_program_id=projection.selected_program_id,
        endpoint_passed=projection.gate.endpoint_passed,
        autonomy_level=(
            AutonomyLevel(projection.gate.autonomy_level)
            if projection.gate.autonomy_level is not None
            else None
        ),
        manuscript_path=_project_result_path(
            resolved,
            projection.result_paths.manuscript_kind,
            projection.result_paths.manuscript_value,
        ),
        manuscript_pdf_path=_project_result_path(
            resolved,
            projection.result_paths.paper_pdf_kind,
            projection.result_paths.paper_pdf_value,
        ),
        manifest_path=(resolved / "sprint-manifest.json").as_posix(),
    )


def _project_result_path(
    root: Path,
    kind: Literal["none", "root_relative", "relative"],
    value: str | None,
) -> str | None:
    if kind == "none":
        return None
    if value is None:
        raise SprintMigrationError("Sprint projection path is missing")
    if kind == "relative":
        return value
    return (root / value).resolve().as_posix()


def _find_existing_report(
    sprint_migration_root: Path,
    source_fingerprint: str,
) -> SprintParityReport | None:
    return next(
        (
            report
            for report in _load_reports(sprint_migration_root)
            if report.source_fingerprint == source_fingerprint
        ),
        None,
    )


def _load_reports(
    sprint_migration_root: Path,
) -> list[SprintParityReport]:
    invocations = sprint_migration_root / "invocations"
    if not invocations.is_dir():
        return []
    reports: list[SprintParityReport] = []
    for path in sorted(invocations.glob("*/parity-report.json")):
        report = SprintParityReport.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        root = _root_for_sprint(sprint_migration_root)
        journal = EventJournal.open(_resolve_under_root(root, report.journal_path))
        snapshot = journal.snapshot()
        if len(snapshot.events) != report.journal_event_count:
            raise SprintMigrationError(
                f"Sprint journal event count changed: {report.invocation_index}"
            )
        if snapshot.lineage_hash != report.journal_lineage_hash:
            raise SprintMigrationError(
                f"Sprint journal lineage changed: {report.invocation_index}"
            )
        if snapshot.seal is None or (
            snapshot.seal.seal_hash != report.journal_seal_hash
        ):
            raise SprintMigrationError(
                f"Sprint journal seal changed: {report.invocation_index}"
            )
        projected = _projection_from_journal(snapshot.events)
        projected_semantics = _event_semantics_from_journal(snapshot.events)
        expected_semantics = report.expected_event_semantics
        checks = _parity_checks(
            legacy=report.legacy,
            projected=projected,
            expected_event_semantics=expected_semantics,
            projected_event_semantics=projected_semantics,
        )
        if (
            projected != report.projected
            or checks != report.checks
            or not report.equivalent
            or not report.legacy_compatibility_files_retained
            or _json_sha256(expected_semantics)
            != report.expected_event_semantics_sha256
            or _json_sha256(projected_semantics)
            != report.projected_event_semantics_sha256
            or _source_fingerprint(report.legacy) != report.source_fingerprint
        ):
            raise SprintMigrationError(
                f"Sprint parity report changed: {report.invocation_index}"
            )
        control_path = _resolve_under_root(
            root,
            report.control_projection_path,
        )
        control = GraphSnapshot.model_validate_json(
            control_path.read_text(encoding="utf-8")
        )
        expected_control = _control_projection(
            sprint_id=report.legacy.sprint_id,
            invocation_index=report.invocation_index,
            events=snapshot.events,
        )
        if control != expected_control:
            raise SprintMigrationError(
                f"Sprint Control Graph changed: {report.invocation_index}"
            )
        reports.append(report)
    expected_indices = list(range(1, len(reports) + 1))
    if [report.invocation_index for report in reports] != expected_indices:
        raise SprintMigrationError("Sprint invocation index sequence is invalid")
    return reports


def _root_for_sprint(sprint_migration_root: Path) -> Path:
    if sprint_migration_root.parent.name != "sprints":
        raise SprintMigrationError("invalid Sprint migration path")
    return sprint_migration_root.parent.parent


def _write_terminal_idempotency_report(
    *,
    sprint_migration_root: Path,
    existing: SprintParityReport,
    requested_invocation_kind: Literal["run", "resume"],
    requested_mode: SprintMigrationMode,
    observed: SprintLifecycleSnapshot,
) -> Path:
    root = _root_for_sprint(sprint_migration_root)
    journal = EventJournal.open(root / existing.journal_path)
    before = journal.snapshot()
    after = journal.snapshot()
    semantic_manifest_unchanged = (
        observed.manifest_semantics_sha256
        == existing.legacy.manifest_semantics_sha256
    )
    ledger_unchanged = (
        observed.autonomy_ledger_sha256
        == existing.legacy.autonomy_ledger_sha256
    )
    journal_unchanged = before == after
    report = SprintTerminalIdempotencyReport(
        sprint_id=existing.legacy.sprint_id,
        source_fingerprint=existing.source_fingerprint,
        requested_invocation_kind=requested_invocation_kind,
        requested_migration_mode=requested_mode,
        original_invocation_index=existing.invocation_index,
        original_event_count=existing.journal_event_count,
        observed_event_count=len(after.events),
        semantic_manifest_unchanged=semantic_manifest_unchanged,
        autonomy_ledger_unchanged=ledger_unchanged,
        journal_unchanged=journal_unchanged,
        passed=all(
            (
                existing.journal_event_count == len(after.events),
                semantic_manifest_unchanged,
                ledger_unchanged,
                journal_unchanged,
            )
        ),
    )
    path = (
        sprint_migration_root
        / "terminal-idempotency"
        / f"{existing.source_fingerprint[:16]}.json"
    )
    _write_model(path, report)
    return path


def _formal_gate_ready(snapshot: SprintLifecycleSnapshot) -> bool:
    return all(
        (
            snapshot.gate.endpoint_emitted,
            snapshot.gate.paper_emitted,
            snapshot.gate.paper_status == "compiled",
            snapshot.gate.paper_quality_passed is True,
            snapshot.gate.audit_emitted,
            snapshot.gate.autonomy_level == "bounded_autonomous",
            snapshot.gate.autonomy_checks_passed is True,
            not snapshot.gate.external_submission_authorized,
        )
    )


def _formal_artifacts_ready(snapshot: SprintLifecycleSnapshot) -> bool:
    required = {
        "spec",
        "autonomy_ledger",
        "route_a_manifest",
        "llm_config",
        "literature_snapshot",
        "topic_selection",
        "systems_result",
        "task_level_endpoint",
        "research_report",
        "manuscript",
        "manuscript_generation",
        "paper_build",
        "paper_pdf",
        "autonomy_audit",
        "sprint_vault_report",
    }
    by_role = {item.role: item for item in snapshot.artifacts}
    return all(
        role in by_role
        and by_role[role].exists
        and by_role[role].matches_expected is not False
        for role in required
    )


def _compatibility_files_retained(sprint_dir: Path) -> bool:
    return all(
        (sprint_dir / name).is_file()
        for name in (
            "sprint-spec.json",
            "sprint-manifest.json",
            "autonomy-ledger.json",
        )
    )


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
    resolved_root = root.resolve()
    candidate = (resolved_root / relative_path).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise SprintMigrationError(
            f"Sprint migration artifact escapes root: {relative_path}"
        ) from exc
    return candidate


def _existing_roles(
    artifacts: Mapping[str, SprintArtifactBinding],
    roles: tuple[str, ...],
) -> list[str]:
    return sorted(
        role for role in roles if role in artifacts and artifacts[role].exists
    )


def _failed_check_names(report: SprintParityReport) -> str:
    return ", ".join(check.name for check in report.checks if not check.passed)


def _report_path_for(report: SprintParityReport) -> str:
    return (Path(report.journal_path).parent / "parity-report.json").as_posix()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = [
    "SPRINT_FORMAL_RUN_ENV",
    "SPRINT_MIGRATION_MODE_ENV",
    "SprintArtifactBinding",
    "SprintCutoverNotReadyError",
    "SprintFailureSemantics",
    "SprintFormalRunRecord",
    "SprintGateSemantics",
    "SprintInterventionSemantics",
    "SprintLifecycleSnapshot",
    "SprintMigrationCoordinator",
    "SprintMigrationError",
    "SprintMigrationMode",
    "SprintParityCheck",
    "SprintParityError",
    "SprintParityReport",
    "SprintPromotionLedger",
    "SprintResultPathSemantics",
    "SprintRollbackReport",
    "SprintTerminalIdempotencyReport",
    "rehearse_sprint_rollback",
    "resolve_sprint_formal_run_id",
    "resolve_sprint_migration_mode",
]
