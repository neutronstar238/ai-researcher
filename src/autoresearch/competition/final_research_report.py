"""Materialize one evidence-bound final report without rewriting preregistration.

The final report is a derived view of four independently validated artifacts:

* the system-authored, grader-accepted research plan;
* the human-approved copy of those exact plan bytes and its execution contract;
* the signed execution package for a selected plan-aligned implementation; and
* the accepted system-authored outcome, including numeric provenance and relation
  audits.

No scientific prose is authored here.  Fixed headings and table labels are template
text; every scientific statement is copied verbatim from either the plan or the
outcome.  The preregistration is read twice and hashed before and after rendering so
observed results can never be written back into it.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.competition.official_development_search import (
    OfficialCandidateRecord,
    OfficialDevelopmentSearchPackage,
)
from autoresearch.competition.plan_execution_contract import (
    PlanExecutionContract,
    compile_plan_execution_contract,
    load_plan_execution_contract,
    require_candidate_plan_alignment,
)
from autoresearch.competition.research_plan_latex import (
    _PREAMBLE,
    _itemize,
    _render_reference,
    _tex_escape,
    assert_all_prose_is_authored,
    guard_references,
)
from autoresearch.competition.system_authored_outcome import (
    AuthoredInterpretation,
    SystemAuthoredOutcome,
    authored_interpretation_non_chinese_fields,
)
from autoresearch.competition.system_authored_plan import (
    SystemAuthoredPlanArtifact,
    authored_plan_non_chinese_fields,
)
from autoresearch.research.plan_confirmation import (
    ResearchPlanDecisionRecord,
    load_plan_decision,
    require_approved_plan,
)
from autoresearch.schemas import ResearchPlan, file_hash

_PLAN_ARTIFACT_NAME = "system-authored-research-plan.json"
_APPROVED_PLAN_RELATIVE = Path("plan") / "research-plan.json"
_PACKAGE_NAME = "official-development-search-package.json"
_OUTCOME_NAME = "system-authored-outcome.json"
_REPORT_NAME = "final-research-report.json"
_MARKDOWN_NAME = "final-research-report.md"
_LATEX_NAME = "final-research-report.tex"
_PDF_NAME = "final-research-report.pdf"
_BUILD_NAME = "final-research-report-build.json"

_INPUT_CHECKS: tuple[str, ...] = (
    "system_authored_plan_integrity",
    "plan_guard_accepted",
    "system_authored_plan_chinese",
    "authored_plan_matches_preregistration",
    "human_approval_bound_to_plan",
    "plan_execution_contract_matches",
    "package_integrity",
    "complete_observed_metrics",
    "selected_candidate_plan_aligned",
    "selected_candidate_source_matches",
    "outcome_integrity",
    "system_authored_outcome_chinese",
    "model_authorship_attested",
    "outcome_matches_package",
    "outcome_accepted",
    "numeric_traceability_passed",
    "numeric_relations_passed",
    "frozen_gate_semantics_consistent",
    "references_verifiable",
)

_METRIC_ORDER: tuple[tuple[str, str], ...] = (
    ("selected_candidate_id", "selected_candidate_id"),
    ("overall_median_log_effect", "overall_median_log_effect"),
    ("bootstrap_lower", "bootstrap_lower"),
    ("bootstrap_upper", "bootstrap_upper"),
    ("ode_stratum_median", "ode_stratum_median"),
    ("pde_stratum_median", "pde_stratum_median"),
    ("minimum_overall_log_effect", "minimum_overall_log_effect"),
    ("paired_system_count", "paired_system_count"),
    ("baseline_coverage_gap_count", "baseline_coverage_gap_count"),
    ("candidate_win_count", "candidate_win_count"),
    ("executed_cell_count", "executed_cell_count"),
    ("succeeded_cell_count", "succeeded_cell_count"),
    ("failed_cell_count", "failed_cell_count"),
    ("timed_out_cell_count", "timed_out_cell_count"),
    ("search_freeze_receipt_issued", "search_freeze_receipt_issued"),
)

_VERDICT_LABELS: dict[str, str] = {
    "claim_supported": "结论获得支持",
    "claim_not_supported": "结论未获支持",
    "inconclusive_underpowered": "证据不足（检验力有限）",
}


class FinalResearchReportError(RuntimeError):
    """Raised when a final report would overstate or detach from its evidence."""


class FinalReportInputAudit(StrictFrozenModel):
    """Hash-bound, non-narrative preflight for final-report materialization."""

    schema_version: Literal["final-report-input-audit-v1"] = (
        "final-report-input-audit-v1"
    )
    lineage_id: str = Field(min_length=1)
    checks: dict[str, bool]
    findings: tuple[str, ...]
    accepted: bool
    plan_artifact_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    approved_plan_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    plan_contract_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    package_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    outcome_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    selected_candidate_id: str | None = None
    audit_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate(self) -> FinalReportInputAudit:
        if set(self.checks) != set(_INPUT_CHECKS):
            raise FinalResearchReportError(
                "final-report input audit does not cover every required check"
            )
        expected_accepted = all(self.checks.values()) and not self.findings
        if self.accepted != expected_accepted:
            raise FinalResearchReportError(
                "final-report input verdict contradicts its checks or findings"
            )
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"audit_hash"})
        )
        if self.audit_hash != expected:
            raise FinalResearchReportError("final-report input audit hash mismatch")
        return self


class FinalObservedMetrics(StrictFrozenModel):
    """Only values copied from, or deterministically counted in, the signed package."""

    schema_version: Literal["final-observed-metrics-v1"] = (
        "final-observed-metrics-v1"
    )
    selected_candidate_id: str = Field(min_length=1)
    overall_median_log_effect: float
    bootstrap_lower: float
    bootstrap_upper: float
    ode_stratum_median: float
    pde_stratum_median: float
    minimum_overall_log_effect: float
    paired_system_count: int = Field(ge=1)
    baseline_coverage_gap_count: int = Field(ge=0)
    candidate_win_count: int = Field(ge=0)
    executed_cell_count: int = Field(ge=1)
    succeeded_cell_count: int = Field(ge=0)
    failed_cell_count: int = Field(ge=0)
    timed_out_cell_count: int = Field(ge=0)
    gate_checks: dict[str, bool] = Field(min_length=1)
    frozen_gate_passed: bool
    search_freeze_receipt_issued: bool

    @model_validator(mode="after")
    def _validate(self) -> FinalObservedMetrics:
        if self.bootstrap_lower > self.bootstrap_upper:
            raise FinalResearchReportError("bootstrap interval is reversed")
        if self.candidate_win_count > self.paired_system_count:
            raise FinalResearchReportError("candidate wins exceed paired systems")
        terminal_count = (
            self.succeeded_cell_count
            + self.failed_cell_count
            + self.timed_out_cell_count
        )
        if terminal_count != self.executed_cell_count:
            raise FinalResearchReportError(
                "terminal cell counts do not equal the executed-cell count"
            )
        gate_passed = all(self.gate_checks.values())
        if self.frozen_gate_passed != gate_passed:
            raise FinalResearchReportError(
                "observed metric gate verdict contradicts its checks"
            )
        if self.search_freeze_receipt_issued != gate_passed:
            raise FinalResearchReportError(
                "search-freeze receipt does not exactly match the frozen gate"
            )
        return self


class FinalResearchReport(StrictFrozenModel):
    """The immutable plan and observed outcome joined only after all gates pass."""

    schema_version: Literal["final-research-report-v1"] = "final-research-report-v1"
    lineage_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    preregistered_plan: dict[str, Any]
    preregistered_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_artifact_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_plan_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_guard_report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_execution_contract_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_candidate_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    package_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_audit_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    metrics: FinalObservedMetrics
    interpretation: AuthoredInterpretation
    plan_model_name: str = Field(min_length=1)
    outcome_model_name: str = Field(min_length=1)
    plan_authored_by_model: Literal[True] = True
    outcome_authored_by_model: Literal[True] = True
    hand_written_scientific_prose_field_count: Literal[0] = 0
    preregistration_preserved: Literal[True] = True
    human_approval_is_scientific_evidence: Literal[False] = False
    publication_ready: Literal[False] = False
    created_at: datetime
    report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str

    @model_validator(mode="after")
    def _validate(self) -> FinalResearchReport:
        if canonical_model_hash(self.preregistered_plan) != self.preregistered_plan_hash:
            raise FinalResearchReportError("final report carries altered plan content")
        plan = ResearchPlan.model_validate(self.preregistered_plan)
        plan_language_failures = authored_plan_non_chinese_fields(plan)
        outcome_language_failures = authored_interpretation_non_chinese_fields(
            self.interpretation
        )
        if plan_language_failures or outcome_language_failures:
            raise FinalResearchReportError(
                "final report contains non-Chinese system-authored prose: "
                f"plan={list(plan_language_failures)}, "
                f"outcome={list(outcome_language_failures)}"
            )
        contract = compile_plan_execution_contract(plan)
        if contract.approved_plan_hash != self.approved_plan_hash:
            raise FinalResearchReportError("final report approved-plan hash mismatch")
        if contract.contract_hash != self.plan_execution_contract_hash:
            raise FinalResearchReportError("final report plan-contract hash mismatch")
        if (
            self.interpretation.claims_frozen_gate_passed
            != self.metrics.frozen_gate_passed
        ):
            raise FinalResearchReportError(
                "final narrative gate claim contradicts observed metrics"
            )
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"report_hash", "output_path"})
        )
        if self.report_hash != expected:
            raise FinalResearchReportError("final research report hash mismatch")
        return self


class FinalReportBuildReceipt(StrictFrozenModel):
    """Hashes and semantic checks for the four synchronized report renderings."""

    schema_version: Literal["final-report-build-receipt-v1"] = (
        "final-report-build-receipt-v1"
    )
    report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    json_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    markdown_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    latex_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pdf_compiled: bool
    pdf_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    compiler: str | None = None
    compiler_version: str | None = None
    compiler_command: tuple[str, ...] = ()
    consistency_checks: dict[str, bool] = Field(min_length=1)
    all_renderings_consistent: bool
    created_at: datetime
    receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str

    @model_validator(mode="after")
    def _validate(self) -> FinalReportBuildReceipt:
        if self.pdf_compiled != (self.pdf_sha256 is not None):
            raise FinalResearchReportError(
                "PDF build verdict contradicts the retained PDF hash"
            )
        expected_consistency = self.pdf_compiled and all(
            self.consistency_checks.values()
        )
        if self.all_renderings_consistent != expected_consistency:
            raise FinalResearchReportError(
                "rendering consistency verdict contradicts its checks"
            )
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"receipt_hash", "output_path"})
        )
        if self.receipt_hash != expected:
            raise FinalResearchReportError("final-report build receipt hash mismatch")
        return self


def audit_final_report_inputs(
    *, lineage_dir: Path | str
) -> FinalReportInputAudit:
    """Audit every required input without mutating the retained lineage."""

    root = Path(lineage_dir).resolve()
    lineage_id = root.name
    checks = {name: False for name in _INPUT_CHECKS}
    findings: list[str] = []

    def fail(check: str, message: str) -> None:
        findings.append(f"{check}: {message}")

    artifact: SystemAuthoredPlanArtifact | None = None
    plan: ResearchPlan | None = None
    decision: ResearchPlanDecisionRecord | None = None
    contract: PlanExecutionContract | None = None
    package: OfficialDevelopmentSearchPackage | None = None
    outcome: SystemAuthoredOutcome | None = None
    selected: OfficialCandidateRecord | None = None

    try:
        artifact = SystemAuthoredPlanArtifact.model_validate_json(
            (root / _PLAN_ARTIFACT_NAME).read_text(encoding="utf-8")
        )
        checks["system_authored_plan_integrity"] = artifact.lineage_id == lineage_id
        if not checks["system_authored_plan_integrity"]:
            fail(
                "system_authored_plan_integrity",
                "plan artifact belongs to a different lineage",
            )
        checks["plan_guard_accepted"] = artifact.guard_report.accepted
        if not checks["plan_guard_accepted"]:
            fail("plan_guard_accepted", "system-authored plan guard refused the plan")
    except (OSError, RuntimeError, ValueError) as exc:
        fail("system_authored_plan_integrity", str(exc))
        fail("plan_guard_accepted", "no valid system-authored plan is available")

    try:
        plan = ResearchPlan.model_validate_json(
            (root / _APPROVED_PLAN_RELATIVE).read_text(encoding="utf-8")
        )
        non_chinese_plan = authored_plan_non_chinese_fields(plan)
        checks["system_authored_plan_chinese"] = not non_chinese_plan
        if non_chinese_plan:
            fail(
                "system_authored_plan_chinese",
                "non-Chinese system-authored fields: " + str(list(non_chinese_plan)),
            )
        checks["authored_plan_matches_preregistration"] = bool(
            artifact is not None
            and artifact.plan == plan.model_dump(mode="json")
            and artifact.plan_hash == canonical_model_hash(artifact.plan)
        )
        if not checks["authored_plan_matches_preregistration"]:
            fail(
                "authored_plan_matches_preregistration",
                "approved preregistration is not the exact system-authored plan",
            )
        decision = load_plan_decision(project_id=plan.project_id, output_dir=root / "plan")
        require_approved_plan(plan=plan, decision=decision)
        checks["human_approval_bound_to_plan"] = True
    except (OSError, RuntimeError, ValueError, PermissionError) as exc:
        if plan is None:
            fail("authored_plan_matches_preregistration", str(exc))
            fail("system_authored_plan_chinese", "approved plan is unavailable")
        fail("human_approval_bound_to_plan", str(exc))

    try:
        if plan is None:
            raise FinalResearchReportError("approved research plan is unavailable")
        expected_contract = compile_plan_execution_contract(plan)
        contract = load_plan_execution_contract(root)
        checks["plan_execution_contract_matches"] = contract == expected_contract
        if not checks["plan_execution_contract_matches"]:
            fail(
                "plan_execution_contract_matches",
                "retained contract differs from the approved plan",
            )
    except (OSError, RuntimeError, ValueError) as exc:
        fail("plan_execution_contract_matches", str(exc))

    try:
        package = OfficialDevelopmentSearchPackage.model_validate_json(
            (root / _PACKAGE_NAME).read_text(encoding="utf-8")
        )
        checks["package_integrity"] = True
        observed = (
            package.overall_median_log_effect,
            package.bootstrap_lower,
            package.bootstrap_upper,
            package.ode_stratum_median,
            package.pde_stratum_median,
        )
        has_selected_full = any(
            cell.method_kind == "candidate"
            and cell.stage == "full"
            and cell.candidate_id == package.selected_candidate_id
            for cell in package.cell_results
        )
        has_baseline = any(
            cell.method_kind == "baseline" and cell.stage == "baseline"
            for cell in package.cell_results
        )
        checks["complete_observed_metrics"] = bool(
            package.selected_candidate_id
            and all(value is not None for value in observed)
            and package.system_effects
            and has_selected_full
            and has_baseline
        )
        if not checks["complete_observed_metrics"]:
            fail(
                "complete_observed_metrics",
                "signed package lacks selected full cells, baseline cells, effects, or aggregates",
            )
        selected = next(
            (
                item
                for item in package.candidates
                if item.candidate_id == package.selected_candidate_id
            ),
            None,
        )
        if selected is None:
            fail(
                "selected_candidate_plan_aligned",
                "selected candidate is absent from the signed candidate registry",
            )
        elif contract is None:
            fail(
                "selected_candidate_plan_aligned",
                "no matching plan contract exists for the selected candidate",
            )
        else:
            require_candidate_plan_alignment(candidates=[selected], contract=contract)
            checks["selected_candidate_plan_aligned"] = selected.static_review_approved
            if not selected.static_review_approved:
                fail(
                    "selected_candidate_plan_aligned",
                    "selected candidate failed static review",
                )

        if selected is not None:
            source_path = _candidate_source_path(root=root, candidate=selected)
            checks["selected_candidate_source_matches"] = bool(
                source_path.is_file() and file_hash(source_path) == selected.source_sha256
            )
            if not checks["selected_candidate_source_matches"]:
                fail(
                    "selected_candidate_source_matches",
                    "selected candidate source is missing or differs from its signed hash",
                )
        else:
            fail(
                "selected_candidate_source_matches",
                "no selected candidate source can be verified",
            )
    except (OSError, RuntimeError, ValueError) as exc:
        fail("package_integrity", str(exc))
        if not checks["selected_candidate_plan_aligned"]:
            fail("selected_candidate_plan_aligned", str(exc))
        if not checks["selected_candidate_source_matches"]:
            fail("selected_candidate_source_matches", str(exc))

    try:
        outcome = SystemAuthoredOutcome.model_validate_json(
            (root / _OUTCOME_NAME).read_text(encoding="utf-8")
        )
        checks["outcome_integrity"] = outcome.lineage_id == lineage_id
        if not checks["outcome_integrity"]:
            fail("outcome_integrity", "outcome belongs to a different lineage")
        non_chinese_outcome = authored_interpretation_non_chinese_fields(
            outcome.interpretation
        )
        checks["system_authored_outcome_chinese"] = not non_chinese_outcome
        if non_chinese_outcome:
            fail(
                "system_authored_outcome_chinese",
                "non-Chinese system-authored fields: "
                + str(list(non_chinese_outcome)),
            )
        checks["model_authorship_attested"] = bool(
            artifact is not None
            and artifact.authored_by_model
            and artifact.hand_written_prose_field_count == 0
            and artifact.model_name
            and artifact.reasoning_tokens > 0
            and outcome.authored_by_model
            and outcome.hand_written_prose_count == 0
            and outcome.model_name
            and outcome.reasoning_tokens > 0
        )
        if not checks["model_authorship_attested"]:
            fail(
                "model_authorship_attested",
                "plan/outcome lacks positive model-generation provenance or reports hand-written prose",
            )
        checks["outcome_matches_package"] = bool(
            package is not None and outcome.package_hash == package.package_hash
        )
        if not checks["outcome_matches_package"]:
            fail("outcome_matches_package", "outcome binds a different signed package")
        checks["outcome_accepted"] = outcome.accepted and not outcome.refusal_reasons
        if not checks["outcome_accepted"]:
            fail("outcome_accepted", "system-authored outcome was refused by its graders")
        checks["numeric_traceability_passed"] = outcome.traceability.passed
        if not checks["numeric_traceability_passed"]:
            fail(
                "numeric_traceability_passed",
                f"untraceable numbers: {list(outcome.traceability.untraceable_numbers)}",
            )
        checks["numeric_relations_passed"] = bool(
            outcome.relation_audit is not None and outcome.relation_audit.passed
        )
        if not checks["numeric_relations_passed"]:
            detail = (
                "relation audit is absent"
                if outcome.relation_audit is None
                else f"contradictions: {list(outcome.relation_audit.contradictions)}"
            )
            fail("numeric_relations_passed", detail)
        if package is not None:
            gate_passed = all(package.gate_checks.values())
            checks["frozen_gate_semantics_consistent"] = bool(
                package.gate_checks
                and package.search_freeze_receipt_issued == gate_passed
                and outcome.frozen_gate_passed == gate_passed
                and outcome.verdict_consistent_with_gate
                and outcome.interpretation.claims_frozen_gate_passed == gate_passed
            )
        if not checks["frozen_gate_semantics_consistent"]:
            fail(
                "frozen_gate_semantics_consistent",
                "package receipt, gate checks, and authored verdict do not agree",
            )
    except (OSError, RuntimeError, ValueError) as exc:
        fail("outcome_integrity", str(exc))
        for check in (
            "system_authored_outcome_chinese",
            "model_authorship_attested",
            "outcome_matches_package",
            "outcome_accepted",
            "numeric_traceability_passed",
            "numeric_relations_passed",
            "frozen_gate_semantics_consistent",
        ):
            if not checks[check]:
                fail(check, "no valid system-authored outcome is available")

    if plan is not None:
        problems = guard_references(plan.literature_references)
        checks["references_verifiable"] = not problems
        if problems:
            fail("references_verifiable", "; ".join(problems))
    else:
        fail("references_verifiable", "approved plan is unavailable")

    payload: dict[str, Any] = {
        "schema_version": "final-report-input-audit-v1",
        "lineage_id": lineage_id,
        "checks": checks,
        "findings": tuple(dict.fromkeys(findings)),
        "accepted": all(checks.values()) and not findings,
        "plan_artifact_hash": artifact.artifact_hash if artifact else None,
        "approved_plan_hash": contract.approved_plan_hash if contract else None,
        "plan_contract_hash": contract.contract_hash if contract else None,
        "package_hash": package.package_hash if package else None,
        "outcome_hash": outcome.outcome_hash if outcome else None,
        "selected_candidate_id": package.selected_candidate_id if package else None,
    }
    payload["audit_hash"] = canonical_model_hash(payload)
    return FinalReportInputAudit.model_validate(payload)


def materialize_final_research_report(
    *,
    lineage_dir: Path | str,
    output_dir: Path | str | None = None,
    compile_pdf: bool = True,
    clock: datetime | None = None,
) -> FinalResearchReport:
    """Write synchronized JSON, Markdown, TeX, and (normally) PDF report views."""

    root = Path(lineage_dir).resolve()
    audit = audit_final_report_inputs(lineage_dir=root)
    if not audit.accepted:
        raise FinalResearchReportError(
            "final report input audit failed: " + "; ".join(audit.findings)
        )

    artifact_path = root / _PLAN_ARTIFACT_NAME
    approved_plan_path = root / _APPROVED_PLAN_RELATIVE
    artifact_before = file_hash(artifact_path)
    approved_before = file_hash(approved_plan_path)
    artifact = SystemAuthoredPlanArtifact.model_validate_json(
        artifact_path.read_text(encoding="utf-8")
    )
    plan = ResearchPlan.model_validate_json(approved_plan_path.read_text(encoding="utf-8"))
    contract = load_plan_execution_contract(root)
    package = OfficialDevelopmentSearchPackage.model_validate_json(
        (root / _PACKAGE_NAME).read_text(encoding="utf-8")
    )
    outcome = SystemAuthoredOutcome.model_validate_json(
        (root / _OUTCOME_NAME).read_text(encoding="utf-8")
    )
    selected = next(
        item
        for item in package.candidates
        if item.candidate_id == package.selected_candidate_id
    )
    source_path = _candidate_source_path(root=root, candidate=selected)

    metrics = _observed_metrics(package)
    now = clock or datetime.now(timezone.utc)
    destination = Path(output_dir).resolve() if output_dir else root / "final-report"
    destination.mkdir(parents=True, exist_ok=True)
    report_path = destination / _REPORT_NAME
    payload: dict[str, Any] = {
        "schema_version": "final-research-report-v1",
        "lineage_id": root.name,
        "title": plan.title,
        "preregistered_plan": plan.model_dump(mode="json"),
        "preregistered_plan_hash": artifact.plan_hash,
        "plan_artifact_hash": artifact.artifact_hash,
        "plan_artifact_file_sha256": artifact_before,
        "approved_plan_hash": contract.approved_plan_hash,
        "approved_plan_file_sha256": approved_before,
        "plan_guard_report_hash": artifact.guard_report.report_hash,
        "plan_execution_contract_hash": contract.contract_hash,
        "selected_candidate_source_sha256": file_hash(source_path),
        "package_hash": package.package_hash,
        "outcome_hash": outcome.outcome_hash,
        "input_audit_hash": audit.audit_hash,
        "metrics": metrics.model_dump(mode="json"),
        "interpretation": outcome.interpretation.model_dump(mode="json"),
        "plan_model_name": artifact.model_name,
        "outcome_model_name": outcome.model_name,
        "plan_authored_by_model": True,
        "outcome_authored_by_model": True,
        "hand_written_scientific_prose_field_count": 0,
        "preregistration_preserved": True,
        "human_approval_is_scientific_evidence": False,
        "publication_ready": False,
        "created_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    payload["report_hash"] = canonical_model_hash(payload)
    payload["output_path"] = report_path.as_posix()
    report = FinalResearchReport.model_validate(payload)
    write_json_model(report_path, report)

    markdown_path = destination / _MARKDOWN_NAME
    latex_path = destination / _LATEX_NAME
    _write_text_atomic(markdown_path, render_final_research_report_markdown(report))
    _write_text_atomic(latex_path, render_final_research_report_latex(report))

    pdf_path: Path | None = None
    compiler: str | None = None
    compiler_version: str | None = None
    command: tuple[str, ...] = ()
    pdf_text: str | None = None
    if compile_pdf:
        pdf_path, compiler, compiler_version, command, pdf_text = _compile_and_read_pdf(
            latex_path
        )

    checks = validate_final_report_renderings(
        report=report,
        json_text=report_path.read_text(encoding="utf-8"),
        markdown_text=markdown_path.read_text(encoding="utf-8"),
        latex_text=latex_path.read_text(encoding="utf-8"),
        pdf_text=pdf_text,
    )
    required_checks = {"json_key_metrics", "markdown_key_metrics", "latex_key_metrics"}
    if not all(checks[name] for name in required_checks):
        raise FinalResearchReportError(
            f"derived report views disagree before PDF publication: {checks}"
        )
    if compile_pdf and not checks["pdf_key_metrics"]:
        raise FinalResearchReportError(
            "compiled PDF text does not contain the exact verdict and key metrics"
        )

    receipt_path = destination / _BUILD_NAME
    receipt_payload: dict[str, Any] = {
        "schema_version": "final-report-build-receipt-v1",
        "report_hash": report.report_hash,
        "json_sha256": file_hash(report_path),
        "markdown_sha256": file_hash(markdown_path),
        "latex_sha256": file_hash(latex_path),
        "pdf_compiled": pdf_path is not None,
        "pdf_sha256": file_hash(pdf_path) if pdf_path is not None else None,
        "compiler": compiler,
        "compiler_version": compiler_version,
        "compiler_command": command,
        "consistency_checks": checks,
        "all_renderings_consistent": pdf_path is not None and all(checks.values()),
        "created_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    receipt_payload["receipt_hash"] = canonical_model_hash(receipt_payload)
    receipt_payload["output_path"] = receipt_path.as_posix()
    receipt = FinalReportBuildReceipt.model_validate(receipt_payload)
    write_json_model(receipt_path, receipt)

    if file_hash(artifact_path) != artifact_before or file_hash(approved_plan_path) != approved_before:
        raise FinalResearchReportError(
            "preregistered plan bytes changed while materializing observed results"
        )
    return FinalResearchReport.model_validate_json(report_path.read_text(encoding="utf-8"))


def render_final_research_report_markdown(report: FinalResearchReport) -> str:
    """Render a human view while copying all scientific prose verbatim."""

    plan = report.preregistered_plan
    interpretation = report.interpretation
    out = [f"# {report.title}——最终研究报告", ""]
    out.extend(
        [
            "> 本报告由不可变研究计划、签名执行包和通过确定性审计的系统结果解读单向派生。",
            "> 人工撰写的科学散文字段数：0；人工审批仅授权范围，不构成科学证据。",
            ">",
            f"> - `report_hash`：`{report.report_hash}`",
            f"> - `preregistered_plan_hash`：`{report.preregistered_plan_hash}`",
            f"> - `approved_plan_hash`：`{report.approved_plan_hash}`",
            f"> - `plan_execution_contract_hash`：`{report.plan_execution_contract_hash}`",
            f"> - `package_hash`：`{report.package_hash}`",
            f"> - `outcome_hash`：`{report.outcome_hash}`",
            "",
            "## 摘要",
            "",
            str(plan["abstract"]),
            "",
            "## 1. 先验研究计划（不可变）",
            "",
            "### 待研究问题",
            "",
            str(plan["problem_statement"]),
            "",
            "### 解决思路",
            "",
            str(plan["rationale"]),
            "",
            "### 必要的技术手段",
            "",
            str(plan["technical_details"]),
            "",
            "### 数据集",
            "",
            f"- 来源数据：{plan['datasets']['source']}",
            f"- 目标数据：{plan['datasets']['target']}",
            "",
            "### 方法论",
            "",
            str(plan["methods"]),
            "",
            "### 实验设计",
            "",
            *_markdown_list(plan["experiments"], ordered=True),
            "",
            "### 对照基线",
            "",
            *_markdown_list(plan["baselines"]),
            "",
            "### 评估指标",
            "",
            *_markdown_list(plan["metrics"]),
            "",
            "### 预期结果与可反驳条件",
            "",
            str(plan["expected_results"]),
            "",
            "## 2. 观测结果",
            "",
            "系统判定："
            f"{_VERDICT_LABELS.get(interpretation.verdict, '未知判定')}"
            f"（机器标识：`{interpretation.verdict}`）",
            "",
            "| 指标 | 观测值 |",
            "| --- | ---: |",
        ]
    )
    for field, label in _METRIC_ORDER:
        out.append(f"| `{label}` | `{_display(getattr(report.metrics, field))}` |")
    out.extend(["", "### 冻结门禁", "", "| 检查 | 结果 |", "| --- | --- |"])
    for name, passed in sorted(report.metrics.gate_checks.items()):
        out.append(f"| `{name}` | {'通过' if passed else '**未通过**'} |")
    out.extend(
        [
            "",
            "## 3. 结论",
            "",
            "### 证据支持什么",
            "",
            interpretation.what_the_evidence_supports,
            "",
            "### 证据不支持什么",
            "",
            interpretation.what_the_evidence_does_not_support,
            "",
            "### 最强的反面解读",
            "",
            interpretation.strongest_counter_reading,
            "",
            "## 4. 局限",
            "",
            *_markdown_list(interpretation.limitations),
            "",
            "## 5. 风险与备选方案",
            "",
            *_markdown_list(plan["risks_and_alternatives"]),
            "",
            "## 6. 参考论文",
            "",
            *_markdown_references(plan["literature_references"]),
            "",
        ]
    )
    return "\n".join(out).rstrip() + "\n"


def render_final_research_report_latex(report: FinalResearchReport) -> str:
    """Render the same report content as Chinese XeLaTeX source."""

    plan = report.preregistered_plan
    assert_all_prose_is_authored(plan)
    references = plan.get("literature_references") or ()
    problems = guard_references(references)
    if problems:
        raise FinalResearchReportError("final report references are invalid: " + "; ".join(problems))
    metrics_rows = [
        rf"\texttt{{{_tex_escape(label)}}} & \texttt{{{_tex_escape(_display(getattr(report.metrics, field)))}}} \\"
        for field, label in _METRIC_ORDER
    ]
    gate_rows = [
        rf"\texttt{{{_tex_escape(name)}}} & {'通过' if passed else '未通过'} \\"
        for name, passed in sorted(report.metrics.gate_checks.items())
    ]
    provenance_rows = [
        ("report_hash", report.report_hash),
        ("preregistered_plan_hash", report.preregistered_plan_hash),
        ("approved_plan_hash", report.approved_plan_hash),
        ("plan_execution_contract_hash", report.plan_execution_contract_hash),
        ("package_hash", report.package_hash),
        ("outcome_hash", report.outcome_hash),
    ]
    provenance = "\n".join(
        rf"\texttt{{{_tex_escape(name)}}} & "
        # Hash fields are schema-validated lowercase hexadecimal.  Do not pass them
        # through the prose escaper: its long-number protection inserts ``\mbox``
        # fragments, which are deliberately incompatible with ``\seqsplit``.
        rf"\texttt{{\footnotesize\seqsplit{{{value}}}}} \\"
        for name, value in provenance_rows
    )
    body = [
        _PREAMBLE,
        r"\fancyhead[C]{\songti\zihao{5} 最终研究报告}",
        r"\begin{document}",
        r"\begin{center}",
        r"{\heiti\zihao{2} " + _tex_escape(report.title) + r"}\\[1.0em]",
        r"{\songti\zihao{4} 最终研究报告}\\[0.5em]",
        r"{\songti\zihao{5} 由系统研究计划与通过审计的系统结果单向派生}",
        r"\end{center}",
        r"\vspace{0.6em}",
        r"\begin{center}\begin{tabularx}{0.96\linewidth}{@{}lX@{}}\toprule",
        provenance,
        r"人工撰写的科学散文字段数 & 0 \\",
        r"人工审批是否构成科学证据 & 否 \\",
        r"\bottomrule\end{tabularx}\end{center}",
        r"\section*{摘要}",
        _tex_escape(plan["abstract"]),
        r"\section{先验研究计划（不可变）}",
        r"\subsection{待研究问题}",
        _tex_escape(plan["problem_statement"]),
        r"\subsection{解决思路}",
        _tex_escape(plan["rationale"]),
        r"\subsection{必要的技术手段}",
        _tex_escape(plan["technical_details"]),
        r"\subsection{数据集}",
        r"\begin{tabularx}{\linewidth}{@{}lX@{}}\toprule",
        r"来源数据 & " + _tex_escape(plan["datasets"]["source"]) + r" \\",
        r"目标数据 & " + _tex_escape(plan["datasets"]["target"]) + r" \\",
        r"\bottomrule\end{tabularx}",
        r"\subsection{方法论}",
        _tex_escape(plan["methods"]),
        r"\subsection{实验设计}",
        _itemize(plan["experiments"], ordered=True),
        r"\subsection{对照基线}",
        _itemize(plan["baselines"]),
        r"\subsection{评估指标}",
        _itemize(plan["metrics"]),
        r"\subsection{预期结果与可反驳条件}",
        _tex_escape(plan["expected_results"]),
        r"\section{观测结果}",
        r"\noindent 系统判定："
        + _tex_escape(_VERDICT_LABELS.get(report.interpretation.verdict, "未知判定"))
        + r"（机器标识：\texttt{"
        + _tex_escape(report.interpretation.verdict)
        + "}）",
        r"\begin{center}\begin{tabularx}{0.96\linewidth}{@{}lX@{}}\toprule",
        r"指标 & 观测值 \\\midrule",
        "\n".join(metrics_rows),
        r"\bottomrule\end{tabularx}\end{center}",
        r"\subsection{冻结门禁}",
        r"\begin{center}\begin{tabularx}{0.96\linewidth}{@{}Xl@{}}\toprule",
        r"检查 & 结果 \\\midrule",
        "\n".join(gate_rows),
        r"\bottomrule\end{tabularx}\end{center}",
        r"\section{结论}",
        r"\subsection{证据支持什么}",
        _tex_escape(report.interpretation.what_the_evidence_supports),
        r"\subsection{证据不支持什么}",
        _tex_escape(report.interpretation.what_the_evidence_does_not_support),
        r"\subsection{最强的反面解读}",
        _tex_escape(report.interpretation.strongest_counter_reading),
        r"\section{局限}",
        _itemize(report.interpretation.limitations),
        r"\section{风险与备选方案}",
        _itemize(plan["risks_and_alternatives"]),
        r"\section{参考论文}",
        r"\begin{enumerate}[label={[\arabic*]}]",
        "\n".join(rf"\item {_render_reference(item)}" for item in references),
        r"\end{enumerate}",
        r"\end{document}",
        "",
    ]
    return "\n".join(body)


def validate_final_report_renderings(
    *,
    report: FinalResearchReport,
    json_text: str,
    markdown_text: str,
    latex_text: str,
    pdf_text: str | None,
) -> dict[str, bool]:
    """Check the exact verdict and key metrics in every derived representation."""

    tokens = _consistency_tokens(report)
    try:
        reloaded = FinalResearchReport.model_validate_json(json_text)
        json_valid = reloaded == report
    except ValueError:
        json_valid = False
    return {
        "json_key_metrics": json_valid and _contains_tokens(json_text, tokens),
        "markdown_key_metrics": _contains_tokens(markdown_text, tokens),
        "latex_key_metrics": _contains_tokens(
            latex_text, tuple(_tex_escape(token) for token in tokens)
        ),
        "pdf_key_metrics": pdf_text is not None and _contains_tokens(pdf_text, tokens),
    }


def _observed_metrics(package: OfficialDevelopmentSearchPackage) -> FinalObservedMetrics:
    required = {
        "overall_median_log_effect": package.overall_median_log_effect,
        "bootstrap_lower": package.bootstrap_lower,
        "bootstrap_upper": package.bootstrap_upper,
        "ode_stratum_median": package.ode_stratum_median,
        "pde_stratum_median": package.pde_stratum_median,
    }
    absent = [name for name, value in required.items() if value is None]
    if absent or package.selected_candidate_id is None:
        raise FinalResearchReportError(
            f"signed package lacks final observed metrics: {absent}"
        )
    overall = package.overall_median_log_effect
    lower = package.bootstrap_lower
    upper = package.bootstrap_upper
    ode = package.ode_stratum_median
    pde = package.pde_stratum_median
    assert overall is not None
    assert lower is not None
    assert upper is not None
    assert ode is not None
    assert pde is not None
    paired = [item for item in package.system_effects if item.is_paired]
    statuses = [item.status for item in package.cell_results]
    return FinalObservedMetrics(
        selected_candidate_id=package.selected_candidate_id,
        overall_median_log_effect=float(overall),
        bootstrap_lower=float(lower),
        bootstrap_upper=float(upper),
        ode_stratum_median=float(ode),
        pde_stratum_median=float(pde),
        minimum_overall_log_effect=package.minimum_overall_log_effect,
        paired_system_count=len(paired),
        baseline_coverage_gap_count=len(package.system_effects) - len(paired),
        candidate_win_count=sum(item.paired_log_effect > 0 for item in paired),
        executed_cell_count=len(statuses),
        succeeded_cell_count=statuses.count("succeeded"),
        failed_cell_count=statuses.count("failed"),
        timed_out_cell_count=statuses.count("timed_out"),
        gate_checks=package.gate_checks,
        frozen_gate_passed=all(package.gate_checks.values()),
        search_freeze_receipt_issued=package.search_freeze_receipt_issued,
    )


def _candidate_source_path(
    *, root: Path, candidate: OfficialCandidateRecord
) -> Path:
    path = (root / Path(candidate.source_relative_path)).resolve()
    if not path.is_relative_to(root):
        raise FinalResearchReportError(
            "selected candidate source resolves outside the lineage directory"
        )
    return path


def _compile_and_read_pdf(
    latex_path: Path,
) -> tuple[Path, str, str, tuple[str, ...], str]:
    compiler = shutil.which("xelatex")
    extractor = shutil.which("pdftotext")
    if compiler is None or extractor is None:
        raise FinalResearchReportError(
            "XeLaTeX and pdftotext are required to build and verify the final PDF"
        )
    command = (
        compiler,
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-file-line-error",
        latex_path.name,
    )
    for _ in range(2):
        completed = subprocess.run(
            command,
            cwd=latex_path.parent,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stdout + "\n" + completed.stderr)[-6_000:]
            raise FinalResearchReportError(f"XeLaTeX compilation failed:\n{detail}")
    pdf_path = latex_path.with_name(_PDF_NAME)
    if not pdf_path.is_file() or pdf_path.stat().st_size == 0:
        raise FinalResearchReportError("XeLaTeX returned success without a PDF")
    extracted = subprocess.run(
        (extractor, "-layout", str(pdf_path), "-"),
        cwd=latex_path.parent,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if extracted.returncode != 0 or not extracted.stdout.strip():
        raise FinalResearchReportError(
            "compiled PDF is not text-extractable, so its content cannot be audited"
        )
    version_result = subprocess.run(
        (compiler, "--version"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    version = version_result.stdout.splitlines()[0] if version_result.stdout else "unknown"
    return pdf_path, compiler, version, command, extracted.stdout


def _consistency_tokens(report: FinalResearchReport) -> tuple[str, ...]:
    metrics = report.metrics
    values = [
        metrics.selected_candidate_id,
        report.interpretation.verdict,
        _display(metrics.overall_median_log_effect),
        _display(metrics.bootstrap_lower),
        _display(metrics.bootstrap_upper),
        _display(metrics.ode_stratum_median),
        _display(metrics.pde_stratum_median),
        _display(metrics.minimum_overall_log_effect),
    ]
    return tuple(values)


def _contains_tokens(text: str, tokens: Sequence[str]) -> bool:
    compact = "".join(text.split())
    return all(token in text or "".join(token.split()) in compact for token in tokens)


def _display(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if value is None:
        return "null"
    return str(value)


def _markdown_list(items: Sequence[Any], *, ordered: bool = False) -> list[str]:
    if ordered:
        return [f"{index}. {item}" for index, item in enumerate(items, 1)]
    return [f"- {item}" for item in items]


def _markdown_references(references: Sequence[Mapping[str, Any]]) -> list[str]:
    rendered: list[str] = []
    for index, reference in enumerate(references, 1):
        authors = reference.get("authors") or ()
        author_text = "，".join(str(item) for item in authors)
        title = str(reference.get("title") or "")
        venue = str(reference.get("venue") or "")
        date = str(reference.get("publication_date") or "")
        doi = str(reference.get("doi") or "").removeprefix("https://doi.org/")
        url = str(reference.get("url") or "")
        locator = f"https://doi.org/{doi}" if doi else url
        citation = ". ".join(item for item in (author_text, title, venue, date) if item)
        rendered.append(f"{index}. {citation}. [{locator}]({locator})")
    return rendered


def _write_text_atomic(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
