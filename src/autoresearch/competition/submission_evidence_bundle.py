"""One fail-closed audit for a competition submission evidence lineage.

This module does not invent scientific prose and does not repair historical evidence.
It reads the retained lineage, replays deterministic calculations, verifies raw
provider/source/cell bytes, compares configured and recorded model identities, and
writes a Chinese audit report.  Every absent or contradictory proof remains a failed
check.  Scientific producers permanently refuse to self-authorize publication; a
separate explicit human authorization must bind every final artifact and the source
commit before the deterministic audit can label the lineage submission-ready.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from autoresearch.competition.autonomous_engine import AutonomousModelInteraction
from autoresearch.competition.final_research_report import (
    FinalReportBuildReceipt,
    FinalResearchReport,
    audit_final_report_inputs,
)
from autoresearch.competition.language_guard import non_chinese_prose_fields
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.model_authorship import (
    ModelAuthorshipReceipt,
    load_bound_authorship_receipt,
    outcome_authored_fields,
    plan_authored_fields,
)
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.competition.official_baseline_policy import PAIRED, load_baseline_policy
from autoresearch.competition.official_development_search import (
    _SPLIT_POLICY,
    OfficialCandidateRecord,
    OfficialCellResult,
    OfficialCellSpec,
    OfficialDevelopmentIdentity,
    OfficialDevelopmentSearchPackage,
    aggregate_paired_effects,
    baseline_method_for,
    compute_system_effects,
    select_official_candidate,
)
from autoresearch.competition.official_spend_ledger import OfficialSpendLedger
from autoresearch.competition.plan_execution_contract import (
    ProspectivePlanExecutionContract,
    compile_system_authored_plan_execution_contract,
    load_prospective_plan_execution_contract,
    require_prospective_candidate_plan_alignment,
)
from autoresearch.competition.preregistered_stage_breadth import load_stage_breadth
from autoresearch.competition.publication_signature import (
    PublicationSignatureError,
    verify_human_publication_signature,
)
from autoresearch.competition.scientific_contract_harness import (
    ScientificContractSourceResponse,
)
from autoresearch.competition.system_authored_outcome import SystemAuthoredOutcome
from autoresearch.competition.system_authored_plan import (
    SystemAuthoredPlanArtifact,
    authored_plan_non_chinese_fields,
)
from autoresearch.config import ConfigParser, SystemConfig
from autoresearch.kernel.contracts import canonical_json
from autoresearch.knowledge.raw_memory import RawMemoryRecord
from autoresearch.research.plan_confirmation import (
    load_plan_decision,
    require_approved_plan,
)
from autoresearch.schemas import ResearchPlan, file_hash

_BUNDLE_NAME = "submission-evidence-bundle.json"
_MARKDOWN_NAME = "submission-evidence-bundle.md"
_QUALITY_NAME = "submission-quality-gate-receipt.json"
_INNOVATION_NAME = "publication-innovation-audit.json"
_REEXECUTION_NAME = "independent-reexecution-receipt.json"
_PUBLICATION_AUTHORIZATION_NAME = "human-publication-authorization.json"

_UNTRACKED_OUTPUT_ROOTS = ("runs", "artifacts", "outputs")
_UNTRACKED_CACHE_DIRS = {
    ".cache",
    ".codex-remote-attachments",
    ".hypothesis",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "htmlcov",
}
_UNTRACKED_CACHE_FILES = {".coverage"}
_CANONICAL_CONFIG_RELATIVE_PATH = "config.yaml"
_LOCAL_SECRET_ENV_RELATIVE_PATH = ".env"
_SOVEREIGN_PRIVATE_CONTAINER = Path("autoresearch-vault") / "_private"
_SOVEREIGN_RAW_MEMORY_ROOT = _SOVEREIGN_PRIVATE_CONTAINER / "raw-memory"

_CHECK_TITLES: dict[str, str] = {
    "plan_model_authorship_provenance": "研究计划模型作者来源",
    "plan_is_chinese_and_guarded": "研究计划中文与自动门禁",
    "human_plan_approval_boundary": "人工计划批准边界",
    "plan_to_code_alignment": "批准计划到候选代码对齐",
    "candidate_model_authorship_provenance": "候选代码模型作者来源",
    "executed_cell_provenance": "已执行实验单元逐层来源",
    "signed_package_semantics": "签名结果包与冻结门禁语义",
    "numeric_claim_semantics": "数值来源与算术关系",
    "configured_model_identity_matches": "配置与记录模型身份一致性",
    "innovation_evidence_audited": "创新性与最近先前工作审计",
    "reproducibility_package_complete": "复现材料完整性",
    "deterministic_result_replay": "确定性结果重算",
    "independent_scientific_reexecution": "独立科学重执行",
    "final_report_cross_format_integrity": "最终报告跨格式一致性",
    "broad_quality_gates": "广泛代码质量门",
    "required_audits_present": "必需审计齐备性",
    "human_approval_not_scientific_evidence": "人工批准不充当科学证据",
    "human_publication_authorization": "人工最终发表与提交授权",
    "publication_readiness": "发表与提交就绪状态",
    "secrets_absent": "证据包未记录凭据值",
}
_REQUIRED_CHECKS = tuple(_CHECK_TITLES)
_REQUIRED_GATE_NAMES = {
    "all_candidate_cells_succeeded",
    "all_baseline_cells_succeeded",
    "overall_median_at_least_minimum",
    "bootstrap_lower_above_zero",
    "ode_stratum_non_negative",
    "pde_stratum_non_negative",
    "budget_conformant",
}

_PLAN_ARTIFACT = "system-authored-research-plan.json"
_APPROVED_PLAN = Path("plan") / "research-plan.json"
_PACKAGE = "official-development-search-package.json"
_OUTCOME = "system-authored-outcome.json"
_FINAL_DIR = "final-report"
_FINAL_REPORT = "final-research-report.json"
_FINAL_BUILD = "final-research-report-build.json"


class SubmissionEvidenceError(RuntimeError):
    """Raised only when the audit artifact itself cannot be constructed safely."""


class SubmissionAuditCheck(StrictFrozenModel):
    """One deterministic, Chinese-labelled blocking submission check."""

    name: str
    title_zh: str
    passed: bool
    findings: tuple[str, ...] = ()
    evidence_paths: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate(self) -> SubmissionAuditCheck:
        if self.title_zh != _CHECK_TITLES.get(self.name):
            raise SubmissionEvidenceError("submission check title/name mismatch")
        if self.passed != (not self.findings):
            raise SubmissionEvidenceError(
                f"submission check verdict contradicts findings: {self.name}"
            )
        return self


class ConfiguredModelIdentity(StrictFrozenModel):
    """Credential-free model identity read from the audited configuration."""

    provider: str
    base_url: str
    model_name: str
    config_path: str
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    api_key_env_name: str
    api_key_value_logged: Literal[False] = False


class RecordedModelIdentity(StrictFrozenModel):
    """Identity retained by one exact provider transaction."""

    artifact_role: Literal["research_plan", "candidate_code", "outcome"]
    interaction_id: str
    provider: str
    base_url: str
    model_name: str
    endpoint: str
    interaction_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    api_key_value_logged: Literal[False] = False


class SubmissionArtifactDigest(StrictFrozenModel):
    """One file included in or consulted by the audit."""

    role: str
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_count: int = Field(ge=0)


class QualityCommandResult(StrictFrozenModel):
    """One executed broad quality command with hashed output."""

    name: Literal["pytest", "ruff", "mypy"]
    command: tuple[str, ...]
    exit_code: int
    skipped_count: int = Field(ge=0)
    deselected_count: int = Field(ge=0)
    duration_seconds: float = Field(ge=0.0)
    stdout_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stderr_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    log_relative_path: str
    log_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    log_byte_count: int = Field(ge=1)
    passed: bool

    @model_validator(mode="after")
    def _validate(self) -> QualityCommandResult:
        expected_command = _canonical_quality_commands()[self.name]
        if self.command != expected_command:
            raise SubmissionEvidenceError(
                f"quality command differs from the frozen production command: {self.name}"
            )
        if self.log_relative_path != f"quality-logs/{self.name}.log":
            raise SubmissionEvidenceError(
                f"quality log path differs from the frozen contract: {self.name}"
            )
        expected = (
            self.exit_code == 0
            and self.skipped_count == 0
            and self.deselected_count == 0
        )
        if self.passed != expected:
            raise SubmissionEvidenceError(
                f"quality result contradicts command outcome: {self.name}"
            )
        return self


class SubmissionQualityGateReceipt(StrictFrozenModel):
    """Source-commit-bound receipt for the three broad code gates."""

    schema_version: Literal["submission-quality-gate-receipt-v3"] = (
        "submission-quality-gate-receipt-v3"
    )
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    configuration_relative_path: Literal["config.yaml"] = "config.yaml"
    configuration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    local_secret_env_excluded: Literal[True] = True
    sovereign_raw_memory_excluded: Literal[True] = True
    tracked_worktree_clean: bool
    command_contract_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    commands: tuple[QualityCommandResult, ...]
    all_passed: bool
    created_at: datetime
    receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str

    @model_validator(mode="after")
    def _validate(self) -> SubmissionQualityGateReceipt:
        if len(self.commands) != 3 or {item.name for item in self.commands} != {
            "pytest",
            "ruff",
            "mypy",
        }:
            raise SubmissionEvidenceError("quality receipt omits a required command")
        if self.command_contract_hash != _quality_command_contract_hash():
            raise SubmissionEvidenceError(
                "quality receipt does not use the frozen production command contract"
            )
        expected_pass = self.tracked_worktree_clean and all(
            item.passed for item in self.commands
        )
        if self.all_passed != expected_pass:
            raise SubmissionEvidenceError(
                "quality receipt verdict contradicts command or worktree state"
            )
        expected_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"receipt_hash", "output_path"})
        )
        if self.receipt_hash != expected_hash:
            raise SubmissionEvidenceError("quality receipt hash mismatch")
        return self


class PublicationInnovationAudit(StrictFrozenModel):
    """System-authored novelty comparison required before publication claims."""

    schema_version: Literal["publication-innovation-audit-v1"] = (
        "publication-innovation-audit-v1"
    )
    lineage_id: str
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    literature_survey_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    novelty_claims: tuple[str, ...] = Field(min_length=1)
    nearest_prior_work_comparisons: tuple[str, ...] = Field(min_length=3)
    overlap_risks: tuple[str, ...] = Field(min_length=1)
    novelty_supported: bool
    positive_method_effect_supported: bool
    publication_innovation_ready: bool
    authorship_receipt_relative_path: str
    authorship_receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    authored_by_model: Literal[True] = True
    hand_written_scientific_prose_count: Literal[0] = 0
    is_scientific_evidence: Literal[False] = False
    publication_ready: Literal[False] = False
    audit_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str

    @model_validator(mode="after")
    def _validate(self) -> PublicationInnovationAudit:
        expected_ready = self.novelty_supported and self.positive_method_effect_supported
        if self.publication_innovation_ready != expected_ready:
            raise SubmissionEvidenceError(
                "innovation readiness contradicts novelty/effect findings"
            )
        prose = {
            "novelty_claims": self.novelty_claims,
            "nearest_prior_work_comparisons": self.nearest_prior_work_comparisons,
            "overlap_risks": self.overlap_risks,
        }
        if non_chinese_prose_fields(prose):
            raise SubmissionEvidenceError(
                "innovation audit scientific prose is not predominantly Chinese"
            )
        expected_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"audit_hash", "output_path"})
        )
        if self.audit_hash != expected_hash:
            raise SubmissionEvidenceError("innovation audit hash mismatch")
        return self


class ReexecutionCellArtifact(StrictFrozenModel):
    """One independently reexecuted raw cell result retained as a real file."""

    attempt_id: str = Field(min_length=1)
    relative_path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_count: int = Field(ge=1)


class IndependentReexecutionManifest(StrictFrozenModel):
    """Content-addressed inventory of every independent raw cell result."""

    schema_version: Literal["independent-reexecution-manifest-v1"] = (
        "independent-reexecution-manifest-v1"
    )
    lineage_id: str = Field(min_length=1)
    package_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    cell_artifacts: tuple[ReexecutionCellArtifact, ...] = Field(min_length=1)
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str

    @model_validator(mode="after")
    def _validate(self) -> IndependentReexecutionManifest:
        attempt_ids = [item.attempt_id for item in self.cell_artifacts]
        paths = [item.relative_path for item in self.cell_artifacts]
        if len(set(attempt_ids)) != len(attempt_ids):
            raise SubmissionEvidenceError(
                "independent reexecution manifest repeats a cell attempt"
            )
        if len(set(paths)) != len(paths):
            raise SubmissionEvidenceError(
                "independent reexecution manifest repeats an artifact path"
            )
        expected_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"manifest_hash", "output_path"})
        )
        if self.manifest_hash != expected_hash:
            raise SubmissionEvidenceError("independent reexecution manifest hash mismatch")
        return self


class IndependentReexecutionReceipt(StrictFrozenModel):
    """Proof that a clean second run re-executed every scientific cell."""

    schema_version: Literal["independent-reexecution-receipt-v2"] = (
        "independent-reexecution-receipt-v2"
    )
    lineage_id: str
    package_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    clean_output_directory: str = Field(min_length=1)
    artifact_manifest_relative_path: str = Field(min_length=1)
    artifact_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_manifest_byte_count: int = Field(ge=1)
    artifact_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reexecuted_cell_count: int = Field(ge=1)
    expected_cell_count: int = Field(ge=1)
    all_cells_reexecuted: bool
    aggregate_metrics_match: bool
    gate_verdict_matches: bool
    network_disabled: bool
    passed: bool
    created_at: datetime
    receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str

    @model_validator(mode="after")
    def _validate(self) -> IndependentReexecutionReceipt:
        expected_all = self.reexecuted_cell_count == self.expected_cell_count
        if self.all_cells_reexecuted != expected_all:
            raise SubmissionEvidenceError(
                "reexecution cell-completeness verdict contradicts counts"
            )
        expected_passed = (
            self.all_cells_reexecuted
            and self.aggregate_metrics_match
            and self.gate_verdict_matches
            and self.network_disabled
        )
        if self.passed != expected_passed:
            raise SubmissionEvidenceError(
                "independent reexecution verdict contradicts its checks"
            )
        expected_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"receipt_hash", "output_path"})
        )
        if self.receipt_hash != expected_hash:
            raise SubmissionEvidenceError("independent reexecution hash mismatch")
        return self


_HUMAN_PUBLICATION_STATEMENT = (
    "我已审阅并授权将上述哈希绑定的材料用于本次提交；"
    "该授权仅是发表与提交决定，不构成科学证据。"
)


class HumanPublicationAuthorization(StrictFrozenModel):
    """Explicit human release decision bound to every final immutable artifact.

    Upstream scientific artifacts intentionally keep ``publication_ready=false``:
    neither Qwen nor a deterministic builder may grant itself permission to publish.
    This record is process authorization only and can never repair a failed scientific
    gate or become an evidence reference.
    """

    schema_version: Literal["human-publication-authorization-v2"] = (
        "human-publication-authorization-v2"
    )
    lineage_id: str = Field(min_length=1)
    decision: Literal["authorize"] = "authorize"
    authorized_by: str = Field(min_length=1)
    authorization_statement: Literal[
        "我已审阅并授权将上述哈希绑定的材料用于本次提交；"
        "该授权仅是发表与提交决定，不构成科学证据。"
    ] = (
        "我已审阅并授权将上述哈希绑定的材料用于本次提交；"
        "该授权仅是发表与提交决定，不构成科学证据。"
    )
    notes: str = Field(min_length=1)
    plan_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_decision_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    signed_package_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    final_report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    final_report_build_receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    innovation_audit_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reexecution_receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality_gate_receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    authorization_request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    signature_base64: str = Field(min_length=1)
    signer_public_key_pem: str = Field(min_length=1)
    signer_public_key_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    authorized_at: datetime
    authored_by_model: Literal[False] = False
    is_scientific_evidence: Literal[False] = False
    evidence_refs: tuple[()] = ()
    changes_scientific_verdict: Literal[False] = False
    authorization_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str

    @model_validator(mode="after")
    def _validate(self) -> HumanPublicationAuthorization:
        if self.evidence_refs:
            raise SubmissionEvidenceError(
                "human publication authorization must never carry evidence refs"
            )
        expected_request_hash = _human_publication_authorization_request_hash(
            self.model_dump(mode="json")
        )
        if self.authorization_request_hash != expected_request_hash:
            raise SubmissionEvidenceError(
                "human publication authorization request hash mismatch"
            )
        expected_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"authorization_hash", "output_path"})
        )
        if self.authorization_hash != expected_hash:
            raise SubmissionEvidenceError("human publication authorization hash mismatch")
        return self


class SubmissionEvidenceBundle(StrictFrozenModel):
    """Canonical answer to whether one lineage is honestly submission-ready."""

    schema_version: Literal["submission-evidence-bundle-v1"] = (
        "submission-evidence-bundle-v1"
    )
    lineage_id: str
    checks: tuple[SubmissionAuditCheck, ...]
    configured_model_identity: ConfiguredModelIdentity | None = None
    recorded_model_identities: tuple[RecordedModelIdentity, ...] = ()
    artifacts: tuple[SubmissionArtifactDigest, ...] = ()
    executed_cell_count: int = Field(ge=0)
    raw_cell_result_count: int = Field(ge=0)
    scientific_experiment_independently_reexecuted: bool
    human_approval_is_scientific_evidence: Literal[False] = False
    publication_ready: bool
    submission_ready: bool
    blocking_findings: tuple[str, ...]
    created_at: datetime
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str

    @model_validator(mode="after")
    def _validate(self) -> SubmissionEvidenceBundle:
        by_name = {item.name: item for item in self.checks}
        if set(by_name) != set(_REQUIRED_CHECKS) or len(by_name) != len(self.checks):
            raise SubmissionEvidenceError(
                "submission bundle does not cover every required check exactly once"
            )
        expected_publication = (
            by_name["publication_readiness"].passed
            and by_name["secrets_absent"].passed
        )
        if self.publication_ready != expected_publication:
            raise SubmissionEvidenceError(
                "bundle publication flag contradicts publication-readiness check"
            )
        expected_ready = all(item.passed for item in self.checks)
        if self.submission_ready != expected_ready:
            raise SubmissionEvidenceError(
                "submission-ready flag contradicts blocking checks"
            )
        expected_findings = tuple(
            finding for item in self.checks for finding in item.findings
        )
        if self.blocking_findings != expected_findings:
            raise SubmissionEvidenceError(
                "bundle blocking findings differ from failed checks"
            )
        if not self.publication_ready and self.submission_ready:
            raise SubmissionEvidenceError(
                "submission-ready is forbidden while publication_ready=false"
            )
        expected_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"bundle_hash", "output_path"})
        )
        if self.bundle_hash != expected_hash:
            raise SubmissionEvidenceError("submission evidence bundle hash mismatch")
        return self


@dataclass(frozen=True)
class _CellAudit:
    provenance_passed: bool
    reproducibility_complete: bool
    findings: tuple[str, ...]
    reproducibility_findings: tuple[str, ...]
    artifact_paths: tuple[Path, ...]
    executed_count: int
    raw_result_count: int


class _CheckLedger:
    def __init__(self) -> None:
        self._checks: dict[str, SubmissionAuditCheck] = {}

    def record(
        self,
        name: str,
        *,
        findings: Sequence[str] = (),
        evidence_paths: Sequence[str] = (),
    ) -> None:
        unique_findings = tuple(dict.fromkeys(str(item) for item in findings if item))
        unique_paths = tuple(dict.fromkeys(str(item) for item in evidence_paths if item))
        self._checks[name] = SubmissionAuditCheck(
            name=name,
            title_zh=_CHECK_TITLES[name],
            passed=not unique_findings,
            findings=unique_findings,
            evidence_paths=unique_paths,
        )

    def finish(self) -> tuple[SubmissionAuditCheck, ...]:
        for name in _REQUIRED_CHECKS:
            if name not in self._checks:
                self.record(name, findings=("该必需检查未执行。",))
        return tuple(self._checks[name] for name in _REQUIRED_CHECKS)


def _load_formal_prospective_plan_contract(
    root: Path,
) -> tuple[
    SystemAuthoredPlanArtifact,
    ResearchPlan,
    ProspectivePlanExecutionContract,
]:
    """Load and recompile the only plan/contract shape eligible for submission."""

    artifact = SystemAuthoredPlanArtifact.model_validate_json(
        (root / _PLAN_ARTIFACT).read_text(encoding="utf-8")
    )
    if artifact.schema_version != "system-authored-research-plan-v2":
        raise SubmissionEvidenceError(
            "formal submission requires SystemAuthoredPlanArtifact v2"
        )
    plan = ResearchPlan.model_validate_json(
        (root / _APPROVED_PLAN).read_text(encoding="utf-8")
    )
    if artifact.lineage_id != root.name:
        raise SubmissionEvidenceError("plan artifact belongs to another lineage")
    if artifact.plan != plan.model_dump(mode="json"):
        raise SubmissionEvidenceError("approved plan differs from system plan artifact")
    expected_contract = compile_system_authored_plan_execution_contract(artifact)
    retained_contract = load_prospective_plan_execution_contract(root)
    if retained_contract != expected_contract:
        raise SubmissionEvidenceError(
            "retained prospective contract differs from the exact artifact compilation"
        )
    if (
        retained_contract.selected_intervention_identity
        != expected_contract.selected_intervention_identity
        or retained_contract.implementation_anchor
        != expected_contract.implementation_anchor
        or retained_contract.paired_control_treatment
        != expected_contract.paired_control_treatment
    ):
        raise SubmissionEvidenceError(
            "prospective intervention identity or paired control/treatment drifted"
        )
    return artifact, plan, retained_contract


def prepare_human_publication_authorization_request(
    *,
    lineage_dir: Path | str,
    authorized_by: str,
    notes: str,
    repository_root: Path | str = Path("."),
    quality_receipt_path: Path | str | None = None,
    clock: datetime | None = None,
) -> dict[str, Any]:
    """Build the exact objective request that must be signed outside AutoResearch.

    This function never changes a scientific verdict or writes an authorization. It
    refuses to produce a request until
    the already-generated artifacts prove that all frozen gates, numeric audits,
    innovation/effect review, independent reexecution, renderings, and broad source
    checks passed. The returned request hash is the only value an external human
    signer signs; no private key is available to this module.
    """

    root = Path(lineage_dir).resolve()
    repo = Path(repository_root).resolve()
    if not authorized_by.strip() or not notes.strip():
        raise SubmissionEvidenceError(
            "human publication authorization requires an identity and non-empty notes"
        )

    plan_artifact, plan, contract = _load_formal_prospective_plan_contract(root)
    decision_path = _plan_decision_path(root, plan.project_id)
    decision = load_plan_decision(project_id=plan.project_id, output_dir=root / "plan")
    require_approved_plan(plan=plan, decision=decision)

    package = OfficialDevelopmentSearchPackage.model_validate_json(
        (root / _PACKAGE).read_text(encoding="utf-8")
    )
    if not package.gate_checks or not all(package.gate_checks.values()):
        raise SubmissionEvidenceError(
            "human authorization cannot override a failed frozen scientific gate"
        )
    if not package.search_freeze_receipt_issued:
        raise SubmissionEvidenceError("signed package has no valid search-freeze receipt")
    selected = next(
        (
            candidate
            for candidate in package.candidates
            if candidate.candidate_id == package.selected_candidate_id
        ),
        None,
    )
    if selected is None:
        raise SubmissionEvidenceError(
            "signed package has no selected candidate in its registry"
        )
    require_prospective_candidate_plan_alignment(
        candidates=[selected], contract=contract
    )
    selected_source = _inside(root, selected.source_relative_path)
    if not selected_source.is_file() or file_hash(selected_source) != selected.source_sha256:
        raise SubmissionEvidenceError(
            "selected prospective candidate source is missing or hash-mismatched"
        )

    outcome = SystemAuthoredOutcome.model_validate_json(
        (root / _OUTCOME).read_text(encoding="utf-8")
    )
    if outcome.package_hash != package.package_hash or not outcome.accepted:
        raise SubmissionEvidenceError(
            "system-authored outcome is absent, refused, or bound to another package"
        )
    if outcome.relation_audit is None or not outcome.relation_audit.passed:
        raise SubmissionEvidenceError("system-authored outcome lacks a green relation audit")

    report_path = root / _FINAL_DIR / _FINAL_REPORT
    build_path = root / _FINAL_DIR / _FINAL_BUILD
    report = FinalResearchReport.model_validate_json(
        report_path.read_text(encoding="utf-8")
    )
    build = FinalReportBuildReceipt.model_validate_json(
        build_path.read_text(encoding="utf-8")
    )
    if (
        report.lineage_id != root.name
        or report.plan_artifact_hash != plan_artifact.artifact_hash
        or report.system_authored_plan_artifact != plan_artifact
        or report.prospective_plan_execution_contract != contract
        or report.plan_execution_contract_hash != contract.contract_hash
        or report.selected_candidate_source_sha256 != selected.source_sha256
        or report.package_hash != package.package_hash
        or report.outcome_hash != outcome.outcome_hash
        or build.report_hash != report.report_hash
        or not build.pdf_compiled
        or not build.all_renderings_consistent
    ):
        raise SubmissionEvidenceError(
            "final report or its cross-format build does not bind the green lineage"
        )

    innovation = PublicationInnovationAudit.model_validate_json(
        (root / _INNOVATION_NAME).read_text(encoding="utf-8")
    )
    if (
        innovation.lineage_id != root.name
        or innovation.plan_hash != plan_artifact.plan_hash
        or not innovation.publication_innovation_ready
    ):
        raise SubmissionEvidenceError(
            "innovation and positive-effect audit is not ready for publication"
        )

    reexecution = IndependentReexecutionReceipt.model_validate_json(
        (root / _REEXECUTION_NAME).read_text(encoding="utf-8")
    )
    if (
        reexecution.lineage_id != root.name
        or reexecution.package_hash != package.package_hash
        or not reexecution.passed
    ):
        raise SubmissionEvidenceError("independent scientific reexecution did not pass")

    quality_path = _contained_quality_receipt_path(root, quality_receipt_path)
    quality = SubmissionQualityGateReceipt.model_validate_json(
        quality_path.read_text(encoding="utf-8")
    )
    _verify_quality_receipt_artifacts(receipt=quality, receipt_path=quality_path)
    _verify_quality_runtime_configuration(receipt=quality, repository_root=repo)
    source_commit = _git_text(repo, "rev-parse", "HEAD")
    if quality.source_commit != source_commit or not quality.all_passed:
        raise SubmissionEvidenceError(
            "broad quality receipt is red or bound to another source commit"
        )
    if not _tracked_worktree_clean(
        repo, expected_config_sha256=quality.configuration_sha256
    ):
        raise SubmissionEvidenceError(
            "source worktree changed after the broad quality receipt"
        )
    _verify_reexecution_evidence(
        root=root,
        package=package,
        receipt=reexecution,
        current_source_commit=source_commit,
        quality_source_commit=quality.source_commit,
    )

    now = clock or datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "schema_version": "human-publication-authorization-request-v1",
        "lineage_id": root.name,
        "decision": "authorize",
        "authorized_by": authorized_by.strip(),
        "authorization_statement": _HUMAN_PUBLICATION_STATEMENT,
        "notes": notes.strip(),
        "plan_artifact_hash": plan_artifact.artifact_hash,
        "plan_decision_file_sha256": file_hash(decision_path),
        "signed_package_hash": package.package_hash,
        "outcome_hash": outcome.outcome_hash,
        "final_report_hash": report.report_hash,
        "final_report_build_receipt_hash": build.receipt_hash,
        "innovation_audit_hash": innovation.audit_hash,
        "reexecution_receipt_hash": reexecution.receipt_hash,
        "quality_gate_receipt_hash": quality.receipt_hash,
        "source_commit": source_commit,
        "authorized_at": now.astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "authored_by_model": False,
        "is_scientific_evidence": False,
        "evidence_refs": (),
        "changes_scientific_verdict": False,
    }
    request_hash = _human_publication_authorization_request_hash(payload)
    payload["authorization_request_hash"] = request_hash
    return payload


def record_human_publication_authorization(
    *,
    lineage_dir: Path | str,
    authorized_by: str,
    notes: str,
    signature_base64: str,
    signer_public_key_pem: str,
    trusted_public_key_sha256: str,
    repository_root: Path | str = Path("."),
    quality_receipt_path: Path | str | None = None,
    clock: datetime | None = None,
) -> HumanPublicationAuthorization:
    """Verify an external signature and record the exact authorized snapshot."""

    root = Path(lineage_dir).resolve()
    payload = prepare_human_publication_authorization_request(
        lineage_dir=root,
        authorized_by=authorized_by,
        notes=notes,
        repository_root=repository_root,
        quality_receipt_path=quality_receipt_path,
        clock=clock,
    )
    request_hash = str(payload["authorization_request_hash"])
    try:
        signer_fingerprint = verify_human_publication_signature(
            authorization_request_hash=request_hash,
            signature_base64=signature_base64,
            public_key_pem=signer_public_key_pem,
            trusted_public_key_sha256=trusted_public_key_sha256,
        )
    except PublicationSignatureError as exc:
        raise SubmissionEvidenceError(
            f"human publication signature is not externally trusted: {exc}"
        ) from exc
    payload["schema_version"] = "human-publication-authorization-v2"
    payload.update(
        {
            "signature_base64": signature_base64,
            "signer_public_key_pem": signer_public_key_pem,
            "signer_public_key_sha256": signer_fingerprint,
        }
    )
    payload["authorization_hash"] = canonical_model_hash(payload)
    output_path = root / _PUBLICATION_AUTHORIZATION_NAME
    payload["output_path"] = output_path.as_posix()
    authorization = HumanPublicationAuthorization.model_validate(payload)
    write_json_model(output_path, authorization)
    return authorization


def audit_submission_evidence_bundle(
    *,
    lineage_dir: Path | str,
    config_path: Path | str = Path("config.yaml"),
    output_dir: Path | str | None = None,
    repository_root: Path | str = Path("."),
    run_quality_gates: bool = False,
    quality_commands: Mapping[str, Sequence[str]] | None = None,
    trusted_publication_key_sha256: str | None = None,
    clock: datetime | None = None,
) -> SubmissionEvidenceBundle:
    """Run every submission-critical audit and always persist the truthful verdict."""

    root = Path(lineage_dir).resolve()
    repo = Path(repository_root).resolve()
    destination = (
        Path(output_dir).resolve() if output_dir else root / "submission-evidence"
    )
    destination.mkdir(parents=True, exist_ok=True)
    bundle_path = destination / _BUNDLE_NAME
    ledger = _CheckLedger()
    artifacts: dict[Path, SubmissionArtifactDigest] = {}

    def add_artifact(path: Path, role: str) -> None:
        resolved = path.resolve()
        if not resolved.is_file() or resolved in artifacts:
            return
        _require_submission_artifact_is_public(repo=repo, path=resolved)
        artifacts[resolved] = SubmissionArtifactDigest(
            role=role,
            path=_display_path(resolved, root=root),
            sha256=file_hash(resolved),
            byte_count=resolved.stat().st_size,
        )

    artifact: SystemAuthoredPlanArtifact | None = None
    plan: ResearchPlan | None = None
    package: OfficialDevelopmentSearchPackage | None = None
    outcome: SystemAuthoredOutcome | None = None
    selected: OfficialCandidateRecord | None = None
    plan_receipt: ModelAuthorshipReceipt | None = None
    outcome_receipt: ModelAuthorshipReceipt | None = None
    candidate_interaction: AutonomousModelInteraction | None = None
    recorded_identities: list[RecordedModelIdentity] = []

    # Plan authorship and Chinese guard.
    plan_authorship_findings: list[str] = []
    plan_guard_findings: list[str] = []
    try:
        artifact_path = root / _PLAN_ARTIFACT
        approved_path = root / _APPROVED_PLAN
        artifact = SystemAuthoredPlanArtifact.model_validate_json(
            artifact_path.read_text(encoding="utf-8")
        )
        plan = ResearchPlan.model_validate_json(
            approved_path.read_text(encoding="utf-8")
        )
        add_artifact(artifact_path, "系统自主生成的研究计划")
        add_artifact(approved_path, "人工确认时看到的冻结计划")
        if artifact.schema_version != "system-authored-research-plan-v2":
            plan_authorship_findings.append(
                "正式提交只接受含完整前瞻谱系的研究计划制品 v2。"
            )
        if artifact.lineage_id != root.name:
            plan_authorship_findings.append("研究计划属于另一条谱系。")
        if artifact.plan != plan.model_dump(mode="json"):
            plan_authorship_findings.append("冻结计划并非模型计划的完全相同内容。")
        plan_receipt = load_bound_authorship_receipt(
            lineage_dir=root,
            relative_path=artifact.authorship_receipt_relative_path,
            expected_hash=artifact.authorship_receipt_hash,
            artifact_kind="research_plan",
            expected_model_name=artifact.model_name,
            expected_fields=plan_authored_fields(artifact.plan),
        )
        add_artifact(
            _inside(root, str(artifact.authorship_receipt_relative_path)),
            "研究计划原始模型调用回执",
        )
        recorded_identities.append(_identity_from_receipt("research_plan", plan_receipt))
        if not artifact.guard_report.accepted:
            plan_guard_findings.append("系统计划门禁没有接受该计划。")
        non_chinese = authored_plan_non_chinese_fields(plan)
        if non_chinese:
            plan_guard_findings.append(
                f"计划仍含非中文科学字段：{list(non_chinese)}。"
            )
    except (OSError, RuntimeError, ValueError) as exc:
        plan_authorship_findings.append(f"无法证明研究计划的模型来源：{exc}")
        plan_guard_findings.append("没有可通过中文与计划门禁核验的研究计划。")
    ledger.record(
        "plan_model_authorship_provenance",
        findings=plan_authorship_findings,
        evidence_paths=_paths_for(artifacts, "研究计划"),
    )
    ledger.record(
        "plan_is_chinese_and_guarded",
        findings=plan_guard_findings,
        evidence_paths=_paths_for(artifacts, "计划"),
    )

    # Human scope approval and plan execution contract.
    approval_findings: list[str] = []
    contract_findings: list[str] = []
    contract: ProspectivePlanExecutionContract | None = None
    decision = None
    if plan is None or artifact is None:
        approval_findings.append("批准边界无法核验，因为冻结计划不可用。")
        contract_findings.append("执行合同无法核验，因为正式计划制品不可用。")
    else:
        try:
            decision_path = _plan_decision_path(root, plan.project_id)
            decision = load_plan_decision(
                project_id=plan.project_id, output_dir=root / "plan"
            )
            require_approved_plan(plan=plan, decision=decision)
            if decision is None:
                raise SubmissionEvidenceError("计划决定记录缺失")
            if decision.is_evidence or decision.evidence_refs:
                approval_findings.append("人工计划批准被错误标记为科学证据。")
            add_artifact(decision_path, "人工研究范围批准记录")
        except (OSError, RuntimeError, ValueError, PermissionError) as exc:
            approval_findings.append(f"人工计划批准无效：{exc}")
        try:
            if artifact.schema_version != "system-authored-research-plan-v2":
                raise SubmissionEvidenceError(
                    "正式提交拒绝历史研究计划制品 v1"
                )
            expected_contract = compile_system_authored_plan_execution_contract(
                artifact
            )
            contract = load_prospective_plan_execution_contract(root)
            if contract != expected_contract:
                contract_findings.append(
                    "保留的前瞻执行合同不等于完整计划制品的确定性编译结果。"
                )
            if (
                contract.selected_intervention_identity
                != expected_contract.selected_intervention_identity
                or contract.implementation_anchor
                != expected_contract.implementation_anchor
                or contract.paired_control_treatment
                != expected_contract.paired_control_treatment
            ):
                contract_findings.append(
                    "前瞻干预身份或配对对照—处理合同发生漂移。"
                )
            add_artifact(
                root / "plan-execution-contract.json", "批准计划执行合同"
            )
        except (OSError, RuntimeError, ValueError) as exc:
            contract_findings.append(f"计划执行合同无效：{exc}")
    ledger.record(
        "human_plan_approval_boundary",
        findings=approval_findings,
        evidence_paths=_paths_for(artifacts, "批准"),
    )

    # Signed package, selected source, candidate interaction.
    candidate_findings: list[str] = []
    package_findings: list[str] = []
    try:
        package_path = root / _PACKAGE
        package = OfficialDevelopmentSearchPackage.model_validate_json(
            package_path.read_text(encoding="utf-8")
        )
        add_artifact(package_path, "签名实验结果包")
        package_findings.extend(
            _package_semantic_findings(
                root=root,
                package=package,
                add_artifact=add_artifact,
            )
        )
        if not package.gate_checks:
            package_findings.append("签名结果包没有冻结门禁检查。")
        expected_receipt = bool(package.gate_checks) and all(
            package.gate_checks.values()
        )
        if package.search_freeze_receipt_issued != expected_receipt:
            package_findings.append("搜索冻结回执与冻结门禁结果矛盾。")
        if not package.selected_candidate_id:
            package_findings.append("签名结果包没有入选候选。")
        selected = next(
            (
                item
                for item in package.candidates
                if item.candidate_id == package.selected_candidate_id
            ),
            None,
        )
        if selected is None:
            candidate_findings.append("入选候选不在签名候选登记表中。")
        else:
            if contract is None:
                candidate_findings.append("入选候选没有可比较的批准计划合同。")
            else:
                require_prospective_candidate_plan_alignment(
                    candidates=[selected], contract=contract
                )
            source_path = _inside(root, selected.source_relative_path)
            if file_hash(source_path) != selected.source_sha256:
                candidate_findings.append("入选候选源文件与签名哈希不同。")
            add_artifact(source_path, "入选候选精确源代码")
            candidate_interaction = _load_candidate_interaction(
                root=root,
                candidate=selected,
                source_path=source_path,
            )
            interaction_path = (
                root / "interactions" / f"{selected.interaction_id}.json"
            )
            add_artifact(interaction_path, "入选候选原始模型调用")
            recorded_identities.append(
                _identity_from_interaction(candidate_interaction)
            )
    except (OSError, RuntimeError, ValueError) as exc:
        if package is None:
            package_findings.append(f"签名结果包无效：{exc}")
        else:
            candidate_findings.append(f"候选来源链无效：{exc}")
    if contract_findings:
        candidate_findings.extend(contract_findings)
    ledger.record(
        "plan_to_code_alignment",
        findings=candidate_findings,
        evidence_paths=_paths_for(artifacts, "候选", "执行合同"),
    )
    candidate_authorship_findings = []
    if candidate_interaction is None:
        candidate_authorship_findings.append("没有入选候选的精确模型调用与源字节证明。")
    ledger.record(
        "candidate_model_authorship_provenance",
        findings=candidate_authorship_findings,
        evidence_paths=_paths_for(artifacts, "候选", "原始模型调用"),
    )
    ledger.record(
        "signed_package_semantics",
        findings=package_findings,
        evidence_paths=_paths_for(artifacts, "签名实验结果包"),
    )

    # Raw executed-cell chain and reproducibility material.
    if package is None or contract is None:
        cell_audit = _CellAudit(
            provenance_passed=False,
            reproducibility_complete=False,
            findings=("缺少有效签名结果包或批准计划合同，无法审计实验单元。",),
            reproducibility_findings=("复现包缺少有效签名结果包或计划合同。",),
            artifact_paths=(),
            executed_count=(len(package.cell_results) if package is not None else 0),
            raw_result_count=0,
        )
    else:
        cell_audit = _audit_cells(
            root=root,
            package=package,
            approved_plan_hash=contract.approved_plan_hash,
            contract_hash=contract.contract_hash,
        )
        for path in cell_audit.artifact_paths:
            add_artifact(path, "实验单元来源文件")
    ledger.record(
        "executed_cell_provenance",
        findings=cell_audit.findings,
        evidence_paths=_paths_for(artifacts, "实验单元"),
    )
    ledger.record(
        "reproducibility_package_complete",
        findings=cell_audit.reproducibility_findings,
        evidence_paths=_paths_for(artifacts, "实验单元", "候选精确源代码"),
    )

    # Outcome numeric semantics and exact authorship.
    numeric_findings: list[str] = []
    outcome_authorship_error: str | None = None
    try:
        outcome_path = root / _OUTCOME
        outcome = SystemAuthoredOutcome.model_validate_json(
            outcome_path.read_text(encoding="utf-8")
        )
        add_artifact(outcome_path, "系统自主生成的结果解释")
        if package is None or outcome.package_hash != package.package_hash:
            numeric_findings.append("结果解释没有绑定当前签名结果包。")
        if not outcome.accepted or outcome.refusal_reasons:
            numeric_findings.append("结果解释未被自身确定性审计接受。")
        if not outcome.traceability.passed:
            numeric_findings.append("结果解释含无法回溯到证据的数值。")
        if outcome.relation_audit is None:
            numeric_findings.append("结果解释缺少显式数值关系审计。")
        elif not outcome.relation_audit.passed:
            numeric_findings.append("结果解释含算术上不成立的数值关系。")
        if package is not None:
            gate_passed = all(package.gate_checks.values())
            if not (
                outcome.frozen_gate_passed == gate_passed
                and outcome.verdict_consistent_with_gate
                and outcome.interpretation.claims_frozen_gate_passed == gate_passed
            ):
                numeric_findings.append("模型结论与冻结门禁语义不一致。")
        outcome_receipt = load_bound_authorship_receipt(
            lineage_dir=root,
            relative_path=outcome.authorship_receipt_relative_path,
            expected_hash=outcome.authorship_receipt_hash,
            artifact_kind="outcome_interpretation",
            expected_model_name=outcome.model_name,
            expected_fields=outcome_authored_fields(
                outcome.interpretation.model_dump(mode="json")
            ),
        )
        add_artifact(
            _inside(root, str(outcome.authorship_receipt_relative_path)),
            "结果解释原始模型调用回执",
        )
        recorded_identities.append(_identity_from_receipt("outcome", outcome_receipt))
    except (OSError, RuntimeError, ValueError) as exc:
        outcome_authorship_error = str(exc)
        numeric_findings.append(f"结果解释或其作者来源无效：{exc}")
    ledger.record(
        "numeric_claim_semantics",
        findings=numeric_findings,
        evidence_paths=_paths_for(artifacts, "结果解释", "签名实验结果包"),
    )

    # Configured-vs-recorded identity.
    config_identity: ConfiguredModelIdentity | None = None
    config_file: Path | None = None
    identity_findings: list[str] = []
    try:
        config_file = Path(config_path).resolve()
        parsed = ConfigParser().parse_file(config_file, model_type=SystemConfig)
        if not isinstance(parsed, SystemConfig):
            raise SubmissionEvidenceError("配置解析结果不是 SystemConfig")
        llm = parsed.deployment.llm
        config_identity = ConfiguredModelIdentity(
            provider=llm.provider,
            base_url=llm.base_url,
            model_name=llm.model_name,
            config_path=config_file.as_posix(),
            config_sha256=file_hash(config_file),
            api_key_env_name=llm.api_key_env,
            api_key_value_logged=False,
        )
        add_artifact(config_file, "无凭据值的模型配置")
        if len(recorded_identities) != 3:
            identity_findings.append(
                "计划、候选代码、结果解释三类模型调用身份没有全部保留。"
            )
        for identity in recorded_identities:
            if (
                identity.provider != config_identity.provider
                or _normal_url(identity.base_url) != _normal_url(config_identity.base_url)
                or identity.model_name != config_identity.model_name
            ):
                identity_findings.append(
                    f"{identity.artifact_role} 记录的模型身份与当前配置不一致。"
                )
    except (OSError, RuntimeError, ValueError) as exc:
        identity_findings.append(f"模型配置身份无法核验：{exc}")
    ledger.record(
        "configured_model_identity_matches",
        findings=identity_findings,
        evidence_paths=_paths_for(artifacts, "模型配置", "模型调用"),
    )

    # Publication innovation audit: deliberately absent until system-authored and
    # bound to both literature and the measured positive effect.
    innovation_findings: list[str] = []
    innovation: PublicationInnovationAudit | None = None
    try:
        innovation_path = root / _INNOVATION_NAME
        innovation = PublicationInnovationAudit.model_validate_json(
            innovation_path.read_text(encoding="utf-8")
        )
        add_artifact(innovation_path, "系统自主生成的创新性审计")
        if artifact is None or innovation.plan_hash != artifact.plan_hash:
            innovation_findings.append("创新性审计没有绑定当前研究计划。")
        if selected is None or (
            innovation.candidate_source_sha256 != selected.source_sha256
        ):
            innovation_findings.append("创新性审计没有绑定当前入选代码。")
        survey_path = root / "plan-literature-survey.json"
        if (
            not survey_path.is_file()
            or innovation.literature_survey_sha256 != file_hash(survey_path)
        ):
            innovation_findings.append("创新性审计没有绑定真实文献检索快照。")
        else:
            add_artifact(survey_path, "计划前文献检索快照")
        load_bound_authorship_receipt(
            lineage_dir=root,
            relative_path=innovation.authorship_receipt_relative_path,
            expected_hash=innovation.authorship_receipt_hash,
            artifact_kind="innovation_audit",
            expected_model_name=(
                plan_receipt.model_name if plan_receipt is not None else ""
            ),
            expected_fields={
                "novelty_claims": list(innovation.novelty_claims),
                "nearest_prior_work_comparisons": list(
                    innovation.nearest_prior_work_comparisons
                ),
                "overlap_risks": list(innovation.overlap_risks),
                "novelty_supported": innovation.novelty_supported,
                "positive_method_effect_supported": (
                    innovation.positive_method_effect_supported
                ),
            },
        )
        add_artifact(
            _inside(root, innovation.authorship_receipt_relative_path),
            "创新性审计模型调用回执",
        )
        if not innovation.publication_innovation_ready:
            innovation_findings.append("创新性或正向方法效果尚未达到发表门槛。")
    except (OSError, RuntimeError, ValueError) as exc:
        innovation_findings.append(f"缺少可验证的系统自主创新性审计：{exc}")
    ledger.record(
        "innovation_evidence_audited",
        findings=innovation_findings,
        evidence_paths=_paths_for(artifacts, "创新性", "文献检索"),
    )

    # Pure deterministic replay is useful, but is explicitly not an independent
    # scientific rerun.
    replay_findings = _replay_findings(package)
    ledger.record(
        "deterministic_result_replay",
        findings=replay_findings,
        evidence_paths=_paths_for(artifacts, "签名实验结果包"),
    )

    reexecution_findings: list[str] = []
    reexecution: IndependentReexecutionReceipt | None = None
    try:
        reexecution_path = root / _REEXECUTION_NAME
        reexecution = IndependentReexecutionReceipt.model_validate_json(
            reexecution_path.read_text(encoding="utf-8")
        )
        add_artifact(reexecution_path, "独立科学重执行回执")
        if package is None or reexecution.package_hash != package.package_hash:
            reexecution_findings.append("独立重执行没有绑定当前签名结果包。")
        if not reexecution.passed:
            reexecution_findings.append("独立科学重执行没有通过。")
    except (OSError, RuntimeError, ValueError) as exc:
        reexecution_findings.append(f"缺少有效的独立科学重执行回执：{exc}")

    # Final report and all four synchronized views.
    report_findings: list[str] = []
    report: FinalResearchReport | None = None
    build: FinalReportBuildReceipt | None = None
    final_input = None
    try:
        final_input = audit_final_report_inputs(lineage_dir=root)
        if not final_input.accepted:
            report_findings.append("最终报告输入审计未通过。")
        report_path = root / _FINAL_DIR / _FINAL_REPORT
        build_path = root / _FINAL_DIR / _FINAL_BUILD
        report = FinalResearchReport.model_validate_json(
            report_path.read_text(encoding="utf-8")
        )
        build = FinalReportBuildReceipt.model_validate_json(
            build_path.read_text(encoding="utf-8")
        )
        add_artifact(report_path, "中文最终研究报告 JSON")
        add_artifact(build_path, "最终报告跨格式构建回执")
        views = {
            "json": (report_path, build.json_sha256),
            "markdown": (
                report_path.with_name("final-research-report.md"),
                build.markdown_sha256,
            ),
            "latex": (
                report_path.with_name("final-research-report.tex"),
                build.latex_sha256,
            ),
        }
        if build.pdf_sha256 is not None:
            views["pdf"] = (
                report_path.with_name("final-research-report.pdf"),
                build.pdf_sha256,
            )
        for role, (path, expected_hash) in views.items():
            if not path.is_file() or file_hash(path) != expected_hash:
                report_findings.append(f"最终报告 {role} 文件缺失或哈希不符。")
            else:
                add_artifact(path, f"最终研究报告 {role}")
        if build.report_hash != report.report_hash:
            report_findings.append("构建回执绑定了另一份最终报告。")
        if artifact is None or contract is None:
            report_findings.append("最终报告无法绑定有效的正式计划与前瞻执行合同。")
        elif (
            report.system_authored_plan_artifact != artifact
            or report.prospective_plan_execution_contract != contract
            or report.plan_execution_contract_hash != contract.contract_hash
            or report.prospective_plan_execution_contract.selected_intervention_identity
            != contract.selected_intervention_identity
            or report.prospective_plan_execution_contract.paired_control_treatment
            != contract.paired_control_treatment
        ):
            report_findings.append(
                "最终报告没有逐字绑定重编译后的干预身份与配对对照—处理合同。"
            )
        if not build.pdf_compiled or not build.all_renderings_consistent:
            report_findings.append("PDF 未编译或跨格式语义检查未全部通过。")
    except (OSError, RuntimeError, ValueError) as exc:
        report_findings.append(f"最终报告及其跨格式回执无效：{exc}")
    ledger.record(
        "final_report_cross_format_integrity",
        findings=report_findings,
        evidence_paths=_paths_for(artifacts, "最终研究报告", "跨格式"),
    )

    # Broad source quality. Running is optional at the API layer so unit tests and
    # read-only audits do not unexpectedly consume minutes; the CLI defaults to run.
    quality_findings: list[str] = []
    quality: SubmissionQualityGateReceipt | None = None
    quality_current_commit: str | None = None
    try:
        quality_path = destination / _QUALITY_NAME
        authorization_freezes_quality = (
            root / _PUBLICATION_AUTHORIZATION_NAME
        ).is_file()
        if run_quality_gates and not authorization_freezes_quality:
            if config_file is None:
                raise SubmissionEvidenceError(
                    "广泛质量门不能绑定缺失或无效的正式配置文件。"
                )
            quality = run_submission_quality_gates(
                repository_root=repo,
                output_dir=destination,
                config_path=config_file,
                commands=quality_commands,
                clock=clock,
            )
        else:
            quality = SubmissionQualityGateReceipt.model_validate_json(
                quality_path.read_text(encoding="utf-8")
            )
        add_artifact(quality_path, "广泛代码质量门回执")
        for log_path in _verify_quality_receipt_artifacts(
            receipt=quality, receipt_path=quality_path
        ):
            add_artifact(log_path, f"质量门日志 {log_path.stem}")
        _verify_quality_runtime_configuration(receipt=quality, repository_root=repo)
        if (
            config_identity is None
            or config_file is None
            or config_file != (repo / _CANONICAL_CONFIG_RELATIVE_PATH).resolve()
            or quality.configuration_sha256 != config_identity.config_sha256
        ):
            quality_findings.append(
                "质量门没有绑定本次审计使用的仓库根目录 config.yaml 精确字节。"
            )
        quality_current_commit = _git_text(repo, "rev-parse", "HEAD")
        if quality.source_commit != quality_current_commit:
            quality_findings.append("质量门回执不是针对当前源码提交。")
        if not quality.all_passed:
            quality_findings.append("pytest、ruff、mypy 或源码洁净门仍为红色。")
        if not _tracked_worktree_clean(
            repo, expected_config_sha256=quality.configuration_sha256
        ):
            quality_findings.append("当前源码工作区在质量回执之后又发生了变化。")
    except (OSError, RuntimeError, ValueError) as exc:
        quality_findings.append(f"缺少当前提交的广泛质量门回执：{exc}")
    ledger.record(
        "broad_quality_gates",
        findings=quality_findings,
        evidence_paths=_paths_for(artifacts, "质量门"),
    )

    if reexecution is not None and package is not None:
        try:
            if quality is None or quality_current_commit is None:
                raise SubmissionEvidenceError(
                    "独立重执行无法绑定当前源码提交与质量门回执"
                )
            reexecution_paths = _verify_reexecution_evidence(
                root=root,
                package=package,
                receipt=reexecution,
                current_source_commit=quality_current_commit,
                quality_source_commit=quality.source_commit,
            )
            for path in reexecution_paths:
                add_artifact(path, "独立科学重执行实物")
        except (OSError, RuntimeError, ValueError) as exc:
            reexecution_findings.append(f"独立科学重执行实物不可验证：{exc}")
    elif reexecution is not None:
        reexecution_findings.append("独立重执行无法绑定有效签名结果包。")
    ledger.record(
        "independent_scientific_reexecution",
        findings=reexecution_findings,
        evidence_paths=_paths_for(artifacts, "独立科学重执行"),
    )

    required_findings: list[str] = []
    if final_input is None or not final_input.accepted:
        required_findings.append("最终报告输入审计缺失或未通过。")
    if outcome is None or outcome.relation_audit is None:
        required_findings.append("数值关系审计缺失。")
    if selected is None or selected.prospective_plan_alignment is None:
        required_findings.append("候选前瞻计划对齐审计缺失。")
    if not cell_audit.provenance_passed:
        required_findings.append("实验单元来源审计缺失或未通过。")
    if innovation is None:
        required_findings.append("创新性审计缺失。")
    if reexecution is None:
        required_findings.append("独立科学重执行审计缺失。")
    if quality is None:
        required_findings.append("广泛质量门审计缺失。")
    if build is None:
        required_findings.append("最终报告构建审计缺失。")
    ledger.record(
        "required_audits_present",
        findings=required_findings,
        evidence_paths=tuple(item.path for item in artifacts.values()),
    )

    human_boundary_findings: list[str] = []
    if decision is None or decision.is_evidence or decision.evidence_refs:
        human_boundary_findings.append("计划批准边界缺失或被用作科学证据。")
    if report is not None and report.human_approval_is_scientific_evidence:
        human_boundary_findings.append("最终报告错误地把人工批准计为科学证据。")
    ledger.record(
        "human_approval_not_scientific_evidence",
        findings=human_boundary_findings,
        evidence_paths=_paths_for(artifacts, "批准", "最终研究报告"),
    )

    authorization_findings: list[str] = []
    authorization: HumanPublicationAuthorization | None = None
    try:
        authorization_path = root / _PUBLICATION_AUTHORIZATION_NAME
        authorization = HumanPublicationAuthorization.model_validate_json(
            authorization_path.read_text(encoding="utf-8")
        )
        add_artifact(authorization_path, "人工最终发表与提交授权")
        if authorization.lineage_id != root.name:
            authorization_findings.append("最终发表授权属于另一条谱系。")
        if authorization.authored_by_model or authorization.is_scientific_evidence:
            authorization_findings.append("最终发表授权越界成为模型产物或科学证据。")
        if trusted_publication_key_sha256 is None:
            authorization_findings.append("未提供外部可信的人工发表签名公钥指纹。")
        else:
            try:
                verified_fingerprint = verify_human_publication_signature(
                    authorization_request_hash=authorization.authorization_request_hash,
                    signature_base64=authorization.signature_base64,
                    public_key_pem=authorization.signer_public_key_pem,
                    trusted_public_key_sha256=trusted_publication_key_sha256,
                )
                if verified_fingerprint != authorization.signer_public_key_sha256:
                    authorization_findings.append("最终发表授权记录的签名公钥指纹不符。")
            except PublicationSignatureError as exc:
                authorization_findings.append(f"最终发表授权的外部签名无效：{exc}")

        expected_bindings: dict[str, str | None] = {
            "plan_artifact_hash": (
                artifact.artifact_hash if artifact is not None else None
            ),
            "signed_package_hash": (
                package.package_hash if package is not None else None
            ),
            "outcome_hash": outcome.outcome_hash if outcome is not None else None,
            "final_report_hash": report.report_hash if report is not None else None,
            "final_report_build_receipt_hash": (
                build.receipt_hash if build is not None else None
            ),
            "innovation_audit_hash": (
                innovation.audit_hash if innovation is not None else None
            ),
            "reexecution_receipt_hash": (
                reexecution.receipt_hash if reexecution is not None else None
            ),
            "quality_gate_receipt_hash": (
                quality.receipt_hash if quality is not None else None
            ),
        }
        for field_name, expected_value in expected_bindings.items():
            if expected_value is None or getattr(authorization, field_name) != expected_value:
                authorization_findings.append(
                    f"最终发表授权未绑定当前 {field_name}。"
                )
        if plan is None:
            authorization_findings.append("无法核对最终发表授权绑定的人工计划决定。")
        else:
            decision_path = _plan_decision_path(root, plan.project_id)
            if (
                not decision_path.is_file()
                or authorization.plan_decision_file_sha256 != file_hash(decision_path)
            ):
                authorization_findings.append("最终发表授权未绑定当前人工计划决定。")
        current_commit = _git_text(repo, "rev-parse", "HEAD")
        if authorization.source_commit != current_commit:
            authorization_findings.append("最终发表授权不是针对当前源码提交。")
    except (OSError, RuntimeError, ValueError) as exc:
        authorization_findings.append(f"缺少有效的人工最终发表授权：{exc}")
    ledger.record(
        "human_publication_authorization",
        findings=authorization_findings,
        evidence_paths=_paths_for(artifacts, "最终发表与提交授权"),
    )

    secret_findings = _secret_findings(tuple(artifacts))
    if config_identity is not None and config_identity.api_key_value_logged:
        secret_findings.append("模型配置记录了 API 密钥值。")

    publication_findings: list[str] = []
    # Scientific producers must remain unable to self-authorize publication.  Their
    # permanent false flags are therefore a boundary, not an unreachable readiness
    # prerequisite.  Readiness is derived only after all objective gates pass and a
    # human authorization binds their exact hashes.
    producer_self_authorization = {
        "签名结果包": package.publication_ready if package is not None else False,
        "系统结果解释": outcome.publication_ready if outcome is not None else False,
        "最终研究报告": report.publication_ready if report is not None else False,
        "创新性审计": innovation.publication_ready if innovation is not None else False,
    }
    self_authorized_roles = [
        name for name, value in producer_self_authorization.items() if value
    ]
    if self_authorized_roles:
        publication_findings.append(
            "科学制品不得自行授予发表权限：" + "、".join(self_authorized_roles) + "。"
        )
    if authorization is None or authorization_findings:
        publication_findings.append("缺少绑定全部最终制品与源码提交的人工发表授权。")
    if (
        package is None
        or not package.gate_checks
        or not all(package.gate_checks.values())
        or not package.search_freeze_receipt_issued
        or package_findings
    ):
        publication_findings.append("签名结果包的冻结科学门禁尚未全绿。")
    if (
        outcome is None
        or not outcome.accepted
        or outcome.relation_audit is None
        or not outcome.relation_audit.passed
        or numeric_findings
    ):
        publication_findings.append("系统中文结果解释尚未通过数值与语义审计。")
    if (
        report is None
        or build is None
        or not build.pdf_compiled
        or not build.all_renderings_consistent
        or report_findings
    ):
        publication_findings.append("最终中文报告尚未完成一致的 PDF 构建。")
    if quality is None or not quality.all_passed or quality_findings:
        publication_findings.append("广泛代码质量门尚未全绿。")
    if (
        innovation is None
        or not innovation.publication_innovation_ready
        or innovation_findings
    ):
        publication_findings.append("创新性与正向效果证据尚未同时通过。")
    if reexecution is None or not reexecution.passed or reexecution_findings:
        publication_findings.append("尚无通过的独立科学重执行。")
    upstream_readiness_findings = (
        *plan_authorship_findings,
        *plan_guard_findings,
        *approval_findings,
        *candidate_findings,
        *candidate_authorship_findings,
        *cell_audit.findings,
        *cell_audit.reproducibility_findings,
        *replay_findings,
        *identity_findings,
        *required_findings,
        *human_boundary_findings,
    )
    if upstream_readiness_findings:
        publication_findings.append("仍有上游作者来源、计划、执行、复现或身份门禁未通过。")
    if secret_findings:
        publication_findings.append("提交证据仍包含凭据字段或疑似凭据值。")
    ledger.record(
        "publication_readiness",
        findings=publication_findings,
        evidence_paths=tuple(item.path for item in artifacts.values()),
    )

    if outcome_authorship_error and "authorship" in outcome_authorship_error.casefold():
        # This is not itself a secret, but keeps the local variable meaningful while
        # avoiding any temptation to expose raw response content in the audit.
        pass
    ledger.record(
        "secrets_absent",
        findings=secret_findings,
        evidence_paths=tuple(item.path for item in artifacts.values()),
    )

    checks = ledger.finish()
    now = clock or datetime.now(timezone.utc)
    publication_ready = all(
        next(item.passed for item in checks if item.name == name)
        for name in ("publication_readiness", "secrets_absent")
    )
    payload: dict[str, Any] = {
        "schema_version": "submission-evidence-bundle-v1",
        "lineage_id": root.name,
        "checks": [item.model_dump(mode="json") for item in checks],
        "configured_model_identity": (
            config_identity.model_dump(mode="json")
            if config_identity is not None
            else None
        ),
        "recorded_model_identities": [
            item.model_dump(mode="json") for item in recorded_identities
        ],
        "artifacts": [
            item.model_dump(mode="json")
            for item in sorted(artifacts.values(), key=lambda value: value.path)
        ],
        "executed_cell_count": cell_audit.executed_count,
        "raw_cell_result_count": cell_audit.raw_result_count,
        "scientific_experiment_independently_reexecuted": bool(
            reexecution is not None and reexecution.passed
        ),
        "human_approval_is_scientific_evidence": False,
        "publication_ready": publication_ready,
        "submission_ready": all(item.passed for item in checks),
        "blocking_findings": tuple(
            finding for item in checks for finding in item.findings
        ),
        "created_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    payload["bundle_hash"] = canonical_model_hash(payload)
    payload["output_path"] = bundle_path.as_posix()
    bundle = SubmissionEvidenceBundle.model_validate(payload)
    write_json_model(bundle_path, bundle)
    (destination / _MARKDOWN_NAME).write_text(
        render_submission_evidence_markdown(bundle), encoding="utf-8"
    )
    return bundle


def run_submission_quality_gates(
    *,
    repository_root: Path | str,
    output_dir: Path | str,
    config_path: Path | str = Path("config.yaml"),
    commands: Mapping[str, Sequence[str]] | None = None,
    clock: datetime | None = None,
) -> SubmissionQualityGateReceipt:
    """Run strict broad gates; skipped or deselected tests remain a red gate."""

    repo = Path(repository_root).resolve()
    destination = Path(output_dir).resolve()
    quality_dir = destination / "quality-logs"
    quality_dir.mkdir(parents=True, exist_ok=True)
    frozen_commands = _canonical_quality_commands()
    selected_commands = {
        name: tuple(str(item) for item in command)
        for name, command in (commands or frozen_commands).items()
    }
    if selected_commands != frozen_commands:
        raise SubmissionEvidenceError(
            "quality commands must exactly match the frozen production contract"
        )
    supplied_config = Path(config_path)
    config_file = (
        supplied_config.resolve()
        if supplied_config.is_absolute()
        else (repo / supplied_config).resolve()
    )
    canonical_config = (repo / _CANONICAL_CONFIG_RELATIVE_PATH).resolve()
    if (
        config_file != canonical_config
        or not config_file.is_file()
        or config_file.is_symlink()
    ):
        raise SubmissionEvidenceError(
            "quality gates require the regular repository-root config.yaml"
        )
    parsed_config = ConfigParser().parse_file(config_file, model_type=SystemConfig)
    if not isinstance(parsed_config, SystemConfig):
        raise SubmissionEvidenceError("quality configuration is not a SystemConfig")
    if _secret_findings((config_file,)):
        raise SubmissionEvidenceError(
            "quality configuration contains a credential field or value"
        )
    configuration_sha256 = file_hash(config_file)
    results: list[QualityCommandResult] = []
    for name in ("pytest", "ruff", "mypy"):
        command = tuple(str(item) for item in selected_commands[name])
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                cwd=repo,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=3_600,
            )
            stdout = completed.stdout
            stderr = completed.stderr
            exit_code = completed.returncode
        except subprocess.TimeoutExpired as exc:
            stdout = _timeout_text(exc.stdout)
            stderr = _timeout_text(exc.stderr) + "\n命令超过 3600 秒审计上限。"
            exit_code = -1
        duration = time.monotonic() - started
        combined = stdout + "\n" + stderr
        skipped = _summary_count(combined, "skipped")
        deselected = _summary_count(combined, "deselected")
        log_path = quality_dir / f"{name}.log"
        log_payload = {
            "name": name,
            "command": list(command),
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
        }
        log_path.write_bytes(
            (
                json.dumps(
                    log_payload,
                    allow_nan=False,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
        )
        results.append(
            QualityCommandResult(
                name=name,
                command=command,
                exit_code=exit_code,
                skipped_count=skipped,
                deselected_count=deselected,
                duration_seconds=duration,
                stdout_sha256=_text_hash(stdout),
                stderr_sha256=_text_hash(stderr),
                log_relative_path=log_path.relative_to(destination).as_posix(),
                log_sha256=file_hash(log_path),
                log_byte_count=log_path.stat().st_size,
                passed=exit_code == 0 and skipped == 0 and deselected == 0,
            )
        )
    commit = _git_text(repo, "rev-parse", "HEAD")
    tracked_clean = _tracked_worktree_clean(
        repo, expected_config_sha256=configuration_sha256
    )
    now = clock or datetime.now(timezone.utc)
    output_path = destination / _QUALITY_NAME
    payload: dict[str, Any] = {
        "schema_version": "submission-quality-gate-receipt-v3",
        "source_commit": commit,
        "configuration_relative_path": _CANONICAL_CONFIG_RELATIVE_PATH,
        "configuration_sha256": configuration_sha256,
        "local_secret_env_excluded": True,
        "sovereign_raw_memory_excluded": True,
        "tracked_worktree_clean": tracked_clean,
        "command_contract_hash": _quality_command_contract_hash(),
        "commands": [item.model_dump(mode="json") for item in results],
        "all_passed": tracked_clean and all(item.passed for item in results),
        "created_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    payload["receipt_hash"] = canonical_model_hash(payload)
    payload["output_path"] = output_path.as_posix()
    receipt = SubmissionQualityGateReceipt.model_validate(payload)
    write_json_model(output_path, receipt)
    return receipt


def render_submission_evidence_markdown(bundle: SubmissionEvidenceBundle) -> str:
    """Render the canonical bundle as a Chinese, non-scientific audit view."""

    verdict = "可提交" if bundle.submission_ready else "禁止宣称可提交"
    lines = [
        "# 提交证据总审计",
        "",
        f"> 结论：**{verdict}**",
        f"> 谱系：`{bundle.lineage_id}`",
        f"> 证据包哈希：`{bundle.bundle_hash}`",
        f"> `publication_ready`：`{str(bundle.publication_ready).lower()}`",
        f"> `submission_ready`：`{str(bundle.submission_ready).lower()}`",
        "",
        "本报告仅汇总确定性审计；不生成研究假设、结果解释或创新性主张。",
        "",
        "## 阻断检查",
        "",
        "| 检查 | 状态 | 发现 |",
        "|---|---:|---|",
    ]
    for check in bundle.checks:
        status = "通过" if check.passed else "阻断"
        detail = "无" if not check.findings else "；".join(check.findings)
        lines.append(f"| {check.title_zh} | {status} | {detail} |")
    lines.extend(
        [
            "",
            "## 模型身份",
            "",
        ]
    )
    if bundle.configured_model_identity is None:
        lines.append("未能读取配置模型身份。")
    else:
        configured = bundle.configured_model_identity
        lines.append(
            f"配置模型：`{configured.provider}` / `{configured.model_name}` / "
            f"`{configured.base_url}`。只记录密钥环境变量名，不记录密钥值。"
        )
    for identity in bundle.recorded_model_identities:
        lines.append(
            f"- `{identity.artifact_role}`：`{identity.provider}` / "
            f"`{identity.model_name}` / `{identity.interaction_id}`"
        )
    lines.extend(
        [
            "",
            "## 复现与人工边界",
            "",
            f"- 签名实验单元数：`{bundle.executed_cell_count}`",
            f"- 原始单元结果数：`{bundle.raw_cell_result_count}`",
            "- 人工批准是否作为科学证据：`false`",
            "- 是否完成独立科学重执行：`"
            + str(bundle.scientific_experiment_independently_reexecuted).lower()
            + "`",
            "",
            "## 证据文件",
            "",
        ]
    )
    for item in bundle.artifacts:
        lines.append(
            f"- {item.role}：`{item.path}`；SHA256 `{item.sha256}`；"
            f"{item.byte_count} 字节"
        )
    return "\n".join(lines) + "\n"


def _package_semantic_findings(
    *,
    root: Path,
    package: OfficialDevelopmentSearchPackage,
    add_artifact: Callable[[Path, str], None],
) -> tuple[str, ...]:
    """Refuse a hash-valid package whose scientific execution is incomplete."""

    findings: list[str] = []
    if package.stages_executed != ("pilot", "baseline", "full"):
        findings.append("签名结果包没有按 pilot、baseline、full 完整记录三个阶段。")
    if set(package.gate_checks) != _REQUIRED_GATE_NAMES:
        findings.append("签名结果包的冻结门禁集合不完整或含未注册门禁。")
    observed = (
        package.overall_median_log_effect,
        package.bootstrap_lower,
        package.bootstrap_upper,
        package.ode_stratum_median,
        package.pde_stratum_median,
    )
    if any(value is None for value in observed) or not package.system_effects:
        findings.append("签名结果包缺少总体、区间、分层或逐系统观测结果。")
    attempt_ids = [item.attempt_id for item in package.cell_results]
    if len(attempt_ids) != len(set(attempt_ids)):
        findings.append("签名结果包存在重复实验单元编号。")
    if any(item.stage not in package.stages_executed for item in package.cell_results):
        findings.append("签名单元结果包含未声明执行的阶段。")

    identity_path = root / "official-development-identity.json"
    try:
        retained_identity = OfficialDevelopmentIdentity.model_validate_json(
            identity_path.read_text(encoding="utf-8")
        )
        add_artifact(identity_path, "冻结官方实验身份")
        if retained_identity != package.identity:
            findings.append("独立冻结身份文件与签名结果包中的身份不同。")
    except (OSError, RuntimeError, ValueError) as exc:
        findings.append(f"冻结官方实验身份缺失或无效：{exc}")

    ledger: OfficialSpendLedger | None = None
    ledger_path = root / "official-spend-ledger.json"
    try:
        ledger = OfficialSpendLedger.model_validate_json(
            ledger_path.read_text(encoding="utf-8")
        )
        add_artifact(ledger_path, "官方执行预算账本")
        if ledger.lineage_id != root.name or ledger.plan_hash != package.identity.plan_hash:
            findings.append("预算账本没有绑定当前谱系和冻结实验计划。")
        candidate_count = sum(
            item.method_kind == "candidate" for item in package.cell_results
        )
        baseline_count = sum(
            item.method_kind == "baseline" for item in package.cell_results
        )
        if ledger.spent_candidate_cells != candidate_count:
            findings.append("预算账本的候选实验单元数与签名结果包不同。")
        if ledger.spent_baseline_cells != baseline_count:
            findings.append("预算账本的基线实验单元数与签名结果包不同。")
        budget_conformant = all(value >= 0 for value in ledger.remaining().values())
        if package.gate_checks.get("budget_conformant") != budget_conformant:
            findings.append("预算门禁不能由官方预算账本重算。")
    except (OSError, RuntimeError, ValueError) as exc:
        findings.append(f"官方执行预算账本缺失或无效：{exc}")

    selected = next(
        (
            item
            for item in package.candidates
            if item.candidate_id == package.selected_candidate_id
        ),
        None,
    )
    if selected is None or not selected.static_review_approved:
        findings.append("签名结果包没有通过静态审查的入选候选。")

    full_cells = [item for item in package.cell_results if item.stage == "full"]
    baseline_cells = [
        item for item in package.cell_results if item.stage == "baseline"
    ]
    pilot_cells = [item for item in package.cell_results if item.stage == "pilot"]
    full_by_candidate = _cells_by_candidate(full_cells)
    pilot_by_candidate = _cells_by_candidate(pilot_cells)
    selected_full = full_by_candidate.get(package.selected_candidate_id or "", ())
    selected_systems = {item.system_name for item in selected_full}

    expected_full_systems: set[str] | None = None
    policy_path = root / "preregistered-baseline-policy.json"
    policy = None
    if policy_path.is_file():
        try:
            policy = load_baseline_policy(output_dir=root)
            add_artifact(policy_path, "预注册基线处理策略")
            expected_full_systems = {
                item.system_name for item in policy.systems if item.handling == PAIRED
            }
            if policy.lineage_id != root.name:
                findings.append("基线处理策略属于另一条谱系。")
            if policy.parent_plan_hash != package.identity.plan_hash:
                findings.append("基线处理策略没有绑定冻结官方实验计划。")
            if policy.parent_paired_system_count != package.identity.full_system_count:
                findings.append("基线策略的父面板规模与冻结身份不同。")
            if policy.paired_system_count != len(expected_full_systems):
                findings.append("基线策略的配对系统数与逐系统策略不同。")
        except (OSError, RuntimeError, ValueError) as exc:
            findings.append(f"预注册基线处理策略无效：{exc}")
    elif len(selected_systems) != package.identity.full_system_count:
        findings.append("完整阶段系统数少于冻结身份，且没有预注册面板变更。")

    if expected_full_systems is None:
        expected_full_systems = set(selected_systems)
    if selected_systems != expected_full_systems:
        findings.append("入选候选的完整阶段系统集合与预注册面板不同。")
    if not full_by_candidate:
        findings.append("签名结果包没有完整阶段候选单元。")
    for candidate_id, cells in full_by_candidate.items():
        findings.extend(
            _matrix_findings(
                cells=cells,
                expected_systems=expected_full_systems,
                expected_conditions=set(package.identity.conditions),
                expected_seeds=set(package.identity.seeds),
                label=f"完整阶段候选 {candidate_id}",
            )
        )
    findings.extend(
        _matrix_findings(
            cells=baseline_cells,
            expected_systems=expected_full_systems,
            expected_conditions=set(package.identity.conditions),
            expected_seeds=set(package.identity.seeds),
            label="完整阶段基线",
        )
    )
    if {item.candidate_id for item in baseline_cells} != {"operon_or_pdefind"}:
        findings.append("完整阶段基线单元没有全部使用冻结基线身份。")
    effect_systems = [item.system_name for item in package.system_effects]
    if len(effect_systems) != len(set(effect_systems)):
        findings.append("逐系统效果包含重复系统。")
    if set(effect_systems) != expected_full_systems:
        findings.append("逐系统效果没有覆盖完整预注册面板。")

    breadth_path = root / "preregistered-stage-breadth.json"
    expected_pilot_count = package.identity.pilot_system_count
    if breadth_path.is_file():
        try:
            breadth = load_stage_breadth(output_dir=root)
            if breadth is None:
                raise SubmissionEvidenceError("阶段宽度文件未能加载")
            add_artifact(breadth_path, "预注册试运行宽度")
            expected_pilot_count = breadth.pilot_system_count
            if breadth.lineage_id != root.name:
                findings.append("试运行宽度属于另一条谱系。")
            if breadth.parent_plan_hash != package.identity.plan_hash:
                findings.append("试运行宽度没有绑定冻结官方实验计划。")
            if policy is None or breadth.baseline_policy_hash != policy.policy_hash:
                findings.append("试运行宽度没有绑定当前基线处理策略。")
        except (OSError, RuntimeError, ValueError) as exc:
            findings.append(f"预注册试运行宽度无效：{exc}")
    if not pilot_by_candidate:
        findings.append("签名结果包没有试运行候选单元。")
    else:
        first_pilot = next(iter(pilot_by_candidate.values()))
        pilot_systems = {item.system_name for item in first_pilot}
        pilot_seeds = {item.seed for item in first_pilot}
        if len(pilot_systems) != expected_pilot_count:
            findings.append("试运行系统数与预注册宽度不同。")
        if not pilot_seeds or not pilot_seeds.issubset(set(package.identity.seeds)):
            findings.append("试运行种子不属于冻结种子集合。")
        for candidate_id, cells in pilot_by_candidate.items():
            findings.extend(
                _matrix_findings(
                    cells=cells,
                    expected_systems=pilot_systems,
                    expected_conditions=set(package.identity.conditions),
                    expected_seeds=pilot_seeds,
                    label=f"试运行候选 {candidate_id}",
                )
            )
    return tuple(dict.fromkeys(findings))


def _cells_by_candidate(
    cells: Sequence[OfficialCellResult],
) -> dict[str, tuple[OfficialCellResult, ...]]:
    grouped: dict[str, list[OfficialCellResult]] = {}
    for cell in cells:
        grouped.setdefault(cell.candidate_id, []).append(cell)
    return {name: tuple(items) for name, items in grouped.items()}


def _matrix_findings(
    *,
    cells: Sequence[OfficialCellResult],
    expected_systems: set[str],
    expected_conditions: set[str],
    expected_seeds: set[int],
    label: str,
) -> tuple[str, ...]:
    findings: list[str] = []
    if not cells:
        return (f"{label}没有实验单元。",)
    systems = {item.system_name for item in cells}
    if systems != expected_systems:
        findings.append(f"{label}的系统集合不完整。")
    expected = {
        (system, condition, seed)
        for system in expected_systems
        for condition in expected_conditions
        for seed in expected_seeds
    }
    observed = [(item.system_name, item.condition, item.seed) for item in cells]
    if set(observed) != expected or len(observed) != len(expected):
        findings.append(f"{label}没有精确覆盖系统×条件×种子矩阵。")
    return tuple(findings)


def _audit_cells(
    *,
    root: Path,
    package: OfficialDevelopmentSearchPackage,
    approved_plan_hash: str,
    contract_hash: str,
) -> _CellAudit:
    findings: list[str] = []
    reproducibility: list[str] = []
    artifact_paths: list[Path] = []
    stage_results: dict[str, OfficialCellResult] = {}
    raw_result_ids: set[str] = set()
    candidate_by_id = {item.candidate_id: item for item in package.candidates}
    data_specs: dict[tuple[str, str], OfficialCellSpec] = {}

    for stage in package.stages_executed:
        specs_path = root / "cells" / f"{stage}-specs.json"
        results_path = root / "cells" / f"{stage}-results.json"
        artifact_paths.extend((specs_path, results_path))
        try:
            specs_payload = json.loads(specs_path.read_text(encoding="utf-8"))
            results_payload = json.loads(results_path.read_text(encoding="utf-8"))
            specs = [OfficialCellSpec.model_validate(item) for item in specs_payload["specs"]]
            results = [
                OfficialCellResult.model_validate(item)
                for item in results_payload["results"]
            ]
        except (OSError, KeyError, TypeError, ValueError) as exc:
            findings.append(f"{stage} 阶段规格或结果汇总无效：{exc}")
            continue
        spec_by_id = {item.attempt_id: item for item in specs}
        if len(spec_by_id) != len(specs):
            findings.append(f"{stage} 阶段存在重复实验单元规格。")
        if results_payload.get("approved_research_plan_hash") != approved_plan_hash:
            findings.append(f"{stage} 阶段结果没有绑定批准计划哈希。")
        if results_payload.get("plan_execution_contract_hash") != contract_hash:
            findings.append(f"{stage} 阶段结果没有绑定计划执行合同哈希。")
        for spec in specs:
            raw = spec.model_dump(mode="json")
            digest = raw.pop("spec_hash")
            if digest != canonical_model_hash(raw):
                findings.append(f"外层单元规格哈希不符：{spec.attempt_id}。")
        for result in results:
            if result.attempt_id in stage_results:
                findings.append(f"跨阶段实验单元编号重复：{result.attempt_id}。")
                continue
            stage_results[result.attempt_id] = result
            outer_spec = spec_by_id.get(result.attempt_id)
            if outer_spec is None:
                findings.append(f"已执行结果没有冻结外层规格：{result.attempt_id}。")
                continue
            data_specs[(outer_spec.data_relative_path, outer_spec.data_sha256)] = outer_spec
            raw_dir = root / "cells" / stage / result.attempt_id
            raw_spec_path = raw_dir / "spec.json"
            raw_result_path = raw_dir / "result.json"
            artifact_paths.extend((raw_spec_path, raw_result_path))
            try:
                raw_spec = json.loads(raw_spec_path.read_text(encoding="utf-8"))
                raw_result = json.loads(raw_result_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                findings.append(f"原始单元文件缺失或无效：{result.attempt_id}：{exc}")
                continue
            raw_spec_hash = raw_spec.get("spec_hash")
            raw_spec_body = dict(raw_spec)
            raw_spec_body.pop("spec_hash", None)
            if raw_spec_hash != canonical_model_hash(raw_spec_body):
                findings.append(f"原始执行规格哈希不符：{result.attempt_id}。")
            if raw_result.get("spec_hash") != raw_spec_hash:
                findings.append(f"原始结果没有绑定原始执行规格：{result.attempt_id}。")
            raw_result_hash = raw_result.get("result_hash")
            raw_result_body = dict(raw_result)
            raw_result_body.pop("result_hash", None)
            if raw_result_hash != canonical_model_hash(raw_result_body):
                findings.append(f"原始执行结果哈希不符：{result.attempt_id}。")
            if result.result_hash != raw_result_hash:
                findings.append(f"汇总结果与原始结果哈希不同：{result.attempt_id}。")
            if not _raw_result_matches_summary(raw_result, result):
                findings.append(f"汇总字段与原始结果不同：{result.attempt_id}。")
            attempt = raw_spec.get("attempt") or {}
            expected_attempt = {
                "attempt_id": outer_spec.attempt_id,
                "system_name": outer_spec.system_name,
                "condition": outer_spec.condition,
                "data_type": outer_spec.data_type,
                "seed": outer_spec.seed,
            }
            if attempt != expected_attempt:
                findings.append(f"原始执行规格身份不同：{result.attempt_id}。")
            if raw_spec.get("method_kind") != outer_spec.method_kind:
                findings.append(f"原始执行方法类型不同：{result.attempt_id}。")
            if raw_spec.get("split_policy") != _SPLIT_POLICY:
                findings.append(f"原始执行数据切分策略不同：{result.attempt_id}。")
            if raw_spec.get("baseline_method") != baseline_method_for(
                outer_spec.data_type
            ):
                findings.append(f"原始执行基线定义不同：{result.attempt_id}。")
            baseline_runner_hash = raw_spec.get("expected_baseline_runner_sha256")
            if not re.fullmatch(r"[0-9a-f]{64}", str(baseline_runner_hash or "")):
                findings.append(f"原始执行未绑定基线执行器：{result.attempt_id}。")
            maximum_fit = raw_spec.get("maximum_fit_seconds")
            maximum_predict = raw_spec.get("maximum_predict_seconds")
            if (
                not isinstance(maximum_fit, int)
                or isinstance(maximum_fit, bool)
                or not 1 <= maximum_fit <= 3_600
                or maximum_predict != 10
            ):
                findings.append(f"原始执行时间预算无效：{result.attempt_id}。")
            if raw_spec.get("expected_data_sha256") != outer_spec.data_sha256:
                findings.append(f"原始执行数据哈希不同：{result.attempt_id}。")
            if (
                raw_spec.get("candidate_source_sha256")
                != outer_spec.candidate_source_sha256
            ):
                findings.append(f"原始执行候选代码哈希不同：{result.attempt_id}。")
            if outer_spec.method_kind == "candidate":
                candidate = candidate_by_id.get(outer_spec.candidate_id)
                if (
                    candidate is None
                    or candidate.source_sha256 != outer_spec.candidate_source_sha256
                ):
                    findings.append(f"单元规格没有绑定登记候选代码：{result.attempt_id}。")
            raw_result_ids.add(result.attempt_id)
        disk_result_ids = {
            path.parent.name
            for path in (root / "cells" / stage).glob("*/result.json")
        }
        summary_ids = {item.attempt_id for item in results}
        if disk_result_ids != summary_ids:
            findings.append(
                f"{stage} 阶段原始结果集合与汇总集合不相等："
                f"仅原始={sorted(disk_result_ids - summary_ids)}，"
                f"仅汇总={sorted(summary_ids - disk_result_ids)}。"
            )

    package_results = {item.attempt_id: item for item in package.cell_results}
    if len(package_results) != len(package.cell_results):
        findings.append("签名结果包含重复实验单元编号。")
    if set(package_results) != set(stage_results):
        findings.append("签名结果包的实验单元集合与阶段汇总不相等。")
    else:
        for attempt_id, result in stage_results.items():
            if package_results[attempt_id] != result:
                findings.append(f"签名结果包改变了阶段汇总：{attempt_id}。")

    # Reproducibility adds source runner and exact input-byte availability to the
    # already strict provenance chain.
    if findings:
        reproducibility.append("实验单元来源链未通过，复现材料不能视为完整。")
    runner_matches = [
        path
        for path in (root / "runner").glob("*.py")
        if path.is_file() and file_hash(path) == package.identity.runner_sha256
    ]
    if not runner_matches:
        reproducibility.append("冻结执行器源文件缺失或哈希不符。")
    else:
        artifact_paths.extend(runner_matches)
    data_root = Path(package.identity.data_root).resolve()
    for relative_path, expected_hash in data_specs:
        data_path = (data_root / relative_path).resolve()
        if not data_path.is_relative_to(data_root):
            reproducibility.append(f"冻结输入数据路径越出数据根目录：{relative_path}。")
        elif not data_path.is_file() or file_hash(data_path) != expected_hash:
            reproducibility.append(f"冻结输入数据缺失或哈希不符：{relative_path}。")
        else:
            artifact_paths.append(data_path)
    for candidate in package.candidates:
        source_path = _inside(root, candidate.source_relative_path)
        if not source_path.is_file() or file_hash(source_path) != candidate.source_sha256:
            reproducibility.append(
                f"登记候选源文件缺失或哈希不符：{candidate.candidate_id}。"
            )
        else:
            artifact_paths.append(source_path)
    return _CellAudit(
        provenance_passed=not findings,
        reproducibility_complete=not findings and not reproducibility,
        findings=tuple(dict.fromkeys(findings)),
        reproducibility_findings=tuple(dict.fromkeys(reproducibility)),
        artifact_paths=tuple(dict.fromkeys(artifact_paths)),
        executed_count=len(package.cell_results),
        raw_result_count=len(raw_result_ids),
    )


def _replay_findings(
    package: OfficialDevelopmentSearchPackage | None,
) -> tuple[str, ...]:
    if package is None:
        return ("没有有效签名结果包，无法重算确定性结果。",)
    findings: list[str] = []
    candidates = [item for item in package.candidates if item.generation == 2]
    if not candidates:
        candidates = [item for item in package.candidates if item.generation == 1]
    full = [item for item in package.cell_results if item.stage == "full"]
    baseline = [item for item in package.cell_results if item.stage == "baseline"]
    selected, basis = select_official_candidate(candidates=candidates, results=full)
    if selected != package.selected_candidate_id:
        findings.append("按冻结选择规则重算得到另一入选候选。")
    if basis != package.selection_basis:
        findings.append("签名结果包记录的选择规则文本与实际确定性规则不同。")
    effects = compute_system_effects(
        candidate_id=selected or "",
        candidate_results=full,
        baseline_results=baseline,
    )
    if effects != package.system_effects:
        findings.append("逐系统配对效果无法从签名单元结果精确重算。")
    summary = aggregate_paired_effects(effects)
    expected = {
        "overall_median_log_effect": package.overall_median_log_effect,
        "bootstrap_lower": package.bootstrap_lower,
        "bootstrap_upper": package.bootstrap_upper,
        "ode_stratum_median": package.ode_stratum_median,
        "pde_stratum_median": package.pde_stratum_median,
    }
    if any(summary.get(key) != value for key, value in expected.items()):
        findings.append("总体效果、分层效果或自助区间无法精确重算。")
    selected_full = [item for item in full if item.candidate_id == selected]
    recomputed_gate = {
        "all_candidate_cells_succeeded": bool(selected_full)
        and all(item.status == "succeeded" for item in selected_full),
        "all_baseline_cells_succeeded": bool(baseline)
        and all(item.status == "succeeded" for item in baseline),
        "overall_median_at_least_minimum": (
            package.overall_median_log_effect is not None
            and package.overall_median_log_effect >= package.minimum_overall_log_effect
        ),
        "bootstrap_lower_above_zero": (
            package.bootstrap_lower is not None and package.bootstrap_lower > 0.0
        ),
        "ode_stratum_non_negative": (
            package.ode_stratum_median is not None
            and package.ode_stratum_median >= 0.0
        ),
        "pde_stratum_non_negative": (
            package.pde_stratum_median is not None
            and package.pde_stratum_median >= 0.0
        ),
    }
    for name, expected_value in recomputed_gate.items():
        if package.gate_checks.get(name) != expected_value:
            findings.append(f"冻结门禁 {name} 不能由签名结果重算。")
    gate_passed = bool(package.gate_checks) and all(package.gate_checks.values())
    if package.search_freeze_receipt_issued != gate_passed:
        findings.append("冻结门禁回执不能由门禁布尔值重算。")
    return tuple(findings)


def _load_candidate_interaction(
    *, root: Path, candidate: OfficialCandidateRecord, source_path: Path
) -> AutonomousModelInteraction:
    if candidate.interaction_hash is None:
        raise SubmissionEvidenceError("入选候选没有交互哈希")
    path = _inside(root, f"interactions/{candidate.interaction_id}.json")
    interaction = AutonomousModelInteraction.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    if interaction.interaction_id != candidate.interaction_id:
        raise SubmissionEvidenceError("候选交互编号不符")
    if interaction.interaction_hash != candidate.interaction_hash:
        raise SubmissionEvidenceError("候选交互哈希不符")
    if interaction.candidate_id != candidate.candidate_id:
        raise SubmissionEvidenceError("候选交互绑定另一候选")
    response = ScientificContractSourceResponse.model_validate(
        interaction.parsed_payload
    )
    if response.source_text.encode("utf-8") != source_path.read_bytes():
        raise SubmissionEvidenceError("候选源代码不是接受模型响应的精确字节")
    if response.implementation_summary != candidate.implementation_summary:
        raise SubmissionEvidenceError("候选摘要不是接受模型响应的精确字段")
    return interaction


def _identity_from_receipt(
    role: Literal["research_plan", "outcome"], receipt: ModelAuthorshipReceipt
) -> RecordedModelIdentity:
    return RecordedModelIdentity(
        artifact_role=role,
        interaction_id=receipt.interaction_id,
        provider=receipt.provider,
        base_url=receipt.base_url,
        model_name=receipt.model_name,
        endpoint=receipt.endpoint,
        interaction_hash=receipt.receipt_hash,
        api_key_value_logged=False,
    )


def _identity_from_interaction(
    interaction: AutonomousModelInteraction,
) -> RecordedModelIdentity:
    return RecordedModelIdentity(
        artifact_role="candidate_code",
        interaction_id=interaction.interaction_id,
        provider=interaction.provider,
        base_url=interaction.base_url,
        model_name=interaction.model_name,
        endpoint=interaction.endpoint,
        interaction_hash=interaction.interaction_hash,
        api_key_value_logged=False,
    )


def _raw_result_matches_summary(
    raw: Mapping[str, Any], summary: OfficialCellResult
) -> bool:
    status = raw.get("status", "failed")
    if status not in {"succeeded", "failed", "timed_out"}:
        status = "failed"
    expected = {
        "status": status,
        "derivative_nmse": raw.get("derivative_nmse"),
        "validation_nmse": raw.get("validation_nmse"),
        "selected_term_count": raw.get("selected_term_count"),
        "equation_changed_on_shuffled_training": raw.get(
            "equation_changed_on_shuffled_training"
        ),
        "maximum_equation_prediction_delta": raw.get(
            "maximum_equation_prediction_delta"
        ),
        "wall_time_seconds": raw.get("wall_time_seconds"),
        "failure_reason": raw.get("failure_reason"),
        "result_hash": raw.get("result_hash"),
    }
    actual = {
        key: getattr(summary, key)
        for key in (
            "status",
            "derivative_nmse",
            "validation_nmse",
            "selected_term_count",
            "equation_changed_on_shuffled_training",
            "maximum_equation_prediction_delta",
            "wall_time_seconds",
            "failure_reason",
            "result_hash",
        )
    }
    return actual == expected


def _secret_findings(paths: Sequence[Path]) -> list[str]:
    findings: list[str] = []
    value_patterns = (
        re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
        re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE),
    )
    forbidden_keys = {
        "api_key",
        "apikey",
        "authorization",
        "password",
        "secret",
        "access_token",
        "refresh_token",
    }
    allowed_keys = {"api_key_env_name", "api_key_value_logged"}
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if any(pattern.search(text) for pattern in value_patterns):
            findings.append(f"证据文件含疑似凭据值：{path.name}。")
        if path.suffix.casefold() in {".yaml", ".yml"} and re.search(
            r"(?im)^\s*(?:api_key|apikey|authorization|password|secret|"
            r"access_token|refresh_token)\s*:",
            text,
        ):
            findings.append(f"证据配置含疑似凭据字段：{path.name}。")
        try:
            payload = json.loads(text)
        except ValueError:
            continue
        bad_keys: set[str] = set()

        def inspect(value: Any, keys: set[str] = bad_keys) -> None:
            if isinstance(value, Mapping):
                for key, item in value.items():
                    normalized = str(key).casefold()
                    if normalized in forbidden_keys and normalized not in allowed_keys:
                        keys.add(str(key))
                    inspect(item)
            elif isinstance(value, list | tuple):
                for item in value:
                    inspect(item)

        inspect(payload)
        if bad_keys:
            findings.append(
                f"证据 JSON 含疑似凭据字段 {sorted(bad_keys)}：{path.name}。"
            )
    return findings


def _paths_for(
    artifacts: Mapping[Path, SubmissionArtifactDigest], *needles: str
) -> tuple[str, ...]:
    return tuple(
        item.path
        for item in artifacts.values()
        if any(needle in item.role for needle in needles)
    )


def _canonical_quality_commands() -> dict[str, tuple[str, ...]]:
    return {
        "pytest": (sys.executable, "-m", "pytest", "tests", "-q"),
        "ruff": (sys.executable, "-m", "ruff", "check", "src", "tests"),
        "mypy": (sys.executable, "-m", "mypy", "src/autoresearch"),
    }


def _quality_command_contract_hash() -> str:
    return canonical_model_hash(
        {
            name: list(command)
            for name, command in _canonical_quality_commands().items()
        }
    )


_HUMAN_AUTHORIZATION_REQUEST_FIELDS = (
    "lineage_id",
    "decision",
    "authorized_by",
    "authorization_statement",
    "notes",
    "plan_artifact_hash",
    "plan_decision_file_sha256",
    "signed_package_hash",
    "outcome_hash",
    "final_report_hash",
    "final_report_build_receipt_hash",
    "innovation_audit_hash",
    "reexecution_receipt_hash",
    "quality_gate_receipt_hash",
    "source_commit",
    "authorized_at",
    "authored_by_model",
    "is_scientific_evidence",
    "evidence_refs",
    "changes_scientific_verdict",
)


def human_publication_authorization_request_hash(
    payload: Mapping[str, Any],
) -> str:
    """Hash the exact objective snapshot and human intent signed out of band."""

    missing = [name for name in _HUMAN_AUTHORIZATION_REQUEST_FIELDS if name not in payload]
    if missing:
        raise SubmissionEvidenceError(
            "human publication authorization request omits fields: "
            + ", ".join(missing)
        )
    request = {
        "schema_version": "human-publication-authorization-request-v1",
        **{name: payload[name] for name in _HUMAN_AUTHORIZATION_REQUEST_FIELDS},
    }
    return canonical_model_hash(request)


def _human_publication_authorization_request_hash(
    payload: Mapping[str, Any],
) -> str:
    return human_publication_authorization_request_hash(payload)


def _verify_quality_receipt_artifacts(
    *, receipt: SubmissionQualityGateReceipt, receipt_path: Path
) -> tuple[Path, ...]:
    resolved_receipt = receipt_path.resolve()
    if not resolved_receipt.is_file():
        raise SubmissionEvidenceError("quality receipt file is missing")
    if Path(receipt.output_path).resolve() != resolved_receipt:
        raise SubmissionEvidenceError("quality receipt output path does not match its file")
    results = {item.name: item for item in receipt.commands}
    verified_paths: list[Path] = []
    for name in ("pytest", "ruff", "mypy"):
        result = results[name]
        log_path = _inside(resolved_receipt.parent, result.log_relative_path)
        if not log_path.is_file():
            raise SubmissionEvidenceError(f"quality log is missing: {name}")
        raw = log_path.read_bytes()
        if len(raw) != result.log_byte_count or file_hash(log_path) != result.log_sha256:
            raise SubmissionEvidenceError(f"quality log bytes do not match receipt: {name}")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise SubmissionEvidenceError(
                f"quality log is not canonical UTF-8 JSON: {name}"
            ) from exc
        if not isinstance(payload, Mapping) or set(payload) != {
            "name",
            "command",
            "exit_code",
            "stdout",
            "stderr",
        }:
            raise SubmissionEvidenceError(f"quality log schema mismatch: {name}")
        stdout = payload.get("stdout")
        stderr = payload.get("stderr")
        logged_command = payload.get("command")
        if (
            not isinstance(stdout, str)
            or not isinstance(stderr, str)
            or not isinstance(logged_command, list)
            or not all(isinstance(item, str) for item in logged_command)
        ):
            raise SubmissionEvidenceError(f"quality log streams are not text: {name}")
        if (
            payload.get("name") != name
            or tuple(logged_command) != result.command
            or payload.get("exit_code") != result.exit_code
            or _text_hash(stdout) != result.stdout_sha256
            or _text_hash(stderr) != result.stderr_sha256
            or _summary_count(stdout + "\n" + stderr, "skipped")
            != result.skipped_count
            or _summary_count(stdout + "\n" + stderr, "deselected")
            != result.deselected_count
        ):
            raise SubmissionEvidenceError(f"quality log content contradicts receipt: {name}")
        verified_paths.append(log_path)
    return tuple(verified_paths)


def _verify_reexecution_evidence(
    *,
    root: Path,
    package: OfficialDevelopmentSearchPackage,
    receipt: IndependentReexecutionReceipt,
    current_source_commit: str,
    quality_source_commit: str,
) -> tuple[Path, ...]:
    if not (
        receipt.source_commit == current_source_commit == quality_source_commit
    ):
        raise SubmissionEvidenceError(
            "independent reexecution, quality receipt, and current source commit differ"
        )
    output_directory = _inside(root, receipt.clean_output_directory)
    if output_directory == root.resolve():
        raise SubmissionEvidenceError(
            "independent reexecution requires a dedicated clean output directory"
        )
    if not output_directory.is_dir():
        raise SubmissionEvidenceError(
            "independent reexecution clean output directory is missing"
        )
    manifest_path = _inside(
        output_directory, receipt.artifact_manifest_relative_path
    )
    if not manifest_path.is_file():
        raise SubmissionEvidenceError("independent reexecution manifest is missing")
    if (
        manifest_path.stat().st_size != receipt.artifact_manifest_byte_count
        or file_hash(manifest_path) != receipt.artifact_manifest_sha256
    ):
        raise SubmissionEvidenceError(
            "independent reexecution manifest bytes do not match receipt"
        )
    manifest = IndependentReexecutionManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    if Path(manifest.output_path).resolve() != manifest_path:
        raise SubmissionEvidenceError(
            "independent reexecution manifest output path does not match its file"
        )
    if (
        manifest.lineage_id != root.name
        or manifest.package_hash != package.package_hash
        or manifest.source_commit != current_source_commit
        or manifest.manifest_hash != receipt.artifact_manifest_hash
    ):
        raise SubmissionEvidenceError(
            "independent reexecution manifest binds another lineage, package, or commit"
        )

    expected_results = {item.attempt_id: item for item in package.cell_results}
    if len(expected_results) != len(package.cell_results):
        raise SubmissionEvidenceError("signed package repeats an official cell attempt")
    manifest_entries = {item.attempt_id: item for item in manifest.cell_artifacts}
    if (
        set(manifest_entries) != set(expected_results)
        or len(manifest_entries) != receipt.expected_cell_count
        or receipt.expected_cell_count != len(expected_results)
        or receipt.reexecuted_cell_count != len(manifest_entries)
    ):
        raise SubmissionEvidenceError(
            "independent reexecution manifest does not cover every signed package cell"
        )

    verified_paths: list[Path] = [manifest_path]
    reexecuted_results: dict[str, OfficialCellResult] = {}
    for attempt_id, entry in manifest_entries.items():
        result_path = _inside(output_directory, entry.relative_path)
        if not result_path.is_file():
            raise SubmissionEvidenceError(
                f"independent reexecution cell result is missing: {attempt_id}"
            )
        if (
            result_path.stat().st_size != entry.byte_count
            or file_hash(result_path) != entry.sha256
        ):
            raise SubmissionEvidenceError(
                f"independent reexecution cell bytes do not match manifest: {attempt_id}"
            )
        try:
            raw_result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise SubmissionEvidenceError(
                f"independent reexecution cell is not valid JSON: {attempt_id}"
            ) from exc
        if not isinstance(raw_result, dict):
            raise SubmissionEvidenceError(
                f"independent reexecution cell is not an object: {attempt_id}"
            )
        claimed_result_hash = raw_result.get("result_hash")
        result_body = dict(raw_result)
        result_body.pop("result_hash", None)
        if claimed_result_hash != canonical_model_hash(result_body):
            raise SubmissionEvidenceError(
                f"independent reexecution cell result hash mismatch: {attempt_id}"
            )
        parsed_result = OfficialCellResult.model_validate(raw_result)
        if parsed_result.attempt_id != attempt_id:
            raise SubmissionEvidenceError(
                f"independent reexecution cell id contradicts manifest: {attempt_id}"
            )
        expected_result = expected_results[attempt_id]
        immutable_identity_fields = (
            "method_kind",
            "candidate_id",
            "stage",
            "system_name",
            "data_type",
            "condition",
            "seed",
        )
        if any(
            getattr(parsed_result, field_name)
            != getattr(expected_result, field_name)
            for field_name in immutable_identity_fields
        ):
            raise SubmissionEvidenceError(
                f"independent reexecution cell identity changed: {attempt_id}"
            )
        reexecuted_results[attempt_id] = parsed_result
        verified_paths.append(result_path)

    replay_package = package.model_copy(
        update={
            "cell_results": tuple(
                reexecuted_results[item.attempt_id] for item in package.cell_results
            )
        }
    )
    replay_findings = _replay_findings(replay_package)
    if replay_findings:
        raise SubmissionEvidenceError(
            "independent reexecution raw results do not reproduce the signed verdict: "
            + "；".join(replay_findings)
        )
    return tuple(verified_paths)


def _plan_decision_path(root: Path, project_id: str) -> Path:
    return _inside(
        root,
        Path("plan")
        / project_id
        / "research-plan"
        / "research-plan-decision.json",
    )


def _contained_quality_receipt_path(
    root: Path, quality_receipt_path: Path | str | None
) -> Path:
    path = _inside(
        root,
        quality_receipt_path
        if quality_receipt_path is not None
        else Path("submission-evidence") / _QUALITY_NAME,
    )
    if path.name != _QUALITY_NAME:
        raise SubmissionEvidenceError(
            "quality receipt path must use the canonical receipt filename"
        )
    return path


def _inside(root: Path, relative: str | Path) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise SubmissionEvidenceError(f"证据路径越出谱系目录：{relative}")
    return path


def _display_path(path: Path, *, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _normal_url(value: str) -> str:
    return value.rstrip("/").casefold()


def _text_hash(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _summary_count(output: str, label: str) -> int:
    matches = re.findall(rf"(\d+)\s+{re.escape(label)}\b", output, re.IGNORECASE)
    return max((int(item) for item in matches), default=0)


def _timeout_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _git_text(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ("git", *args),
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    value = completed.stdout.strip()
    if completed.returncode != 0 or not value:
        raise SubmissionEvidenceError(
            "无法读取 Git 源码身份：" + completed.stderr.strip()
        )
    return value


def _verify_quality_runtime_configuration(
    *, receipt: SubmissionQualityGateReceipt, repository_root: Path
) -> Path:
    """Recheck the exact non-secret configuration bound by a quality receipt."""

    repo = repository_root.resolve()
    config_path = (repo / receipt.configuration_relative_path).resolve()
    if (
        receipt.configuration_relative_path != _CANONICAL_CONFIG_RELATIVE_PATH
        or config_path != (repo / _CANONICAL_CONFIG_RELATIVE_PATH).resolve()
        or not config_path.is_file()
        or config_path.is_symlink()
        or file_hash(config_path) != receipt.configuration_sha256
    ):
        raise SubmissionEvidenceError(
            "quality receipt configuration bytes do not match repository-root config.yaml"
        )
    parsed = ConfigParser().parse_file(config_path, model_type=SystemConfig)
    if not isinstance(parsed, SystemConfig):
        raise SubmissionEvidenceError("quality receipt configuration is not a SystemConfig")
    if _secret_findings((config_path,)):
        raise SubmissionEvidenceError(
            "quality receipt configuration contains a credential field or value"
        )
    return config_path


def _require_submission_artifact_is_public(*, repo: Path, path: Path) -> None:
    """Keep local credentials and sovereign raw bytes out of bundle inventories."""

    repository = repo.resolve()
    resolved = path.resolve()
    if resolved == (repository / _LOCAL_SECRET_ENV_RELATIVE_PATH).resolve():
        raise SubmissionEvidenceError(
            "local secret .env must never enter a submission evidence bundle"
        )
    private_container = (repository / _SOVEREIGN_PRIVATE_CONTAINER).resolve()
    if resolved == private_container or resolved.is_relative_to(private_container):
        raise SubmissionEvidenceError(
            "sovereign raw memory must never enter a submission evidence bundle"
        )


def _tracked_worktree_clean(
    repo: Path, *, expected_config_sha256: str | None = None
) -> bool:
    repo = repo.resolve()
    tracked_private = subprocess.run(
        (
            "git",
            "ls-files",
            "-z",
            "--",
            _LOCAL_SECRET_ENV_RELATIVE_PATH,
            _CANONICAL_CONFIG_RELATIVE_PATH,
            _SOVEREIGN_PRIVATE_CONTAINER.as_posix(),
        ),
        cwd=repo,
        capture_output=True,
        check=False,
    )
    if (
        tracked_private.returncode != 0
        or not isinstance(tracked_private.stdout, bytes)
        or tracked_private.stdout
    ):
        return False
    completed = subprocess.run(
        (
            "git",
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--ignored=matching",
        ),
        cwd=repo,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0 or not isinstance(completed.stdout, bytes):
        return False
    if not completed.stdout:
        return True
    if not completed.stdout.endswith(b"\0"):
        return False

    for record in completed.stdout[:-1].split(b"\0"):
        if len(record) < 4 or record[2:3] != b" ":
            return False
        status = record[:2]
        if status not in {b"??", b"!!"}:
            return False
        path = _parse_status_path(record[3:])
        if path is None:
            return False
        if status == b"!!" and _allowed_canonical_private_runtime_state(
            repo=repo,
            path=path,
            expected_config_sha256=expected_config_sha256,
        ):
            continue
        if not _allowed_untracked_output_or_cache(path):
            return False
    return True


def _allowed_canonical_private_runtime_state(
    *, repo: Path, path: str, expected_config_sha256: str | None
) -> bool:
    normalized = path.rstrip("/")
    if normalized == _LOCAL_SECRET_ENV_RELATIVE_PATH:
        env_path = repo / _LOCAL_SECRET_ENV_RELATIVE_PATH
        return env_path.is_file() and not env_path.is_symlink()
    if normalized == _CANONICAL_CONFIG_RELATIVE_PATH:
        config_path = repo / _CANONICAL_CONFIG_RELATIVE_PATH
        return (
            expected_config_sha256 is not None
            and config_path.is_file()
            and not config_path.is_symlink()
            and file_hash(config_path) == expected_config_sha256
        )
    private_prefix = _SOVEREIGN_PRIVATE_CONTAINER.as_posix()
    if normalized != private_prefix and not normalized.startswith(private_prefix + "/"):
        return False
    return _canonical_sovereign_raw_memory_tree(repo)


def _canonical_sovereign_raw_memory_tree(repo: Path) -> bool:
    """Verify that the one ignored private tree contains only canonical raw memory.

    This reads locally to validate content addressing but returns no payload bytes or
    private hashes.  The tree is deliberately not represented in the quality receipt,
    evidence inventory, authorization request, or any publication package.
    """

    vault_root = (repo / "autoresearch-vault").resolve()
    private_container = vault_root / "_private"
    raw_root = private_container / "raw-memory"
    if (
        not private_container.is_dir()
        or private_container.is_symlink()
        or not raw_root.is_dir()
        or raw_root.is_symlink()
    ):
        return False

    blob_paths: set[Path] = set()
    referenced_blobs: set[Path] = set()
    for item in private_container.rglob("*"):
        if item.is_symlink():
            return False
        relative = item.relative_to(private_container)
        parts = relative.parts
        if item.is_dir():
            if not _canonical_raw_memory_directory(parts):
                return False
            continue
        if not item.is_file():
            return False

        blob_match = re.fullmatch(
            r"raw-memory/blobs/sha256/([0-9a-f]{2})/([0-9a-f]{64})"
            r"(?:\.[A-Za-z0-9]+)",
            relative.as_posix(),
        )
        if blob_match is not None:
            payload_hash = blob_match.group(2)
            if payload_hash[:2] != blob_match.group(1) or file_hash(item) != payload_hash:
                return False
            blob_paths.add(item.resolve())
            continue

        record_match = re.fullmatch(
            r"raw-memory/projects/([A-Za-z0-9][A-Za-z0-9_.-]*)/"
            r"records/([0-9]{4})/([0-9]{2})/(rawmem_[0-9a-f]{64})\.json",
            relative.as_posix(),
        )
        if record_match is None:
            return False
        try:
            raw = item.read_bytes()
            record = RawMemoryRecord.model_validate_json(raw)
        except (OSError, ValueError):
            return False
        if (
            raw != (canonical_json(record) + "\n").encode("utf-8")
            or record.envelope.project_id != record_match.group(1)
            or f"{record.envelope.captured_at.year:04d}" != record_match.group(2)
            or f"{record.envelope.captured_at.month:02d}" != record_match.group(3)
            or record.record_id != record_match.group(4)
        ):
            return False
        blob = (vault_root / record.blob_relative_path).resolve()
        if (
            not blob.is_relative_to(raw_root)
            or not blob.is_file()
            or blob.is_symlink()
            or blob.stat().st_size != record.envelope.payload_size
            or file_hash(blob) != record.envelope.payload_sha256
        ):
            return False
        referenced_blobs.add(blob)
    return blob_paths == referenced_blobs


def _canonical_raw_memory_directory(parts: tuple[str, ...]) -> bool:
    if parts in {
        ("raw-memory",),
        ("raw-memory", "blobs"),
        ("raw-memory", "blobs", "sha256"),
        ("raw-memory", "projects"),
    }:
        return True
    if (
        len(parts) == 4
        and parts[:3] == ("raw-memory", "blobs", "sha256")
        and re.fullmatch(r"[0-9a-f]{2}", parts[3])
    ):
        return True
    if len(parts) >= 3 and parts[:2] == ("raw-memory", "projects"):
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", parts[2]) is None:
            return False
        suffix = parts[3:]
        if suffix in {(), ("records",)}:
            return True
        if len(suffix) == 2 and suffix[0] == "records":
            return re.fullmatch(r"[0-9]{4}", suffix[1]) is not None
        if len(suffix) == 3 and suffix[0] == "records":
            return (
                re.fullmatch(r"[0-9]{4}", suffix[1]) is not None
                and re.fullmatch(r"(?:0[1-9]|1[0-2])", suffix[2]) is not None
            )
    return False


def _parse_status_path(raw_path: bytes) -> str | None:
    try:
        path = raw_path.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if (
        not path
        or path.startswith("/")
        or "\\" in path
        or any(ord(character) < 32 or ord(character) == 127 for character in path)
    ):
        return None
    parts = path.rstrip("/").split("/")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return None
    if ":" in parts[0]:
        return None
    return path


def _allowed_untracked_output_or_cache(path: str) -> bool:
    if path in _UNTRACKED_CACHE_FILES:
        return True
    for root in _UNTRACKED_OUTPUT_ROOTS:
        if path.startswith(root + "/"):
            return True
    components = path.rstrip("/").split("/")
    for index, component in enumerate(components):
        if component not in _UNTRACKED_CACHE_DIRS:
            continue
        cache_root = "/".join(components[: index + 1])
        if path.startswith(cache_root + "/"):
            return True
    return False
