"""Strangler migration adapter for the legacy autonomous Campaign service.

The legacy campaign remains the scientific execution engine and compatibility
writer.  ``shadow`` records one immutable vNext event lineage for every
distinct persisted observation and compares its projection with the legacy
state.  After two distinct complete formal runs, ``vnext`` may make the
verified projection the lifecycle return authority while the old state and
reader remain available for a compatibility window.
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

from .models import (
    CampaignManifest,
    CampaignOutcome,
    CampaignResult,
    CampaignSpec,
    CampaignStage,
    ContributionGateResult,
    RoundDecision,
    RoundManifest,
)

CAMPAIGN_MIGRATION_MODE_ENV = "AUTORESEARCH_CAMPAIGN_MIGRATION_MODE"
CAMPAIGN_FORMAL_RUN_ENV = "AUTORESEARCH_CAMPAIGN_FORMAL_RUN_ID"
CAMPAIGN_MIGRATION_SCHEMA_VERSION = 1
CAMPAIGN_MIGRATION_TASK_ID = "262.8.2"
MINIMUM_FORMAL_RUNS = 2


class CampaignMigrationError(RuntimeError):
    """Base error for Campaign lifecycle migration failures."""


class CampaignCutoverNotReadyError(CampaignMigrationError):
    """Raised before work starts when vNext has not earned promotion."""


class CampaignParityError(CampaignMigrationError):
    """Raised when the projected Campaign lifecycle differs from legacy."""


class CampaignMigrationMode(str, Enum):
    """Reversible Campaign lifecycle authority feature flag."""

    LEGACY = "legacy"
    SHADOW = "shadow"
    VNEXT = "vnext"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CampaignArtifactBinding(_FrozenModel):
    """Path-safe logical artifact identity and observed content digest."""

    role: str = Field(min_length=1)
    logical_path: str = Field(min_length=1)
    exists: bool
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    size_bytes: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _validate_presence(self) -> CampaignArtifactBinding:
        if self.exists != (self.sha256 is not None and self.size_bytes is not None):
            raise ValueError("existing artifacts require sha256 and size_bytes")
        return self


class CampaignRoundSemantics(_FrozenModel):
    """Normalized persisted meaning for one Campaign round."""

    round_id: str = Field(min_length=1)
    round_number: int = Field(ge=1)
    stage: str = Field(min_length=1)
    outcome: str = Field(min_length=1)
    stage_history: tuple[str, ...] = ()
    parent_round_id: str | None = None
    parent_result_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    completed: bool
    experimental: bool
    decision: str | None = None
    result_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class CampaignRoundGateSemantics(_FrozenModel):
    """Contribution-gate meaning for one persisted Campaign round."""

    round_id: str = Field(min_length=1)
    emitted: bool
    passed: bool | None = None
    failure_count: int = Field(default=0, ge=0)
    warning_count: int = Field(default=0, ge=0)
    decision: str | None = None
    round_outcome: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_emission(self) -> CampaignRoundGateSemantics:
        if self.emitted and self.passed is None:
            raise ValueError("an emitted Campaign gate requires a decision")
        if not self.emitted and (
            self.passed is not None
            or self.failure_count
            or self.warning_count
            or self.decision is not None
        ):
            raise ValueError("a missing Campaign gate cannot report gate semantics")
        return self


class CampaignGateSemantics(_FrozenModel):
    """Aggregate contribution-gate meaning across a Campaign lineage."""

    rounds: tuple[CampaignRoundGateSemantics, ...] = ()
    emitted_round_count: int = Field(default=0, ge=0)
    passed_round_count: int = Field(default=0, ge=0)
    failed_round_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _validate_counts(self) -> CampaignGateSemantics:
        emitted = [item for item in self.rounds if item.emitted]
        passed = [item for item in emitted if item.passed is True]
        if self.emitted_round_count != len(emitted):
            raise ValueError("Campaign emitted gate count is inconsistent")
        if self.passed_round_count != len(passed):
            raise ValueError("Campaign passed gate count is inconsistent")
        if self.failed_round_count != len(emitted) - len(passed):
            raise ValueError("Campaign failed gate count is inconsistent")
        return self


class CampaignFailureSemantics(_FrozenModel):
    """Redacted legacy exception identity without persisting exception text."""

    category: Literal["legacy_exception"]
    error_type: str = Field(min_length=1)
    message_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    persisted_stage: str = Field(min_length=1)
    persisted_outcome: str = Field(min_length=1)
    current_round_id: str | None = None


class CampaignLifecycleSnapshot(_FrozenModel):
    """Comparable legacy or vNext Campaign lifecycle endpoint."""

    schema_version: Literal[1] = 1
    service: Literal["campaign"] = "campaign"
    campaign_id: str = Field(min_length=1)
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    lineage_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    stage: str = Field(min_length=1)
    outcome: str = Field(min_length=1)
    terminal_status: EventStatus
    scientific_endpoint: str = Field(min_length=1)
    current_round_id: str | None = None
    rounds: tuple[CampaignRoundSemantics, ...] = ()
    gate: CampaignGateSemantics
    artifacts: tuple[CampaignArtifactBinding, ...]
    failure: CampaignFailureSemantics | None = None
    round_count: int = Field(ge=0)
    completed_round_count: int = Field(ge=0)
    experimental_round_count: int = Field(ge=0)
    minimum_experimental_rounds: int = Field(ge=1)
    human_intervention_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_terminal_meaning(self) -> CampaignLifecycleSnapshot:
        if self.round_count != len(self.rounds):
            raise ValueError("Campaign round count is inconsistent")
        if self.failure is not None and self.terminal_status is not EventStatus.FAILED:
            raise ValueError("legacy exceptions must project to failed")
        if (
            self.outcome == CampaignOutcome.BLOCKED.value
            and self.terminal_status is not EventStatus.BLOCKED
        ):
            raise ValueError("blocked Campaigns must project to blocked")
        if (
            self.outcome == CampaignOutcome.DEADLINE_REACHED.value
            and self.terminal_status is not EventStatus.CANCELLED
        ):
            raise ValueError("deadline-reached Campaigns must project to cancelled")
        return self


class CampaignParityCheck(_FrozenModel):
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


class CampaignParityReport(_FrozenModel):
    """Immutable comparison for one distinct legacy Campaign observation."""

    schema_version: Literal[1] = 1
    service: Literal["campaign"] = "campaign"
    migration_task_id: Literal["262.8.2"] = "262.8.2"
    invocation_index: int = Field(ge=1)
    invocation_kind: Literal["run", "resume"]
    migration_mode: CampaignMigrationMode
    lifecycle_authority: Literal["legacy", "vnext"]
    source_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    formal_run_id: str | None = None
    legacy: CampaignLifecycleSnapshot
    projected: CampaignLifecycleSnapshot
    expected_event_semantics_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    projected_event_semantics_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    checks: tuple[CampaignParityCheck, ...]
    equivalent: bool
    journal_path: str = Field(min_length=1)
    control_projection_path: str = Field(min_length=1)
    journal_event_count: int = Field(ge=1)
    journal_lineage_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    journal_seal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    legacy_compatibility_files_retained: bool = True

    @model_validator(mode="after")
    def _validate_equivalence(self) -> CampaignParityReport:
        if self.equivalent != all(check.passed for check in self.checks):
            raise ValueError("equivalent must equal the conjunction of parity checks")
        if self.lifecycle_authority == "vnext" and (
            self.migration_mode is not CampaignMigrationMode.VNEXT
        ):
            raise ValueError("vnext authority requires vnext migration mode")
        return self


class CampaignFormalRunRecord(_FrozenModel):
    """One distinct complete Campaign vertical accepted for promotion."""

    formal_run_id: str = Field(min_length=1)
    legacy_campaign_id: str = Field(min_length=1)
    source_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    parity_report_path: str = Field(min_length=1)
    parity_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    journal_seal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    scientific_endpoint: Literal["contribution_ready"]
    equivalent: Literal[True] = True


class CampaignPromotionLedger(_FrozenModel):
    """Cross-run evidence required before vNext authority is accepted."""

    schema_version: Literal[1] = 1
    service: Literal["campaign"] = "campaign"
    required_equivalent_formal_runs: Literal[2] = 2
    formal_runs: tuple[CampaignFormalRunRecord, ...] = ()
    cutover_eligible: bool = False
    legacy_compatibility_writer_retained: bool = True
    compatibility_reader_window: Literal["vnext-plus-one-release"] = (
        "vnext-plus-one-release"
    )

    @model_validator(mode="after")
    def _validate_eligibility(self) -> CampaignPromotionLedger:
        formal_ids = [item.formal_run_id for item in self.formal_runs]
        campaign_ids = [item.legacy_campaign_id for item in self.formal_runs]
        if len(formal_ids) != len(set(formal_ids)):
            raise ValueError("formal_run_id values must be unique")
        if len(campaign_ids) != len(set(campaign_ids)):
            raise ValueError("formal runs must use distinct Campaign IDs")
        expected = len(self.formal_runs) >= MINIMUM_FORMAL_RUNS
        if self.cutover_eligible != expected:
            raise ValueError("cutover_eligible does not match formal run evidence")
        return self


class CampaignTerminalIdempotencyReport(_FrozenModel):
    """Evidence that an unchanged terminal Campaign did not create events."""

    schema_version: Literal[1] = 1
    service: Literal["campaign"] = "campaign"
    campaign_id: str = Field(min_length=1)
    source_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    requested_invocation_kind: Literal["run", "resume"]
    requested_migration_mode: CampaignMigrationMode
    original_invocation_index: int = Field(ge=1)
    original_event_count: int = Field(ge=1)
    observed_event_count: int = Field(ge=1)
    new_invocation_created: Literal[False] = False
    manifest_hash_unchanged: bool
    lineage_hash_unchanged: bool
    passed: bool

    @model_validator(mode="after")
    def _validate_result(self) -> CampaignTerminalIdempotencyReport:
        expected = (
            self.original_event_count == self.observed_event_count
            and self.manifest_hash_unchanged
            and self.lineage_hash_unchanged
        )
        if self.passed != expected:
            raise ValueError("idempotency passed does not match observed invariants")
        return self


class CampaignRollbackReport(_FrozenModel):
    """Read-after-cutover proof that the legacy Campaign path remains viable."""

    schema_version: Literal[1] = 1
    service: Literal["campaign"] = "campaign"
    campaign_id: str = Field(min_length=1)
    from_mode: Literal["vnext"] = "vnext"
    to_mode: Literal["legacy"] = "legacy"
    feature_flag: Literal["AUTORESEARCH_CAMPAIGN_MIGRATION_MODE"] = (
        "AUTORESEARCH_CAMPAIGN_MIGRATION_MODE"
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
    def _validate_result(self) -> CampaignRollbackReport:
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


def resolve_campaign_migration_mode(
    value: CampaignMigrationMode | str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> CampaignMigrationMode:
    """Resolve the reversible flag, defaulting to behavior-identical legacy."""

    if isinstance(value, CampaignMigrationMode):
        return value
    raw = value
    if raw is None:
        source = os.environ if env is None else env
        raw = source.get(CAMPAIGN_MIGRATION_MODE_ENV, "")
    normalized = str(raw or CampaignMigrationMode.LEGACY.value).strip().lower()
    try:
        return CampaignMigrationMode(normalized)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in CampaignMigrationMode)
        raise CampaignMigrationError(
            f"{CAMPAIGN_MIGRATION_MODE_ENV} must be one of: {allowed}"
        ) from exc


def resolve_campaign_formal_run_id(
    value: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> str | None:
    """Resolve an explicit formal-run identity without inventing one."""

    raw = value
    if raw is None:
        source = os.environ if env is None else env
        raw = source.get(CAMPAIGN_FORMAL_RUN_ENV)
    normalized = str(raw).strip() if raw is not None else ""
    if not normalized:
        return None
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", normalized):
        raise CampaignMigrationError(
            f"{CAMPAIGN_FORMAL_RUN_ENV} must be a path-safe identifier"
        )
    return normalized


class CampaignMigrationCoordinator:
    """Persist, compare, and promote one Campaign lifecycle at a time."""

    def __init__(
        self,
        *,
        root: Path | str,
        mode: CampaignMigrationMode | str,
        formal_run_id: str | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.mode = resolve_campaign_migration_mode(mode)
        self.formal_run_id = resolve_campaign_formal_run_id(formal_run_id)
        if self.mode is CampaignMigrationMode.LEGACY:
            raise CampaignMigrationError(
                "the migration coordinator is unnecessary in legacy mode"
            )

    @property
    def promotion_ledger_path(self) -> Path:
        return self.root / "promotion-ledger.json"

    def assert_mode_allowed(self) -> None:
        """Reject premature cutover before any scientific work starts."""

        if self.mode is not CampaignMigrationMode.VNEXT:
            return
        if not self.load_promotion_ledger().cutover_eligible:
            raise CampaignCutoverNotReadyError(
                "Campaign vNext authority requires two distinct equivalent formal runs"
            )

    def load_promotion_ledger(self) -> CampaignPromotionLedger:
        if not self.promotion_ledger_path.is_file():
            return CampaignPromotionLedger()
        ledger = CampaignPromotionLedger.model_validate_json(
            self.promotion_ledger_path.read_text(encoding="utf-8")
        )
        for record in ledger.formal_runs:
            report_path = _resolve_under_root(self.root, record.parity_report_path)
            if not report_path.is_file():
                raise CampaignMigrationError(
                    f"formal parity report is missing: {record.parity_report_path}"
                )
            if _sha256_file(report_path) != record.parity_report_sha256:
                raise CampaignMigrationError(
                    f"formal parity report hash changed: {record.formal_run_id}"
                )
            report = CampaignParityReport.model_validate_json(
                report_path.read_text(encoding="utf-8")
            )
            complete_vertical = (
                report.formal_run_id == record.formal_run_id
                and report.legacy.campaign_id == record.legacy_campaign_id
                and report.source_fingerprint == record.source_fingerprint
                and report.journal_seal_hash == record.journal_seal_hash
                and report.equivalent
                and report.migration_mode is CampaignMigrationMode.SHADOW
                and report.lifecycle_authority == "legacy"
                and report.legacy.scientific_endpoint
                == CampaignOutcome.CONTRIBUTION_READY.value
                and report.legacy.completed_round_count >= 2
                and report.legacy.experimental_round_count >= 2
                and report.legacy.failure is None
                and all(item.exists for item in report.legacy.artifacts)
            )
            if not complete_vertical:
                raise CampaignMigrationError(
                    f"formal parity evidence is inconsistent: {record.formal_run_id}"
                )
            campaign_root = self.root / "campaigns" / record.legacy_campaign_id
            if _find_existing_report(campaign_root, record.source_fingerprint) != report:
                raise CampaignMigrationError(
                    "formal parity report is not the validated Campaign report: "
                    f"{record.formal_run_id}"
                )
        return ledger

    def record_result(
        self,
        *,
        campaign_dir: Path | str,
        result: CampaignResult,
        invocation_kind: Literal["run", "resume"],
    ) -> CampaignResult:
        """Record one successful legacy invocation and return active authority."""

        report, _ = self._record(
            campaign_dir=Path(campaign_dir),
            campaign_id=Path(campaign_dir).name,
            invocation_kind=invocation_kind,
            error=None,
        )
        if not report.equivalent:
            raise CampaignParityError(
                f"Campaign lifecycle parity failed for {report.legacy.campaign_id}"
            )
        if self.mode is CampaignMigrationMode.SHADOW:
            return result
        projected = _campaign_result_from_projection(Path(campaign_dir), report.projected)
        if projected.model_dump(mode="json") != result.model_dump(mode="json"):
            raise CampaignParityError(
                "vNext Campaign return object differs from the legacy endpoint"
            )
        return projected

    def record_failure(
        self,
        *,
        campaign_dir: Path | str,
        campaign_id: str,
        invocation_kind: Literal["run", "resume"],
        error: Exception,
    ) -> CampaignParityReport:
        """Persist a redacted failed event before re-raising the legacy error."""

        report, _ = self._record(
            campaign_dir=Path(campaign_dir),
            campaign_id=campaign_id,
            invocation_kind=invocation_kind,
            error=error,
        )
        if not report.equivalent:
            raise CampaignParityError(
                f"Campaign failure parity failed for {report.legacy.campaign_id}"
            )
        return report

    def _record(
        self,
        *,
        campaign_dir: Path,
        campaign_id: str,
        invocation_kind: Literal["run", "resume"],
        error: Exception | None,
    ) -> tuple[CampaignParityReport, bool]:
        resolved_campaign = campaign_dir.resolve()
        spec, manifest, rounds = _validated_campaign(resolved_campaign)
        if manifest.campaign_id != campaign_id:
            campaign_id = manifest.campaign_id
        legacy = _legacy_snapshot(
            campaign_dir=resolved_campaign,
            spec=spec,
            manifest=manifest,
            rounds=rounds,
            error=error,
        )
        source_fingerprint = _source_fingerprint(legacy)
        campaign_migration_root = self.root / "campaigns" / campaign_id
        existing = _find_existing_report(
            campaign_migration_root,
            source_fingerprint,
        )
        if existing is not None:
            if self.formal_run_id not in (None, existing.formal_run_id):
                raise CampaignMigrationError(
                    "an existing Campaign observation cannot be relabeled as formal"
                )
            _write_terminal_idempotency_report(
                campaign_migration_root=campaign_migration_root,
                existing=existing,
                requested_invocation_kind=invocation_kind,
                requested_mode=self.mode,
            )
            return existing, True

        reports = _load_reports(campaign_migration_root)
        invocation_index = len(reports) + 1
        invocation_root = (
            campaign_migration_root / "invocations" / f"{invocation_index:06d}"
        )
        journal_root = invocation_root / "journal"
        previous_report = reports[-1] if reports else None
        journal = _create_invocation_journal(
            journal_root=journal_root,
            migration_root=self.root,
            campaign_id=campaign_id,
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
            campaign_id=campaign_id,
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
            raise CampaignMigrationError("Campaign invocation journal is not sealed")
        report = CampaignParityReport(
            invocation_index=invocation_index,
            invocation_kind=invocation_kind,
            migration_mode=self.mode,
            lifecycle_authority=(
                "vnext" if self.mode is CampaignMigrationMode.VNEXT else "legacy"
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
            raise CampaignParityError(
                f"Campaign parity mismatch: {_failed_check_names(report)}"
            )
        if self.formal_run_id is not None:
            self._record_formal_run(report_path=report_path, report=report)
        return report, False

    def _record_formal_run(
        self,
        *,
        report_path: Path,
        report: CampaignParityReport,
    ) -> None:
        if self.mode is not CampaignMigrationMode.SHADOW:
            raise CampaignMigrationError(
                "formal parity runs require legacy authority in shadow mode"
            )
        if (
            report.legacy.scientific_endpoint
            != CampaignOutcome.CONTRIBUTION_READY.value
            or report.legacy.completed_round_count < 2
            or report.legacy.experimental_round_count < 2
            or not all(item.exists for item in report.legacy.artifacts)
        ):
            raise CampaignMigrationError(
                "formal promotion evidence requires a complete two-round Campaign"
            )
        if report.legacy.failure is not None:
            raise CampaignMigrationError("failed invocations cannot count as formal runs")
        if self.formal_run_id is None:
            raise CampaignMigrationError("formal_run_id is required")

        ledger = self.load_promotion_ledger()
        existing = next(
            (
                item
                for item in ledger.formal_runs
                if item.formal_run_id == self.formal_run_id
            ),
            None,
        )
        candidate = CampaignFormalRunRecord(
            formal_run_id=self.formal_run_id,
            legacy_campaign_id=report.legacy.campaign_id,
            source_fingerprint=report.source_fingerprint,
            parity_report_path=_relative_posix(report_path, self.root),
            parity_report_sha256=_sha256_file(report_path),
            journal_seal_hash=report.journal_seal_hash,
            scientific_endpoint=CampaignOutcome.CONTRIBUTION_READY.value,
        )
        if existing is not None:
            if existing != candidate:
                raise CampaignMigrationError(
                    f"formal run ID {self.formal_run_id} binds different evidence"
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


def rehearse_campaign_rollback(
    *,
    campaign_dir: Path | str,
    migration_root: Path | str,
    vnext_result: CampaignResult,
    legacy_result: CampaignResult,
) -> CampaignRollbackReport:
    """Verify that the flag can return to the retained legacy Campaign path."""

    resolved_campaign = Path(campaign_dir).resolve()
    resolved_root = Path(migration_root).resolve()
    spec, manifest, rounds = _validated_campaign(resolved_campaign)
    campaign_root = resolved_root / "campaigns" / manifest.campaign_id
    vnext_reports = [
        report
        for report in _load_reports(campaign_root)
        if report.migration_mode is CampaignMigrationMode.VNEXT
    ]
    if not vnext_reports:
        raise CampaignMigrationError(
            "rollback rehearsal requires a prior vnext-authority Campaign invocation"
        )
    report = vnext_reports[-1]
    journal = EventJournal.open(resolved_root / report.journal_path)
    before = journal.snapshot()
    current = _legacy_snapshot(
        campaign_dir=resolved_campaign,
        spec=spec,
        manifest=manifest,
        rounds=rounds,
        error=None,
    )
    after = journal.snapshot()
    compatibility_files_preserved = all(
        item.exists for item in current.artifacts
    )
    result_equal = (
        vnext_result.model_dump(mode="json")
        == legacy_result.model_dump(mode="json")
    )
    rollback = CampaignRollbackReport(
        campaign_id=manifest.campaign_id,
        parity_report_path=_report_path_for(report),
        legacy_manifest_hash=manifest.manifest_hash or "",
        vnext_lineage_hash=before.lineage_hash,
        vnext_seal_hash=before.seal.seal_hash if before.seal is not None else "",
        compatibility_files_preserved=compatibility_files_preserved,
        lifecycle_result_equal=result_equal,
        projection_equal=current == report.projected,
        journal_unchanged=before == after,
        passed=all(
            (
                compatibility_files_preserved,
                result_equal,
                current == report.projected,
                before == after,
            )
        ),
    )
    output = (
        resolved_root
        / "rollback-rehearsals"
        / f"{manifest.campaign_id}-{report.source_fingerprint[:12]}.json"
    )
    _write_model(output, rollback)
    return rollback


def _validated_campaign(
    campaign_dir: Path,
) -> tuple[CampaignSpec, CampaignManifest, tuple[RoundManifest, ...]]:
    # Imported lazily because the legacy service imports this migration adapter.
    from .service import validate_campaign_directory

    return validate_campaign_directory(campaign_dir)


def _legacy_snapshot(
    *,
    campaign_dir: Path,
    spec: CampaignSpec,
    manifest: CampaignManifest,
    rounds: tuple[RoundManifest, ...],
    error: Exception | None,
) -> CampaignLifecycleSnapshot:
    round_semantics = tuple(
        _round_semantics(campaign_dir=campaign_dir, manifest=item)
        for item in rounds
    )
    failure = None
    if error is not None:
        failure = CampaignFailureSemantics(
            category="legacy_exception",
            error_type=type(error).__name__,
            message_sha256=_sha256_text(str(error)),
            persisted_stage=manifest.stage.value,
            persisted_outcome=manifest.outcome.value,
            current_round_id=manifest.current_round_id,
        )
    return CampaignLifecycleSnapshot(
        campaign_id=manifest.campaign_id,
        manifest_hash=manifest.manifest_hash or "",
        lineage_hash=manifest.lineage_hash or "",
        stage=manifest.stage.value,
        outcome=manifest.outcome.value,
        terminal_status=_terminal_status(manifest.outcome, error=error),
        scientific_endpoint=(
            f"failed:{type(error).__name__}"
            if error is not None
            else manifest.outcome.value
        ),
        current_round_id=manifest.current_round_id,
        rounds=round_semantics,
        gate=_gate_semantics(campaign_dir=campaign_dir, rounds=rounds),
        artifacts=_artifact_bindings(
            campaign_dir=campaign_dir,
            manifest=manifest,
            rounds=rounds,
        ),
        failure=failure,
        round_count=len(rounds),
        completed_round_count=manifest.completed_round_count,
        experimental_round_count=manifest.experimental_round_count,
        minimum_experimental_rounds=spec.min_experimental_rounds,
        human_intervention_count=manifest.human_intervention_count,
    )


def _round_semantics(
    *,
    campaign_dir: Path,
    manifest: RoundManifest,
) -> CampaignRoundSemantics:
    decision: RoundDecision | None = None
    raw_path = manifest.artifact_paths.get("round_decision")
    if raw_path is not None:
        decision = RoundDecision.model_validate_json(
            _managed_path(campaign_dir, raw_path).read_text(encoding="utf-8")
        )
    return CampaignRoundSemantics(
        round_id=manifest.round_id,
        round_number=manifest.round_number,
        stage=manifest.stage.value,
        outcome=manifest.outcome.value,
        stage_history=tuple(item.stage.value for item in manifest.stage_history),
        parent_round_id=manifest.parent_round_id,
        parent_result_hash=manifest.parent_result_hash,
        manifest_hash=manifest.manifest_hash or "",
        completed=manifest.completed_at is not None,
        experimental="unseen_evaluation" in manifest.artifact_paths,
        decision=decision.decision.value if decision is not None else None,
        result_hash=decision.result_hash if decision is not None else None,
    )


def _gate_semantics(
    *,
    campaign_dir: Path,
    rounds: tuple[RoundManifest, ...],
) -> CampaignGateSemantics:
    items: list[CampaignRoundGateSemantics] = []
    for round_manifest in rounds:
        gate_path = round_manifest.artifact_paths.get("contribution_gate")
        decision_path = round_manifest.artifact_paths.get("round_decision")
        if gate_path is None:
            items.append(
                CampaignRoundGateSemantics(
                    round_id=round_manifest.round_id,
                    emitted=False,
                    round_outcome=round_manifest.outcome.value,
                )
            )
            continue
        gate = ContributionGateResult.model_validate_json(
            _managed_path(campaign_dir, gate_path).read_text(encoding="utf-8")
        )
        decision = (
            RoundDecision.model_validate_json(
                _managed_path(campaign_dir, decision_path).read_text(encoding="utf-8")
            )
            if decision_path is not None
            else None
        )
        items.append(
            CampaignRoundGateSemantics(
                round_id=round_manifest.round_id,
                emitted=True,
                passed=gate.passed,
                failure_count=len(gate.failures),
                warning_count=len(gate.warnings),
                decision=decision.decision.value if decision is not None else None,
                round_outcome=round_manifest.outcome.value,
            )
        )
    emitted = [item for item in items if item.emitted]
    passed = [item for item in emitted if item.passed is True]
    return CampaignGateSemantics(
        rounds=tuple(items),
        emitted_round_count=len(emitted),
        passed_round_count=len(passed),
        failed_round_count=len(emitted) - len(passed),
    )


def _terminal_status(
    outcome: CampaignOutcome,
    *,
    error: Exception | None,
) -> EventStatus:
    if error is not None or outcome is CampaignOutcome.FAILED:
        return EventStatus.FAILED
    if outcome is CampaignOutcome.BLOCKED:
        return EventStatus.BLOCKED
    if outcome is CampaignOutcome.DEADLINE_REACHED:
        return EventStatus.CANCELLED
    if outcome is CampaignOutcome.CONTRIBUTION_READY:
        return EventStatus.SUCCEEDED
    if outcome is CampaignOutcome.STOPPED:
        return EventStatus.NEGATIVE_RESULT
    return EventStatus.PAUSED


def _artifact_bindings(
    *,
    campaign_dir: Path,
    manifest: CampaignManifest,
    rounds: tuple[RoundManifest, ...],
) -> tuple[CampaignArtifactBinding, ...]:
    raw: dict[str, Path] = {
        "campaign_spec": campaign_dir / "campaign-spec.json",
        "campaign_manifest": campaign_dir / "campaign-manifest.json",
    }
    for role, raw_path in manifest.artifact_paths.items():
        raw.setdefault(
            f"campaign_{_safe_component(role)}",
            _managed_path(campaign_dir, raw_path),
        )
    for round_manifest, manifest_path in zip(
        rounds,
        manifest.round_manifest_paths,
        strict=True,
    ):
        prefix = f"round_{round_manifest.round_number:03d}"
        raw[f"{prefix}_manifest"] = _managed_path(campaign_dir, manifest_path)
        for role, raw_path in round_manifest.artifact_paths.items():
            raw[f"{prefix}_{_safe_component(role)}"] = _managed_path(
                campaign_dir,
                raw_path,
            )
        if round_manifest.vault_note_path is not None:
            raw[f"{prefix}_vault_note"] = Path(round_manifest.vault_note_path)

    bindings: list[CampaignArtifactBinding] = []
    for role, artifact_path in sorted(raw.items()):
        resolved = artifact_path.resolve()
        exists = resolved.is_file()
        bindings.append(
            CampaignArtifactBinding(
                role=role,
                logical_path=_logical_artifact_path(
                    campaign_dir=campaign_dir,
                    role=role,
                    path=resolved,
                ),
                exists=exists,
                sha256=_sha256_file(resolved) if exists else None,
                size_bytes=resolved.stat().st_size if exists else None,
            )
        )
    return tuple(bindings)


def _logical_artifact_path(*, campaign_dir: Path, role: str, path: Path) -> str:
    try:
        return path.relative_to(campaign_dir.resolve()).as_posix()
    except ValueError:
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", path.name).strip("-")
        return f"external/{_safe_component(role)}/{safe_name or 'artifact'}"


def _managed_path(campaign_dir: Path, raw_path: str) -> Path:
    root = campaign_dir.resolve()
    path = Path(raw_path)
    candidate = path.resolve() if path.is_absolute() else (root / path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise CampaignMigrationError(
            f"managed Campaign artifact escapes root: {raw_path}"
        ) from exc
    return candidate


def _source_fingerprint(snapshot: CampaignLifecycleSnapshot) -> str:
    return canonical_sha256(
        {
            "service": snapshot.service,
            "campaign_id": snapshot.campaign_id,
            "manifest_hash": snapshot.manifest_hash,
            "failure": (
                snapshot.failure.model_dump(mode="json")
                if snapshot.failure is not None
                else None
            ),
        }
    )


def _expected_event_semantics(
    snapshot: CampaignLifecycleSnapshot,
    *,
    invocation_kind: Literal["run", "resume"],
    migration_mode: CampaignMigrationMode,
    formal_run_id: str | None,
) -> tuple[dict[str, Any], ...]:
    artifacts = {item.role: item for item in snapshot.artifacts}
    start_roles = _existing_roles(artifacts, ("campaign_spec",))
    semantics: list[dict[str, Any]] = [
        {
            "event_type": "campaign.lifecycle.started",
            "status": EventStatus.STARTED.value,
            "action": "Observe legacy Campaign lifecycle",
            "artifact_roles": start_roles,
            "payload": {
                "artifact_roles": start_roles,
                "campaign_id": snapshot.campaign_id,
                "formal_run_id": formal_run_id,
                "invocation_kind": invocation_kind,
                "lifecycle_authority": (
                    "vnext"
                    if migration_mode is CampaignMigrationMode.VNEXT
                    else "legacy"
                ),
                "migration_mode": migration_mode.value,
                "observed_stage": snapshot.stage,
            },
        }
    ]
    for round_item in snapshot.rounds:
        prefix = f"round_{round_item.round_number:03d}"
        for stage_index, stage in enumerate(round_item.stage_history, start=1):
            roles = _stage_artifact_roles(
                artifacts=artifacts,
                prefix=prefix,
                stage=stage,
            )
            semantics.append(
                {
                    "event_type": f"campaign.stage.{stage}.observed",
                    "status": EventStatus.STARTED.value,
                    "action": f"Observe persisted Campaign stage {stage}",
                    "artifact_roles": roles,
                    "payload": {
                        "artifact_roles": roles,
                        "round_id": round_item.round_id,
                        "round_number": round_item.round_number,
                        "stage": stage,
                        "stage_index": stage_index,
                    },
                }
            )
        if round_item.completed:
            roles = sorted(
                role
                for role, binding in artifacts.items()
                if role.startswith(f"{prefix}_") and binding.exists
            )
            gate = next(
                item
                for item in snapshot.gate.rounds
                if item.round_id == round_item.round_id
            )
            semantics.append(
                {
                    "event_type": "campaign.round.finalized",
                    "status": EventStatus.STARTED.value,
                    "action": "Observe finalized Campaign round",
                    "artifact_roles": roles,
                    "payload": {
                        "artifact_roles": roles,
                        "gate": gate.model_dump(mode="json"),
                        "round": round_item.model_dump(mode="json"),
                    },
                }
            )
    terminal_roles = sorted(
        role for role, binding in artifacts.items() if binding.exists
    )
    semantics.append(
        {
            "event_type": "campaign.lifecycle.terminal",
            "status": snapshot.terminal_status.value,
            "action": "Seal Campaign lifecycle observation",
            "artifact_roles": terminal_roles,
            "payload": {"snapshot": snapshot.model_dump(mode="json")},
        }
    )
    return tuple(semantics)


def _stage_artifact_roles(
    *,
    artifacts: Mapping[str, CampaignArtifactBinding],
    prefix: str,
    stage: str,
) -> list[str]:
    suffixes = {
        CampaignStage.OBSERVE.value: ("manifest",),
        CampaignStage.DIAGNOSE.value: ("observation",),
        CampaignStage.PROPOSE.value: ("failure_diagnosis",),
        CampaignStage.SCREEN.value: ("hypothesis",),
        CampaignStage.PREREGISTER.value: ("screening",),
        CampaignStage.DEVELOP.value: ("preregistration",),
        CampaignStage.FREEZE.value: ("development_result",),
        CampaignStage.UNSEEN_EVALUATE.value: ("frozen_protocol",),
        CampaignStage.ADJUDICATE.value: ("unseen_evaluation",),
        CampaignStage.REPORT.value: ("contribution_gate", "round_decision"),
    }.get(stage, ())
    roles = tuple(f"{prefix}_{suffix}" for suffix in suffixes)
    return _existing_roles(artifacts, roles)


def _create_invocation_journal(
    *,
    journal_root: Path,
    migration_root: Path,
    campaign_id: str,
    invocation_index: int,
    previous_report: CampaignParityReport | None,
    created_at: datetime,
) -> EventJournal:
    journal_run_id = (
        f"campaign.{_safe_component(campaign_id)}.vnext.{invocation_index:06d}"
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
        actor_id="service_campaign_legacy_v1",
        kind=ActorKind.SYSTEM,
        version="campaign-migration-v1",
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
            event_id=f"evt_campaign_{source_fingerprint[:16]}_{index:04d}",
            run_id=journal.metadata.run_id,
            task_id=CAMPAIGN_MIGRATION_TASK_ID,
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
) -> CampaignLifecycleSnapshot:
    if not events:
        raise CampaignMigrationError("cannot project an empty Campaign journal")
    terminal = events[-1]
    if terminal.event_type != "campaign.lifecycle.terminal":
        raise CampaignMigrationError("Campaign journal lacks a terminal lifecycle event")
    payload = terminal.payload.get("snapshot")
    if not isinstance(payload, dict):
        raise CampaignMigrationError("Campaign terminal event lacks a snapshot")
    return CampaignLifecycleSnapshot.model_validate(payload)


def _control_projection(
    *,
    campaign_id: str,
    invocation_index: int,
    events: list[RunEvent],
) -> GraphSnapshot:
    nodes = [
        GraphNode(
            node_id=f"node_{event.event_id}",
            plane=GraphPlane.CONTROL,
            node_type="campaign.event",
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
            edge_id=f"edge_campaign_{invocation_index:06d}_{index:04d}",
            plane=GraphPlane.CONTROL,
            edge_type="campaign.precedes",
            source_id=nodes[index - 1].node_id,
            target_id=nodes[index].node_id,
        )
        for index in range(1, len(nodes))
    ]
    return GraphSnapshot(
        graph_id=f"graph_campaign_{_safe_component(campaign_id)}",
        version=invocation_index,
        plane=GraphPlane.CONTROL,
        control_cycle_policy=ControlCyclePolicy.ACYCLIC,
        nodes=nodes,
        edges=edges,
        metadata={
            "service": "campaign",
            "migration_task_id": CAMPAIGN_MIGRATION_TASK_ID,
            "legacy_campaign_id": campaign_id,
        },
    )


def _parity_checks(
    *,
    legacy: CampaignLifecycleSnapshot,
    projected: CampaignLifecycleSnapshot,
    expected_event_semantics: tuple[dict[str, Any], ...],
    projected_event_semantics: tuple[dict[str, Any], ...],
) -> tuple[CampaignParityCheck, ...]:
    values: tuple[tuple[str, Any, Any], ...] = (
        ("events", expected_event_semantics, projected_event_semantics),
        (
            "terminal_state",
            {
                "stage": legacy.stage,
                "outcome": legacy.outcome,
                "terminal_status": legacy.terminal_status.value,
                "current_round_id": legacy.current_round_id,
            },
            {
                "stage": projected.stage,
                "outcome": projected.outcome,
                "terminal_status": projected.terminal_status.value,
                "current_round_id": projected.current_round_id,
            },
        ),
        (
            "scientific_endpoint",
            {
                "scientific_endpoint": legacy.scientific_endpoint,
                "lineage_hash": legacy.lineage_hash,
                "rounds": [
                    item.model_dump(mode="json") for item in legacy.rounds
                ],
                "round_count": legacy.round_count,
                "completed_round_count": legacy.completed_round_count,
                "experimental_round_count": legacy.experimental_round_count,
                "minimum_experimental_rounds": legacy.minimum_experimental_rounds,
            },
            {
                "scientific_endpoint": projected.scientific_endpoint,
                "lineage_hash": projected.lineage_hash,
                "rounds": [
                    item.model_dump(mode="json") for item in projected.rounds
                ],
                "round_count": projected.round_count,
                "completed_round_count": projected.completed_round_count,
                "experimental_round_count": projected.experimental_round_count,
                "minimum_experimental_rounds": projected.minimum_experimental_rounds,
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
            {"human_intervention_count": legacy.human_intervention_count},
            {"human_intervention_count": projected.human_intervention_count},
        ),
    )
    return tuple(
        CampaignParityCheck(
            name=name,  # type: ignore[arg-type]
            passed=_json_sha256(old) == _json_sha256(new),
            legacy_sha256=_json_sha256(old),
            projected_sha256=_json_sha256(new),
        )
        for name, old, new in values
    )


def _campaign_result_from_projection(
    campaign_dir: Path,
    projection: CampaignLifecycleSnapshot,
) -> CampaignResult:
    resolved = campaign_dir.resolve()
    return CampaignResult(
        campaign_dir=resolved.as_posix(),
        manifest_path=(resolved / "campaign-manifest.json").as_posix(),
        outcome=CampaignOutcome(projection.outcome),
        stage=CampaignStage(projection.stage),
        completed_round_count=projection.completed_round_count,
        experimental_round_count=projection.experimental_round_count,
        human_intervention_count=projection.human_intervention_count,
        current_round_id=projection.current_round_id,
    )


def _find_existing_report(
    campaign_migration_root: Path,
    source_fingerprint: str,
) -> CampaignParityReport | None:
    return next(
        (
            report
            for report in _load_reports(campaign_migration_root)
            if report.source_fingerprint == source_fingerprint
        ),
        None,
    )


def _load_reports(campaign_migration_root: Path) -> list[CampaignParityReport]:
    invocations = campaign_migration_root / "invocations"
    if not invocations.is_dir():
        return []
    reports: list[CampaignParityReport] = []
    for path in sorted(invocations.glob("*/parity-report.json")):
        report = CampaignParityReport.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        root = _root_for_campaign(campaign_migration_root)
        journal = EventJournal.open(_resolve_under_root(root, report.journal_path))
        snapshot = journal.snapshot()
        if len(snapshot.events) != report.journal_event_count:
            raise CampaignMigrationError(
                f"journal event count changed for invocation {report.invocation_index}"
            )
        if snapshot.lineage_hash != report.journal_lineage_hash:
            raise CampaignMigrationError(
                f"journal lineage changed for invocation {report.invocation_index}"
            )
        if snapshot.seal is None or snapshot.seal.seal_hash != report.journal_seal_hash:
            raise CampaignMigrationError(
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
            or not report.equivalent
            or not report.legacy_compatibility_files_retained
            or _json_sha256(expected_semantics)
            != report.expected_event_semantics_sha256
            or _json_sha256(projected_semantics)
            != report.projected_event_semantics_sha256
            or _source_fingerprint(report.legacy) != report.source_fingerprint
        ):
            raise CampaignMigrationError(
                f"parity report changed for invocation {report.invocation_index}"
            )
        control_path = _resolve_under_root(root, report.control_projection_path)
        control = GraphSnapshot.model_validate_json(
            control_path.read_text(encoding="utf-8")
        )
        expected_control = _control_projection(
            campaign_id=report.legacy.campaign_id,
            invocation_index=report.invocation_index,
            events=snapshot.events,
        )
        if control != expected_control:
            raise CampaignMigrationError(
                f"control projection changed for invocation {report.invocation_index}"
            )
        reports.append(report)
    expected = list(range(1, len(reports) + 1))
    actual = [report.invocation_index for report in reports]
    if actual != expected:
        raise CampaignMigrationError("Campaign invocation index sequence is invalid")
    return reports


def _root_for_campaign(campaign_migration_root: Path) -> Path:
    if campaign_migration_root.parent.name != "campaigns":
        raise CampaignMigrationError("invalid Campaign migration path")
    return campaign_migration_root.parent.parent


def _write_terminal_idempotency_report(
    *,
    campaign_migration_root: Path,
    existing: CampaignParityReport,
    requested_invocation_kind: Literal["run", "resume"],
    requested_mode: CampaignMigrationMode,
) -> Path:
    root = _root_for_campaign(campaign_migration_root)
    journal = EventJournal.open(root / existing.journal_path)
    first = journal.snapshot()
    second = journal.snapshot()
    unchanged_manifest = (
        existing.legacy.manifest_hash == existing.projected.manifest_hash
    )
    unchanged_lineage = (
        first.lineage_hash == second.lineage_hash == existing.journal_lineage_hash
    )
    report = CampaignTerminalIdempotencyReport(
        campaign_id=existing.legacy.campaign_id,
        source_fingerprint=existing.source_fingerprint,
        requested_invocation_kind=requested_invocation_kind,
        requested_migration_mode=requested_mode,
        original_invocation_index=existing.invocation_index,
        original_event_count=existing.journal_event_count,
        observed_event_count=len(second.events),
        manifest_hash_unchanged=unchanged_manifest,
        lineage_hash_unchanged=unchanged_lineage,
        passed=(
            existing.journal_event_count == len(second.events)
            and unchanged_manifest
            and unchanged_lineage
        ),
    )
    path = (
        campaign_migration_root
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
    resolved_root = root.resolve()
    candidate = (resolved_root / relative_path).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise CampaignMigrationError(
            f"migration artifact path escapes root: {relative_path}"
        ) from exc
    return candidate


def _existing_roles(
    artifacts: Mapping[str, CampaignArtifactBinding],
    roles: tuple[str, ...],
) -> list[str]:
    return [role for role in roles if role in artifacts and artifacts[role].exists]


def _failed_check_names(report: CampaignParityReport) -> str:
    return ", ".join(check.name for check in report.checks if not check.passed)


def _report_path_for(report: CampaignParityReport) -> str:
    return (Path(report.journal_path).parent / "parity-report.json").as_posix()


__all__ = [
    "CAMPAIGN_FORMAL_RUN_ENV",
    "CAMPAIGN_MIGRATION_MODE_ENV",
    "CampaignArtifactBinding",
    "CampaignCutoverNotReadyError",
    "CampaignFailureSemantics",
    "CampaignFormalRunRecord",
    "CampaignGateSemantics",
    "CampaignLifecycleSnapshot",
    "CampaignMigrationCoordinator",
    "CampaignMigrationError",
    "CampaignMigrationMode",
    "CampaignParityCheck",
    "CampaignParityError",
    "CampaignParityReport",
    "CampaignPromotionLedger",
    "CampaignRollbackReport",
    "CampaignRoundGateSemantics",
    "CampaignRoundSemantics",
    "CampaignTerminalIdempotencyReport",
    "rehearse_campaign_rollback",
    "resolve_campaign_formal_run_id",
    "resolve_campaign_migration_mode",
]
