"""One fail-closed audit for a competition submission evidence lineage.

This module does not invent scientific prose and does not repair historical evidence.
It reads the retained lineage, replays deterministic calculations, verifies raw
provider/source/cell bytes, compares configured and recorded model identities, and
writes a Chinese audit report.  Every absent or contradictory proof remains a failed
check.  In particular, a lineage whose artifacts still say
``publication_ready=false`` can never be labelled submission-ready.
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
    compile_plan_execution_contract,
    load_plan_execution_contract,
    require_candidate_plan_alignment,
)
from autoresearch.competition.preregistered_stage_breadth import load_stage_breadth
from autoresearch.competition.scientific_contract_harness import (
    ScientificContractSourceResponse,
)
from autoresearch.competition.system_authored_outcome import SystemAuthoredOutcome
from autoresearch.competition.system_authored_plan import (
    SystemAuthoredPlanArtifact,
    authored_plan_non_chinese_fields,
)
from autoresearch.config import ConfigParser, SystemConfig
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
    passed: bool

    @model_validator(mode="after")
    def _validate(self) -> QualityCommandResult:
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

    schema_version: Literal["submission-quality-gate-receipt-v1"] = (
        "submission-quality-gate-receipt-v1"
    )
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    tracked_worktree_clean: bool
    commands: tuple[QualityCommandResult, ...]
    all_passed: bool
    created_at: datetime
    receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str

    @model_validator(mode="after")
    def _validate(self) -> SubmissionQualityGateReceipt:
        if {item.name for item in self.commands} != {"pytest", "ruff", "mypy"}:
            raise SubmissionEvidenceError("quality receipt omits a required command")
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


class IndependentReexecutionReceipt(StrictFrozenModel):
    """Proof that a clean second run re-executed every scientific cell."""

    schema_version: Literal["independent-reexecution-receipt-v1"] = (
        "independent-reexecution-receipt-v1"
    )
    lineage_id: str
    package_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    clean_output_directory: str
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
        expected_publication = by_name["publication_readiness"].passed
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


def audit_submission_evidence_bundle(
    *,
    lineage_dir: Path | str,
    config_path: Path | str = Path("config.yaml"),
    output_dir: Path | str | None = None,
    repository_root: Path | str = Path("."),
    run_quality_gates: bool = False,
    quality_commands: Mapping[str, Sequence[str]] | None = None,
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
    contract = None
    decision = None
    if plan is None:
        approval_findings.append("批准边界无法核验，因为冻结计划不可用。")
        contract_findings.append("执行合同无法核验，因为冻结计划不可用。")
    else:
        try:
            decision = load_plan_decision(
                project_id=plan.project_id, output_dir=root / "plan"
            )
            require_approved_plan(plan=plan, decision=decision)
            if decision is None:
                raise SubmissionEvidenceError("计划决定记录缺失")
            if decision.is_evidence or decision.evidence_refs:
                approval_findings.append("人工计划批准被错误标记为科学证据。")
            decision_path = (
                root
                / "plan"
                / plan.project_id
                / "research-plan"
                / "research-plan-decision.json"
            )
            add_artifact(decision_path, "人工研究范围批准记录")
        except (OSError, RuntimeError, ValueError, PermissionError) as exc:
            approval_findings.append(f"人工计划批准无效：{exc}")
        try:
            contract = load_plan_execution_contract(root)
            expected_contract = compile_plan_execution_contract(plan)
            if contract != expected_contract:
                contract_findings.append("保留的执行合同不等于批准计划的确定性编译结果。")
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
                require_candidate_plan_alignment(candidates=[selected], contract=contract)
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
    ledger.record(
        "independent_scientific_reexecution",
        findings=reexecution_findings,
        evidence_paths=_paths_for(artifacts, "独立科学重执行"),
    )

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
    try:
        quality_path = destination / _QUALITY_NAME
        if run_quality_gates:
            quality = run_submission_quality_gates(
                repository_root=repo,
                output_dir=destination,
                commands=quality_commands,
                clock=clock,
            )
        else:
            quality = SubmissionQualityGateReceipt.model_validate_json(
                quality_path.read_text(encoding="utf-8")
            )
        add_artifact(quality_path, "广泛代码质量门回执")
        current_commit = _git_text(repo, "rev-parse", "HEAD")
        if quality.source_commit != current_commit:
            quality_findings.append("质量门回执不是针对当前源码提交。")
        if not quality.all_passed:
            quality_findings.append("pytest、ruff、mypy 或源码洁净门仍为红色。")
    except (OSError, RuntimeError, ValueError) as exc:
        quality_findings.append(f"缺少当前提交的广泛质量门回执：{exc}")
    ledger.record(
        "broad_quality_gates",
        findings=quality_findings,
        evidence_paths=_paths_for(artifacts, "质量门"),
    )

    required_findings: list[str] = []
    if final_input is None or not final_input.accepted:
        required_findings.append("最终报告输入审计缺失或未通过。")
    if outcome is None or outcome.relation_audit is None:
        required_findings.append("数值关系审计缺失。")
    if selected is None or selected.plan_alignment is None:
        required_findings.append("候选计划对齐审计缺失。")
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

    publication_findings: list[str] = []
    publication_flags = {
        "签名结果包": package.publication_ready if package is not None else False,
        "系统结果解释": outcome.publication_ready if outcome is not None else False,
        "最终研究报告": report.publication_ready if report is not None else False,
        "创新性审计": innovation.publication_ready if innovation is not None else False,
    }
    false_roles = [name for name, value in publication_flags.items() if not value]
    if false_roles:
        publication_findings.append(
            "以下权威制品仍明确标记 publication_ready=false："
            + "、".join(false_roles)
            + "。"
        )
    if quality is None or not quality.all_passed:
        publication_findings.append("广泛代码质量门尚未全绿。")
    if innovation is None or not innovation.publication_innovation_ready:
        publication_findings.append("创新性与正向效果证据尚未同时通过。")
    if reexecution is None or not reexecution.passed:
        publication_findings.append("尚无通过的独立科学重执行。")
    ledger.record(
        "publication_readiness",
        findings=publication_findings,
        evidence_paths=tuple(item.path for item in artifacts.values()),
    )

    secret_findings = _secret_findings(
        [path for path in artifacts if path.suffix.casefold() == ".json"]
    )
    if config_identity is not None and config_identity.api_key_value_logged:
        secret_findings.append("模型配置记录了 API 密钥值。")
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
    publication_ready = next(
        item.passed for item in checks if item.name == "publication_readiness"
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
    commands: Mapping[str, Sequence[str]] | None = None,
    clock: datetime | None = None,
) -> SubmissionQualityGateReceipt:
    """Run strict broad gates; skipped or deselected tests remain a red gate."""

    repo = Path(repository_root).resolve()
    destination = Path(output_dir).resolve()
    quality_dir = destination / "quality-logs"
    quality_dir.mkdir(parents=True, exist_ok=True)
    default_commands: dict[str, Sequence[str]] = {
        "pytest": (
            sys.executable,
            "-m",
            "pytest",
            "tests",
            "-q",
        ),
        "ruff": (sys.executable, "-m", "ruff", "check", "src", "tests"),
        "mypy": (sys.executable, "-m", "mypy", "src/autoresearch"),
    }
    selected_commands = dict(commands or default_commands)
    if set(selected_commands) != {"pytest", "ruff", "mypy"}:
        raise SubmissionEvidenceError(
            "quality command set must contain exactly pytest, ruff, and mypy"
        )
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
        log_path.write_text(
            "命令：" + " ".join(command) + "\n\n标准输出：\n" + stdout
            + "\n\n标准错误：\n" + stderr,
            encoding="utf-8",
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
                passed=exit_code == 0 and skipped == 0 and deselected == 0,
            )
        )
    commit = _git_text(repo, "rev-parse", "HEAD")
    tracked_clean = _tracked_worktree_clean(repo)
    now = clock or datetime.now(timezone.utc)
    output_path = destination / _QUALITY_NAME
    payload: dict[str, Any] = {
        "schema_version": "submission-quality-gate-receipt-v1",
        "source_commit": commit,
        "tracked_worktree_clean": tracked_clean,
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
            payload = json.loads(text)
        except (OSError, UnicodeDecodeError, ValueError):
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
        if any(pattern.search(text) for pattern in value_patterns):
            findings.append(f"证据 JSON 含疑似凭据值：{path.name}。")
    return findings


def _paths_for(
    artifacts: Mapping[Path, SubmissionArtifactDigest], *needles: str
) -> tuple[str, ...]:
    return tuple(
        item.path
        for item in artifacts.values()
        if any(needle in item.role for needle in needles)
    )


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


def _tracked_worktree_clean(repo: Path) -> bool:
    unstaged = subprocess.run(("git", "diff", "--quiet"), cwd=repo, check=False)
    staged = subprocess.run(
        ("git", "diff", "--cached", "--quiet"), cwd=repo, check=False
    )
    return unstaged.returncode == 0 and staged.returncode == 0
