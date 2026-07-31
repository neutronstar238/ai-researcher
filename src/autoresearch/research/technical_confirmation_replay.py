"""Consumed-panel technical repair replay for Task 263.6.2.

The first Task 263.6 confirmation is immutable and invalid.  This module
creates a result-before-outcome stop/advance freeze, copies the already
consumed inputs into two path-confined workspaces, runs the exact frozen claim
with the certified v2 evaluator, independently reconstructs the technical
analysis, and applies a non-publication decision rule.  No output from this
module can satisfy an independent-confirmation or publication gate.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections import Counter
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from autoresearch.kernel.contracts import (
    KernelContract,
    NonEmptyText,
    Sha256,
    StableId,
    canonical_sha256,
)

from . import confirmatory_evaluation as confirmation
from .confirmatory_evaluation import (
    CONFIRMATION_FREEZE_FILENAME,
    EXECUTION_INDEX_FILENAME,
    ConfirmationStatus,
    ConfirmatoryExecutionIndex,
    ConfirmatoryNullControlSummary,
    ConfirmatoryPolicyComparison,
    ConfirmatoryPolicySummary,
    ConfirmatoryTaskInput,
    ConfirmatoryTaskPolicyOutcome,
    load_confirmatory_evaluation_report,
    load_confirmatory_execution_index,
)
from .evaluator_compatibility import (
    EvaluatorCompatibilityStatus,
    load_evaluator_compatibility_certificate,
)
from .portfolio import PortfolioIntegrityError

REPAIR_FREEZE_FILENAME = "consumed-panel-repair-freeze.json"
TECHNICAL_REPORT_FILENAME = "consumed-panel-technical-report.json"
TECHNICAL_MARKDOWN_FILENAME = "consumed-panel-technical-report.md"
TECHNICAL_MANIFEST_FILENAME = "consumed-panel-technical-manifest.json"
TECHNICAL_SCHEMA_FILENAME = "consumed-panel-technical-schemas.json"
CONTROLLER_RESULT_RELATIVE = Path("technical-execution/controller-result.json")
PRIMARY_WORKSPACE = "primary-workspace"
REPLAY_WORKSPACE = "replay-workspace"

V2_POLICY_CONTROLLER_SOURCE_PATH = Path(
    "src/autoresearch/research/assets/frozen_confirmation_policy_controller_v2.py"
)
V1_POLICY_CONTROLLER_SOURCE_PATH = Path(
    "src/autoresearch/research/assets/frozen_confirmation_policy_controller_v1.py"
)
V2_CONFIRMATION_RUNNER_SOURCE_PATH = Path(
    "src/autoresearch/research/assets/frozen_tabular_confirmation_runner_v2.py"
)
V2_CANDIDATE_RUNNER_SOURCE_PATH = Path(
    "src/autoresearch/research/assets/frozen_tabular_candidate_runner_v2.py"
)
V1_CANDIDATE_RUNNER_SOURCE_PATH = Path(
    "src/autoresearch/research/assets/frozen_tabular_candidate_runner_v1.py"
)

EXPECTED_ALLOWED_REPAIRS = [
    "classification-target-token-canonicalization",
    "f1-f2-physical-label-isolation",
    "structured-input-candidate-evaluator-failure-domains",
]
EXPECTED_STOP_RULE_CHECKS = {
    "both-benchmark-family-risk-differences-nonnegative",
    "complete-primary-and-replay-matrices",
    "corrected-risk-difference-at-least-0.10",
    "directionally-more-favorable-than-unfavorable-tasks",
    "f1-f2-physical-label-isolation-complete",
    "no-input-evaluator-or-infrastructure-failures",
    "no-unexpected-candidate-failures",
    "null-control-zero-integrity-failures",
    "repair-scope-and-route-unchanged",
    "two-interpreter-scientific-projection-exact",
}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _with_canonical_hash(
    model: type[KernelContract],
    payload: Mapping[str, Any],
    field: str,
) -> dict[str, Any]:
    normalized = model.model_construct(**dict(payload)).model_dump(
        mode="json",
        exclude={field},
    )
    normalized[field] = canonical_sha256(normalized)
    return normalized


def _verify_json_hash(payload: Mapping[str, Any], field: str) -> None:
    expected = payload.get(field)
    if not isinstance(expected, str):
        raise PortfolioIntegrityError(f"{field} is missing")
    body = dict(payload)
    body.pop(field, None)
    if canonical_sha256(body) != expected:
        raise PortfolioIntegrityError(f"{field} mismatch")


def _load_hashed_json(path: Path, field: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise PortfolioIntegrityError(f"{path} is not a JSON object")
    _verify_json_hash(payload, field)
    return payload


def _workspace_name(role: Literal["primary", "replay"]) -> str:
    return PRIMARY_WORKSPACE if role == "primary" else REPLAY_WORKSPACE


def _source_asset_path(relative: Path) -> Path:
    return (Path(__file__).resolve().parents[3] / relative).resolve()


class TechnicalRepairDecision(str, Enum):
    """Result of the pre-frozen technical stop/advance conjunction."""

    STOP_PORTFOLIO_MEMORY_CLAIM = "stop_portfolio_memory_claim"
    ELIGIBLE_FOR_NEW_MECHANISM_REVIEW = "eligible_for_new_mechanism_review"


class V1MeasurementFailureSignature(KernelContract):
    """Content-addressed signature of the immutable v1 evaluator failure."""

    schema_version: Literal["v1-measurement-failure-signature-v1"] = (
        "v1-measurement-failure-signature-v1"
    )
    source_report_status: Literal["invalid_confirmation"] = "invalid_confirmation"
    null_integrity_failure_count: Literal[69] = 69
    affected_classification_task_count: Literal[23] = 23
    affected_seed_count: Literal[3] = 3
    source_failure_code: Literal["runner_nonzero_exit"] = "runner_nonzero_exit"
    root_cause_signature: Literal["Mix of label input types (string and number)"] = (
        "Mix of label input types (string and number)"
    )
    failure_rows_hash: Sha256
    signature_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> V1MeasurementFailureSignature:
        if self.signature_hash != self.calculated_hash():
            raise PortfolioIntegrityError("v1 failure signature_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> V1MeasurementFailureSignature:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "v1-measurement-failure-signature-v1",
                "source_report_status": "invalid_confirmation",
                "null_integrity_failure_count": 69,
                "affected_classification_task_count": 23,
                "affected_seed_count": 3,
                "source_failure_code": "runner_nonzero_exit",
                "root_cause_signature": "Mix of label input types (string and number)",
            }
        )
        return cls.model_validate(
            _with_canonical_hash(cls, payload, "signature_hash")
        )

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"signature_hash"})
        )


class ConsumedPanelRepairFreeze(KernelContract):
    """Outcome-free lineage, repair scope, and stop rule for Task 263.6.2."""

    schema_version: Literal["consumed-panel-repair-freeze-v1"] = (
        "consumed-panel-repair-freeze-v1"
    )
    repair_id: Literal["task-263.6.2-consumed-panel-repair-v1"] = (
        "task-263.6.2-consumed-panel-repair-v1"
    )
    source_confirmation_freeze_hash: Sha256
    source_reveal_hash: Sha256
    source_report_hash: Sha256
    source_manifest_hash: Sha256
    source_controller_result_hash: Sha256
    source_scientific_projection_hash: Sha256
    source_failure_signature: V1MeasurementFailureSignature
    evaluator_certificate_report_hash: Sha256
    evaluator_certificate_manifest_hash: Sha256
    evaluator_certificate_status: Literal["certified"] = "certified"
    v1_policy_controller_sha256: Sha256
    v2_policy_controller_sha256: Sha256
    v1_candidate_runner_sha256: Sha256
    v2_candidate_runner_sha256: Sha256
    v2_confirmation_runner_sha256: Sha256
    v2_confirmation_runner_relative_path: Literal[
        "execution-assets/frozen_tabular_confirmation_runner_v2.py"
    ] = "execution-assets/frozen_tabular_confirmation_runner_v2.py"
    orchestrator_source_sha256: Sha256
    technical_execution_index_hashes: dict[
        Literal["primary", "replay"],
        Sha256,
    ]
    frozen_candidate_catalog_hash: Sha256
    frozen_policy_catalog_hash: Sha256
    frozen_assignment_catalog_hash: Sha256
    frozen_claim_hash: Sha256
    allowed_repair_fields: list[StableId] = Field(min_length=3, max_length=3)
    minimum_observed_risk_difference_to_review: float = Field(
        default=0.10,
        ge=0.10,
        le=0.10,
    )
    minimum_confirmatory_claim_risk_difference_unchanged: float = Field(
        default=0.25,
        ge=0.25,
        le=0.25,
    )
    stop_rule_check_ids: list[StableId] = Field(min_length=10, max_length=10)
    numerical_advance_authorizes_new_confirmation: Literal[False] = False
    new_mechanism_rationale_required: Literal[True] = True
    new_development_evidence_required: Literal[True] = True
    new_research_question_certificate_required: Literal[True] = True
    disjoint_zero_result_panel_required: Literal[True] = True
    result_record_count_at_freeze: Literal[0] = 0
    source_panel_consumed: Literal[True] = True
    technical_only: Literal[True] = True
    exploratory_only: Literal[True] = True
    independent_confirmation_eligible: Literal[False] = False
    publication_evidence_eligible: Literal[False] = False
    post_reveal_retuning_allowed: Literal[False] = False
    result_contingent_route_change_allowed: Literal[False] = False
    public_release_authorized: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    frozen_at: datetime
    repair_freeze_hash: Sha256

    @field_validator("frozen_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("repair freeze time must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _validate_freeze(self) -> ConsumedPanelRepairFreeze:
        if self.allowed_repair_fields != EXPECTED_ALLOWED_REPAIRS:
            raise ValueError("repair whitelist changed")
        if set(self.stop_rule_check_ids) != EXPECTED_STOP_RULE_CHECKS:
            raise ValueError("stop-rule check inventory changed")
        if set(self.technical_execution_index_hashes) != {"primary", "replay"}:
            raise ValueError("technical execution-index roles changed")
        if self.repair_freeze_hash != self.calculated_hash():
            raise PortfolioIntegrityError("repair_freeze_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ConsumedPanelRepairFreeze:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "consumed-panel-repair-freeze-v1",
                "repair_id": "task-263.6.2-consumed-panel-repair-v1",
                "evaluator_certificate_status": "certified",
                "v2_confirmation_runner_relative_path": (
                    "execution-assets/frozen_tabular_confirmation_runner_v2.py"
                ),
                "minimum_observed_risk_difference_to_review": 0.10,
                "minimum_confirmatory_claim_risk_difference_unchanged": 0.25,
                "numerical_advance_authorizes_new_confirmation": False,
                "new_mechanism_rationale_required": True,
                "new_development_evidence_required": True,
                "new_research_question_certificate_required": True,
                "disjoint_zero_result_panel_required": True,
                "result_record_count_at_freeze": 0,
                "source_panel_consumed": True,
                "technical_only": True,
                "exploratory_only": True,
                "independent_confirmation_eligible": False,
                "publication_evidence_eligible": False,
                "post_reveal_retuning_allowed": False,
                "result_contingent_route_change_allowed": False,
                "public_release_authorized": False,
                "external_submission_authorized": False,
            }
        )
        payload["allowed_repair_fields"] = list(EXPECTED_ALLOWED_REPAIRS)
        payload["stop_rule_check_ids"] = sorted(EXPECTED_STOP_RULE_CHECKS)
        payload["technical_execution_index_hashes"] = dict(
            sorted(payload["technical_execution_index_hashes"].items())
        )
        return cls.model_validate(
            _with_canonical_hash(cls, payload, "repair_freeze_hash")
        )

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"repair_freeze_hash"})
        )


class TechnicalFailureCostComparison(KernelContract):
    """Explicit v1-to-v2 measurement-failure and resource comparison."""

    v1_unique_evaluation_count: int = Field(ge=1)
    v2_unique_evaluation_count: int = Field(ge=1)
    v1_evaluation_failure_count: int = Field(ge=0)
    v2_evaluation_failure_count: int = Field(ge=0)
    v1_failure_code_counts: dict[StableId, int]
    v2_failure_domain_counts: dict[StableId, int]
    v2_failure_code_counts: dict[StableId, int]
    v1_null_integrity_failure_count: Literal[69] = 69
    v2_null_integrity_failure_count: int = Field(ge=0)
    v1_newly_executed_cpu_seconds: float = Field(ge=0)
    v2_newly_executed_cpu_seconds: float = Field(ge=0)
    v1_newly_executed_wall_seconds: float = Field(ge=0)
    v2_newly_executed_wall_seconds: float = Field(ge=0)
    comparison_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> TechnicalFailureCostComparison:
        for values in (
            self.v1_failure_code_counts,
            self.v2_failure_domain_counts,
            self.v2_failure_code_counts,
        ):
            if list(values) != sorted(values):
                raise ValueError("failure comparison mappings must be sorted")
        if self.comparison_hash != self.calculated_hash():
            raise PortfolioIntegrityError("failure/cost comparison_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> TechnicalFailureCostComparison:
        payload = dict(values)
        payload["v1_null_integrity_failure_count"] = 69
        for field in (
            "v1_failure_code_counts",
            "v2_failure_domain_counts",
            "v2_failure_code_counts",
        ):
            payload[field] = dict(sorted(payload[field].items()))
        return cls.model_validate(
            _with_canonical_hash(cls, payload, "comparison_hash")
        )

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"comparison_hash"})
        )


class TechnicalRepairAnalysis(KernelContract):
    """Deterministic consumed-panel projection and stop/advance decision."""

    schema_version: Literal["consumed-panel-technical-analysis-v1"] = (
        "consumed-panel-technical-analysis-v1"
    )
    task_outcomes: list[ConfirmatoryTaskPolicyOutcome] = Field(
        min_length=540,
        max_length=540,
    )
    policy_summaries: list[ConfirmatoryPolicySummary] = Field(
        min_length=9,
        max_length=9,
    )
    primary_comparison: ConfirmatoryPolicyComparison
    null_control: ConfirmatoryNullControlSummary
    benchmark_family_risk_differences: dict[StableId, float]
    v1_primary_risk_difference: float = Field(ge=-1, le=1)
    corrected_minus_v1_risk_difference: float = Field(ge=-2, le=2)
    failure_cost_comparison: TechnicalFailureCostComparison
    stop_rule_checks: dict[StableId, bool]
    decision: TechnicalRepairDecision
    source_panel_consumed: Literal[True] = True
    technical_only: Literal[True] = True
    exploratory_only: Literal[True] = True
    inferential_confirmation_claim_allowed: Literal[False] = False
    publication_evidence_eligible: Literal[False] = False
    analysis_hash: Sha256

    @model_validator(mode="after")
    def _validate_analysis(self) -> TechnicalRepairAnalysis:
        if set(self.stop_rule_checks) != EXPECTED_STOP_RULE_CHECKS:
            raise ValueError("technical stop-rule checks changed")
        expected = (
            TechnicalRepairDecision.ELIGIBLE_FOR_NEW_MECHANISM_REVIEW
            if all(self.stop_rule_checks.values())
            else TechnicalRepairDecision.STOP_PORTFOLIO_MEMORY_CLAIM
        )
        if self.decision is not expected:
            raise ValueError("technical decision differs from frozen conjunction")
        if self.analysis_hash != self.calculated_hash():
            raise PortfolioIntegrityError("technical analysis_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> TechnicalRepairAnalysis:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "consumed-panel-technical-analysis-v1",
                "source_panel_consumed": True,
                "technical_only": True,
                "exploratory_only": True,
                "inferential_confirmation_claim_allowed": False,
                "publication_evidence_eligible": False,
            }
        )
        payload["task_outcomes"] = sorted(
            payload["task_outcomes"],
            key=lambda item: (item.policy_id, item.unit_id),
        )
        payload["policy_summaries"] = sorted(
            payload["policy_summaries"],
            key=lambda item: item.policy_id,
        )
        payload["benchmark_family_risk_differences"] = dict(
            sorted(payload["benchmark_family_risk_differences"].items())
        )
        payload["stop_rule_checks"] = dict(
            sorted(payload["stop_rule_checks"].items())
        )
        return cls.model_validate(
            _with_canonical_hash(cls, payload, "analysis_hash")
        )

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"analysis_hash"})
        )


class ConsumedPanelTechnicalReport(KernelContract):
    """Top-level technical report that cannot become confirmation evidence."""

    schema_version: Literal["consumed-panel-technical-report-v1"] = (
        "consumed-panel-technical-report-v1"
    )
    report_id: Literal["task-263.6.2-consumed-panel-technical-replay"] = (
        "task-263.6.2-consumed-panel-technical-replay"
    )
    repair_freeze_hash: Sha256
    source_confirmation_freeze_hash: Sha256
    source_report_hash: Sha256
    source_manifest_hash: Sha256
    source_status: Literal["invalid_confirmation"] = "invalid_confirmation"
    evaluator_certificate_report_hash: Sha256
    primary_execution_index_hash: Sha256
    replay_execution_index_hash: Sha256
    primary_controller_result_hash: Sha256
    replay_controller_result_hash: Sha256
    primary_scientific_projection_hash: Sha256
    replay_scientific_projection_hash: Sha256
    scientific_projection_exact: Literal[True] = True
    assignment_count_per_interpreter: Literal[1620] = 1620
    null_control_count_per_interpreter: Literal[180] = 180
    analysis: TechnicalRepairAnalysis
    decision: TechnicalRepairDecision
    route_after_decision: Literal[
        "close-portfolio-memory-or-new-mechanism-review-only"
    ] = "close-portfolio-memory-or-new-mechanism-review-only"
    new_confirmation_authorized: Literal[False] = False
    source_panel_consumed: Literal[True] = True
    technical_only: Literal[True] = True
    exploratory_only: Literal[True] = True
    independent_confirmation_eligible: Literal[False] = False
    publication_evidence_eligible: Literal[False] = False
    post_reveal_retuning_authorized: Literal[False] = False
    result_contingent_route_change_authorized: Literal[False] = False
    public_release_authorized: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    completed_at: datetime
    report_hash: Sha256

    @field_validator("completed_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("technical report time must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _validate_report(self) -> ConsumedPanelTechnicalReport:
        if (
            self.primary_scientific_projection_hash
            != self.replay_scientific_projection_hash
        ):
            raise ValueError("technical two-interpreter projection differs")
        if self.decision is not self.analysis.decision:
            raise ValueError("technical report/analysis decision differs")
        if self.report_hash != self.calculated_hash():
            raise PortfolioIntegrityError("technical report_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ConsumedPanelTechnicalReport:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "consumed-panel-technical-report-v1",
                "report_id": "task-263.6.2-consumed-panel-technical-replay",
                "source_status": "invalid_confirmation",
                "scientific_projection_exact": True,
                "assignment_count_per_interpreter": 1620,
                "null_control_count_per_interpreter": 180,
                "route_after_decision": (
                    "close-portfolio-memory-or-new-mechanism-review-only"
                ),
                "new_confirmation_authorized": False,
                "source_panel_consumed": True,
                "technical_only": True,
                "exploratory_only": True,
                "independent_confirmation_eligible": False,
                "publication_evidence_eligible": False,
                "post_reveal_retuning_authorized": False,
                "result_contingent_route_change_authorized": False,
                "public_release_authorized": False,
                "external_submission_authorized": False,
            }
        )
        return cls.model_validate(
            _with_canonical_hash(cls, payload, "report_hash")
        )

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"report_hash"})
        )


class TechnicalReplayArtifactManifest(KernelContract):
    """Recursive internal artifact inventory for the technical replay."""

    schema_version: Literal["consumed-panel-technical-manifest-v1"] = (
        "consumed-panel-technical-manifest-v1"
    )
    repair_freeze_hash: Sha256
    report_hash: Sha256
    artifact_hashes: dict[NonEmptyText, Sha256]
    consumed_confirmation_payloads_included: Literal[True] = True
    independent_confirmation_eligible: Literal[False] = False
    publication_evidence_eligible: Literal[False] = False
    public_release_authorized: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    manifest_hash: Sha256

    @model_validator(mode="after")
    def _validate_manifest(self) -> TechnicalReplayArtifactManifest:
        if list(self.artifact_hashes) != sorted(self.artifact_hashes):
            raise ValueError("technical artifact hashes must be sorted")
        if self.manifest_hash != self.calculated_hash():
            raise PortfolioIntegrityError("technical manifest_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> TechnicalReplayArtifactManifest:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "consumed-panel-technical-manifest-v1",
                "consumed_confirmation_payloads_included": True,
                "independent_confirmation_eligible": False,
                "publication_evidence_eligible": False,
                "public_release_authorized": False,
                "external_submission_authorized": False,
            }
        )
        payload["artifact_hashes"] = dict(
            sorted(payload["artifact_hashes"].items())
        )
        return cls.model_validate(
            _with_canonical_hash(cls, payload, "manifest_hash")
        )

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"manifest_hash"})
        )


TECHNICAL_REPLAY_CONTRACT_MODELS = (
    V1MeasurementFailureSignature,
    ConsumedPanelRepairFreeze,
    TechnicalFailureCostComparison,
    TechnicalRepairAnalysis,
    ConsumedPanelTechnicalReport,
    TechnicalReplayArtifactManifest,
)


def technical_replay_json_schemas() -> dict[str, dict[str, Any]]:
    """Return deterministic JSON Schemas for Task 263.6.2 contracts."""

    return {
        model.__name__: model.model_json_schema()
        for model in TECHNICAL_REPLAY_CONTRACT_MODELS
    }


def _v1_failure_signature(
    source_dir: Path,
    report: confirmation.ConfirmatoryEvaluationReport,
) -> V1MeasurementFailureSignature:
    if report.status is not ConfirmationStatus.INVALID_CONFIRMATION:
        raise ValueError("technical repair requires the retained invalid v1 endpoint")
    index = load_confirmatory_execution_index(source_dir)
    family_by_unit = {task.unit_id: task.family for task in index.tasks}
    evaluation_by_hash: dict[str, dict[str, Any]] = {}
    for path in sorted(
        (source_dir / "primary-execution/evaluation-cache").glob(
            "*/evaluation.json"
        )
    ):
        item = _load_hashed_json(path, "evaluation_hash")
        evaluation_by_hash[str(item["evaluation_hash"])] = item
    rows: list[dict[str, Any]] = []
    for unit_id in sorted(family_by_unit):
        for seed in (1729, 3253, 7919):
            null_path = (
                source_dir
                / "primary-execution/null-controls"
                / f"null-{unit_id}-{seed}"
                / "result.json"
            )
            null = _load_hashed_json(null_path, "result_hash")
            if (
                null["artifact_valid"]
                and null["prediction_replay_valid"]
                and null["evaluator_integrity_valid"]
            ):
                continue
            evaluation = evaluation_by_hash[str(null["evaluation_hash"])]
            eval_dir = (
                source_dir
                / "primary-execution/evaluation-cache"
                / str(evaluation["evaluation_id"])
            )
            stderr = (eval_dir / "runner.stderr.log").read_text(
                encoding="utf-8",
                errors="replace",
            )
            rows.append(
                {
                    "unit_id": unit_id,
                    "family": family_by_unit[unit_id],
                    "within_unit_seed": seed,
                    "failure_code": null["failure_code"],
                    "evaluation_hash": evaluation["evaluation_hash"],
                    "stderr_sha256": evaluation["stderr_sha256"],
                    "root_cause_signature_present": (
                        "Mix of label input types (string and number)" in stderr
                    ),
                }
            )
    affected = {row["unit_id"] for row in rows}
    if (
        len(rows) != 69
        or len(affected) != 23
        or {row["family"] for row in rows} != {"tabular_classification"}
        or {row["failure_code"] for row in rows} != {"runner_nonzero_exit"}
        or not all(row["root_cause_signature_present"] for row in rows)
    ):
        raise PortfolioIntegrityError("v1 failure pattern no longer matches diagnosis")
    return V1MeasurementFailureSignature.create(
        failure_rows_hash=canonical_sha256(rows),
    )


def _copy_task_index(
    source_index: ConfirmatoryExecutionIndex,
    source_freeze_path: Path,
    workspace: Path,
    *,
    role: Literal["primary", "replay"],
) -> ConfirmatoryExecutionIndex:
    workspace.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        source_freeze_path,
        workspace / CONFIRMATION_FREEZE_FILENAME,
    )
    tasks: list[ConfirmatoryTaskInput] = []
    for source in source_index.tasks:
        bundle_dir = workspace / "task-bundles" / source.opaque_unit_id
        bundle_dir.mkdir(parents=True, exist_ok=True)
        copied: dict[str, Path] = {}
        for field, name in (
            ("train_path", "train.csv"),
            ("test_path", "test.csv"),
            ("labels_path", "labels.json"),
        ):
            target = bundle_dir / name
            if target.exists():
                if _file_sha256(target) != getattr(source, field.replace("path", "sha256")):
                    raise PortfolioIntegrityError(
                        f"technical input copy changed: {source.unit_id} {field}"
                    )
            else:
                shutil.copy2(Path(getattr(source, field)), target)
            copied[field] = target
        tasks.append(
            ConfirmatoryTaskInput.create(
                unit_id=source.unit_id,
                opaque_unit_id=source.opaque_unit_id,
                family=source.family,
                benchmark_id=source.benchmark_id,
                domain=source.domain,
                independence_group=source.independence_group,
                train_path=copied["train_path"].resolve().as_posix(),
                test_path=copied["test_path"].resolve().as_posix(),
                labels_path=copied["labels_path"].resolve().as_posix(),
                train_sha256=source.train_sha256,
                test_sha256=source.test_sha256,
                labels_sha256=source.labels_sha256,
                data_sha256=source.data_sha256,
                split_sha256=source.split_sha256,
                source_data_md5=source.source_data_md5,
                train_row_count=source.train_row_count,
                test_row_count=source.test_row_count,
                feature_count=source.feature_count,
                metric_id=source.metric_id,
                baseline_score=source.baseline_score,
                minimum_gain=source.minimum_gain,
                threshold_hash=source.threshold_hash,
                baseline_replay=source.baseline_replay,
                reveal_hash=source.reveal_hash,
                confirmation_freeze_hash=source.confirmation_freeze_hash,
            )
        )
    index = ConfirmatoryExecutionIndex.create(
        freeze_hash=source_index.freeze_hash,
        reveal_hash=source_index.reveal_hash,
        interpreter_role=role,
        tasks=tasks,
        source_urls=source_index.source_urls,
    )
    index_path = workspace / EXECUTION_INDEX_FILENAME
    serialized = index.canonical_json() + "\n"
    if index_path.exists():
        observed = ConfirmatoryExecutionIndex.model_validate_json(
            index_path.read_text(encoding="utf-8")
        )
        if observed.execution_index_hash != index.execution_index_hash:
            raise PortfolioIntegrityError("technical execution index changed")
    else:
        _write_text_atomic(index_path, serialized)
    return index


def _copy_execution_assets(
    workspace: Path,
    source_confirmation_dir: Path,
) -> dict[str, str]:
    asset_dir = workspace / "execution-assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    for source in sorted(
        (source_confirmation_dir / "execution-assets").iterdir()
    ):
        if not source.is_file():
            continue
        target = asset_dir / source.name
        if target.exists():
            if _file_sha256(target) != _file_sha256(source):
                raise PortfolioIntegrityError(
                    f"frozen v1 execution asset changed: {source.name}"
                )
        else:
            shutil.copy2(source, target)
        hashes[source.name] = _file_sha256(target)
    for relative in (
        V2_POLICY_CONTROLLER_SOURCE_PATH,
        V2_CONFIRMATION_RUNNER_SOURCE_PATH,
    ):
        source = _source_asset_path(relative)
        target = asset_dir / relative.name
        if target.exists():
            if _file_sha256(target) != _file_sha256(source):
                raise PortfolioIntegrityError(
                    f"technical execution asset changed: {relative.name}"
                )
        else:
            shutil.copy2(source, target)
        hashes[relative.name] = _file_sha256(target)
    return dict(sorted(hashes.items()))


def _result_record_count(output_dir: Path) -> int:
    return sum(
        path.name in {"evaluation.json", "result.json", "controller-result.json"}
        for workspace_name in (PRIMARY_WORKSPACE, REPLAY_WORKSPACE)
        for path in (output_dir / workspace_name / "technical-execution").rglob(
            "*.json"
        )
    )


def freeze_consumed_panel_repair(
    source_confirmation_dir: Path,
    evaluator_certificate_dir: Path,
    output_dir: Path,
    *,
    frozen_at: datetime | None = None,
) -> ConsumedPanelRepairFreeze:
    """Freeze the technical-only lineage and stop rule before any v2 result."""

    source_confirmation_dir = source_confirmation_dir.resolve()
    evaluator_certificate_dir = evaluator_certificate_dir.resolve()
    output_dir = output_dir.resolve()
    freeze_path = output_dir / REPAIR_FREEZE_FILENAME
    if freeze_path.exists():
        repair = ConsumedPanelRepairFreeze.model_validate_json(
            freeze_path.read_text(encoding="utf-8")
        )
        if (
            _file_sha256(Path(__file__).resolve())
            != repair.orchestrator_source_sha256
            or _file_sha256(_source_asset_path(V2_POLICY_CONTROLLER_SOURCE_PATH))
            != repair.v2_policy_controller_sha256
        ):
            raise PortfolioIntegrityError("technical repair source changed after freeze")
        roles: tuple[Literal["primary", "replay"], ...] = (
            "primary",
            "replay",
        )
        for role in roles:
            target = output_dir / _workspace_name(role) / REPAIR_FREEZE_FILENAME
            if target.exists():
                if _file_sha256(target) != _file_sha256(freeze_path):
                    raise PortfolioIntegrityError(
                        f"{role} repair-freeze copy changed"
                    )
            else:
                shutil.copy2(freeze_path, target)
        return repair
    output_dir.mkdir(parents=True, exist_ok=True)
    if _result_record_count(output_dir) != 0:
        raise PortfolioIntegrityError(
            "technical results exist before the repair freeze"
        )
    source_report, source_freeze, source_manifest = (
        load_confirmatory_evaluation_report(source_confirmation_dir)
    )
    certificate, certificate_manifest = (
        load_evaluator_compatibility_certificate(
            evaluator_certificate_dir,
            source_confirmation_dir=source_confirmation_dir,
        )
    )
    if certificate.status is not EvaluatorCompatibilityStatus.CERTIFIED:
        raise ValueError("v2 evaluator compatibility certificate is not certified")
    source_index = load_confirmatory_execution_index(source_confirmation_dir)
    indexes: dict[str, ConfirmatoryExecutionIndex] = {}
    asset_hashes: dict[str, dict[str, str]] = {}
    for role in ("primary", "replay"):
        typed_role: Literal["primary", "replay"] = role
        workspace = output_dir / _workspace_name(typed_role)
        indexes[typed_role] = _copy_task_index(
            source_index,
            source_confirmation_dir / CONFIRMATION_FREEZE_FILENAME,
            workspace,
            role=typed_role,
        )
        asset_hashes[typed_role] = _copy_execution_assets(
            workspace,
            source_confirmation_dir,
        )
    if asset_hashes["primary"] != asset_hashes["replay"]:
        raise PortfolioIntegrityError("technical workspace assets differ")
    assets = asset_hashes["primary"]
    for relative in (
        V2_POLICY_CONTROLLER_SOURCE_PATH,
        V2_CONFIRMATION_RUNNER_SOURCE_PATH,
    ):
        if not confirmation.audit_independent_execution_source(
            _source_asset_path(relative)
        ):
            raise PortfolioIntegrityError(
                f"technical execution source crossed isolation boundary: {relative.name}"
            )
    source_design = json.loads(
        (
            source_confirmation_dir / CONFIRMATION_FREEZE_FILENAME
        ).read_text(encoding="utf-8")
    )
    if not isinstance(source_design, dict):
        raise PortfolioIntegrityError("source confirmation freeze is not an object")
    failure_signature = _v1_failure_signature(
        source_confirmation_dir,
        source_report,
    )
    repair = ConsumedPanelRepairFreeze.create(
        source_confirmation_freeze_hash=source_freeze.freeze_hash,
        source_reveal_hash=source_report.reveal_hash,
        source_report_hash=source_report.report_hash,
        source_manifest_hash=source_manifest.manifest_hash,
        source_controller_result_hash=source_report.controller_result_hash,
        source_scientific_projection_hash=(
            source_report.controller_scientific_projection_hash
        ),
        source_failure_signature=failure_signature,
        evaluator_certificate_report_hash=certificate.report_hash,
        evaluator_certificate_manifest_hash=certificate_manifest.manifest_hash,
        v1_policy_controller_sha256=assets[
            V1_POLICY_CONTROLLER_SOURCE_PATH.name
        ],
        v2_policy_controller_sha256=assets[
            V2_POLICY_CONTROLLER_SOURCE_PATH.name
        ],
        v1_candidate_runner_sha256=assets[
            V1_CANDIDATE_RUNNER_SOURCE_PATH.name
        ],
        v2_candidate_runner_sha256=assets[
            V2_CANDIDATE_RUNNER_SOURCE_PATH.name
        ],
        v2_confirmation_runner_sha256=assets[
            V2_CONFIRMATION_RUNNER_SOURCE_PATH.name
        ],
        orchestrator_source_sha256=_file_sha256(Path(__file__).resolve()),
        technical_execution_index_hashes={
            role: index.execution_index_hash for role, index in indexes.items()
        },
        frozen_candidate_catalog_hash=canonical_sha256(
            [
                candidate["candidate_hash"]
                for candidate in source_design["candidates"]
            ]
        ),
        frozen_policy_catalog_hash=canonical_sha256(
            [policy["policy_hash"] for policy in source_design["policies"]]
        ),
        frozen_assignment_catalog_hash=canonical_sha256(
            [
                assignment["assignment_hash"]
                for assignment in source_design["assignments"]
            ]
        ),
        frozen_claim_hash=source_design["claim"]["claim_hash"],
        allowed_repair_fields=EXPECTED_ALLOWED_REPAIRS,
        stop_rule_check_ids=sorted(EXPECTED_STOP_RULE_CHECKS),
        frozen_at=frozen_at or datetime.now(timezone.utc),
    )
    _write_text_atomic(freeze_path, repair.canonical_json() + "\n")
    copy_roles: tuple[Literal["primary", "replay"], ...] = (
        "primary",
        "replay",
    )
    for role in copy_roles:
        shutil.copy2(
            freeze_path,
            output_dir / _workspace_name(role) / REPAIR_FREEZE_FILENAME,
        )
    return repair


def _baseline_environment() -> dict[str, str]:
    return confirmation._baseline_environment()


def _run_controller(
    output_dir: Path,
    repair: ConsumedPanelRepairFreeze,
    *,
    role: Literal["primary", "replay"],
    interpreter: Path,
    timeout_seconds: int,
    progress: Callable[[str], None] | None,
) -> dict[str, Any]:
    workspace = output_dir / _workspace_name(role)
    result_path = workspace / CONTROLLER_RESULT_RELATIVE
    if result_path.exists():
        return _load_hashed_json(result_path, "result_hash")
    controller_path = (
        workspace
        / "execution-assets"
        / V2_POLICY_CONTROLLER_SOURCE_PATH.name
    )
    execution_dir = workspace / "technical-execution"
    command = [
        interpreter.resolve().as_posix(),
        controller_path.resolve().as_posix(),
        "--design",
        (workspace / CONFIRMATION_FREEZE_FILENAME).resolve().as_posix(),
        "--input-index",
        (workspace / EXECUTION_INDEX_FILENAME).resolve().as_posix(),
        "--repair-freeze",
        (workspace / REPAIR_FREEZE_FILENAME).resolve().as_posix(),
        "--output",
        execution_dir.resolve().as_posix(),
        "--python",
        interpreter.resolve().as_posix(),
        "--allowed-root",
        workspace.resolve().as_posix(),
        "--progress",
        (execution_dir / "progress.txt").resolve().as_posix(),
    ]
    if progress is not None:
        progress(f"{role} technical controller started")
    completed = subprocess.run(
        command,
        cwd=workspace,
        env=_baseline_environment(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        check=False,
    )
    _write_text_atomic(execution_dir / "controller.stdout.log", completed.stdout)
    _write_text_atomic(execution_dir / "controller.stderr.log", completed.stderr)
    if completed.returncode != 0 or not result_path.exists():
        raise RuntimeError(
            f"{role} technical controller failed with {completed.returncode}: "
            f"{completed.stderr[-3000:]}"
        )
    result = _load_hashed_json(result_path, "result_hash")
    if (
        result.get("repair_freeze_hash") != repair.repair_freeze_hash
        or result.get("technical_only") is not True
        or result.get("independent_confirmation_eligible") is not False
    ):
        raise PortfolioIntegrityError(
            f"{role} technical controller boundary mismatch"
        )
    if progress is not None:
        progress(f"{role} technical controller completed")
    return result


def _assignment_projection(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "unit_id": result["unit_id"],
        "within_unit_seed": result["within_unit_seed"],
        "policy_id": result["policy_id"],
        "selected_candidate_id": result["selected_candidate_id"],
        "selected_candidate_family": result["selected_candidate_family"],
        "policy_score": result["policy_score"],
        "baseline_score": result["baseline_score"],
        "minimum_gain": result["minimum_gain"],
        "normalized_margin": result["normalized_margin"],
        "objective_task_success": result["objective_task_success"],
        "artifact_valid": result["artifact_valid"],
        "prediction_replay_valid": result["prediction_replay_valid"],
        "budget_valid": result["budget_valid"],
        "evaluator_integrity_valid": result["evaluator_integrity_valid"],
        "failure_codes": result["failure_codes"],
        "memory_before_hash": result["memory_before_hash"],
        "memory_after_hash": result["memory_after_hash"],
        "stage_records": [
            {
                "candidate_id": record["candidate_id"],
                "stage": record["stage"],
                "status": record["status"],
                "objective_score": record["objective_score"],
                "selection_score": record["selection_score"],
                "memory_correction": record["memory_correction"],
                "promoted": record["promoted"],
                "failure_code": record["failure_code"],
            }
            for record in result["stage_records"]
        ],
    }


def _load_technical_matrix(
    workspace: Path,
    repair: ConsumedPanelRepairFreeze,
    controller: Mapping[str, Any],
) -> tuple[
    ConfirmatoryExecutionIndex,
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    design = confirmation.load_confirmatory_freeze(workspace)
    index = ConfirmatoryExecutionIndex.model_validate_json(
        (workspace / EXECUTION_INDEX_FILENAME).read_text(encoding="utf-8")
    )
    expected_index_hash = repair.technical_execution_index_hashes[
        index.interpreter_role
    ]
    if (
        index.freeze_hash != repair.source_confirmation_freeze_hash
        or index.reveal_hash != repair.source_reveal_hash
        or index.execution_index_hash != expected_index_hash
    ):
        raise PortfolioIntegrityError("technical index/freeze binding mismatch")
    assignment_hashes = controller.get("assignment_result_hashes")
    null_hashes = controller.get("null_control_result_hashes")
    if (
        not isinstance(assignment_hashes, dict)
        or len(assignment_hashes) != 1620
        or not isinstance(null_hashes, dict)
        or len(null_hashes) != 180
    ):
        raise PortfolioIntegrityError("technical controller matrix is incomplete")
    results: list[dict[str, Any]] = []
    assignment_projections: list[dict[str, Any]] = []
    for assignment in design.assignments:
        path = (
            workspace
            / "technical-execution/assignments"
            / assignment.assignment_id
            / "result.json"
        )
        result = _load_hashed_json(path, "result_hash")
        if (
            result["result_hash"] != assignment_hashes[assignment.assignment_id]
            or result.get("schema_version")
            != "consumed-panel-technical-assignment-result-v1"
            or result.get("repair_freeze_hash") != repair.repair_freeze_hash
            or result.get("partition") != "consumed_confirmatory_technical"
            or result.get("technical_only") is not True
            or result.get("independent_confirmation_eligible") is not False
            or result["assignment_hash"] != assignment.assignment_hash
            or result["freeze_hash"] != design.freeze_hash
            or result["reveal_hash"] != index.reveal_hash
            or result["unit_id"] != assignment.unit_id
            or result["policy_id"] != assignment.policy_id
            or int(result["within_unit_seed"]) != assignment.within_unit_seed
        ):
            raise PortfolioIntegrityError(
                f"technical assignment binding mismatch: {assignment.assignment_id}"
            )
        records = result.get("stage_records")
        if not isinstance(records, list) or len(records) != 48:
            raise PortfolioIntegrityError("technical assignment lacks 48 stage rows")
        results.append(result)
        assignment_projections.append(_assignment_projection(result))
    null_results: list[dict[str, Any]] = []
    null_projections: list[dict[str, Any]] = []
    for unit_id in design.confirmatory_unit_ids:
        for seed in design.within_unit_seeds:
            control_id = f"null-{unit_id}-{seed}"
            path = (
                workspace
                / "technical-execution/null-controls"
                / control_id
                / "result.json"
            )
            result = _load_hashed_json(path, "result_hash")
            if (
                result["result_hash"] != null_hashes[control_id]
                or result.get("schema_version")
                != "consumed-panel-technical-null-control-result-v1"
                or result.get("repair_freeze_hash") != repair.repair_freeze_hash
                or result.get("technical_only") is not True
                or result.get("independent_confirmation_eligible") is not False
                or result["unit_id"] != unit_id
                or int(result["within_unit_seed"]) != seed
            ):
                raise PortfolioIntegrityError(
                    f"technical null binding mismatch: {control_id}"
                )
            null_results.append(result)
            null_projections.append(
                {
                    key: result[key]
                    for key in (
                        "unit_id",
                        "within_unit_seed",
                        "candidate_id",
                        "score",
                        "baseline_score",
                        "minimum_gain",
                        "normalized_margin",
                        "objective_task_success",
                        "artifact_valid",
                        "prediction_replay_valid",
                        "evaluator_integrity_valid",
                        "failure_code",
                    )
                }
            )
    evaluations: list[dict[str, Any]] = []
    referenced = {
        str(record["evaluation_hash"])
        for result in results
        for record in result["stage_records"]
        if record["evaluation_hash"] is not None
    }.union(str(result["evaluation_hash"]) for result in null_results)
    task_by_id = {task.unit_id: task for task in index.tasks}
    candidate_by_id = {
        candidate.candidate_id: candidate for candidate in design.candidates
    }
    cache = workspace / "technical-execution/evaluation-cache"
    for path in sorted(cache.glob("*/evaluation.json")):
        evaluation = _load_hashed_json(path, "evaluation_hash")
        task = task_by_id[str(evaluation["unit_id"])]
        candidate = candidate_by_id[str(evaluation["candidate_id"])]
        stage = str(evaluation["stage"])
        config = json.loads(
            (path.parent / "execution-config.json").read_text(encoding="utf-8")
        )
        if (
            evaluation.get("schema_version")
            != "consumed-panel-technical-candidate-evaluation-v1"
            or evaluation.get("repair_freeze_hash") != repair.repair_freeze_hash
            or evaluation.get("technical_only") is not True
            or evaluation.get("independent_confirmation_eligible") is not False
            or evaluation["candidate_hash"] != candidate.candidate_hash
            or evaluation["train_sha256"] != task.train_sha256
            or evaluation["test_sha256"] != task.test_sha256
            or evaluation["sealed_labels_sha256"] != task.labels_sha256
            or evaluation["runner_source_hash"]
            != repair.v2_confirmation_runner_sha256
            or evaluation["config_hash"] != canonical_sha256(config)
            or config["confirmation_freeze_hash"] != design.freeze_hash
            or config["reveal_hash"] != index.reveal_hash
        ):
            raise PortfolioIntegrityError(
                f"technical evaluation binding mismatch: {path.parent.name}"
            )
        if stage == "F3":
            if (
                config.get("labels_path") != task.labels_path
                or config.get("labels_sha256") != task.labels_sha256
                or evaluation.get("labels_accessed") is not True
            ):
                raise PortfolioIntegrityError("technical F3 label binding failed")
        elif (
            "labels_path" in config
            or "labels_sha256" in config
            or evaluation.get("labels_accessed") is not False
            or evaluation.get("runner_labels_sha256") is not None
        ):
            raise PortfolioIntegrityError(
                "technical F1/F2 exposed sealed labels"
            )
        evaluations.append(evaluation)
    if {str(item["evaluation_hash"]) for item in evaluations} != referenced:
        raise PortfolioIntegrityError(
            "technical result/evaluation provenance inventory mismatch"
        )
    projection = {
        "source_confirmation_freeze_hash": design.freeze_hash,
        "repair_freeze_hash": repair.repair_freeze_hash,
        "source_reveal_hash": index.reveal_hash,
        "consumed_panel": True,
        "technical_only": True,
        "assignments": assignment_projections,
        "null_controls": null_projections,
    }
    if canonical_sha256(projection) != controller["scientific_projection_hash"]:
        raise PortfolioIntegrityError(
            "technical scientific projection reconstruction differs"
        )
    return index, results, null_results, evaluations


def _analyze_technical_repair(
    source_report: confirmation.ConfirmatoryEvaluationReport,
    repair: ConsumedPanelRepairFreeze,
    primary_controller: Mapping[str, Any],
    replay_controller: Mapping[str, Any],
    primary_matrix: tuple[
        ConfirmatoryExecutionIndex,
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
    ],
) -> TechnicalRepairAnalysis:
    index, results, null_results, evaluations = primary_matrix
    outcomes = confirmation._task_policy_outcomes(index, results)
    summaries = confirmation._policy_summaries(outcomes, results)
    primary = confirmation._comparison(
        outcomes,
        comparison_id="portfolio-memory-vs-linear-self-loop",
        role="primary",
        policy_a="portfolio_memory",
        policy_b="linear_self_loop",
    )
    null_control = confirmation._null_control_summary(null_results)
    _, family_differences = confirmation._block_effects(outcomes)
    failure_domains = Counter(
        str(item["failure_domain"])
        for item in evaluations
        if item.get("failure_domain") is not None
    )
    failure_codes = Counter(
        str(item["failure_code"])
        for item in evaluations
        if item.get("failure_code") is not None
    )
    unexpected_candidate_failures = sum(
        item.get("failure_domain") == "candidate"
        and item.get("candidate_id") != "invalid-schema-probe"
        for item in evaluations
    )
    label_isolation = all(
        item["labels_accessed"] is False
        and item["runner_labels_sha256"] is None
        for item in evaluations
        if item["stage"] in {"F1", "F2"}
    )
    v1_cost = source_report.analysis.cost_failure_audit
    v2_cpu = sum(
        float(item["cost"]["newly_executed_cpu_seconds"]) for item in results
    )
    v2_wall = sum(
        float(item["cost"]["newly_executed_wall_seconds"]) for item in results
    )
    assignment_evaluations = {
        str(record["evaluation_hash"])
        for result in results
        for record in result["stage_records"]
        if record["evaluation_hash"] is not None
    }
    for item in evaluations:
        if str(item["evaluation_hash"]) not in assignment_evaluations:
            v2_cpu += float(item["cpu_seconds"])
            v2_wall += float(item["wall_seconds"])
    failure_cost = TechnicalFailureCostComparison.create(
        v1_unique_evaluation_count=v1_cost.unique_evaluation_count,
        v2_unique_evaluation_count=len(evaluations),
        v1_evaluation_failure_count=v1_cost.evaluation_failure_count,
        v2_evaluation_failure_count=sum(
            item["status"] == "failed" for item in evaluations
        ),
        v1_failure_code_counts=v1_cost.failure_code_counts,
        v2_failure_domain_counts=dict(failure_domains),
        v2_failure_code_counts=dict(failure_codes),
        v2_null_integrity_failure_count=null_control.integrity_failure_count,
        v1_newly_executed_cpu_seconds=v1_cost.newly_executed_cpu_seconds,
        v2_newly_executed_cpu_seconds=v2_cpu,
        v1_newly_executed_wall_seconds=v1_cost.newly_executed_wall_seconds,
        v2_newly_executed_wall_seconds=v2_wall,
    )
    v1_risk_difference = (
        source_report.analysis.primary_comparison.risk_difference_a_minus_b
    )
    stop_checks = {
        "both-benchmark-family-risk-differences-nonnegative": all(
            value >= 0 for value in family_differences.values()
        ),
        "complete-primary-and-replay-matrices": (
            primary_controller["assignment_count"] == 1620
            and primary_controller["null_control_count"] == 180
            and replay_controller["assignment_count"] == 1620
            and replay_controller["null_control_count"] == 180
            and primary_controller["full_matrix_complete"] is True
            and replay_controller["full_matrix_complete"] is True
        ),
        "corrected-risk-difference-at-least-0.10": (
            primary.risk_difference_a_minus_b
            >= repair.minimum_observed_risk_difference_to_review
        ),
        "directionally-more-favorable-than-unfavorable-tasks": (
            primary.favorable_to_a > primary.unfavorable_to_a
        ),
        "f1-f2-physical-label-isolation-complete": label_isolation,
        "no-input-evaluator-or-infrastructure-failures": not any(
            failure_domains.get(domain, 0)
            for domain in ("input", "evaluator", "infrastructure")
        ),
        "no-unexpected-candidate-failures": (
            unexpected_candidate_failures == 0
        ),
        "null-control-zero-integrity-failures": (
            null_control.integrity_failure_count == 0
        ),
        "repair-scope-and-route-unchanged": (
            repair.allowed_repair_fields == EXPECTED_ALLOWED_REPAIRS
            and primary_controller["post_reveal_retuning_authorized"] is False
            and primary_controller[
                "result_contingent_route_change_authorized"
            ]
            is False
            and primary_controller["technical_only"] is True
            and primary_controller["publication_evidence_eligible"] is False
        ),
        "two-interpreter-scientific-projection-exact": (
            primary_controller["scientific_projection_hash"]
            == replay_controller["scientific_projection_hash"]
        ),
    }
    decision = (
        TechnicalRepairDecision.ELIGIBLE_FOR_NEW_MECHANISM_REVIEW
        if all(stop_checks.values())
        else TechnicalRepairDecision.STOP_PORTFOLIO_MEMORY_CLAIM
    )
    return TechnicalRepairAnalysis.create(
        task_outcomes=outcomes,
        policy_summaries=summaries,
        primary_comparison=primary,
        null_control=null_control,
        benchmark_family_risk_differences=family_differences,
        v1_primary_risk_difference=v1_risk_difference,
        corrected_minus_v1_risk_difference=(
            primary.risk_difference_a_minus_b - v1_risk_difference
        ),
        failure_cost_comparison=failure_cost,
        stop_rule_checks=stop_checks,
        decision=decision,
    )


def render_technical_replay_markdown(
    report: ConsumedPanelTechnicalReport,
) -> str:
    """Render an intentionally unmistakable technical-only reader view."""

    primary = report.analysis.primary_comparison
    summaries = {
        summary.policy_id: summary for summary in report.analysis.policy_summaries
    }
    checks = "\n".join(
        f"- `{key}`: `{value}`"
        for key, value in report.analysis.stop_rule_checks.items()
    )
    return (
        "# Consumed-panel technical evaluator repair replay\n\n"
        "> **TECHNICAL / EXPLORATORY / CONSUMED PANEL.** This is not an "
        "independent confirmation and cannot support a publication claim.\n\n"
        f"- Decision: `{report.decision.value}`\n"
        f"- `portfolio_memory`: "
        f"`{summaries['portfolio_memory'].task_success_count}/60`\n"
        f"- `linear_self_loop`: "
        f"`{summaries['linear_self_loop'].task_success_count}/60`\n"
        f"- Corrected risk difference: "
        f"`{primary.risk_difference_a_minus_b:.6f}`\n"
        f"- Conservative exact 95% interval: "
        f"`[{primary.exact_risk_difference_interval_95[0]:.6f}, "
        f"{primary.exact_risk_difference_interval_95[1]:.6f}]`\n"
        f"- Exact McNemar p: `{primary.exact_mcnemar_p:.12g}`\n"
        f"- v1 risk difference: "
        f"`{report.analysis.v1_primary_risk_difference:.6f}`\n"
        f"- Corrected minus v1: "
        f"`{report.analysis.corrected_minus_v1_risk_difference:.6f}`\n"
        f"- Null-control integrity failures: "
        f"`{report.analysis.null_control.integrity_failure_count}/180`\n"
        f"- Two-interpreter projection exact: "
        f"`{report.scientific_projection_exact}`\n\n"
        "## Frozen stop/review checks\n\n"
        f"{checks}\n\n"
        "## Boundary\n\n"
        "The numerical result can only stop the current claim or, if every "
        "pre-frozen check passes, permit a separate new-mechanism review. It "
        "does not authorize a fresh panel. A new mechanism rationale, new "
        "development evidence, a new question certificate, prospective "
        "power, disjoint source groups, and a zero-result freeze would still "
        "be required. Public release and submission remain unauthorized.\n"
    )


def _artifact_hashes(output_dir: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(item for item in output_dir.rglob("*") if item.is_file()):
        relative = path.relative_to(output_dir).as_posix()
        if relative == TECHNICAL_MANIFEST_FILENAME:
            continue
        hashes[relative] = _file_sha256(path)
    return dict(sorted(hashes.items()))


def run_consumed_panel_technical_replay(
    source_confirmation_dir: Path,
    evaluator_certificate_dir: Path,
    output_dir: Path,
    *,
    timeout_seconds: int = 172_800,
    progress: Callable[[str], None] | None = None,
    completed_at: datetime | None = None,
) -> ConsumedPanelTechnicalReport:
    """Execute, replay, analyze, and adjudicate the complete technical matrix."""

    output_dir = output_dir.resolve()
    report_path = output_dir / TECHNICAL_REPORT_FILENAME
    if report_path.exists():
        report, _ = load_consumed_panel_technical_replay(
            output_dir,
            source_confirmation_dir=source_confirmation_dir,
            evaluator_certificate_dir=evaluator_certificate_dir,
        )
        return report
    repair = freeze_consumed_panel_repair(
        source_confirmation_dir,
        evaluator_certificate_dir,
        output_dir,
    )
    source_report, source_freeze, source_manifest = (
        load_confirmatory_evaluation_report(source_confirmation_dir.resolve())
    )
    interpreters = {
        role: Path(path).resolve()
        for role, path in source_freeze.clean_interpreter_paths.items()
    }
    primary_controller = _run_controller(
        output_dir,
        repair,
        role="primary",
        interpreter=interpreters["primary"],
        timeout_seconds=timeout_seconds,
        progress=progress,
    )
    replay_controller = _run_controller(
        output_dir,
        repair,
        role="replay",
        interpreter=interpreters["replay"],
        timeout_seconds=timeout_seconds,
        progress=progress,
    )
    if (
        primary_controller["scientific_projection_hash"]
        != replay_controller["scientific_projection_hash"]
    ):
        raise PortfolioIntegrityError(
            "technical two-interpreter scientific projection differs"
        )
    primary_matrix = _load_technical_matrix(
        output_dir / PRIMARY_WORKSPACE,
        repair,
        primary_controller,
    )
    _load_technical_matrix(
        output_dir / REPLAY_WORKSPACE,
        repair,
        replay_controller,
    )
    analysis = _analyze_technical_repair(
        source_report,
        repair,
        primary_controller,
        replay_controller,
        primary_matrix,
    )
    report = ConsumedPanelTechnicalReport.create(
        repair_freeze_hash=repair.repair_freeze_hash,
        source_confirmation_freeze_hash=source_freeze.freeze_hash,
        source_report_hash=source_report.report_hash,
        source_manifest_hash=source_manifest.manifest_hash,
        evaluator_certificate_report_hash=(
            repair.evaluator_certificate_report_hash
        ),
        primary_execution_index_hash=(
            repair.technical_execution_index_hashes["primary"]
        ),
        replay_execution_index_hash=(
            repair.technical_execution_index_hashes["replay"]
        ),
        primary_controller_result_hash=primary_controller["result_hash"],
        replay_controller_result_hash=replay_controller["result_hash"],
        primary_scientific_projection_hash=primary_controller[
            "scientific_projection_hash"
        ],
        replay_scientific_projection_hash=replay_controller[
            "scientific_projection_hash"
        ],
        analysis=analysis,
        decision=analysis.decision,
        completed_at=completed_at or datetime.now(timezone.utc),
    )
    _write_text_atomic(report_path, report.canonical_json() + "\n")
    _write_text_atomic(
        output_dir / TECHNICAL_MARKDOWN_FILENAME,
        render_technical_replay_markdown(report),
    )
    _write_text_atomic(
        output_dir / TECHNICAL_SCHEMA_FILENAME,
        json.dumps(
            technical_replay_json_schemas(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
    )
    manifest = TechnicalReplayArtifactManifest.create(
        repair_freeze_hash=repair.repair_freeze_hash,
        report_hash=report.report_hash,
        artifact_hashes=_artifact_hashes(output_dir),
    )
    _write_text_atomic(
        output_dir / TECHNICAL_MANIFEST_FILENAME,
        manifest.canonical_json() + "\n",
    )
    return report


def load_consumed_panel_technical_replay(
    output_dir: Path,
    *,
    source_confirmation_dir: Path | None = None,
    evaluator_certificate_dir: Path | None = None,
) -> tuple[ConsumedPanelTechnicalReport, TechnicalReplayArtifactManifest]:
    """Recursively verify the complete technical replay research object."""

    output_dir = output_dir.resolve()
    repair = ConsumedPanelRepairFreeze.model_validate_json(
        (output_dir / REPAIR_FREEZE_FILENAME).read_text(encoding="utf-8")
    )
    report = ConsumedPanelTechnicalReport.model_validate_json(
        (output_dir / TECHNICAL_REPORT_FILENAME).read_text(encoding="utf-8")
    )
    manifest = TechnicalReplayArtifactManifest.model_validate_json(
        (output_dir / TECHNICAL_MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    if (
        report.repair_freeze_hash != repair.repair_freeze_hash
        or manifest.repair_freeze_hash != repair.repair_freeze_hash
        or manifest.report_hash != report.report_hash
    ):
        raise PortfolioIntegrityError("technical report/manifest binding mismatch")
    if _artifact_hashes(output_dir) != manifest.artifact_hashes:
        raise PortfolioIntegrityError("technical recursive artifact inventory changed")
    if _file_sha256(Path(__file__).resolve()) != repair.orchestrator_source_sha256:
        raise PortfolioIntegrityError("technical orchestrator source changed")
    primary_controller = _load_hashed_json(
        output_dir / PRIMARY_WORKSPACE / CONTROLLER_RESULT_RELATIVE,
        "result_hash",
    )
    replay_controller = _load_hashed_json(
        output_dir / REPLAY_WORKSPACE / CONTROLLER_RESULT_RELATIVE,
        "result_hash",
    )
    if (
        primary_controller["result_hash"]
        != report.primary_controller_result_hash
        or replay_controller["result_hash"]
        != report.replay_controller_result_hash
        or primary_controller["scientific_projection_hash"]
        != report.primary_scientific_projection_hash
        or replay_controller["scientific_projection_hash"]
        != report.replay_scientific_projection_hash
    ):
        raise PortfolioIntegrityError("technical controller/report binding mismatch")
    primary_matrix = _load_technical_matrix(
        output_dir / PRIMARY_WORKSPACE,
        repair,
        primary_controller,
    )
    _load_technical_matrix(
        output_dir / REPLAY_WORKSPACE,
        repair,
        replay_controller,
    )
    if source_confirmation_dir is not None:
        source_report, _, source_manifest = load_confirmatory_evaluation_report(
            source_confirmation_dir.resolve()
        )
        if (
            source_report.report_hash != report.source_report_hash
            or source_manifest.manifest_hash != report.source_manifest_hash
        ):
            raise PortfolioIntegrityError("technical source endpoint changed")
        reconstructed = _analyze_technical_repair(
            source_report,
            repair,
            primary_controller,
            replay_controller,
            primary_matrix,
        )
        if reconstructed.analysis_hash != report.analysis.analysis_hash:
            raise PortfolioIntegrityError("technical analysis reconstruction differs")
    if evaluator_certificate_dir is not None:
        certificate, certificate_manifest = (
            load_evaluator_compatibility_certificate(
                evaluator_certificate_dir.resolve(),
                source_confirmation_dir=source_confirmation_dir,
            )
        )
        if (
            certificate.report_hash
            != report.evaluator_certificate_report_hash
            or certificate_manifest.manifest_hash
            != repair.evaluator_certificate_manifest_hash
        ):
            raise PortfolioIntegrityError(
                "technical evaluator certificate changed"
            )
    return report, manifest
