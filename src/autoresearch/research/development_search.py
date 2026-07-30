"""Budget-matched multi-branch development search for Task 263.5.

The module turns the result-blind Task 263.4.2 preregistration into an
executable, content-addressed development experiment.  It deliberately
separates three layers:

* one model-assisted but grammar-constrained candidate initialization;
* deterministic policy allocation over a common candidate catalogue; and
* a frozen, network-free objective runner with exact prediction replay.

Confirmatory payloads are never fetched or opened here.  Development outcomes
may select a single policy for the later one-use confirmation gate, but they
cannot change the preregistered claim, thresholds, or confirmatory schedule.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import io
import json
import math
import os
import random
import re
import statistics
import subprocess
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal

import requests
from pydantic import BaseModel, Field, field_validator, model_validator
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from autoresearch.kernel.contracts import (
    KernelContract,
    NonEmptyText,
    Sha256,
    StableId,
    canonical_sha256,
)
from autoresearch.llm.client import LLMJsonCompletionResult, run_llm_json_completion

from .baseline_preregistration import (
    BaselineGateStatus,
    BaselineReproductionReport,
    CausalSearchPreregistration,
    FrozenTaskSuccessThreshold,
    load_baseline_preregistration,
)
from .objective_task_panel import (
    OpenObjectiveTaskPanelReport,
    load_open_objective_task_panel,
)
from .objective_task_registry import ObjectiveTaskFamily
from .portfolio import (
    BaselineReproductionEvidence,
    BaselineReproductionPlan,
    BranchBudget,
    FidelityKind,
    FidelityStageSpec,
    MetricDirection,
    NearestWorkDelta,
    OpportunityAssessment,
    OpportunityStage,
    PortfolioArmKind,
    PortfolioAssessment,
    PortfolioBranch,
    PortfolioIntegrityError,
    PortfolioSpec,
    PrimaryMetricSpec,
    ProspectivePowerPlan,
    PublicationEndpoint,
    ResearchBudget,
    ResearchDataSplit,
    ResearchOpportunity,
    ResearchQuestionCertificate,
    ResearchSource,
    SourceMaturity,
    assess_portfolio,
    assess_research_opportunity,
)
from .search_policy_study import (
    StudyAblation,
    StudyArm,
    exact_two_sided_sign_test_pvalue,
)

JsonCompletion = Callable[..., LLMJsonCompletionResult]

RUNNER_SOURCE_PATH = Path(
    "src/autoresearch/research/assets/frozen_tabular_candidate_runner_v2.py"
)
RUNNER_DEPENDENCY_SOURCE_PATH = Path(
    "src/autoresearch/research/assets/frozen_tabular_candidate_runner_v1.py"
)
DEVELOPMENT_METRIC_ID = "paired-objective-task-margin"
DEVELOPMENT_FREEZE_FILENAME = "development-search-freeze.json"
DEVELOPMENT_REPORT_FILENAME = "development-search-report.json"
DEVELOPMENT_MANIFEST_FILENAME = "development-search-manifest.json"
DEVELOPMENT_SCHEMA_FILENAME = "development-search-schemas.json"
DEVELOPMENT_MARKDOWN_FILENAME = "development-search-report.md"
FORBIDDEN_RUNNER_IMPORT_ROOTS = {
    "aiohttp",
    "arxiv",
    "httpx",
    "openai",
    "openml",
    "requests",
    "semanticscholar",
    "socket",
    "urllib",
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
    model: type[BaseModel],
    payload: Mapping[str, Any],
    hash_field: str,
) -> dict[str, Any]:
    normalized = model.model_construct(**dict(payload)).model_dump(
        mode="json",
        exclude={hash_field},
    )
    normalized[hash_field] = canonical_sha256(normalized)
    return normalized


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


class CandidateLearner(str, Enum):
    """Learners admitted by the frozen declarative candidate grammar."""

    DUMMY = "dummy"
    LINEAR = "linear"
    LGBM = "lgbm"
    XGBOOST = "xgboost"
    RF = "rf"
    EXTRA_TREE = "extra_tree"
    HIST_GB = "hist_gb"
    LGBM_XGBOOST_ENSEMBLE = "lgbm_xgboost_ensemble"
    INVALID_PROBE = "invalid_probe"


class CandidatePreprocessing(str, Enum):
    """One allowed preprocessing decision."""

    NONE = "none"
    IMPUTE = "impute"
    STANDARDIZE = "standardize"
    ROBUST = "robust"


class CandidateSpec(KernelContract):
    """One content-addressed branch in the shared candidate catalogue."""

    schema_version: Literal["development-candidate-v1"] = "development-candidate-v1"
    candidate_id: StableId
    mechanism_family: StableId
    arm_kind: PortfolioArmKind
    learner: CandidateLearner
    preprocessing: CandidatePreprocessing
    hyperparameters: dict[StableId, int | float]
    hypothesis: NonEmptyText
    exact_delta: NonEmptyText
    source_ids: list[StableId] = Field(min_length=1)
    intentional_failure_control: bool = False
    candidate_hash: Sha256

    @field_validator("source_ids")
    @classmethod
    def _normalize_sources(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("candidate source IDs must be unique")
        return sorted(value)

    @model_validator(mode="after")
    def _validate_candidate(self) -> CandidateSpec:
        if len(self.hyperparameters) > 2:
            raise ValueError("candidate grammar permits at most two hyperparameters")
        if list(self.hyperparameters) != sorted(self.hyperparameters):
            raise ValueError("candidate hyperparameters must be key-sorted")
        if self.intentional_failure_control != (
            self.learner is CandidateLearner.INVALID_PROBE
        ):
            raise ValueError("intentional failure flag must match invalid_probe learner")
        if (
            self.arm_kind is PortfolioArmKind.NULL_OR_RULE
            and self.learner
            not in {CandidateLearner.DUMMY, CandidateLearner.INVALID_PROBE}
        ):
            raise ValueError("null/rule candidates must use a control learner")
        if self.candidate_hash != self.calculated_hash():
            raise PortfolioIntegrityError("candidate_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> CandidateSpec:
        payload = dict(values)
        payload["schema_version"] = "development-candidate-v1"
        payload["source_ids"] = sorted(payload["source_ids"])
        payload["hyperparameters"] = dict(sorted(payload["hyperparameters"].items()))
        return cls.model_validate(_with_canonical_hash(cls, payload, "candidate_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"candidate_hash"})
        )

    def verify_integrity(self) -> None:
        if self.candidate_hash != self.calculated_hash():
            raise PortfolioIntegrityError("candidate_hash mismatch")


class CandidateInitialization(KernelContract):
    """Accepted result-blind model ordering for the fixed candidate grammar."""

    schema_version: Literal["candidate-initialization-v1"] = (
        "candidate-initialization-v1"
    )
    interaction_id: StableId
    candidate_catalog_hash: Sha256
    preregistration_hash: Sha256
    messages_hash: Sha256
    provider: NonEmptyText
    base_url: NonEmptyText
    model_name: NonEmptyText
    response_sha256: Sha256
    parsed_json_sha256: Sha256
    ordered_candidate_ids: list[StableId] = Field(min_length=12, max_length=12)
    portfolio_rationale: NonEmptyText
    usage: dict[str, Any]
    result_inputs_visible: Literal[False] = False
    confirmatory_inputs_visible: Literal[False] = False
    arbitrary_code_generated: Literal[False] = False
    created_at: datetime
    initialization_hash: Sha256

    @field_validator("created_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("candidate initialization time must be timezone-aware")
        return value

    @field_validator("ordered_candidate_ids")
    @classmethod
    def _require_unique_candidates(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("candidate initialization contains duplicate IDs")
        return value

    @model_validator(mode="after")
    def _validate_hash(self) -> CandidateInitialization:
        if self.initialization_hash != self.calculated_hash():
            raise PortfolioIntegrityError("candidate initialization_hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        interaction_id: str,
        candidate_catalog_hash: str,
        preregistration_hash: str,
        messages: Sequence[Mapping[str, str]],
        response: LLMJsonCompletionResult,
        ordered_candidate_ids: list[str],
        portfolio_rationale: str,
        created_at: datetime,
    ) -> CandidateInitialization:
        payload: dict[str, Any] = {
            "schema_version": "candidate-initialization-v1",
            "interaction_id": interaction_id,
            "candidate_catalog_hash": candidate_catalog_hash,
            "preregistration_hash": preregistration_hash,
            "messages_hash": canonical_sha256(list(messages)),
            "provider": response.provider,
            "base_url": response.base_url,
            "model_name": response.model_name,
            "response_sha256": hashlib.sha256(
                response.response_text.encode("utf-8")
            ).hexdigest(),
            "parsed_json_sha256": canonical_sha256(response.parsed_json),
            "ordered_candidate_ids": ordered_candidate_ids,
            "portfolio_rationale": portfolio_rationale,
            "usage": response.usage,
            "result_inputs_visible": False,
            "confirmatory_inputs_visible": False,
            "arbitrary_code_generated": False,
            "created_at": created_at,
        }
        return cls.model_validate(
            _with_canonical_hash(cls, payload, "initialization_hash")
        )

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"initialization_hash"})
        )

    def verify_integrity(self) -> None:
        if self.initialization_hash != self.calculated_hash():
            raise PortfolioIntegrityError("candidate initialization_hash mismatch")


class DevelopmentLabels(KernelContract):
    """Development-only evaluator labels reconstructed from frozen source bytes."""

    schema_version: Literal["development-labels-v1"] = "development-labels-v1"
    unit_id: StableId
    opaque_unit_id: StableId
    family: Literal["tabular_classification", "tabular_regression"]
    row_ids: list[int] = Field(min_length=1)
    labels: list[str | float] = Field(min_length=1)
    data_sha256: Sha256
    split_sha256: Sha256
    source_data_md5: str = Field(pattern=r"^[0-9a-f]{32}$")
    confirmatory_source: Literal[False] = False
    label_hash: Sha256

    @model_validator(mode="after")
    def _validate_labels(self) -> DevelopmentLabels:
        if len(self.row_ids) != len(self.labels):
            raise ValueError("development row IDs and labels differ in length")
        if self.row_ids != sorted(self.row_ids) or len(self.row_ids) != len(
            set(self.row_ids)
        ):
            raise ValueError("development label row IDs must be unique and sorted")
        if self.family == "tabular_classification" and not all(
            isinstance(item, str) for item in self.labels
        ):
            raise ValueError("classification development labels must be strings")
        if self.family == "tabular_regression" and not all(
            isinstance(item, float) for item in self.labels
        ):
            raise ValueError("regression development labels must be floats")
        if self.label_hash != self.calculated_hash():
            raise PortfolioIntegrityError("development label_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> DevelopmentLabels:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "development-labels-v1",
                "confirmatory_source": False,
            }
        )
        return cls.model_validate(_with_canonical_hash(cls, payload, "label_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"label_hash"}))


class DevelopmentLabelPreparationAudit(KernelContract):
    """Proof that only development payloads were fetched or cache-verified."""

    schema_version: Literal["development-label-preparation-audit-v1"] = (
        "development-label-preparation-audit-v1"
    )
    panel_report_hash: Sha256
    development_resource_urls: list[NonEmptyText] = Field(min_length=2)
    label_file_hashes: dict[StableId, Sha256]
    confirmatory_resource_url_count: Literal[0] = 0
    confirmatory_payloads_downloaded: Literal[False] = False
    raw_payloads_redistributed: Literal[False] = False
    audit_hash: Sha256

    @model_validator(mode="after")
    def _validate_audit(self) -> DevelopmentLabelPreparationAudit:
        if self.development_resource_urls != sorted(
            self.development_resource_urls
        ) or len(self.development_resource_urls) != len(
            set(self.development_resource_urls)
        ):
            raise ValueError("development resource URLs must be unique and sorted")
        if list(self.label_file_hashes) != sorted(self.label_file_hashes):
            raise ValueError("development label file hashes must be unit-sorted")
        if self.audit_hash != self.calculated_hash():
            raise PortfolioIntegrityError("development label audit_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> DevelopmentLabelPreparationAudit:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "development-label-preparation-audit-v1",
                "confirmatory_resource_url_count": 0,
                "confirmatory_payloads_downloaded": False,
                "raw_payloads_redistributed": False,
            }
        )
        payload["development_resource_urls"] = sorted(
            payload["development_resource_urls"]
        )
        payload["label_file_hashes"] = dict(
            sorted(payload["label_file_hashes"].items())
        )
        return cls.model_validate(_with_canonical_hash(cls, payload, "audit_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"audit_hash"}))


class DevelopmentInput(KernelContract):
    """One development-only task bundle and paired baseline threshold."""

    unit_id: StableId
    opaque_unit_id: StableId
    family: Literal["tabular_classification", "tabular_regression"]
    train_path: NonEmptyText
    test_path: NonEmptyText
    labels_path: NonEmptyText
    train_sha256: Sha256
    test_sha256: Sha256
    labels_sha256: Sha256
    label_hash: Sha256
    train_row_count: int = Field(ge=1)
    test_row_count: int = Field(ge=1)
    label_count: int = Field(ge=1)
    feature_count: int = Field(ge=1)
    data_sha256: Sha256
    split_sha256: Sha256
    baseline_score: float
    metric_id: Literal["balanced_accuracy", "r2"]
    minimum_gain: float = Field(gt=0)
    threshold_hash: Sha256


class PolicyRealization(KernelContract):
    """Executable interpretation of one frozen arm or one-at-a-time ablation."""

    policy_id: StableId
    parent_arm: StudyArm
    ablation: StudyAblation | None = None
    topology: Literal["flat_batch", "linear_chain", "branching_portfolio"]
    certificate_enabled: bool
    diversity_enabled: bool
    multi_fidelity_enabled: bool
    reviewer_enabled: bool
    comparative_memory_enabled: bool
    proposal_slots: Literal[12] = 12
    model_calls_per_assignment: Literal[0] = 0
    reviewer_score_is_scientific_gate: Literal[False] = False
    policy_hash: Sha256

    @model_validator(mode="after")
    def _validate_policy(self) -> PolicyRealization:
        if self.ablation is None and self.policy_id != self.parent_arm.value:
            raise ValueError("primary policy ID must equal its arm")
        if self.ablation is not None:
            expected = f"ablation-{self.ablation.value}"
            if self.policy_id != expected:
                raise ValueError("ablation policy ID mismatch")
            disabled = {
                StudyAblation.CERTIFICATE: not self.certificate_enabled,
                StudyAblation.DIVERSITY: not self.diversity_enabled,
                StudyAblation.MULTI_FIDELITY: not self.multi_fidelity_enabled,
                StudyAblation.REVIEWER: not self.reviewer_enabled,
                StudyAblation.MEMORY: not self.comparative_memory_enabled,
            }
            if not disabled[self.ablation]:
                raise ValueError("named ablation component was not disabled")
            if sum(bool(value) for value in disabled.values()) != 1:
                raise ValueError("ablation must disable exactly one component")
        if self.policy_hash != self.calculated_hash():
            raise PortfolioIntegrityError("policy_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> PolicyRealization:
        payload = dict(values)
        payload["ablation"] = payload.get("ablation")
        payload["proposal_slots"] = 12
        payload["model_calls_per_assignment"] = 0
        payload["reviewer_score_is_scientific_gate"] = False
        return cls.model_validate(_with_canonical_hash(cls, payload, "policy_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"policy_hash"}))


class DevelopmentAssignment(KernelContract):
    """One task-seed-policy row in the frozen complete development matrix."""

    assignment_id: StableId
    sequence_index: int = Field(ge=0)
    unit_id: StableId
    within_unit_seed: int = Field(ge=0)
    policy_id: StableId
    partition: Literal["development"] = "development"
    schedule_source: Literal[
        "task-263.4.2-randomization",
        "matched-ablation-sensitivity",
    ]
    assignment_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> DevelopmentAssignment:
        if self.assignment_hash != self.calculated_hash():
            raise PortfolioIntegrityError("assignment_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> DevelopmentAssignment:
        payload = dict(values)
        payload["partition"] = "development"
        return cls.model_validate(
            _with_canonical_hash(cls, payload, "assignment_hash")
        )

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"assignment_hash"})
        )


class DevelopmentBudgetRealization(KernelContract):
    """Result-blind actual call schedule below the preregistered hard caps."""

    schema_version: Literal["development-budget-realization-v1"] = (
        "development-budget-realization-v1"
    )
    preregistered_budget_hash: Sha256
    logical_candidate_proposals_per_assignment: Literal[12] = 12
    proposal_model_calls_per_assignment: Literal[0] = 0
    reviewer_model_calls_per_assignment: Literal[0] = 0
    reflection_model_calls_per_assignment: Literal[0] = 0
    global_initialization_model_calls: Literal[1] = 1
    maximum_total_model_tokens_per_assignment: int = Field(ge=0)
    maximum_cpu_seconds_per_assignment: int = Field(ge=1)
    maximum_memory_mb: int = Field(ge=1)
    unused_budget_reallocated: Literal[False] = False
    scientific_interpretation: NonEmptyText
    realization_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> DevelopmentBudgetRealization:
        if self.realization_hash != self.calculated_hash():
            raise PortfolioIntegrityError("budget realization_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> DevelopmentBudgetRealization:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "development-budget-realization-v1",
                "logical_candidate_proposals_per_assignment": 12,
                "proposal_model_calls_per_assignment": 0,
                "reviewer_model_calls_per_assignment": 0,
                "reflection_model_calls_per_assignment": 0,
                "global_initialization_model_calls": 1,
                "unused_budget_reallocated": False,
            }
        )
        return cls.model_validate(
            _with_canonical_hash(cls, payload, "realization_hash")
        )

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"realization_hash"})
        )


class DevelopmentRepairLineage(KernelContract):
    """Fail-closed record for a result-aware evaluator-only repair."""

    schema_version: Literal["development-repair-lineage-v1"] = (
        "development-repair-lineage-v1"
    )
    predecessor_freeze_hash: Sha256
    predecessor_report_hash: Sha256
    failure_evidence_hash: Sha256
    repair_class: Literal["mixed-type-evaluator-compatibility"] = (
        "mixed-type-evaluator-compatibility"
    )
    repair_reason: NonEmptyText
    candidate_order_reused: Literal[True] = True
    scientific_design_changed: Literal[False] = False
    confirmatory_evidence_used: Literal[False] = False
    lineage_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> DevelopmentRepairLineage:
        if self.lineage_hash != self.calculated_hash():
            raise PortfolioIntegrityError("repair lineage_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> DevelopmentRepairLineage:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "development-repair-lineage-v1",
                "repair_class": "mixed-type-evaluator-compatibility",
                "candidate_order_reused": True,
                "scientific_design_changed": False,
                "confirmatory_evidence_used": False,
            }
        )
        return cls.model_validate(
            _with_canonical_hash(cls, payload, "lineage_hash")
        )

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"lineage_hash"})
        )


class DevelopmentSearchFreeze(KernelContract):
    """Result-free executable contract frozen immediately before search."""

    schema_version: Literal["development-search-freeze-v2"] = (
        "development-search-freeze-v2"
    )
    freeze_id: StableId
    baseline_report_hash: Sha256
    preregistration_hash: Sha256
    preregistration_randomization_hash: Sha256
    portfolio: PortfolioSpec
    portfolio_assessment: PortfolioAssessment
    candidates: list[CandidateSpec] = Field(min_length=12, max_length=12)
    initialization: CandidateInitialization
    inputs: list[DevelopmentInput] = Field(min_length=3)
    label_preparation_audit: DevelopmentLabelPreparationAudit
    policies: list[PolicyRealization] = Field(min_length=9, max_length=9)
    assignments: list[DevelopmentAssignment] = Field(min_length=1)
    budget_realization: DevelopmentBudgetRealization
    controller_source_path: NonEmptyText
    controller_source_hash: Sha256
    runner_source_path: NonEmptyText
    runner_source_hash: Sha256
    runner_dependency_source_path: NonEmptyText
    runner_dependency_source_hash: Sha256
    repair_lineage: DevelopmentRepairLineage | None = None
    clean_interpreter_path: NonEmptyText
    clean_interpreter_hash: Sha256
    development_policy_survival_rule: NonEmptyText
    within_task_aggregation_rule: Literal[
        "task success requires at least two of three seed successes"
    ] = "task success requires at least two of three seed successes"
    minimum_development_task_successes: int = Field(ge=1)
    minimum_low_high_spearman: float = Field(ge=-1, le=1)
    require_nonnegative_primary_risk_difference: Literal[True] = True
    require_zero_integrity_or_budget_failures: Literal[True] = True
    runner_static_network_audit_passed: Literal[True] = True
    confirmatory_payloads_downloaded: Literal[False] = False
    confirmatory_results_visible: Literal[False] = False
    result_record_count: Literal[0] = 0
    created_at: datetime
    freeze_hash: Sha256

    @field_validator("created_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("development freeze time must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _validate_freeze(self) -> DevelopmentSearchFreeze:
        self.portfolio.verify_integrity()
        self.portfolio_assessment.verify_integrity()
        self.initialization.verify_integrity()
        if self.label_preparation_audit.confirmatory_payloads_downloaded:
            raise ValueError("development freeze includes confirmatory labels")
        for candidate in self.candidates:
            candidate.verify_integrity()
        if self.portfolio_assessment.portfolio_hash != self.portfolio.portfolio_hash:
            raise ValueError("portfolio assessment does not bind the portfolio")
        candidate_ids = [item.candidate_id for item in self.candidates]
        if candidate_ids != self.initialization.ordered_candidate_ids:
            raise ValueError("candidate order does not match model initialization")
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("development freeze candidate IDs are duplicated")
        input_ids = [item.unit_id for item in self.inputs]
        if input_ids != sorted(input_ids) or len(input_ids) != len(set(input_ids)):
            raise ValueError("development inputs must be unique and unit-sorted")
        policy_ids = [item.policy_id for item in self.policies]
        if policy_ids != sorted(policy_ids) or len(policy_ids) != len(set(policy_ids)):
            raise ValueError("development policies must be unique and ID-sorted")
        assignment_ids = [item.assignment_id for item in self.assignments]
        if len(assignment_ids) != len(set(assignment_ids)):
            raise ValueError("development assignment IDs are duplicated")
        if [item.sequence_index for item in self.assignments] != list(
            range(len(self.assignments))
        ):
            raise ValueError("development assignments must have contiguous sequence")
        if {item.unit_id for item in self.assignments} != set(input_ids):
            raise ValueError("development assignment/input units differ")
        if not {item.policy_id for item in self.assignments}.issubset(policy_ids):
            raise ValueError("development assignment references unknown policy")
        expected_count = len(self.inputs) * 3 * len(self.policies)
        if len(self.assignments) != expected_count:
            raise ValueError("development matrix is not complete")
        if self.freeze_hash != self.calculated_hash():
            raise PortfolioIntegrityError("development freeze_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> DevelopmentSearchFreeze:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "development-search-freeze-v2",
                "runner_static_network_audit_passed": True,
                "confirmatory_payloads_downloaded": False,
                "confirmatory_results_visible": False,
                "result_record_count": 0,
            }
        )
        return cls.model_validate(_with_canonical_hash(cls, payload, "freeze_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"freeze_hash"}))

    def verify_integrity(self) -> None:
        if self.freeze_hash != self.calculated_hash():
            raise PortfolioIntegrityError("development freeze_hash mismatch")
        self.portfolio.verify_integrity()
        self.portfolio_assessment.verify_integrity()
        self.initialization.verify_integrity()
        for candidate in self.candidates:
            candidate.verify_integrity()


def frozen_candidate_catalogue() -> list[CandidateSpec]:
    """Return twelve safe declarative branches before any model ordering."""

    shared_sources = [
        "search-policy.ai-scientist",
        "search-policy.flaml",
        "search-policy.ml-agent-search",
    ]
    rows: list[dict[str, Any]] = [
        {
            "candidate_id": "null-prior",
            "mechanism_family": "null-control",
            "arm_kind": PortfolioArmKind.NULL_OR_RULE,
            "learner": CandidateLearner.DUMMY,
            "preprocessing": CandidatePreprocessing.NONE,
            "hyperparameters": {},
            "hypothesis": "A prior or mean predictor measures whether search adds objective value.",
            "exact_delta": "Replace the learner with the frozen null predictor.",
        },
        {
            "candidate_id": "linear-raw",
            "mechanism_family": "linear-margin",
            "arm_kind": PortfolioArmKind.MECHANISM,
            "learner": CandidateLearner.LINEAR,
            "preprocessing": CandidatePreprocessing.IMPUTE,
            "hyperparameters": {"C": 1.0},
            "hypothesis": "A regularized linear model may dominate on low-dimensional tasks.",
            "exact_delta": "Change one learner family to linear with one regularization value.",
        },
        {
            "candidate_id": "linear-scaled",
            "mechanism_family": "linear-margin",
            "arm_kind": PortfolioArmKind.MECHANISM,
            "learner": CandidateLearner.LINEAR,
            "preprocessing": CandidatePreprocessing.STANDARDIZE,
            "hyperparameters": {"C": 0.5},
            "hypothesis": "Scaling may improve a regularized linear decision surface.",
            "exact_delta": "Change one preprocessing decision and one regularization value.",
        },
        {
            "candidate_id": "lgbm-shallow",
            "mechanism_family": "leafwise-boosting",
            "arm_kind": PortfolioArmKind.MECHANISM,
            "learner": CandidateLearner.LGBM,
            "preprocessing": CandidatePreprocessing.IMPUTE,
            "hyperparameters": {"n_estimators": 40, "num_leaves": 15},
            "hypothesis": "Small leaf-wise trees trade capacity for stable low-fidelity ranking.",
            "exact_delta": "Use leaf-wise boosting with 40 estimators and 15 leaves.",
        },
        {
            "candidate_id": "lgbm-wide",
            "mechanism_family": "leafwise-boosting",
            "arm_kind": PortfolioArmKind.MECHANISM,
            "learner": CandidateLearner.LGBM,
            "preprocessing": CandidatePreprocessing.IMPUTE,
            "hyperparameters": {"n_estimators": 64, "num_leaves": 31},
            "hypothesis": "Moderate leaf-wise capacity may recover nonlinear interactions.",
            "exact_delta": "Use leaf-wise boosting with 64 estimators and 31 leaves.",
        },
        {
            "candidate_id": "xgb-shallow",
            "mechanism_family": "levelwise-boosting",
            "arm_kind": PortfolioArmKind.MECHANISM,
            "learner": CandidateLearner.XGBOOST,
            "preprocessing": CandidatePreprocessing.IMPUTE,
            "hyperparameters": {"max_depth": 3, "n_estimators": 40},
            "hypothesis": "Shallow level-wise boosting may generalize under small budgets.",
            "exact_delta": "Use level-wise boosting with depth 3 and 40 estimators.",
        },
        {
            "candidate_id": "xgb-deep",
            "mechanism_family": "levelwise-boosting",
            "arm_kind": PortfolioArmKind.MECHANISM,
            "learner": CandidateLearner.XGBOOST,
            "preprocessing": CandidatePreprocessing.IMPUTE,
            "hyperparameters": {"max_depth": 5, "n_estimators": 64},
            "hypothesis": "Moderate depth may capture interactions missed by shallow boosting.",
            "exact_delta": "Use level-wise boosting with depth 5 and 64 estimators.",
        },
        {
            "candidate_id": "random-forest",
            "mechanism_family": "bagging",
            "arm_kind": PortfolioArmKind.MECHANISM,
            "learner": CandidateLearner.RF,
            "preprocessing": CandidatePreprocessing.IMPUTE,
            "hyperparameters": {"max_depth": 14, "n_estimators": 48},
            "hypothesis": "Bagging may be robust when boosting fidelity rankings are unstable.",
            "exact_delta": "Change learner family and set two bounded learner hyperparameters.",
        },
        {
            "candidate_id": "extra-trees",
            "mechanism_family": "randomized-trees",
            "arm_kind": PortfolioArmKind.MECHANISM,
            "learner": CandidateLearner.EXTRA_TREE,
            "preprocessing": CandidatePreprocessing.IMPUTE,
            "hyperparameters": {"max_depth": 16, "n_estimators": 48},
            "hypothesis": "More randomized trees may improve variance control cheaply.",
            "exact_delta": "Change learner family and set two bounded learner hyperparameters.",
        },
        {
            "candidate_id": "hist-gradient",
            "mechanism_family": "histogram-boosting",
            "arm_kind": PortfolioArmKind.MECHANISM,
            "learner": CandidateLearner.HIST_GB,
            "preprocessing": CandidatePreprocessing.IMPUTE,
            "hyperparameters": {"max_iter": 64, "max_leaf_nodes": 31},
            "hypothesis": "Histogram boosting may provide a strong dependency-light branch.",
            "exact_delta": "Change learner family and set two bounded learner hyperparameters.",
        },
        {
            "candidate_id": "tree-ensemble",
            "mechanism_family": "heterogeneous-ensemble",
            "arm_kind": PortfolioArmKind.MECHANISM,
            "learner": CandidateLearner.LGBM_XGBOOST_ENSEMBLE,
            "preprocessing": CandidatePreprocessing.IMPUTE,
            "hyperparameters": {"max_depth": 4, "n_estimators": 40},
            "hypothesis": "A two-member ensemble may reduce learner-specific errors.",
            "exact_delta": "Add one bounded ensemble member with two shared hyperparameters.",
        },
        {
            "candidate_id": "invalid-schema-probe",
            "mechanism_family": "validity-control",
            "arm_kind": PortfolioArmKind.NULL_OR_RULE,
            "learner": CandidateLearner.INVALID_PROBE,
            "preprocessing": CandidatePreprocessing.NONE,
            "hyperparameters": {},
            "hypothesis": "An intentional invalid branch tests reviewer and failure retention.",
            "exact_delta": "Inject one known-invalid learner token as a negative control.",
            "intentional_failure_control": True,
        },
    ]
    return [
        CandidateSpec.create(
            **{
                **row,
                "source_ids": shared_sources,
                "intentional_failure_control": row.get(
                    "intentional_failure_control",
                    False,
                ),
            }
        )
        for row in rows
    ]


def _research_sources(
    preregistration: CausalSearchPreregistration,
) -> list[ResearchSource]:
    snapshots = preregistration.design_source_snapshot_hashes
    rows = [
        {
            "source_id": "search-policy.ai-scientist",
            "title": "Towards end-to-end automation of AI research",
            "year": 2026,
            "locator": "Nature 651, 8107; doi:10.1038/s41586-026-10265-5",
            "source_url": "https://www.nature.com/articles/s41586-026-10265-5",
            "maturity": SourceMaturity.PEER_REVIEWED,
            "source_fingerprint": snapshots["ai-scientist-nature"],
        },
        {
            "source_id": "search-policy.flaml",
            "title": "FLAML: A Fast and Lightweight AutoML Library",
            "year": 2021,
            "locator": "MLSys 2021",
            "source_url": "https://proceedings.mlsys.org/paper/2021/hash/1ccc3bfa05cb37b917068778f3c4523a-Abstract.html",
            "maturity": SourceMaturity.PEER_REVIEWED,
            "source_fingerprint": snapshots["flaml"],
        },
        {
            "source_id": "search-policy.mars",
            "title": "MARS: Modular Agent with Reflective Search for Automated AI Research",
            "year": 2026,
            "locator": "arXiv:2602.02660",
            "source_url": "https://arxiv.org/abs/2602.02660",
            "maturity": SourceMaturity.PREPRINT,
            "source_fingerprint": snapshots["mars"],
        },
        {
            "source_id": "search-policy.ml-agent-search",
            "title": "AI Research Agents for Machine Learning: Search, Exploration, and Generalization in MLE-bench",
            "year": 2025,
            "locator": "arXiv:2507.02554",
            "source_url": "https://arxiv.org/abs/2507.02554",
            "maturity": SourceMaturity.PREPRINT,
            "source_fingerprint": snapshots["ml-agent-search"],
        },
        {
            "source_id": "search-policy.mle-bench",
            "title": "MLE-bench: Evaluating Machine Learning Agents on Machine Learning Engineering",
            "year": 2024,
            "locator": "arXiv:2410.07095",
            "source_url": "https://arxiv.org/abs/2410.07095",
            "maturity": SourceMaturity.PREPRINT,
            "source_fingerprint": snapshots["ml-resource-benchmark"],
        },
        {
            "source_id": "search-policy.mlrc-bench",
            "title": "MLRC-Bench: Can Language Agents Solve Machine Learning Research Challenges?",
            "year": 2025,
            "locator": "arXiv:2504.09702",
            "source_url": "https://arxiv.org/abs/2504.09702",
            "maturity": SourceMaturity.PREPRINT,
            "source_fingerprint": snapshots["mlrc-bench"],
        },
        {
            "source_id": "search-policy.paperbench",
            "title": "PaperBench: Evaluating AI's Ability to Replicate AI Research",
            "year": 2025,
            "locator": "PMLR 267:56843-56873",
            "source_url": "https://proceedings.mlr.press/v267/starace25a.html",
            "maturity": SourceMaturity.PEER_REVIEWED,
            "source_fingerprint": snapshots["paperbench"],
        },
    ]
    return [ResearchSource.model_validate({**row, "verified": True}) for row in rows]


def _nearest_work_rows() -> list[NearestWorkDelta]:
    rows = [
        {
            "source_id": "search-policy.ai-scientist",
            "shared_scope": "End-to-end idea, code, experiment, and paper automation.",
            "claimed_delta": "Causally isolates allocation topology and comparative memory under matched candidate quality and caps.",
            "overlap_risk": "Both systems perform iterative machine-learning research.",
            "decisive_comparison": "Execute frozen policy arms on identical independent tasks with complete trajectories.",
        },
        {
            "source_id": "search-policy.mars",
            "shared_scope": "Modular reflective search for automated AI research.",
            "claimed_delta": "Separates reflection and memory claims from objective task success through one-at-a-time ablations.",
            "overlap_risk": "Both use reflection-like state across experimental branches.",
            "decisive_comparison": "Keep proposals and budgets fixed while disabling one component at a time.",
        },
        {
            "source_id": "search-policy.ml-agent-search",
            "shared_scope": "Search, exploration, and generalization by ML research agents.",
            "claimed_delta": "Measures task-level causal effects and low-to-high-fidelity calibration instead of leaderboard score alone.",
            "overlap_risk": "Both study search strategy on ML tasks.",
            "decisive_comparison": "Use paired task outcomes, seed repeats, exact replay, and a sealed confirmation split.",
        },
        {
            "source_id": "search-policy.mle-bench",
            "shared_scope": "Objective execution-grounded evaluation of ML engineering agents.",
            "claimed_delta": "Treats the research policy rather than the base model as the controlled intervention.",
            "overlap_risk": "Both use bounded tabular ML task execution.",
            "decisive_comparison": "Share the candidate catalogue and evaluator while changing only the allocation policy.",
        },
        {
            "source_id": "search-policy.mlrc-bench",
            "shared_scope": "Machine-learning research challenges for language agents.",
            "claimed_delta": "Retains every failed branch and permits a valid zero-survivor outcome.",
            "overlap_risk": "Both diagnose limitations of agents on research tasks.",
            "decisive_comparison": "Audit complete failures, costs, lineage, and non-significant outcomes.",
        },
        {
            "source_id": "search-policy.paperbench",
            "shared_scope": "Reproducible research execution and objective artifact grading.",
            "claimed_delta": "Uses deterministic native metrics and prediction replay rather than an LLM reviewer as the scientific gate.",
            "overlap_risk": "Both evaluate end-to-end research artifacts.",
            "decisive_comparison": "Bind every result to executable artifacts and keep reviewer judgments non-scientific.",
        },
    ]
    return [NearestWorkDelta.model_validate(row) for row in rows]


def _build_opportunity(
    report: BaselineReproductionReport,
    preregistration: CausalSearchPreregistration,
    *,
    baseline_manifest_hash: str,
) -> tuple[ResearchOpportunity, OpportunityAssessment]:
    sources = _research_sources(preregistration)
    certificate = ResearchQuestionCertificate.create(
        certificate_id="task-263.5-search-policy-causality",
        literature_cutoff=date(2026, 7, 30),
        question=(
            "At matched candidate, model-call, and compute caps on the frozen "
            "open tabular panel, does portfolio allocation with comparative "
            "cross-branch memory change objective task success relative to a "
            "linear self-loop?"
        ),
        primitives=[
            "One OpenML task is the independent scientific unit.",
            "The four arms share a result-blind candidate catalogue and objective evaluator.",
            "Three seeds are within-task repeats and never independent units.",
            "Development and one-use confirmatory task IDs remain disjoint.",
        ],
        assumptions=[
            "The bounded structured learner grammar represents the intervention scope.",
            "Development task outcomes do not enter the frozen confirmatory schedule.",
        ],
        mechanism_model=(
            "Diverse branches reduce premature commitment, successive halving "
            "limits wasted execution, and comparative fidelity memory corrects "
            "systematic proxy error without using reviewer preference."
        ),
        nearest_work_tension=(
            "Autonomous-research systems report integrated performance while "
            "execution benchmarks document low reliability; the frozen nearest "
            "work does not provide this budget-matched component-level causal design."
        ),
        main_claim=preregistration.claim_scope,
        falsifier=(
            "The paired one-use confirmatory task interval fails to support the "
            "frozen effect, any arm exceeds its cap, or replay/evaluator integrity fails."
        ),
        failure_update=(
            "Reject the scoped policy advantage, retain the complete branch and "
            "failure matrix, and do not retune on confirmatory tasks."
        ),
        minimal_decisive_test=(
            "Run all four matched policy arms and five one-at-a-time ablations "
            "through F0-F3 development, then use one sealed confirmatory reveal."
        ),
        primary_metric=PrimaryMetricSpec(
            metric_id=DEVELOPMENT_METRIC_ID,
            name="Paired objective task margin",
            direction=MetricDirection.MAXIMIZE,
            unit="multiples of the frozen task-specific minimum gain",
            meaningful_effect_threshold=1.0,
            evaluator_description=(
                "(policy score - paired FLAML score) / frozen minimum gain; "
                "objective task success is margin >= 1 with all validity gates passing."
            ),
            deterministic_evaluator=True,
            llm_judge_is_gate=False,
        ),
        strong_baseline_ids=[report.specification.baseline_id],
        null_or_control_ids=["null-prior", "invalid-schema-probe"],
        required_ablation_ids=[
            f"ablation-{item.value}" for item in StudyAblation
        ],
        source_ids=[item.source_id for item in sources],
        power_plan=ProspectivePowerPlan(
            analysis_unit="independent OpenML task",
            confirmatory_independent_unit_count=len(
                preregistration.confirmatory_unit_ids
            ),
            within_unit_repeat_count=len(preregistration.within_unit_seeds),
            target_power=preregistration.target_power,
            alpha=preregistration.alpha,
            minimum_detectable_effect=preregistration.minimum_effect,
            uncertainty_method=(
                "two-sided exact McNemar test with task-level paired effects and "
                "a prespecified exact paired risk-difference interval"
            ),
            bootstrap_resamples=20_000,
            heterogeneity_plan=(
                "Report every task, benchmark/domain strata, seed dispersion, "
                "and all arm-attributable failures."
            ),
            analysis_artifact_hash=preregistration.preregistration_hash,
            calculation_verified=True,
            prospective=True,
            seed_repeats_are_independent_units=False,
        ),
        data_split=ResearchDataSplit(
            development_unit_ids=preregistration.development_unit_ids,
            confirmatory_unit_ids=preregistration.confirmatory_unit_ids,
            confirmatory_access_policy=(
                "Task 263.5 may read only the seven prepared development bundles. "
                "Confirmatory payloads remain absent until the one-use Task 263.6 runner."
            ),
            confirmatory_reveal_count=1,
        ),
        budget=ResearchBudget(
            max_cost_usd=500.0,
            max_walltime_minutes=7_200,
            max_model_tokens=4_000_000,
            max_trials=2_000,
        ),
        publication_endpoint=PublicationEndpoint.SYSTEM_CONTRIBUTION,
        endpoint_rationale=(
            "The publishable contribution is a causal and reproducible system-policy "
            "evaluation, including a valid diagnostic-negative endpoint."
        ),
    )
    baseline_plan = BaselineReproductionPlan.create(
        baseline_id=report.specification.baseline_id,
        source_ids=["search-policy.flaml"],
        expected_metric_id=DEVELOPMENT_METRIC_ID,
        reproduction_tolerance=report.specification.replay_tolerance,
        exact_command_hash=report.task_replays[0].command_template_hash,
        environment_hash=report.environment.environment_hash,
    )
    reproduction = BaselineReproductionEvidence.create(
        plan_hash=baseline_plan.plan_hash,
        baseline_id=report.specification.baseline_id,
        metric_id=DEVELOPMENT_METRIC_ID,
        observed_value=0.0,
        within_tolerance=all(item.passed for item in report.task_replays),
        artifact_hashes=[
            baseline_manifest_hash,
            report.environment.environment_hash,
            report.report_hash,
            report.specification.runner_source_hash,
        ],
        reproduction_passed=all(item.passed for item in report.task_replays),
    )
    opportunity = ResearchOpportunity.create(
        opportunity_id="task-263.5-openml-search-policy-opportunity",
        certificate=certificate,
        sources=sources,
        nearest_work=_nearest_work_rows(),
        objective_evaluator_hash=report.specification.evaluator_source_hash,
        baseline_plan=baseline_plan,
        baseline_smoke_passed=True,
        baseline_reproduction=reproduction,
        data_available=True,
        license_clear=True,
        compute_feasible=True,
        source_snapshot_complete=True,
    )
    assessment = assess_research_opportunity(
        opportunity,
        stage=OpportunityStage.NOVELTY_SEARCH,
    )
    if not assessment.admitted:
        raise PortfolioIntegrityError(
            "Task 263.5 research opportunity did not pass novelty-search gates"
        )
    return opportunity, assessment


def _candidate_initialization_schema(
    candidate_ids: Sequence[str],
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "ordered_candidate_ids": {
                "type": "array",
                "minItems": len(candidate_ids),
                "maxItems": len(candidate_ids),
                "uniqueItems": True,
                "items": {"type": "string", "enum": list(candidate_ids)},
            },
            "portfolio_rationale": {"type": "string", "minLength": 20},
        },
        "required": ["ordered_candidate_ids", "portfolio_rationale"],
        "additionalProperties": False,
    }


def initialize_candidate_catalogue(
    candidates: Sequence[CandidateSpec],
    preregistration: CausalSearchPreregistration,
    *,
    config_path: Path | str,
    env_path: Path | str,
    completion: JsonCompletion = run_llm_json_completion,
    created_at: datetime | None = None,
) -> CandidateInitialization:
    """Ask one configured model to order, but not rewrite, the safe catalogue."""

    candidate_rows = [
        {
            "candidate_id": item.candidate_id,
            "mechanism_family": item.mechanism_family,
            "learner": item.learner.value,
            "preprocessing": item.preprocessing.value,
            "hyperparameters": item.hyperparameters,
            "intentional_failure_control": item.intentional_failure_control,
        }
        for item in candidates
    ]
    catalog_hash = canonical_sha256(candidate_rows)
    messages = [
        {
            "role": "system",
            "content": (
                "You are initializing a result-blind, budget-matched research-policy "
                "experiment. Return only the requested JSON. You may only permute the "
                "provided candidate IDs. Do not invent code, scores, task names, URLs, "
                "or benchmark outcomes. Preserve mechanism diversity and both controls."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "claim_scope": preregistration.claim_scope,
                    "operator_grammar": preregistration.operator_grammar,
                    "candidate_catalogue": candidate_rows,
                    "instruction": (
                        "Return a complete permutation of all 12 IDs and a short "
                        "result-blind rationale for the ordering."
                    ),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        },
    ]
    response = completion(
        messages=messages,
        config_path=config_path,
        env_path=env_path,
        timeout_seconds=180,
        max_tokens=768,
        temperature=0.0,
        reasoning_effort="none",
        response_schema=_candidate_initialization_schema(
            [item.candidate_id for item in candidates]
        ),
        response_schema_name="task2635_candidate_initialization",
    )
    ordered = response.parsed_json.get("ordered_candidate_ids")
    rationale = response.parsed_json.get("portfolio_rationale")
    if not isinstance(ordered, list) or not all(
        isinstance(item, str) for item in ordered
    ):
        raise ValueError("model candidate order is not a string array")
    expected = {item.candidate_id for item in candidates}
    if len(ordered) != len(expected) or set(ordered) != expected:
        raise ValueError("model candidate order is not an exact catalogue permutation")
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError("model candidate initialization rationale is missing")
    return CandidateInitialization.create(
        interaction_id="task-263.5-candidate-initialization",
        candidate_catalog_hash=catalog_hash,
        preregistration_hash=preregistration.preregistration_hash,
        messages=messages,
        response=response,
        ordered_candidate_ids=ordered,
        portfolio_rationale=rationale.strip(),
        created_at=created_at or datetime.now(timezone.utc),
    )


def _build_portfolio(
    opportunity: ResearchOpportunity,
    opportunity_assessment: OpportunityAssessment,
    candidates: Sequence[CandidateSpec],
    initialization: CandidateInitialization,
) -> tuple[PortfolioSpec, PortfolioAssessment]:
    by_id = {item.candidate_id: item for item in candidates}
    ordered = [by_id[item] for item in initialization.ordered_candidate_ids]
    branches = [
        PortfolioBranch(
            branch_id=item.candidate_id,
            mechanism_family=item.mechanism_family,
            arm_kind=item.arm_kind,
            hypothesis=item.hypothesis,
            exact_delta=item.exact_delta,
            source_ids=item.source_ids,
            generation_evidence_hash=canonical_sha256(
                {
                    "candidate_hash": item.candidate_hash,
                    "initialization_hash": initialization.initialization_hash,
                }
            ),
            budget=BranchBudget(
                max_cost_usd=0.5,
                max_walltime_minutes=60,
                max_model_tokens=5_000,
                max_trials=12,
            ),
            parent_branch_id=None,
            sealed_confirmatory_evidence_visible=False,
        )
        for item in ordered
    ]
    portfolio = PortfolioSpec.create(
        portfolio_id="task-263.5-shared-structured-portfolio",
        opportunity=opportunity,
        opportunity_assessment=opportunity_assessment,
        branches=branches,
        fidelity_stages=[
            FidelityStageSpec(
                kind=FidelityKind.F0_STATIC,
                max_survivors=6,
                minimum_independent_units=0,
                budget_fraction=0.05,
                promotion_rule=(
                    "Static schema/reviewer gate plus frozen topology; no scientific "
                    "unit or reviewer score is claimed."
                ),
            ),
            FidelityStageSpec(
                kind=FidelityKind.F1_MINIMAL,
                max_survivors=3,
                minimum_independent_units=1,
                budget_fraction=0.25,
                promotion_rule=(
                    "Promote two objective leaders and one prespecified exploration "
                    "branch when diversity is enabled."
                ),
            ),
            FidelityStageSpec(
                kind=FidelityKind.F2_MULTI_TASK,
                max_survivors=1,
                minimum_independent_units=3,
                budget_fraction=0.30,
                promotion_rule=(
                    "Promote one objective leader using only development fidelity "
                    "evidence and frozen comparative-memory corrections."
                ),
            ),
            FidelityStageSpec(
                kind=FidelityKind.F3_FULL_DEVELOPMENT,
                max_survivors=1,
                minimum_independent_units=len(
                    opportunity.certificate.data_split.development_unit_ids
                ),
                budget_fraction=0.40,
                promotion_rule=(
                    "Run exactly one selected branch at full development fidelity; "
                    "zero survivors remains valid after attributable failure."
                ),
            ),
        ],
        total_budget=ResearchBudget(
            max_cost_usd=10.0,
            max_walltime_minutes=720,
            max_model_tokens=60_000,
            max_trials=144,
        ),
        exploration_quota=1,
        survival_rule=(
            "Bounded successive halving with complete branch retention, objective "
            "metric ranking, one diversity exploration slot, and no favorable-effect stop."
        ),
        selection_metric_id=DEVELOPMENT_METRIC_ID,
    )
    assessment = assess_portfolio(portfolio)
    if not assessment.admitted:
        raise PortfolioIntegrityError("Task 263.5 portfolio failed its hard gates")
    return portfolio, assessment


def frozen_policy_realizations() -> list[PolicyRealization]:
    """Return four arms and five exact one-component ablations."""

    primary = [
        PolicyRealization.create(
            policy_id=StudyArm.ONE_SHOT.value,
            parent_arm=StudyArm.ONE_SHOT,
            topology="flat_batch",
            certificate_enabled=True,
            diversity_enabled=False,
            multi_fidelity_enabled=True,
            reviewer_enabled=True,
            comparative_memory_enabled=False,
        ),
        PolicyRealization.create(
            policy_id=StudyArm.LINEAR_SELF_LOOP.value,
            parent_arm=StudyArm.LINEAR_SELF_LOOP,
            topology="linear_chain",
            certificate_enabled=True,
            diversity_enabled=False,
            multi_fidelity_enabled=True,
            reviewer_enabled=True,
            comparative_memory_enabled=False,
        ),
        PolicyRealization.create(
            policy_id=StudyArm.PORTFOLIO.value,
            parent_arm=StudyArm.PORTFOLIO,
            topology="branching_portfolio",
            certificate_enabled=True,
            diversity_enabled=True,
            multi_fidelity_enabled=True,
            reviewer_enabled=True,
            comparative_memory_enabled=False,
        ),
        PolicyRealization.create(
            policy_id=StudyArm.PORTFOLIO_MEMORY.value,
            parent_arm=StudyArm.PORTFOLIO_MEMORY,
            topology="branching_portfolio",
            certificate_enabled=True,
            diversity_enabled=True,
            multi_fidelity_enabled=True,
            reviewer_enabled=True,
            comparative_memory_enabled=True,
        ),
    ]
    ablations: list[PolicyRealization] = []
    for ablation in StudyAblation:
        flags = {
            "certificate_enabled": True,
            "diversity_enabled": True,
            "multi_fidelity_enabled": True,
            "reviewer_enabled": True,
            "comparative_memory_enabled": True,
        }
        disabled_flag = {
            StudyAblation.CERTIFICATE: "certificate_enabled",
            StudyAblation.DIVERSITY: "diversity_enabled",
            StudyAblation.MULTI_FIDELITY: "multi_fidelity_enabled",
            StudyAblation.REVIEWER: "reviewer_enabled",
            StudyAblation.MEMORY: "comparative_memory_enabled",
        }[ablation]
        flags[disabled_flag] = False
        ablations.append(
            PolicyRealization.create(
                policy_id=f"ablation-{ablation.value}",
                parent_arm=StudyArm.PORTFOLIO_MEMORY,
                ablation=ablation,
                topology="branching_portfolio",
                **flags,
            )
        )
    return sorted([*primary, *ablations], key=lambda item: item.policy_id)


def _build_assignments(
    preregistration: CausalSearchPreregistration,
    policies: Sequence[PolicyRealization],
) -> list[DevelopmentAssignment]:
    known_policy_ids = {item.policy_id for item in policies}
    assignments: list[DevelopmentAssignment] = []
    for row in preregistration.randomization_assignments:
        if row.partition != "development":
            continue
        policy_id = row.arm.value
        if policy_id not in known_policy_ids:
            raise ValueError("preregistered arm is absent from policy realizations")
        assignments.append(
            DevelopmentAssignment.create(
                assignment_id=(
                    f"dev-{row.unit_id}-{row.within_unit_seed}-{policy_id}"
                ),
                sequence_index=len(assignments),
                unit_id=row.unit_id,
                within_unit_seed=row.within_unit_seed,
                policy_id=policy_id,
                schedule_source="task-263.4.2-randomization",
            )
        )
    parent_order = [
        item
        for item in assignments
        if item.policy_id == StudyArm.PORTFOLIO_MEMORY.value
    ]
    for ablation in StudyAblation:
        policy_id = f"ablation-{ablation.value}"
        for parent in parent_order:
            assignments.append(
                DevelopmentAssignment.create(
                    assignment_id=(
                        f"dev-{parent.unit_id}-{parent.within_unit_seed}-{policy_id}"
                    ),
                    sequence_index=len(assignments),
                    unit_id=parent.unit_id,
                    within_unit_seed=parent.within_unit_seed,
                    policy_id=policy_id,
                    schedule_source="matched-ablation-sensitivity",
                )
            )
    return assignments


def _threshold_by_unit(
    preregistration: CausalSearchPreregistration,
) -> dict[str, Any]:
    return {item.unit_id: item for item in preregistration.task_thresholds}


_ATTRIBUTE_PATTERN = re.compile(
    r"""^@attribute\s+(?:'([^']+)'|"([^"]+)"|([^\s]+))\s+(.+)$""",
    flags=re.IGNORECASE,
)


def _decode_arff(content: bytes) -> tuple[list[tuple[str, str]], list[list[str]]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")
    attributes: list[tuple[str, str]] = []
    data_lines: list[str] = []
    in_data = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%"):
            continue
        if not in_data:
            match = _ATTRIBUTE_PATTERN.match(line)
            if match:
                name = next(
                    value
                    for value in match.groups()[:3]
                    if value is not None
                )
                attributes.append((name, match.group(4).strip()))
            if line.casefold() == "@data":
                in_data = True
            continue
        if line.startswith("{"):
            raise ValueError("frozen development panel unexpectedly uses sparse ARFF")
        data_lines.append(line)
    rows = [
        [value.strip() for value in row]
        for row in csv.reader(io.StringIO("\n".join(data_lines)))
        if row
    ]
    if not attributes or not rows:
        raise ValueError("ARFF source is empty")
    if any(len(row) != len(attributes) for row in rows):
        raise ValueError("ARFF row width differs from attribute count")
    return attributes, rows


def _split_test_rows(content: bytes) -> list[int]:
    attributes, rows = _decode_arff(content)
    index = {
        name.casefold(): position
        for position, (name, _) in enumerate(attributes)
    }
    if not {"type", "rowid", "repeat", "fold"}.issubset(index):
        raise ValueError("OpenML split ARFF is missing required fields")
    test: list[int] = []
    train: set[int] = set()
    for row in rows:
        if int(float(row[index["repeat"]])) != 0:
            continue
        if int(float(row[index["fold"]])) != 0:
            continue
        row_id = int(float(row[index["rowid"]]))
        split_type = row[index["type"]].casefold()
        if split_type == "train":
            train.add(row_id)
        elif split_type == "test":
            test.append(row_id)
        else:
            raise ValueError(f"unknown OpenML split type: {split_type}")
    if not train or not test or train & set(test):
        raise ValueError("OpenML repeat/fold split is empty or overlapping")
    return sorted(test)


def _requests_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=6,
        connect=6,
        read=5,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update(
        {
            "User-Agent": "AutoResearch/1.0 task-263.5-development-labels",
            "Connection": "close",
        }
    )
    return session


def _bounded_session_get(
    session: requests.Session,
    url: str,
    *,
    maximum_bytes: int,
    timeout: int,
) -> bytes:
    response = session.get(url, timeout=timeout, stream=True)
    response.raise_for_status()
    content = bytearray()
    try:
        for chunk in response.iter_content(chunk_size=65_536):
            if not chunk:
                continue
            content.extend(chunk)
            if len(content) > maximum_bytes:
                raise ValueError(
                    f"development source exceeded {maximum_bytes} bytes: {url}"
                )
    finally:
        response.close()
    return bytes(content)


def prepare_development_labels(
    panel: OpenObjectiveTaskPanelReport,
    report: BaselineReproductionReport,
    output_dir: Path,
    *,
    fetch: Callable[[str, int, int], bytes] | None = None,
) -> tuple[dict[str, DevelopmentLabels], DevelopmentLabelPreparationAudit]:
    """Recover only development evaluator labels from hash-frozen OpenML bytes."""

    replay_by_unit = {item.unit_id: item for item in report.task_replays}
    development_units = sorted(
        (
            unit
            for unit in panel.task_units
            if unit.unit_id in replay_by_unit
        ),
        key=lambda item: item.unit_id,
    )
    if len(development_units) != len(replay_by_unit):
        raise PortfolioIntegrityError(
            "panel development units differ from baseline replay units"
        )
    confirmatory_urls = {
        url
        for unit in panel.task_units
        if unit.unit_id not in replay_by_unit
        for url in (unit.data_url, unit.split_url)
    }
    development_urls = {
        url
        for unit in development_units
        for url in (unit.data_url, unit.split_url)
    }
    if development_urls & confirmatory_urls:
        raise PortfolioIntegrityError(
            "development and confirmatory resource URLs overlap"
        )

    session: requests.Session | None = None
    fetch_resource: Callable[[str, int, int], bytes]
    if fetch is None:
        session = _requests_session()

        def session_fetch(url: str, maximum_bytes: int, timeout: int) -> bytes:
            assert session is not None
            return _bounded_session_get(
                session,
                url,
                maximum_bytes=maximum_bytes,
                timeout=timeout,
            )

        fetch_resource = session_fetch
    else:
        fetch_resource = fetch

    labels_by_unit: dict[str, DevelopmentLabels] = {}
    label_file_hashes: dict[str, str] = {}
    label_dir = output_dir / "development-labels"
    label_dir.mkdir(parents=True, exist_ok=True)
    try:
        for unit in development_units:
            replay = replay_by_unit[unit.unit_id]
            opaque_id = (
                "opaque-" + hashlib.sha256(unit.unit_id.encode()).hexdigest()[:16]
            )
            label_path = label_dir / f"{opaque_id}.json"
            if label_path.exists():
                labels = DevelopmentLabels.model_validate_json(
                    label_path.read_text(encoding="utf-8")
                )
                if (
                    labels.unit_id != unit.unit_id
                    or labels.data_sha256 != replay.data_sha256
                    or labels.split_sha256 != replay.split_sha256
                ):
                    raise PortfolioIntegrityError(
                        f"cached development labels mismatch: {unit.unit_id}"
                    )
            else:
                data_bytes = fetch_resource(
                    unit.data_url,
                    64 * 1024 * 1024,
                    240,
                )
                split_bytes = fetch_resource(
                    unit.split_url,
                    16 * 1024 * 1024,
                    240,
                )
                data_sha256 = hashlib.sha256(data_bytes).hexdigest()
                split_sha256 = hashlib.sha256(split_bytes).hexdigest()
                if data_sha256 != replay.data_sha256:
                    raise PortfolioIntegrityError(
                        f"development data SHA-256 changed: {unit.unit_id}"
                    )
                if split_sha256 != replay.split_sha256:
                    raise PortfolioIntegrityError(
                        f"development split SHA-256 changed: {unit.unit_id}"
                    )
                if hashlib.md5(data_bytes).hexdigest() != unit.data_md5:
                    raise PortfolioIntegrityError(
                        f"development data MD5 changed: {unit.unit_id}"
                    )
                attributes, rows = _decode_arff(data_bytes)
                attribute_names = [name for name, _ in attributes]
                target_index = next(
                    index
                    for index, name in enumerate(attribute_names)
                    if name.casefold() == unit.target_feature.casefold()
                )
                row_ids = _split_test_rows(split_bytes)
                if not row_ids or max(row_ids) >= len(rows):
                    raise PortfolioIntegrityError(
                        f"development split row is outside data: {unit.unit_id}"
                    )
                if unit.family is ObjectiveTaskFamily.TABULAR_CLASSIFICATION:
                    values: list[str | float] = [
                        str(rows[row_id][target_index]) for row_id in row_ids
                    ]
                else:
                    values = [
                        float(rows[row_id][target_index]) for row_id in row_ids
                    ]
                labels = DevelopmentLabels.create(
                    unit_id=unit.unit_id,
                    opaque_unit_id=opaque_id,
                    family=unit.family.value,
                    row_ids=row_ids,
                    labels=values,
                    data_sha256=data_sha256,
                    split_sha256=split_sha256,
                    source_data_md5=unit.data_md5,
                )
                _write_text_atomic(label_path, labels.canonical_json() + "\n")
            labels_by_unit[unit.unit_id] = labels
            label_file_hashes[unit.unit_id] = _file_sha256(label_path)
    finally:
        if session is not None:
            session.close()
    audit = DevelopmentLabelPreparationAudit.create(
        panel_report_hash=panel.report_hash,
        development_resource_urls=sorted(development_urls),
        label_file_hashes=label_file_hashes,
    )
    return labels_by_unit, audit


def _development_inputs(
    baseline_dir: Path,
    report: BaselineReproductionReport,
    preregistration: CausalSearchPreregistration,
    labels_by_unit: Mapping[str, DevelopmentLabels],
    output_dir: Path,
) -> list[DevelopmentInput]:
    replay_by_unit = {item.unit_id: item for item in report.task_replays}
    threshold_by_unit = _threshold_by_unit(preregistration)
    inputs: list[DevelopmentInput] = []
    for unit_id in sorted(preregistration.development_unit_ids):
        replay = replay_by_unit[unit_id]
        input_dir = baseline_dir / "clean-run-a" / unit_id / "input"
        manifest_path = input_dir / "input-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        threshold = threshold_by_unit.get(unit_id) or FrozenTaskSuccessThreshold.create(
            unit_id=unit_id,
            family=ObjectiveTaskFamily(manifest["family"]),
        )
        train_path = (input_dir / manifest["train_file"]).resolve()
        test_path = (input_dir / manifest["test_file"]).resolve()
        train_hash = _file_sha256(train_path)
        test_hash = _file_sha256(test_path)
        if train_hash != manifest["train_sha256"] or test_hash != manifest["test_sha256"]:
            raise PortfolioIntegrityError(f"development input hash mismatch: {unit_id}")
        with train_path.open("rb") as handle:
            train_row_count = max(0, sum(1 for _ in handle) - 1)
        with test_path.open("rb") as handle:
            test_row_count = max(0, sum(1 for _ in handle) - 1)
        labels = labels_by_unit[unit_id]
        labels_path = (
            output_dir / "development-labels" / f"{labels.opaque_unit_id}.json"
        ).resolve()
        labels_file_hash = _file_sha256(labels_path)
        with test_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            observed_row_ids = [int(row["row_id"]) for row in reader]
        if observed_row_ids != labels.row_ids:
            raise PortfolioIntegrityError(
                f"development labels/test row IDs differ: {unit_id}"
            )
        metric_id: Literal["balanced_accuracy", "r2"] = (
            "balanced_accuracy"
            if manifest["family"] == "tabular_classification"
            else "r2"
        )
        inputs.append(
            DevelopmentInput(
                unit_id=unit_id,
                opaque_unit_id=manifest["unit_id"],
                family=manifest["family"],
                train_path=train_path.as_posix(),
                test_path=test_path.as_posix(),
                labels_path=labels_path.as_posix(),
                train_sha256=train_hash,
                test_sha256=test_hash,
                labels_sha256=labels_file_hash,
                label_hash=labels.label_hash,
                train_row_count=train_row_count,
                test_row_count=test_row_count,
                label_count=len(labels.labels),
                feature_count=len(manifest["feature_columns"]),
                data_sha256=labels.data_sha256,
                split_sha256=labels.split_sha256,
                baseline_score=replay.run_a_score,
                metric_id=metric_id,
                minimum_gain=threshold.minimum_gain,
                threshold_hash=threshold.threshold_hash,
            )
        )
    return inputs


def audit_frozen_runner_source(path: Path) -> bool:
    """Reject network-capable or dynamically evaluated runner source."""

    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=path.as_posix())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots = {alias.name.split(".", 1)[0] for alias in node.names}
            if roots & FORBIDDEN_RUNNER_IMPORT_ROOTS:
                return False
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".", 1)[0]
            if root in FORBIDDEN_RUNNER_IMPORT_ROOTS:
                return False
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in {"eval", "exec", "__import__"}:
                return False
    return True


def _load_repair_predecessor(
    predecessor_dir: Path,
    *,
    baseline_report_hash: str,
    preregistration_hash: str,
    catalogue: Sequence[CandidateSpec],
) -> tuple[CandidateInitialization, DevelopmentRepairLineage]:
    """Reuse the prospective ordering after an evaluator-only diagnostic repair."""

    freeze_path = predecessor_dir / DEVELOPMENT_FREEZE_FILENAME
    report_path = predecessor_dir / DEVELOPMENT_REPORT_FILENAME
    if not freeze_path.exists() or not report_path.exists():
        raise FileNotFoundError("repair predecessor freeze/report is missing")

    freeze_payload = json.loads(freeze_path.read_text(encoding="utf-8"))
    if not isinstance(freeze_payload, dict):
        raise PortfolioIntegrityError("repair predecessor freeze is not an object")
    predecessor_freeze_hash = freeze_payload.get("freeze_hash")
    freeze_body = dict(freeze_payload)
    freeze_body.pop("freeze_hash", None)
    if (
        not isinstance(predecessor_freeze_hash, str)
        or canonical_sha256(freeze_body) != predecessor_freeze_hash
    ):
        raise PortfolioIntegrityError("repair predecessor freeze hash mismatch")
    if freeze_payload.get("baseline_report_hash") != baseline_report_hash:
        raise PortfolioIntegrityError("repair predecessor baseline mismatch")
    if freeze_payload.get("preregistration_hash") != preregistration_hash:
        raise PortfolioIntegrityError("repair predecessor preregistration mismatch")
    if (
        freeze_payload.get("confirmatory_payloads_downloaded") is not False
        or freeze_payload.get("confirmatory_results_visible") is not False
    ):
        raise PortfolioIntegrityError("repair predecessor crossed the confirmation seal")

    initialization = CandidateInitialization.model_validate(
        freeze_payload.get("initialization")
    )
    initialization.verify_integrity()
    current_candidates = {
        item.candidate_id: item.candidate_hash for item in catalogue
    }
    predecessor_candidates = {
        str(item["candidate_id"]): str(item["candidate_hash"])
        for item in freeze_payload.get("candidates", [])
        if isinstance(item, dict)
    }
    if predecessor_candidates != current_candidates:
        raise PortfolioIntegrityError("repair predecessor candidate catalogue changed")
    if set(initialization.ordered_candidate_ids) != set(current_candidates):
        raise PortfolioIntegrityError("repair predecessor candidate order is incomplete")

    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(report_payload, dict):
        raise PortfolioIntegrityError("repair predecessor report is not an object")
    predecessor_report_hash = report_payload.get("report_hash")
    report_body = dict(report_payload)
    report_body.pop("report_hash", None)
    if (
        not isinstance(predecessor_report_hash, str)
        or canonical_sha256(report_body) != predecessor_report_hash
    ):
        raise PortfolioIntegrityError("repair predecessor report hash mismatch")
    if report_payload.get("freeze_hash") != predecessor_freeze_hash:
        raise PortfolioIntegrityError("repair predecessor report/freeze mismatch")
    if (
        report_payload.get("status") != "negative_development"
        or report_payload.get("full_matrix_complete") is not True
        or report_payload.get("exact_resume_verified") is not True
    ):
        raise PortfolioIntegrityError(
            "repair predecessor is not a complete diagnostic matrix"
        )
    if (
        report_payload.get("confirmatory_payloads_downloaded") is not False
        or report_payload.get("confirmatory_results_visible") is not False
    ):
        raise PortfolioIntegrityError("repair predecessor report used confirmation")

    marker = "Cannot use median strategy with non-numeric data"
    failure_evidence: list[dict[str, Any]] = []
    for evaluation_path in sorted(
        (predecessor_dir / "evaluation-cache").glob("*/evaluation.json")
    ):
        evaluation = _load_cached_evaluation(evaluation_path)
        if evaluation.failure_code != "runner_nonzero_exit":
            continue
        stderr_path = evaluation_path.with_name("runner.stderr.log")
        if not stderr_path.exists():
            continue
        stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace")
        if marker not in stderr_text:
            continue
        if (
            evaluation.stderr_sha256 is None
            or _file_sha256(stderr_path) != evaluation.stderr_sha256
        ):
            raise PortfolioIntegrityError(
                "repair predecessor stderr hash mismatch"
            )
        failure_evidence.append(
            {
                "candidate_id": evaluation.candidate_id,
                "evaluation_hash": evaluation.evaluation_hash,
                "mechanism_family": evaluation.mechanism_family,
                "stage": evaluation.stage,
                "stderr_sha256": evaluation.stderr_sha256,
                "unit_id": evaluation.unit_id,
                "within_unit_seed": evaluation.within_unit_seed,
            }
        )
    if len({item["mechanism_family"] for item in failure_evidence}) < 3:
        raise PortfolioIntegrityError(
            "repair predecessor lacks evaluator-wide mixed-type failure evidence"
        )
    if len({item["within_unit_seed"] for item in failure_evidence}) < 3:
        raise PortfolioIntegrityError(
            "repair predecessor mixed-type failure lacks all repeated seeds"
        )

    lineage = DevelopmentRepairLineage.create(
        predecessor_freeze_hash=predecessor_freeze_hash,
        predecessor_report_hash=predecessor_report_hash,
        failure_evidence_hash=canonical_sha256(failure_evidence),
        repair_reason=(
            "The complete predecessor matrix exposed an evaluator-only compatibility "
            "defect: non-numeric OpenML features reached a numeric median imputer and "
            "caused otherwise valid mechanisms to fail. The repair adds frozen "
            "mixed-type imputation and one-hot encoding while reusing the exact "
            "prospective candidate order; candidates, policies, budgets, thresholds, "
            "randomization, survival gates, and the sealed confirmation panel do not "
            "change."
        ),
    )
    return initialization, lineage


def freeze_development_search(
    baseline_dir: Path,
    output_dir: Path,
    *,
    panel_path: Path = Path(
        "runs/manual-live/task26341-open-objective-panel-v1/"
        "open-objective-task-panel.json"
    ),
    config_path: Path | str = Path("configs/campaign/ollama-qwen35-9b.yaml"),
    env_path: Path | str = Path(".env"),
    completion: JsonCompletion = run_llm_json_completion,
    label_fetch: Callable[[str, int, int], bytes] | None = None,
    predecessor_dir: Path | None = None,
    created_at: datetime | None = None,
) -> DevelopmentSearchFreeze:
    """Create or exactly resume the result-free Task 263.5 execution freeze."""

    freeze_path = output_dir / DEVELOPMENT_FREEZE_FILENAME
    if freeze_path.exists():
        freeze = DevelopmentSearchFreeze.model_validate_json(
            freeze_path.read_text(encoding="utf-8")
        )
        freeze.verify_integrity()
        _verify_freeze_local_files(freeze)
        return freeze

    report, preregistration, baseline_manifest = load_baseline_preregistration(
        baseline_dir
    )
    if preregistration.status is not BaselineGateStatus.READY_FOR_DEVELOPMENT_SEARCH:
        raise ValueError("Task 263.5 requires ready_for_development_search")
    if preregistration.development_search_started:
        raise ValueError("source preregistration already records development search")
    if preregistration.result_record_count != 0:
        raise ValueError("source preregistration is not result-free")
    if (
        preregistration.confirmatory_payloads_downloaded
        or preregistration.confirmatory_results_sealed is not True
    ):
        raise ValueError("confirmatory boundary is not sealed")

    panel = load_open_objective_task_panel(panel_path)
    if panel.report_hash != preregistration.panel_report_hash:
        raise PortfolioIntegrityError("development panel/preregistration hash mismatch")
    catalogue = frozen_candidate_catalogue()
    if predecessor_dir is None:
        initialization = initialize_candidate_catalogue(
            catalogue,
            preregistration,
            config_path=config_path,
            env_path=env_path,
            completion=completion,
            created_at=created_at,
        )
        repair_lineage = None
    else:
        initialization, repair_lineage = _load_repair_predecessor(
            predecessor_dir,
            baseline_report_hash=report.report_hash,
            preregistration_hash=preregistration.preregistration_hash,
            catalogue=catalogue,
        )
    by_id = {item.candidate_id: item for item in catalogue}
    ordered_candidates = [
        by_id[candidate_id]
        for candidate_id in initialization.ordered_candidate_ids
    ]
    opportunity, opportunity_assessment = _build_opportunity(
        report,
        preregistration,
        baseline_manifest_hash=baseline_manifest.manifest_hash,
    )
    portfolio, portfolio_assessment = _build_portfolio(
        opportunity,
        opportunity_assessment,
        ordered_candidates,
        initialization,
    )
    policies = frozen_policy_realizations()
    assignments = _build_assignments(preregistration, policies)
    labels_by_unit, label_audit = prepare_development_labels(
        panel,
        report,
        output_dir,
        fetch=label_fetch,
    )
    inputs = _development_inputs(
        baseline_dir,
        report,
        preregistration,
        labels_by_unit,
        output_dir,
    )
    runner_path = RUNNER_SOURCE_PATH.resolve()
    runner_dependency_path = RUNNER_DEPENDENCY_SOURCE_PATH.resolve()
    if not audit_frozen_runner_source(
        runner_path
    ) or not audit_frozen_runner_source(runner_dependency_path):
        raise PortfolioIntegrityError("frozen candidate runner failed network audit")
    interpreter = (
        baseline_dir / "clean-venv-a" / "Scripts" / "python.exe"
    ).resolve()
    if not interpreter.exists():
        raise FileNotFoundError(f"clean interpreter is missing: {interpreter}")
    budget = DevelopmentBudgetRealization.create(
        preregistered_budget_hash=preregistration.budget.budget_hash,
        maximum_total_model_tokens_per_assignment=(
            preregistration.budget.maximum_total_model_tokens
        ),
        maximum_cpu_seconds_per_assignment=(
            preregistration.budget.maximum_cpu_seconds_per_task_seed
        ),
        maximum_memory_mb=preregistration.budget.maximum_memory_mb,
        scientific_interpretation=(
            "The single global local-model call orders a fixed safe catalogue before "
            "outcomes. Every assignment receives 12 logical proposal slots and zero "
            "additional model calls; unused preregistered calls and tokens are not "
            "reallocated. The causal estimand is structured allocation topology and "
            "comparative fidelity memory, not base-model proposal quality."
        ),
    )
    freeze = DevelopmentSearchFreeze.create(
        freeze_id="task-263.5-development-search-freeze",
        baseline_report_hash=report.report_hash,
        preregistration_hash=preregistration.preregistration_hash,
        preregistration_randomization_hash=(
            preregistration.randomization_schedule_hash
        ),
        portfolio=portfolio,
        portfolio_assessment=portfolio_assessment,
        candidates=ordered_candidates,
        initialization=initialization,
        inputs=inputs,
        label_preparation_audit=label_audit,
        policies=policies,
        assignments=assignments,
        budget_realization=budget,
        controller_source_path=Path(__file__).resolve().as_posix(),
        controller_source_hash=_file_sha256(Path(__file__).resolve()),
        runner_source_path=runner_path.as_posix(),
        runner_source_hash=_file_sha256(runner_path),
        runner_dependency_source_path=runner_dependency_path.as_posix(),
        runner_dependency_source_hash=_file_sha256(runner_dependency_path),
        repair_lineage=repair_lineage,
        clean_interpreter_path=interpreter.as_posix(),
        clean_interpreter_hash=_file_sha256(interpreter),
        development_policy_survival_rule=(
            "Only the preregistered portfolio_memory policy may reach confirmation. "
            "It survives development iff at least 4 of 7 task-level outcomes succeed, "
            "its success-rate difference versus linear_self_loop is nonnegative, "
            "both F1-to-F3 and F2-to-F3 Spearman correlations are at least 0.20, "
            "and it has zero evaluator, replay, artifact, or budget failures. No "
            "alternative arm may be selected post hoc when this conjunction fails."
        ),
        within_task_aggregation_rule=(
            "task success requires at least two of three seed successes"
        ),
        minimum_development_task_successes=4,
        minimum_low_high_spearman=0.20,
        require_nonnegative_primary_risk_difference=True,
        require_zero_integrity_or_budget_failures=True,
        created_at=created_at or datetime.now(timezone.utc),
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_text_atomic(freeze_path, freeze.canonical_json() + "\n")
    return freeze


def _verify_freeze_local_files(freeze: DevelopmentSearchFreeze) -> None:
    if _file_sha256(Path(freeze.runner_source_path)) != freeze.runner_source_hash:
        raise PortfolioIntegrityError("development runner source hash mismatch")
    if (
        _file_sha256(Path(freeze.runner_dependency_source_path))
        != freeze.runner_dependency_source_hash
    ):
        raise PortfolioIntegrityError(
            "development runner dependency source hash mismatch"
        )
    if (
        _file_sha256(Path(freeze.controller_source_path))
        != freeze.controller_source_hash
    ):
        raise PortfolioIntegrityError("development controller source hash mismatch")
    if (
        _file_sha256(Path(freeze.clean_interpreter_path))
        != freeze.clean_interpreter_hash
    ):
        raise PortfolioIntegrityError("development clean interpreter hash mismatch")
    for task_input in freeze.inputs:
        labels_path = Path(task_input.labels_path)
        if _file_sha256(labels_path) != task_input.labels_sha256:
            raise PortfolioIntegrityError(
                f"development label file hash mismatch: {task_input.unit_id}"
            )
        labels = DevelopmentLabels.model_validate_json(
            labels_path.read_text(encoding="utf-8")
        )
        if (
            labels.label_hash != task_input.label_hash
            or labels.unit_id != task_input.unit_id
            or labels.confirmatory_source
        ):
            raise PortfolioIntegrityError(
                f"development label binding mismatch: {task_input.unit_id}"
            )


def load_development_search_freeze(output_dir: Path) -> DevelopmentSearchFreeze:
    freeze = DevelopmentSearchFreeze.model_validate_json(
        (output_dir / DEVELOPMENT_FREEZE_FILENAME).read_text(encoding="utf-8")
    )
    freeze.verify_integrity()
    _verify_freeze_local_files(freeze)
    return freeze


class EvaluationStatus(str, Enum):
    """Terminal state of one candidate-stage execution."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


class StageRecordStatus(str, Enum):
    """Retention state for every candidate at every fidelity stage."""

    STATIC_PASS = "static_pass"
    STATIC_REJECT = "static_reject"
    EXECUTED = "executed"
    FAILED = "failed"
    NOT_ALLOCATED = "not_allocated"
    COMPONENT_DISABLED = "component_disabled"


class CandidateEvaluation(KernelContract):
    """Content-addressed objective execution and optional exact replay."""

    schema_version: Literal["candidate-evaluation-v1"] = "candidate-evaluation-v1"
    evaluation_id: StableId
    unit_id: StableId
    opaque_unit_id: StableId
    within_unit_seed: int = Field(ge=0)
    candidate_id: StableId
    candidate_hash: Sha256
    mechanism_family: StableId
    stage: Literal["F1", "F2", "F3"]
    status: EvaluationStatus
    config_hash: Sha256
    command_hash: Sha256
    runner_source_hash: Sha256
    train_sha256: Sha256
    test_sha256: Sha256
    labels_sha256: Sha256
    metric_id: Literal["balanced_accuracy", "r2"]
    score: float | None = None
    prediction_sha256: Sha256 | None = None
    prediction_count: int | None = Field(default=None, ge=1)
    fit_row_count: int | None = Field(default=None, ge=1)
    evaluation_row_count: int | None = Field(default=None, ge=1)
    cpu_seconds: float = Field(ge=0)
    wall_seconds: float = Field(ge=0)
    peak_rss_mb: float = Field(ge=0)
    maximum_seconds: int = Field(ge=1)
    maximum_memory_mb: int = Field(ge=1)
    artifact_valid: bool
    evaluator_integrity_valid: bool
    memory_valid: bool
    replay_required: bool
    replay_exact: bool | None = None
    result_file_sha256: Sha256 | None = None
    replay_file_sha256: Sha256 | None = None
    stdout_sha256: Sha256
    stderr_sha256: Sha256
    return_code: int | None = None
    timed_out: bool = False
    failure_code: StableId | None = None
    failure_summary: str | None = None
    evaluation_hash: Sha256

    @model_validator(mode="after")
    def _validate_evaluation(self) -> CandidateEvaluation:
        if self.replay_required != (self.stage == "F3"):
            raise ValueError("only F3 evaluations require exact replay")
        if self.status is EvaluationStatus.SUCCEEDED:
            required = (
                self.score,
                self.prediction_sha256,
                self.prediction_count,
                self.fit_row_count,
                self.evaluation_row_count,
                self.result_file_sha256,
            )
            if any(value is None for value in required):
                raise ValueError("successful evaluation is missing objective artifacts")
            if not all(
                (
                    self.artifact_valid,
                    self.evaluator_integrity_valid,
                    self.memory_valid,
                )
            ):
                raise ValueError("successful evaluation has a failed validity gate")
            if self.failure_code is not None or self.failure_summary is not None:
                raise ValueError("successful evaluation cannot carry a failure")
            if self.replay_required:
                if self.replay_exact is None or self.replay_file_sha256 is None:
                    raise ValueError("F3 evaluation is missing replay evidence")
            elif self.replay_exact is not None or self.replay_file_sha256 is not None:
                raise ValueError("non-F3 evaluation cannot claim replay evidence")
        else:
            if self.failure_code is None or not self.failure_summary:
                raise ValueError("failed evaluation requires a retained failure")
            if self.score is not None or self.prediction_sha256 is not None:
                raise ValueError("failed evaluation cannot claim an objective result")
        if self.evaluation_hash != self.calculated_hash():
            raise PortfolioIntegrityError("candidate evaluation_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> CandidateEvaluation:
        payload = dict(values)
        payload["schema_version"] = "candidate-evaluation-v1"
        return cls.model_validate(
            _with_canonical_hash(cls, payload, "evaluation_hash")
        )

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"evaluation_hash"})
        )

    def verify_integrity(self) -> None:
        if self.evaluation_hash != self.calculated_hash():
            raise PortfolioIntegrityError("candidate evaluation_hash mismatch")


class CandidateStageRecord(KernelContract):
    """One retained candidate-stage decision, including non-allocation."""

    candidate_id: StableId
    candidate_hash: Sha256
    mechanism_family: StableId
    stage: Literal["F0", "F1", "F2", "F3"]
    status: StageRecordStatus
    lineage_parent_id: StableId | None = None
    reviewer_gate_passed: bool | None = None
    objective_score: float | None = None
    selection_score: float | None = None
    memory_correction: float = 0.0
    promoted: bool = False
    evaluation_hash: Sha256 | None = None
    cache_reused: bool | None = None
    failure_code: StableId | None = None
    record_hash: Sha256

    @model_validator(mode="after")
    def _validate_record(self) -> CandidateStageRecord:
        if self.stage == "F0":
            if self.status not in {
                StageRecordStatus.STATIC_PASS,
                StageRecordStatus.STATIC_REJECT,
            }:
                raise ValueError("F0 requires a static status")
            if self.reviewer_gate_passed is None:
                raise ValueError("F0 must retain the reviewer gate")
            if self.evaluation_hash is not None or self.cache_reused is not None:
                raise ValueError("F0 cannot claim an objective execution")
        elif self.status in {
            StageRecordStatus.EXECUTED,
            StageRecordStatus.FAILED,
        }:
            if self.evaluation_hash is None or self.cache_reused is None:
                raise ValueError("executed stage record is missing evaluation provenance")
        elif self.evaluation_hash is not None or self.cache_reused is not None:
            raise ValueError("nonexecuted stage record cannot reference an evaluation")
        if self.status is StageRecordStatus.EXECUTED:
            if self.objective_score is None:
                raise ValueError("executed stage record is missing an objective score")
            if self.failure_code is not None:
                raise ValueError("successful stage record cannot retain a failure code")
        if self.status in {
            StageRecordStatus.STATIC_REJECT,
            StageRecordStatus.FAILED,
        } and self.failure_code is None:
            raise ValueError("rejected or failed stage record needs a failure code")
        if self.promoted and self.status not in {
            StageRecordStatus.STATIC_PASS,
            StageRecordStatus.EXECUTED,
        }:
            raise ValueError("only valid candidates may be promoted")
        if self.record_hash != self.calculated_hash():
            raise PortfolioIntegrityError("candidate stage record_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> CandidateStageRecord:
        payload = dict(values)
        return cls.model_validate(_with_canonical_hash(cls, payload, "record_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"record_hash"}))


class AssignmentCostAudit(KernelContract):
    """Logical and physical resource accounting for one policy assignment."""

    candidate_proposal_slots: Literal[12] = 12
    proposal_model_calls: Literal[0] = 0
    reviewer_model_calls: Literal[0] = 0
    reflection_model_calls: Literal[0] = 0
    model_tokens: Literal[0] = 0
    requested_evaluations: dict[Literal["F1", "F2", "F3"], int]
    reserved_cpu_seconds: int = Field(ge=0)
    observed_logical_cpu_seconds: float = Field(ge=0)
    observed_logical_wall_seconds: float = Field(ge=0)
    newly_executed_cpu_seconds: float = Field(ge=0)
    newly_executed_wall_seconds: float = Field(ge=0)
    peak_rss_mb: float = Field(ge=0)
    maximum_cpu_seconds: int = Field(ge=1)
    maximum_memory_mb: int = Field(ge=1)
    within_budget: bool
    unused_budget_reallocated: Literal[False] = False
    audit_hash: Sha256

    @model_validator(mode="after")
    def _validate_audit(self) -> AssignmentCostAudit:
        if list(self.requested_evaluations) != ["F1", "F2", "F3"]:
            raise ValueError("requested evaluation counts must be ordered F1-F3")
        expected = (
            self.reserved_cpu_seconds <= self.maximum_cpu_seconds
            and self.peak_rss_mb <= self.maximum_memory_mb
        )
        if self.within_budget != expected:
            raise ValueError("cost within_budget does not match hard caps")
        if self.audit_hash != self.calculated_hash():
            raise PortfolioIntegrityError("assignment cost audit_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AssignmentCostAudit:
        payload = dict(values)
        payload.update(
            {
                "candidate_proposal_slots": 12,
                "proposal_model_calls": 0,
                "reviewer_model_calls": 0,
                "reflection_model_calls": 0,
                "model_tokens": 0,
                "unused_budget_reallocated": False,
            }
        )
        return cls.model_validate(_with_canonical_hash(cls, payload, "audit_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"audit_hash"}))


class SearchAssignmentResult(KernelContract):
    """Complete trajectory and objective outcome for one matrix assignment."""

    schema_version: Literal["search-assignment-result-v1"] = (
        "search-assignment-result-v1"
    )
    assignment_hash: Sha256
    freeze_hash: Sha256
    unit_id: StableId
    within_unit_seed: int = Field(ge=0)
    policy_id: StableId
    stage_records: list[CandidateStageRecord] = Field(min_length=48, max_length=48)
    selected_candidate_id: StableId | None = None
    selected_candidate_family: StableId | None = None
    policy_score: float | None = None
    baseline_score: float
    minimum_gain: float = Field(gt=0)
    normalized_margin: float | None = None
    objective_task_success: bool
    artifact_valid: bool
    prediction_replay_valid: bool
    budget_valid: bool
    evaluator_integrity_valid: bool
    failure_codes: list[StableId]
    memory_before_hash: Sha256
    memory_after_hash: Sha256
    cost: AssignmentCostAudit
    llm_reviewer_score_used: Literal[False] = False
    confirmatory_evidence_visible: Literal[False] = False
    result_hash: Sha256

    @field_validator("failure_codes")
    @classmethod
    def _normalize_failures(cls, value: list[str]) -> list[str]:
        return sorted(set(value))

    @model_validator(mode="after")
    def _validate_result(self) -> SearchAssignmentResult:
        stage_counts = {
            stage: sum(record.stage == stage for record in self.stage_records)
            for stage in ("F0", "F1", "F2", "F3")
        }
        if any(value != 12 for value in stage_counts.values()):
            raise ValueError("assignment must retain all 12 candidates at F0-F3")
        record_pairs = [
            (record.stage, record.candidate_id) for record in self.stage_records
        ]
        if len(record_pairs) != len(set(record_pairs)):
            raise ValueError("assignment contains duplicate candidate-stage records")
        gates = (
            self.artifact_valid,
            self.prediction_replay_valid,
            self.budget_valid,
            self.evaluator_integrity_valid,
        )
        expected_success = bool(
            self.policy_score is not None
            and self.normalized_margin is not None
            and self.normalized_margin >= 1.0
            and all(gates)
        )
        if self.objective_task_success != expected_success:
            raise ValueError("objective task success does not match frozen threshold")
        if self.policy_score is None:
            if (
                self.selected_candidate_id is not None
                or self.selected_candidate_family is not None
                or self.normalized_margin is not None
            ):
                raise ValueError("missing policy score cannot claim a selected outcome")
        elif (
            self.selected_candidate_id is None
            or self.selected_candidate_family is None
            or self.normalized_margin is None
        ):
            raise ValueError("policy score is missing selected-candidate metadata")
        if self.cost.within_budget != self.budget_valid:
            raise ValueError("assignment budget validity differs from cost audit")
        if self.result_hash != self.calculated_hash():
            raise PortfolioIntegrityError("search assignment result_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> SearchAssignmentResult:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "search-assignment-result-v1",
                "llm_reviewer_score_used": False,
                "confirmatory_evidence_visible": False,
            }
        )
        payload["failure_codes"] = sorted(set(payload["failure_codes"]))
        return cls.model_validate(_with_canonical_hash(cls, payload, "result_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"result_hash"}))

    def verify_integrity(self) -> None:
        if self.result_hash != self.calculated_hash():
            raise PortfolioIntegrityError("search assignment result_hash mismatch")
        self.cost.model_validate(self.cost.model_dump())
        for record in self.stage_records:
            if record.record_hash != record.calculated_hash():
                raise PortfolioIntegrityError("candidate stage record_hash mismatch")


class _EvaluationOutcome:
    """In-memory cache metadata that is intentionally not a scientific contract."""

    def __init__(self, evaluation: CandidateEvaluation, cache_reused: bool) -> None:
        self.evaluation = evaluation
        self.cache_reused = cache_reused


def _evaluation_id(
    freeze: DevelopmentSearchFreeze,
    task_input: DevelopmentInput,
    candidate: CandidateSpec,
    *,
    seed: int,
    stage: str,
) -> str:
    digest = canonical_sha256(
        {
            "freeze_hash": freeze.freeze_hash,
            "unit_id": task_input.unit_id,
            "train_sha256": task_input.train_sha256,
            "test_sha256": task_input.test_sha256,
            "candidate_hash": candidate.candidate_hash,
            "seed": seed,
            "stage": stage,
        }
    )
    return f"eval-{digest[:24]}"


def _sanitized_execution_environment() -> dict[str, str]:
    blocked_terms = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
    environment = {
        key: value
        for key, value in os.environ.items()
        if not any(term in key.upper() for term in blocked_terms)
    }
    environment.update(
        {
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "VECLIB_MAXIMUM_THREADS": "1",
            "NO_PROXY": "*",
            "no_proxy": "*",
        }
    )
    return environment


def _runner_result_hash_valid(payload: Mapping[str, Any]) -> bool:
    expected = payload.get("result_hash")
    if not isinstance(expected, str):
        return False
    body = dict(payload)
    body.pop("result_hash", None)
    return expected == canonical_sha256(body)


def _scientific_replay_equal(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
) -> bool:
    keys = (
        "candidate_hash",
        "stage",
        "family",
        "metric_id",
        "score",
        "evaluation_split",
        "fit_row_count",
        "evaluation_row_count",
        "feature_count",
        "prediction_count",
        "prediction_sha256",
        "train_sha256",
        "test_sha256",
        "labels_sha256",
        "seed",
        "training_fraction",
        "memory_valid",
        "network_allowed",
    )
    return all(first.get(key) == second.get(key) for key in keys)


def _stage_budget(
    preregistration: CausalSearchPreregistration,
    stage: str,
) -> tuple[float, int]:
    matching = [
        item
        for item in preregistration.budget.fidelity_stages
        if item.stage_id == stage
    ]
    if len(matching) != 1:
        raise ValueError(f"frozen budget is missing {stage}")
    return (
        matching[0].training_fraction,
        matching[0].maximum_seconds_per_candidate,
    )


def _load_cached_evaluation(path: Path) -> CandidateEvaluation:
    evaluation = CandidateEvaluation.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    evaluation.verify_integrity()
    return evaluation


def _execute_candidate(
    freeze: DevelopmentSearchFreeze,
    preregistration: CausalSearchPreregistration,
    task_input: DevelopmentInput,
    candidate: CandidateSpec,
    *,
    seed: int,
    stage: Literal["F1", "F2", "F3"],
    output_dir: Path,
) -> _EvaluationOutcome:
    evaluation_id = _evaluation_id(
        freeze,
        task_input,
        candidate,
        seed=seed,
        stage=stage,
    )
    cache_dir = output_dir / "evaluation-cache" / evaluation_id
    record_path = cache_dir / "evaluation.json"
    if record_path.exists():
        evaluation = _load_cached_evaluation(record_path)
        if evaluation.candidate_hash != candidate.candidate_hash:
            raise PortfolioIntegrityError("cached evaluation candidate mismatch")
        return _EvaluationOutcome(evaluation, cache_reused=True)

    training_fraction, maximum_seconds = _stage_budget(preregistration, stage)
    cache_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "schema_version": "tabular-candidate-execution-v1",
        "execution_id": evaluation_id,
        "opaque_unit_id": task_input.opaque_unit_id,
        "candidate_id": candidate.candidate_id,
        "candidate_hash": candidate.candidate_hash,
        "family": task_input.family,
        "learner": candidate.learner.value,
        "preprocessing": candidate.preprocessing.value,
        "hyperparameters": candidate.hyperparameters,
        "stage": stage,
        "training_fraction": training_fraction,
        "seed": seed,
        "validation_fraction": 0.20,
        "train_path": task_input.train_path,
            "test_path": task_input.test_path,
            "labels_path": task_input.labels_path,
            "train_sha256": task_input.train_sha256,
            "test_sha256": task_input.test_sha256,
            "labels_sha256": task_input.labels_sha256,
        "maximum_memory_mb": freeze.budget_realization.maximum_memory_mb,
    }
    config_hash = canonical_sha256(config)
    config_path = cache_dir / "execution-config.json"
    result_path = cache_dir / "runner-result.json"
    replay_path = cache_dir / "runner-replay.json"
    stdout_path = cache_dir / "runner.stdout.log"
    stderr_path = cache_dir / "runner.stderr.log"
    _write_text_atomic(
        config_path,
        json.dumps(
            config,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
    )
    command = [
        freeze.clean_interpreter_path,
        freeze.runner_source_path,
        "--config",
        config_path.resolve().as_posix(),
        "--output",
        result_path.resolve().as_posix(),
    ]
    command_hash = canonical_sha256(command)
    stdout = ""
    stderr = ""
    return_code: int | None = None
    timed_out = False
    failure_code: str | None = None
    failure_summary: str | None = None
    runner_payload: dict[str, Any] | None = None
    replay_payload: dict[str, Any] | None = None
    try:
        completed = subprocess.run(
            command,
            cwd=cache_dir,
            env=_sanitized_execution_environment(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=maximum_seconds,
            check=False,
        )
        stdout = completed.stdout
        stderr = completed.stderr
        return_code = completed.returncode
        if completed.returncode != 0:
            failure_code = "runner_nonzero_exit"
            failure_summary = (
                f"Frozen candidate runner exited with code {completed.returncode}."
            )
        elif not result_path.exists():
            failure_code = "runner_artifact_missing"
            failure_summary = "Frozen candidate runner produced no result artifact."
        else:
            loaded = json.loads(result_path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict) or not _runner_result_hash_valid(loaded):
                failure_code = "runner_artifact_invalid"
                failure_summary = "Frozen runner result failed its content hash."
            else:
                runner_payload = loaded
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        failure_code = "runner_timeout"
        failure_summary = (
            f"Frozen candidate runner reached the {maximum_seconds}s stage cap."
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        failure_code = "runner_infrastructure_error"
        failure_summary = f"{type(exc).__name__}: {exc}"
    _write_text_atomic(stdout_path, stdout)
    _write_text_atomic(stderr_path, stderr)

    replay_exact: bool | None = None
    replay_file_hash: str | None = None
    if runner_payload is not None and stage == "F3":
        replay_command = [*command[:-1], replay_path.resolve().as_posix()]
        try:
            replay_completed = subprocess.run(
                replay_command,
                cwd=cache_dir,
                env=_sanitized_execution_environment(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=maximum_seconds,
                check=False,
            )
            _write_text_atomic(
                cache_dir / "runner-replay.stdout.log",
                replay_completed.stdout,
            )
            _write_text_atomic(
                cache_dir / "runner-replay.stderr.log",
                replay_completed.stderr,
            )
            if replay_completed.returncode == 0 and replay_path.exists():
                loaded_replay = json.loads(replay_path.read_text(encoding="utf-8"))
                if (
                    isinstance(loaded_replay, dict)
                    and _runner_result_hash_valid(loaded_replay)
                ):
                    replay_payload = loaded_replay
                    replay_exact = _scientific_replay_equal(
                        runner_payload,
                        replay_payload,
                    )
                    replay_file_hash = _file_sha256(replay_path)
                else:
                    replay_exact = False
            else:
                replay_exact = False
        except (
            subprocess.TimeoutExpired,
            OSError,
            ValueError,
            json.JSONDecodeError,
        ):
            replay_exact = False

    evaluator_integrity_valid = bool(
        runner_payload is not None
        and runner_payload.get("candidate_hash") == candidate.candidate_hash
        and runner_payload.get("train_sha256") == task_input.train_sha256
        and runner_payload.get("test_sha256") == task_input.test_sha256
        and runner_payload.get("labels_sha256") == task_input.labels_sha256
        and runner_payload.get("network_allowed") is False
        and freeze.runner_source_hash
        == _file_sha256(Path(freeze.runner_source_path))
    )
    memory_valid = bool(
        runner_payload is not None
        and runner_payload.get("memory_valid") is True
    )
    if runner_payload is not None and not evaluator_integrity_valid:
        failure_code = "evaluator_integrity_failure"
        failure_summary = "Runner output did not bind the frozen candidate or inputs."
        runner_payload = None
    elif runner_payload is not None and not memory_valid:
        failure_code = "memory_budget_exceeded"
        failure_summary = "Runner peak RSS exceeded the frozen memory cap."
        runner_payload = None
    elif (
        stage == "F3"
        and runner_payload is not None
        and replay_exact is not True
    ):
        failure_code = "prediction_replay_failure"
        failure_summary = "F3 prediction replay was not exact."
        runner_payload = None

    if runner_payload is not None:
        evaluation = CandidateEvaluation.create(
            evaluation_id=evaluation_id,
            unit_id=task_input.unit_id,
            opaque_unit_id=task_input.opaque_unit_id,
            within_unit_seed=seed,
            candidate_id=candidate.candidate_id,
            candidate_hash=candidate.candidate_hash,
            mechanism_family=candidate.mechanism_family,
            stage=stage,
            status=EvaluationStatus.SUCCEEDED,
            config_hash=config_hash,
            command_hash=command_hash,
            runner_source_hash=freeze.runner_source_hash,
            train_sha256=task_input.train_sha256,
            test_sha256=task_input.test_sha256,
            labels_sha256=task_input.labels_sha256,
            metric_id=task_input.metric_id,
            score=float(runner_payload["score"]),
            prediction_sha256=runner_payload["prediction_sha256"],
            prediction_count=int(runner_payload["prediction_count"]),
            fit_row_count=int(runner_payload["fit_row_count"]),
            evaluation_row_count=int(runner_payload["evaluation_row_count"]),
            cpu_seconds=float(runner_payload["cpu_seconds"]),
            wall_seconds=float(runner_payload["wall_seconds"]),
            peak_rss_mb=float(runner_payload["peak_rss_mb"]),
            maximum_seconds=maximum_seconds,
            maximum_memory_mb=freeze.budget_realization.maximum_memory_mb,
            artifact_valid=True,
            evaluator_integrity_valid=True,
            memory_valid=True,
            replay_required=stage == "F3",
            replay_exact=replay_exact,
            result_file_sha256=_file_sha256(result_path),
            replay_file_sha256=replay_file_hash,
            stdout_sha256=_file_sha256(stdout_path),
            stderr_sha256=_file_sha256(stderr_path),
            return_code=return_code,
            timed_out=False,
            failure_code=None,
            failure_summary=None,
        )
    else:
        evaluation = CandidateEvaluation.create(
            evaluation_id=evaluation_id,
            unit_id=task_input.unit_id,
            opaque_unit_id=task_input.opaque_unit_id,
            within_unit_seed=seed,
            candidate_id=candidate.candidate_id,
            candidate_hash=candidate.candidate_hash,
            mechanism_family=candidate.mechanism_family,
            stage=stage,
            status=EvaluationStatus.FAILED,
            config_hash=config_hash,
            command_hash=command_hash,
            runner_source_hash=freeze.runner_source_hash,
            train_sha256=task_input.train_sha256,
            test_sha256=task_input.test_sha256,
            labels_sha256=task_input.labels_sha256,
            metric_id=task_input.metric_id,
            score=None,
            prediction_sha256=None,
            prediction_count=None,
            fit_row_count=None,
            evaluation_row_count=None,
            cpu_seconds=(
                float(replay_payload.get("cpu_seconds", 0.0))
                if replay_payload is not None
                else 0.0
            ),
            wall_seconds=(
                float(replay_payload.get("wall_seconds", 0.0))
                if replay_payload is not None
                else float(maximum_seconds if timed_out else 0.0)
            ),
            peak_rss_mb=(
                float(replay_payload.get("peak_rss_mb", 0.0))
                if replay_payload is not None
                else 0.0
            ),
            maximum_seconds=maximum_seconds,
            maximum_memory_mb=freeze.budget_realization.maximum_memory_mb,
            artifact_valid=False,
            evaluator_integrity_valid=evaluator_integrity_valid,
            memory_valid=memory_valid,
            replay_required=stage == "F3",
            replay_exact=replay_exact,
            result_file_sha256=(
                _file_sha256(result_path) if result_path.exists() else None
            ),
            replay_file_sha256=replay_file_hash,
            stdout_sha256=_file_sha256(stdout_path),
            stderr_sha256=_file_sha256(stderr_path),
            return_code=return_code,
            timed_out=timed_out,
            failure_code=failure_code or "unknown_execution_failure",
            failure_summary=failure_summary or "Candidate execution failed.",
        )
    _write_text_atomic(record_path, evaluation.canonical_json() + "\n")
    return _EvaluationOutcome(evaluation, cache_reused=False)


MemoryState = dict[str, dict[str, list[float]]]


def _empty_memory_state() -> MemoryState:
    return {"F1": {}, "F2": {}}


def _memory_hash(state: MemoryState) -> str:
    normalized = {
        stage: {
            family: list(values)
            for family, values in sorted(families.items())
        }
        for stage, families in sorted(state.items())
    }
    return canonical_sha256(normalized)


def _memory_correction(
    state: MemoryState,
    *,
    stage: str,
    mechanism_family: str,
) -> float:
    family_values = state.get(stage, {}).get(mechanism_family, [])
    all_values = [
        value
        for values in state.get(stage, {}).values()
        for value in values
    ]
    values = family_values or all_values
    if not values:
        return 0.0
    return max(-0.25, min(0.25, float(statistics.median(values))))


def _update_memory_from_result(
    state: MemoryState,
    result: SearchAssignmentResult,
    *,
    enabled: bool,
) -> None:
    if not enabled or result.selected_candidate_id is None or result.policy_score is None:
        return
    _update_memory_from_stage_records(
        state,
        result.stage_records,
        selected_candidate_id=result.selected_candidate_id,
        selected_candidate_family=result.selected_candidate_family or "unknown",
        policy_score=result.policy_score,
    )


def _update_memory_from_stage_records(
    state: MemoryState,
    stage_records: Sequence[CandidateStageRecord],
    *,
    selected_candidate_id: str,
    selected_candidate_family: str,
    policy_score: float,
) -> None:
    for stage in ("F1", "F2"):
        matches = [
            record
            for record in stage_records
            if record.stage == stage
            and record.candidate_id == selected_candidate_id
            and record.status is StageRecordStatus.EXECUTED
            and record.objective_score is not None
        ]
        if len(matches) != 1:
            continue
        objective_score = matches[0].objective_score
        if objective_score is None:
            continue
        delta = policy_score - objective_score
        state.setdefault(stage, {}).setdefault(
            selected_candidate_family,
            [],
        ).append(delta)


def _lineage_parent(
    policy: PolicyRealization,
    candidate_id: str,
    ordered_candidates: Sequence[CandidateSpec],
) -> str | None:
    if policy.topology != "linear_chain":
        return None
    ids = [item.candidate_id for item in ordered_candidates]
    index = ids.index(candidate_id)
    return ids[index - 1] if index > 0 else None


def _static_priority(
    candidate: CandidateSpec,
    ordered_candidates: Sequence[CandidateSpec],
) -> float:
    if candidate.intentional_failure_control:
        return 2.0
    index = next(
        index
        for index, item in enumerate(ordered_candidates)
        if item.candidate_id == candidate.candidate_id
    )
    return 1.0 - index / 100.0


def _select_f0_candidates(
    policy: PolicyRealization,
    candidates: Sequence[CandidateSpec],
    *,
    limit: int,
) -> list[str]:
    eligible = [
        item
        for item in candidates
        if not (policy.reviewer_enabled and item.intentional_failure_control)
    ]
    ranked = sorted(
        eligible,
        key=lambda item: (
            -_static_priority(item, candidates),
            item.candidate_id,
        ),
    )
    if policy.topology != "branching_portfolio" or not policy.diversity_enabled:
        return [item.candidate_id for item in ranked[:limit]]
    selected: list[CandidateSpec] = []
    seen_families: set[str] = set()
    for item in ranked:
        if item.mechanism_family in seen_families:
            continue
        selected.append(item)
        seen_families.add(item.mechanism_family)
        if len(selected) == limit:
            break
    for item in ranked:
        if len(selected) == limit:
            break
        if item not in selected:
            selected.append(item)
    return [item.candidate_id for item in selected]


def _rank_successful_candidates(
    candidates: Sequence[CandidateSpec],
    outcomes: Mapping[str, _EvaluationOutcome],
    *,
    stage: str,
    policy: PolicyRealization,
    memory_state: MemoryState,
) -> tuple[list[str], dict[str, float], dict[str, float]]:
    scored: list[tuple[str, float]] = []
    corrections: dict[str, float] = {}
    selection_scores: dict[str, float] = {}
    for candidate in candidates:
        outcome = outcomes.get(candidate.candidate_id)
        if (
            outcome is None
            or outcome.evaluation.status is not EvaluationStatus.SUCCEEDED
            or outcome.evaluation.score is None
        ):
            continue
        correction = (
            _memory_correction(
                memory_state,
                stage=stage,
                mechanism_family=candidate.mechanism_family,
            )
            if policy.comparative_memory_enabled and policy.certificate_enabled
            else 0.0
        )
        if policy.certificate_enabled:
            selection_score = float(outcome.evaluation.score) + correction
        else:
            selection_score = _static_priority(candidate, candidates)
        corrections[candidate.candidate_id] = correction
        selection_scores[candidate.candidate_id] = selection_score
        scored.append((candidate.candidate_id, selection_score))
    initial_index = {
        item.candidate_id: index for index, item in enumerate(candidates)
    }
    scored.sort(
        key=lambda row: (
            -row[1],
            initial_index[row[0]],
            row[0],
        )
    )
    return [candidate_id for candidate_id, _ in scored], selection_scores, corrections


def _linear_survivors(
    evaluated_ids: Sequence[str],
    selection_scores: Mapping[str, float],
    *,
    limit: int,
) -> list[str]:
    incumbent: str | None = None
    incumbent_history: list[str] = []
    for candidate_id in evaluated_ids:
        if candidate_id not in selection_scores:
            continue
        if (
            incumbent is None
            or selection_scores[candidate_id] > selection_scores[incumbent]
        ):
            incumbent = candidate_id
            if candidate_id not in incumbent_history:
                incumbent_history.append(candidate_id)
    survivors: list[str] = []
    if incumbent is not None:
        survivors.append(incumbent)
    for candidate_id in reversed(incumbent_history):
        if candidate_id not in survivors:
            survivors.append(candidate_id)
        if len(survivors) == limit:
            return survivors
    ranked_remaining = sorted(
        (
            candidate_id
            for candidate_id in selection_scores
            if candidate_id not in survivors
        ),
        key=lambda item: (-selection_scores[item], evaluated_ids.index(item), item),
    )
    return [*survivors, *ranked_remaining][:limit]


def _portfolio_survivors(
    ranked_ids: Sequence[str],
    candidates_by_id: Mapping[str, CandidateSpec],
    *,
    limit: int,
    exploration_enabled: bool,
) -> list[str]:
    if not exploration_enabled or limit <= 1 or len(ranked_ids) <= limit:
        return list(ranked_ids[:limit])
    exploit = list(ranked_ids[: limit - 1])
    exploit_families = {
        candidates_by_id[candidate_id].mechanism_family
        for candidate_id in exploit
    }
    exploration = next(
        (
            candidate_id
            for candidate_id in ranked_ids[limit - 1 :]
            if candidates_by_id[candidate_id].mechanism_family
            not in exploit_families
        ),
        ranked_ids[limit - 1],
    )
    return [*exploit, exploration]


def _promote_after_stage(
    policy: PolicyRealization,
    evaluated_ids: Sequence[str],
    ranked_ids: Sequence[str],
    selection_scores: Mapping[str, float],
    candidates_by_id: Mapping[str, CandidateSpec],
    *,
    limit: int,
    exploration_stage: bool,
) -> list[str]:
    if policy.topology == "linear_chain":
        return _linear_survivors(
            evaluated_ids,
            selection_scores,
            limit=limit,
        )
    if policy.topology == "branching_portfolio":
        return _portfolio_survivors(
            ranked_ids,
            candidates_by_id,
            limit=limit,
            exploration_enabled=(
                policy.diversity_enabled and exploration_stage
            ),
        )
    return list(ranked_ids[:limit])


def _nonallocated_record(
    candidate: CandidateSpec,
    policy: PolicyRealization,
    ordered_candidates: Sequence[CandidateSpec],
    *,
    stage: Literal["F1", "F2", "F3"],
    component_disabled: bool = False,
) -> CandidateStageRecord:
    return CandidateStageRecord.create(
        candidate_id=candidate.candidate_id,
        candidate_hash=candidate.candidate_hash,
        mechanism_family=candidate.mechanism_family,
        stage=stage,
        status=(
            StageRecordStatus.COMPONENT_DISABLED
            if component_disabled
            else StageRecordStatus.NOT_ALLOCATED
        ),
        lineage_parent_id=_lineage_parent(
            policy,
            candidate.candidate_id,
            ordered_candidates,
        ),
        reviewer_gate_passed=None,
        objective_score=None,
        selection_score=None,
        memory_correction=0.0,
        promoted=False,
        evaluation_hash=None,
        cache_reused=None,
        failure_code=None,
    )


def _stage_execution_record(
    candidate: CandidateSpec,
    policy: PolicyRealization,
    ordered_candidates: Sequence[CandidateSpec],
    *,
    stage: Literal["F1", "F2", "F3"],
    outcome: _EvaluationOutcome,
    selection_score: float | None,
    memory_correction: float,
    promoted: bool,
) -> CandidateStageRecord:
    evaluation = outcome.evaluation
    if evaluation.status is EvaluationStatus.SUCCEEDED:
        return CandidateStageRecord.create(
            candidate_id=candidate.candidate_id,
            candidate_hash=candidate.candidate_hash,
            mechanism_family=candidate.mechanism_family,
            stage=stage,
            status=StageRecordStatus.EXECUTED,
            lineage_parent_id=_lineage_parent(
                policy,
                candidate.candidate_id,
                ordered_candidates,
            ),
            reviewer_gate_passed=None,
            objective_score=evaluation.score,
            selection_score=selection_score,
            memory_correction=memory_correction,
            promoted=promoted,
            evaluation_hash=evaluation.evaluation_hash,
            cache_reused=outcome.cache_reused,
            failure_code=None,
        )
    return CandidateStageRecord.create(
        candidate_id=candidate.candidate_id,
        candidate_hash=candidate.candidate_hash,
        mechanism_family=candidate.mechanism_family,
        stage=stage,
        status=StageRecordStatus.FAILED,
        lineage_parent_id=_lineage_parent(
            policy,
            candidate.candidate_id,
            ordered_candidates,
        ),
        reviewer_gate_passed=None,
        objective_score=None,
        selection_score=None,
        memory_correction=0.0,
        promoted=False,
        evaluation_hash=evaluation.evaluation_hash,
        cache_reused=outcome.cache_reused,
        failure_code=evaluation.failure_code,
    )


def _execute_assignment(
    freeze: DevelopmentSearchFreeze,
    preregistration: CausalSearchPreregistration,
    assignment: DevelopmentAssignment,
    memory_state: MemoryState,
    *,
    output_dir: Path,
    seen_evaluation_hashes: set[str] | None = None,
) -> SearchAssignmentResult:
    policies = {item.policy_id: item for item in freeze.policies}
    inputs = {item.unit_id: item for item in freeze.inputs}
    policy = policies[assignment.policy_id]
    task_input = inputs[assignment.unit_id]
    candidates = freeze.candidates
    candidates_by_id = {item.candidate_id: item for item in candidates}
    memory_before_hash = _memory_hash(memory_state)
    all_outcomes: list[_EvaluationOutcome] = []
    seen_hashes = (
        seen_evaluation_hashes
        if seen_evaluation_hashes is not None
        else set()
    )
    records_by_stage: dict[str, list[CandidateStageRecord]] = {}

    def logical_cache_outcome(outcome: _EvaluationOutcome) -> _EvaluationOutcome:
        evaluation_hash = outcome.evaluation.evaluation_hash
        logically_reused = evaluation_hash in seen_hashes
        seen_hashes.add(evaluation_hash)
        return _EvaluationOutcome(outcome.evaluation, logically_reused)

    f0_limit = 6 if policy.multi_fidelity_enabled else 1
    f0_selected = _select_f0_candidates(
        policy,
        candidates,
        limit=f0_limit,
    )
    f0_records: list[CandidateStageRecord] = []
    for candidate in candidates:
        rejected = policy.reviewer_enabled and candidate.intentional_failure_control
        f0_records.append(
            CandidateStageRecord.create(
                candidate_id=candidate.candidate_id,
                candidate_hash=candidate.candidate_hash,
                mechanism_family=candidate.mechanism_family,
                stage="F0",
                status=(
                    StageRecordStatus.STATIC_REJECT
                    if rejected
                    else StageRecordStatus.STATIC_PASS
                ),
                lineage_parent_id=_lineage_parent(
                    policy,
                    candidate.candidate_id,
                    candidates,
                ),
                reviewer_gate_passed=not rejected,
                objective_score=None,
                selection_score=_static_priority(candidate, candidates),
                memory_correction=0.0,
                promoted=candidate.candidate_id in f0_selected,
                evaluation_hash=None,
                cache_reused=None,
                failure_code="reviewer_schema_reject" if rejected else None,
            )
        )
    records_by_stage["F0"] = f0_records

    f1_outcomes: dict[str, _EvaluationOutcome] = {}
    f2_outcomes: dict[str, _EvaluationOutcome] = {}
    f3_outcomes: dict[str, _EvaluationOutcome] = {}
    f1_selected: list[str] = []
    f2_selected: list[str] = []
    f1_selection_scores: dict[str, float] = {}
    f2_selection_scores: dict[str, float] = {}
    f1_corrections: dict[str, float] = {}
    f2_corrections: dict[str, float] = {}

    if policy.multi_fidelity_enabled:
        for candidate_id in f0_selected:
            outcome = logical_cache_outcome(
                _execute_candidate(
                    freeze,
                    preregistration,
                    task_input,
                    candidates_by_id[candidate_id],
                    seed=assignment.within_unit_seed,
                    stage="F1",
                    output_dir=output_dir,
                )
            )
            f1_outcomes[candidate_id] = outcome
            all_outcomes.append(outcome)
        ranked_f1, f1_selection_scores, f1_corrections = (
            _rank_successful_candidates(
                candidates,
                f1_outcomes,
                stage="F1",
                policy=policy,
                memory_state=memory_state,
            )
        )
        f1_selected = _promote_after_stage(
            policy,
            f0_selected,
            ranked_f1,
            f1_selection_scores,
            candidates_by_id,
            limit=3,
            exploration_stage=True,
        )
        records_by_stage["F1"] = [
            (
                _stage_execution_record(
                    candidate,
                    policy,
                    candidates,
                    stage="F1",
                    outcome=f1_outcomes[candidate.candidate_id],
                    selection_score=f1_selection_scores.get(candidate.candidate_id),
                    memory_correction=f1_corrections.get(candidate.candidate_id, 0.0),
                    promoted=candidate.candidate_id in f1_selected,
                )
                if candidate.candidate_id in f1_outcomes
                else _nonallocated_record(
                    candidate,
                    policy,
                    candidates,
                    stage="F1",
                )
            )
            for candidate in candidates
        ]

        for candidate_id in f1_selected:
            outcome = logical_cache_outcome(
                _execute_candidate(
                    freeze,
                    preregistration,
                    task_input,
                    candidates_by_id[candidate_id],
                    seed=assignment.within_unit_seed,
                    stage="F2",
                    output_dir=output_dir,
                )
            )
            f2_outcomes[candidate_id] = outcome
            all_outcomes.append(outcome)
        ranked_f2, f2_selection_scores, f2_corrections = (
            _rank_successful_candidates(
                candidates,
                f2_outcomes,
                stage="F2",
                policy=policy,
                memory_state=memory_state,
            )
        )
        f2_selected = _promote_after_stage(
            policy,
            f1_selected,
            ranked_f2,
            f2_selection_scores,
            candidates_by_id,
            limit=1,
            exploration_stage=False,
        )
        records_by_stage["F2"] = [
            (
                _stage_execution_record(
                    candidate,
                    policy,
                    candidates,
                    stage="F2",
                    outcome=f2_outcomes[candidate.candidate_id],
                    selection_score=f2_selection_scores.get(candidate.candidate_id),
                    memory_correction=f2_corrections.get(candidate.candidate_id, 0.0),
                    promoted=candidate.candidate_id in f2_selected,
                )
                if candidate.candidate_id in f2_outcomes
                else _nonallocated_record(
                    candidate,
                    policy,
                    candidates,
                    stage="F2",
                )
            )
            for candidate in candidates
        ]
    else:
        records_by_stage["F1"] = [
            _nonallocated_record(
                candidate,
                policy,
                candidates,
                stage="F1",
                component_disabled=True,
            )
            for candidate in candidates
        ]
        records_by_stage["F2"] = [
            _nonallocated_record(
                candidate,
                policy,
                candidates,
                stage="F2",
                component_disabled=True,
            )
            for candidate in candidates
        ]
        f2_selected = list(f0_selected[:1])

    if f2_selected:
        final_candidate_id = f2_selected[0]
        outcome = logical_cache_outcome(
            _execute_candidate(
                freeze,
                preregistration,
                task_input,
                candidates_by_id[final_candidate_id],
                seed=assignment.within_unit_seed,
                stage="F3",
                output_dir=output_dir,
            )
        )
        f3_outcomes[final_candidate_id] = outcome
        all_outcomes.append(outcome)
    records_by_stage["F3"] = [
        (
            _stage_execution_record(
                candidate,
                policy,
                candidates,
                stage="F3",
                outcome=f3_outcomes[candidate.candidate_id],
                selection_score=(
                    f3_outcomes[candidate.candidate_id].evaluation.score
                    if f3_outcomes[candidate.candidate_id].evaluation.status
                    is EvaluationStatus.SUCCEEDED
                    else None
                ),
                memory_correction=0.0,
                promoted=(
                    f3_outcomes[candidate.candidate_id].evaluation.status
                    is EvaluationStatus.SUCCEEDED
                ),
            )
            if candidate.candidate_id in f3_outcomes
            else _nonallocated_record(
                candidate,
                policy,
                candidates,
                stage="F3",
            )
        )
        for candidate in candidates
    ]
    stage_records = [
        record
        for stage in ("F0", "F1", "F2", "F3")
        for record in records_by_stage[stage]
    ]

    successful_final = next(
        (
            outcome.evaluation
            for outcome in f3_outcomes.values()
            if outcome.evaluation.status is EvaluationStatus.SUCCEEDED
        ),
        None,
    )
    selected_candidate_id = (
        successful_final.candidate_id if successful_final is not None else None
    )
    selected_candidate_family = (
        successful_final.mechanism_family if successful_final is not None else None
    )
    policy_score = (
        float(successful_final.score)
        if successful_final is not None and successful_final.score is not None
        else None
    )
    normalized_margin = (
        (policy_score - task_input.baseline_score) / task_input.minimum_gain
        if policy_score is not None
        else None
    )

    requested = {
        "F1": len(f1_outcomes),
        "F2": len(f2_outcomes),
        "F3": len(f3_outcomes),
    }
    maximum_by_stage = {
        stage: _stage_budget(preregistration, stage)[1]
        for stage in ("F1", "F2", "F3")
    }
    reserved_cpu_seconds = sum(
        requested[stage] * maximum_by_stage[stage]
        for stage in ("F1", "F2", "F3")
    )
    evaluations = [item.evaluation for item in all_outcomes]
    peak_rss_mb = max(
        (evaluation.peak_rss_mb for evaluation in evaluations),
        default=0.0,
    )
    cost = AssignmentCostAudit.create(
        requested_evaluations=requested,
        reserved_cpu_seconds=reserved_cpu_seconds,
        observed_logical_cpu_seconds=sum(
            evaluation.cpu_seconds for evaluation in evaluations
        ),
        observed_logical_wall_seconds=sum(
            evaluation.wall_seconds for evaluation in evaluations
        ),
        newly_executed_cpu_seconds=sum(
            item.evaluation.cpu_seconds
            for item in all_outcomes
            if not item.cache_reused
        ),
        newly_executed_wall_seconds=sum(
            item.evaluation.wall_seconds
            for item in all_outcomes
            if not item.cache_reused
        ),
        peak_rss_mb=peak_rss_mb,
        maximum_cpu_seconds=(
            freeze.budget_realization.maximum_cpu_seconds_per_assignment
        ),
        maximum_memory_mb=freeze.budget_realization.maximum_memory_mb,
        within_budget=(
            reserved_cpu_seconds
            <= freeze.budget_realization.maximum_cpu_seconds_per_assignment
            and peak_rss_mb <= freeze.budget_realization.maximum_memory_mb
        ),
    )
    all_executions_valid = bool(evaluations) and all(
        evaluation.status is EvaluationStatus.SUCCEEDED
        for evaluation in evaluations
    )
    artifact_valid = bool(successful_final is not None and all_executions_valid)
    evaluator_integrity_valid = bool(
        successful_final is not None
        and all(
            evaluation.evaluator_integrity_valid
            for evaluation in evaluations
        )
    )
    prediction_replay_valid = bool(
        successful_final is not None
        and successful_final.replay_required
        and successful_final.replay_exact is True
    )
    failure_codes = [
        evaluation.failure_code
        for evaluation in evaluations
        if evaluation.failure_code is not None
    ]
    if successful_final is None:
        failure_codes.append("no_f3_survivor")
    if not cost.within_budget:
        failure_codes.append("assignment_budget_exceeded")

    if (
        policy.comparative_memory_enabled
        and selected_candidate_id is not None
        and selected_candidate_family is not None
        and policy_score is not None
    ):
        _update_memory_from_stage_records(
            memory_state,
            stage_records,
            selected_candidate_id=selected_candidate_id,
            selected_candidate_family=selected_candidate_family,
            policy_score=policy_score,
        )
    memory_after_hash = _memory_hash(memory_state)
    return SearchAssignmentResult.create(
        assignment_hash=assignment.assignment_hash,
        freeze_hash=freeze.freeze_hash,
        unit_id=task_input.unit_id,
        within_unit_seed=assignment.within_unit_seed,
        policy_id=policy.policy_id,
        stage_records=stage_records,
        selected_candidate_id=selected_candidate_id,
        selected_candidate_family=selected_candidate_family,
        policy_score=policy_score,
        baseline_score=task_input.baseline_score,
        minimum_gain=task_input.minimum_gain,
        normalized_margin=normalized_margin,
        objective_task_success=bool(
            normalized_margin is not None
            and normalized_margin >= 1.0
            and artifact_valid
            and prediction_replay_valid
            and cost.within_budget
            and evaluator_integrity_valid
        ),
        artifact_valid=artifact_valid,
        prediction_replay_valid=prediction_replay_valid,
        budget_valid=cost.within_budget,
        evaluator_integrity_valid=evaluator_integrity_valid,
        failure_codes=failure_codes,
        memory_before_hash=memory_before_hash,
        memory_after_hash=memory_after_hash,
        cost=cost,
    )


class TaskPolicyOutcome(KernelContract):
    """Task-level aggregation; seeds remain repeated measures."""

    unit_id: StableId
    policy_id: StableId
    seed_successes: dict[StableId, bool]
    seed_margins: dict[StableId, float | None]
    successful_seed_count: int = Field(ge=0, le=3)
    task_success: bool
    median_margin: float | None = None
    attributable_failure_seed_count: int = Field(ge=0, le=3)
    outcome_hash: Sha256

    @model_validator(mode="after")
    def _validate_outcome(self) -> TaskPolicyOutcome:
        if list(self.seed_successes) != sorted(self.seed_successes):
            raise ValueError("seed successes must be key-sorted")
        if list(self.seed_margins) != sorted(self.seed_margins):
            raise ValueError("seed margins must be key-sorted")
        if set(self.seed_successes) != set(self.seed_margins):
            raise ValueError("seed success and margin keys differ")
        if len(self.seed_successes) != 3:
            raise ValueError("task outcome requires exactly three within-task seeds")
        observed_successes = sum(self.seed_successes.values())
        if self.successful_seed_count != observed_successes:
            raise ValueError("successful seed count mismatch")
        if self.task_success != (observed_successes >= 2):
            raise ValueError("task success must use the frozen two-of-three rule")
        margins = [
            value for value in self.seed_margins.values() if value is not None
        ]
        expected_median = float(statistics.median(margins)) if margins else None
        if self.median_margin != expected_median:
            raise ValueError("task median margin mismatch")
        if self.outcome_hash != self.calculated_hash():
            raise PortfolioIntegrityError("task policy outcome_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> TaskPolicyOutcome:
        payload = dict(values)
        payload["seed_successes"] = dict(sorted(payload["seed_successes"].items()))
        payload["seed_margins"] = dict(sorted(payload["seed_margins"].items()))
        return cls.model_validate(_with_canonical_hash(cls, payload, "outcome_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"outcome_hash"}))


class PolicyDevelopmentSummary(KernelContract):
    """Complete task, assignment, failure, and cost summary for one policy."""

    policy_id: StableId
    task_count: int = Field(ge=1)
    task_success_count: int = Field(ge=0)
    task_success_rate: float = Field(ge=0, le=1)
    assignment_count: int = Field(ge=1)
    assignment_success_count: int = Field(ge=0)
    failure_assignment_count: int = Field(ge=0)
    failure_code_counts: dict[StableId, int]
    reserved_cpu_seconds: int = Field(ge=0)
    newly_executed_cpu_seconds: float = Field(ge=0)
    newly_executed_wall_seconds: float = Field(ge=0)
    maximum_peak_rss_mb: float = Field(ge=0)
    summary_hash: Sha256

    @model_validator(mode="after")
    def _validate_summary(self) -> PolicyDevelopmentSummary:
        if self.task_success_count > self.task_count:
            raise ValueError("policy task successes exceed task count")
        if not math.isclose(
            self.task_success_rate,
            self.task_success_count / self.task_count,
            rel_tol=0,
            abs_tol=1e-15,
        ):
            raise ValueError("policy task success rate mismatch")
        if (
            self.assignment_success_count + self.failure_assignment_count
            != self.assignment_count
        ):
            raise ValueError("policy assignment outcome counts do not sum")
        if list(self.failure_code_counts) != sorted(self.failure_code_counts):
            raise ValueError("failure code counts must be key-sorted")
        if self.summary_hash != self.calculated_hash():
            raise PortfolioIntegrityError("policy development summary_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> PolicyDevelopmentSummary:
        payload = dict(values)
        payload["failure_code_counts"] = dict(
            sorted(payload["failure_code_counts"].items())
        )
        return cls.model_validate(_with_canonical_hash(cls, payload, "summary_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"summary_hash"}))


class DevelopmentPolicyComparison(KernelContract):
    """Paired task-level exploratory comparison on development only."""

    comparison_id: StableId
    role: Literal["primary_development", "secondary_arm", "secondary_ablation"]
    policy_a: StableId
    policy_b: StableId
    task_count: int = Field(ge=1)
    favorable_to_a: int = Field(ge=0)
    unfavorable_to_a: int = Field(ge=0)
    tied: int = Field(ge=0)
    risk_difference_a_minus_b: float = Field(ge=-1, le=1)
    bootstrap_interval_95: tuple[float, float]
    exact_mcnemar_p: float = Field(ge=0, le=1)
    holm_adjusted_p: float | None = Field(default=None, ge=0, le=1)
    development_only: Literal[True] = True
    confirmatory_inference_allowed: Literal[False] = False
    comparison_hash: Sha256

    @model_validator(mode="after")
    def _validate_comparison(self) -> DevelopmentPolicyComparison:
        if self.favorable_to_a + self.unfavorable_to_a + self.tied != self.task_count:
            raise ValueError("paired comparison task counts do not sum")
        if self.bootstrap_interval_95[0] > self.bootstrap_interval_95[1]:
            raise ValueError("paired bootstrap interval is reversed")
        if self.role == "primary_development" and self.holm_adjusted_p is not None:
            raise ValueError("primary development comparison is outside secondary Holm family")
        if self.comparison_hash != self.calculated_hash():
            raise PortfolioIntegrityError("development comparison_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> DevelopmentPolicyComparison:
        payload = dict(values)
        payload.update(
            {
                "development_only": True,
                "confirmatory_inference_allowed": False,
            }
        )
        return cls.model_validate(
            _with_canonical_hash(cls, payload, "comparison_hash")
        )

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"comparison_hash"})
        )


class FidelityCalibration(KernelContract):
    """Selection-aware low-to-high fidelity diagnostic."""

    policy_id: StableId
    low_stage: Literal["F1", "F2"]
    high_stage: Literal["F3"] = "F3"
    analysis_unit: Literal["independent task"] = "independent task"
    pair_count: int = Field(ge=0)
    spearman_rho: float | None = Field(default=None, ge=-1, le=1)
    mean_absolute_error: float | None = Field(default=None, ge=0)
    selection_conditioned: Literal[True] = True
    calibration_hash: Sha256

    @model_validator(mode="after")
    def _validate_calibration(self) -> FidelityCalibration:
        if self.pair_count < 2 and self.spearman_rho is not None:
            raise ValueError("Spearman correlation needs at least two pairs")
        if self.pair_count == 0 and self.mean_absolute_error is not None:
            raise ValueError("empty calibration cannot claim an error")
        if self.calibration_hash != self.calculated_hash():
            raise PortfolioIntegrityError("fidelity calibration_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> FidelityCalibration:
        payload = dict(values)
        payload.update(
            {
                "high_stage": "F3",
                "analysis_unit": "independent task",
                "selection_conditioned": True,
            }
        )
        return cls.model_validate(
            _with_canonical_hash(cls, payload, "calibration_hash")
        )

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"calibration_hash"})
        )


class DevelopmentSearchAnalysis(KernelContract):
    """Deterministic task-level development analysis."""

    schema_version: Literal["development-search-analysis-v1"] = (
        "development-search-analysis-v1"
    )
    analysis_unit: Literal["independent OpenML task"] = "independent OpenML task"
    seed_role: Literal["within-task repeated measurement"] = (
        "within-task repeated measurement"
    )
    task_outcomes: list[TaskPolicyOutcome]
    policy_summaries: list[PolicyDevelopmentSummary]
    arm_comparisons: list[DevelopmentPolicyComparison]
    ablation_comparisons: list[DevelopmentPolicyComparison]
    fidelity_calibrations: list[FidelityCalibration]
    holm_family_size: int = Field(ge=1)
    surviving_policy_ids: list[StableId]
    survival_checks: dict[StableId, bool]
    zero_survivors_allowed: Literal[True] = True
    confirmatory_results_used: Literal[False] = False
    llm_reviewer_score_used: Literal[False] = False
    analysis_hash: Sha256

    @model_validator(mode="after")
    def _validate_analysis(self) -> DevelopmentSearchAnalysis:
        if [item.policy_id for item in self.policy_summaries] != sorted(
            item.policy_id for item in self.policy_summaries
        ):
            raise ValueError("policy summaries must be policy-sorted")
        if list(self.survival_checks) != sorted(self.survival_checks):
            raise ValueError("survival checks must be key-sorted")
        expected_survivors = (
            [StudyArm.PORTFOLIO_MEMORY.value]
            if all(self.survival_checks.values())
            else []
        )
        if self.surviving_policy_ids != expected_survivors:
            raise ValueError("surviving policy IDs do not match frozen conjunction")
        secondary = [
            *[
                item
                for item in self.arm_comparisons
                if item.role == "secondary_arm"
            ],
            *self.ablation_comparisons,
        ]
        if self.holm_family_size != len(secondary):
            raise ValueError("Holm family size mismatch")
        if any(item.holm_adjusted_p is None for item in secondary):
            raise ValueError("secondary comparison lacks Holm adjustment")
        if self.analysis_hash != self.calculated_hash():
            raise PortfolioIntegrityError("development analysis_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> DevelopmentSearchAnalysis:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "development-search-analysis-v1",
                "analysis_unit": "independent OpenML task",
                "seed_role": "within-task repeated measurement",
                "zero_survivors_allowed": True,
                "confirmatory_results_used": False,
                "llm_reviewer_score_used": False,
            }
        )
        payload["survival_checks"] = dict(
            sorted(payload["survival_checks"].items())
        )
        payload["surviving_policy_ids"] = sorted(payload["surviving_policy_ids"])
        return cls.model_validate(_with_canonical_hash(cls, payload, "analysis_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"analysis_hash"}))


class DevelopmentSearchStatus(str, Enum):
    """Task 263.5 terminal scientific state."""

    READY_FOR_CONFIRMATION = "ready_for_confirmation"
    NEGATIVE_DEVELOPMENT = "negative_development"


class DevelopmentSearchReport(KernelContract):
    """Top-level result with complete matrix references and safe next gate."""

    schema_version: Literal["development-search-report-v1"] = (
        "development-search-report-v1"
    )
    report_id: StableId
    freeze_hash: Sha256
    baseline_report_hash: Sha256
    preregistration_hash: Sha256
    status: DevelopmentSearchStatus
    assignment_result_hashes: dict[StableId, Sha256]
    assignment_count: int = Field(ge=1)
    candidate_stage_record_count: int = Field(ge=1)
    unique_evaluation_count: int = Field(ge=1)
    evaluation_failure_count: int = Field(ge=0)
    evaluation_cache_reuse_count: int = Field(ge=0)
    analysis: DevelopmentSearchAnalysis
    full_matrix_complete: Literal[True] = True
    exact_resume_verified: Literal[True] = True
    failure_cost_provenance_audit_passed: Literal[True] = True
    numerical_outcomes_deterministic: Literal[True] = True
    confirmatory_payloads_downloaded: Literal[False] = False
    confirmatory_results_visible: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    public_release_authorized: Literal[False] = False
    completed_at: datetime
    report_hash: Sha256

    @field_validator("completed_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("development report time must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _validate_report(self) -> DevelopmentSearchReport:
        if list(self.assignment_result_hashes) != sorted(
            self.assignment_result_hashes
        ):
            raise ValueError("assignment result hashes must be key-sorted")
        if self.assignment_count != len(self.assignment_result_hashes):
            raise ValueError("assignment count/hash inventory mismatch")
        expected_status = (
            DevelopmentSearchStatus.READY_FOR_CONFIRMATION
            if self.analysis.surviving_policy_ids
            else DevelopmentSearchStatus.NEGATIVE_DEVELOPMENT
        )
        if self.status is not expected_status:
            raise ValueError("development report status differs from survival result")
        if self.report_hash != self.calculated_hash():
            raise PortfolioIntegrityError("development report_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> DevelopmentSearchReport:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "development-search-report-v1",
                "full_matrix_complete": True,
                "exact_resume_verified": True,
                "failure_cost_provenance_audit_passed": True,
                "numerical_outcomes_deterministic": True,
                "confirmatory_payloads_downloaded": False,
                "confirmatory_results_visible": False,
                "external_submission_authorized": False,
                "public_release_authorized": False,
            }
        )
        payload["assignment_result_hashes"] = dict(
            sorted(payload["assignment_result_hashes"].items())
        )
        return cls.model_validate(_with_canonical_hash(cls, payload, "report_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"report_hash"}))

    def verify_integrity(self) -> None:
        if self.report_hash != self.calculated_hash():
            raise PortfolioIntegrityError("development report_hash mismatch")


class DevelopmentSearchArtifactManifest(KernelContract):
    """Hash inventory for every Task 263.5 artifact and retained log."""

    schema_version: Literal["development-search-artifact-manifest-v1"] = (
        "development-search-artifact-manifest-v1"
    )
    freeze_hash: Sha256
    report_hash: Sha256
    files: dict[NonEmptyText, Sha256]
    confirmatory_payloads_included: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    public_release_authorized: Literal[False] = False
    manifest_hash: Sha256

    @model_validator(mode="after")
    def _validate_manifest(self) -> DevelopmentSearchArtifactManifest:
        if list(self.files) != sorted(self.files):
            raise ValueError("development artifact files must be path-sorted")
        if self.manifest_hash != self.calculated_hash():
            raise PortfolioIntegrityError("development manifest_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> DevelopmentSearchArtifactManifest:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "development-search-artifact-manifest-v1",
                "confirmatory_payloads_included": False,
                "external_submission_authorized": False,
                "public_release_authorized": False,
            }
        )
        payload["files"] = dict(sorted(payload["files"].items()))
        return cls.model_validate(_with_canonical_hash(cls, payload, "manifest_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"manifest_hash"}))

    def verify_integrity(self) -> None:
        if self.manifest_hash != self.calculated_hash():
            raise PortfolioIntegrityError("development manifest_hash mismatch")


def _task_outcomes(
    freeze: DevelopmentSearchFreeze,
    results: Sequence[SearchAssignmentResult],
) -> list[TaskPolicyOutcome]:
    grouped: dict[tuple[str, str], list[SearchAssignmentResult]] = {}
    for result in results:
        grouped.setdefault((result.policy_id, result.unit_id), []).append(result)
    outcomes: list[TaskPolicyOutcome] = []
    for (policy_id, unit_id), rows in sorted(grouped.items()):
        rows = sorted(rows, key=lambda item: item.within_unit_seed)
        seed_successes = {
            str(item.within_unit_seed): item.objective_task_success for item in rows
        }
        seed_margins = {
            str(item.within_unit_seed): item.normalized_margin for item in rows
        }
        margins = [value for value in seed_margins.values() if value is not None]
        outcomes.append(
            TaskPolicyOutcome.create(
                unit_id=unit_id,
                policy_id=policy_id,
                seed_successes=seed_successes,
                seed_margins=seed_margins,
                successful_seed_count=sum(seed_successes.values()),
                task_success=sum(seed_successes.values()) >= 2,
                median_margin=(
                    float(statistics.median(margins)) if margins else None
                ),
                attributable_failure_seed_count=sum(
                    bool(item.failure_codes) for item in rows
                ),
            )
        )
    expected = len(freeze.inputs) * len(freeze.policies)
    if len(outcomes) != expected:
        raise PortfolioIntegrityError("task-policy outcome matrix is incomplete")
    return outcomes


def _policy_summaries(
    outcomes: Sequence[TaskPolicyOutcome],
    results: Sequence[SearchAssignmentResult],
) -> list[PolicyDevelopmentSummary]:
    policy_ids = sorted({item.policy_id for item in results})
    summaries: list[PolicyDevelopmentSummary] = []
    for policy_id in policy_ids:
        policy_outcomes = [
            item for item in outcomes if item.policy_id == policy_id
        ]
        policy_results = [
            item for item in results if item.policy_id == policy_id
        ]
        failure_counts: dict[str, int] = {}
        for result in policy_results:
            for code in result.failure_codes:
                failure_counts[code] = failure_counts.get(code, 0) + 1
        success_count = sum(item.task_success for item in policy_outcomes)
        assignment_success_count = sum(
            all(
                (
                    item.artifact_valid,
                    item.prediction_replay_valid,
                    item.budget_valid,
                    item.evaluator_integrity_valid,
                )
            )
            for item in policy_results
        )
        summaries.append(
            PolicyDevelopmentSummary.create(
                policy_id=policy_id,
                task_count=len(policy_outcomes),
                task_success_count=success_count,
                task_success_rate=success_count / len(policy_outcomes),
                assignment_count=len(policy_results),
                assignment_success_count=assignment_success_count,
                failure_assignment_count=(
                    len(policy_results) - assignment_success_count
                ),
                failure_code_counts=failure_counts,
                reserved_cpu_seconds=sum(
                    item.cost.reserved_cpu_seconds for item in policy_results
                ),
                newly_executed_cpu_seconds=sum(
                    item.cost.newly_executed_cpu_seconds
                    for item in policy_results
                ),
                newly_executed_wall_seconds=sum(
                    item.cost.newly_executed_wall_seconds
                    for item in policy_results
                ),
                maximum_peak_rss_mb=max(
                    (item.cost.peak_rss_mb for item in policy_results),
                    default=0.0,
                ),
            )
        )
    return summaries


def _paired_bootstrap_interval(
    differences: Sequence[float],
    *,
    seed_material: str,
    resamples: int = 20_000,
) -> tuple[float, float]:
    rng = random.Random(int(canonical_sha256(seed_material)[:16], 16))
    size = len(differences)
    estimates = [
        statistics.fmean(
            differences[rng.randrange(size)] for _ in range(size)
        )
        for _ in range(resamples)
    ]
    return (_percentile(estimates, 0.025), _percentile(estimates, 0.975))


def _comparison(
    outcomes: Sequence[TaskPolicyOutcome],
    *,
    comparison_id: str,
    role: Literal["primary_development", "secondary_arm", "secondary_ablation"],
    policy_a: str,
    policy_b: str,
    holm_adjusted_p: float | None = None,
) -> DevelopmentPolicyComparison:
    by_key = {(item.policy_id, item.unit_id): item for item in outcomes}
    unit_ids = sorted(
        item.unit_id for item in outcomes if item.policy_id == policy_a
    )
    differences: list[float] = []
    favorable = 0
    unfavorable = 0
    tied = 0
    for unit_id in unit_ids:
        first = by_key[(policy_a, unit_id)].task_success
        second = by_key[(policy_b, unit_id)].task_success
        difference = float(int(first) - int(second))
        differences.append(difference)
        if difference > 0:
            favorable += 1
        elif difference < 0:
            unfavorable += 1
        else:
            tied += 1
    return DevelopmentPolicyComparison.create(
        comparison_id=comparison_id,
        role=role,
        policy_a=policy_a,
        policy_b=policy_b,
        task_count=len(unit_ids),
        favorable_to_a=favorable,
        unfavorable_to_a=unfavorable,
        tied=tied,
        risk_difference_a_minus_b=statistics.fmean(differences),
        bootstrap_interval_95=_paired_bootstrap_interval(
            differences,
            seed_material=comparison_id,
        ),
        exact_mcnemar_p=exact_two_sided_sign_test_pvalue(
            favorable,
            unfavorable,
        ),
        holm_adjusted_p=holm_adjusted_p,
    )


def _holm_adjustments(
    comparisons: Sequence[DevelopmentPolicyComparison],
) -> dict[str, float]:
    ordered = sorted(
        comparisons,
        key=lambda item: (item.exact_mcnemar_p, item.comparison_id),
    )
    size = len(ordered)
    adjusted: dict[str, float] = {}
    running = 0.0
    for index, item in enumerate(ordered):
        candidate = min(1.0, (size - index) * item.exact_mcnemar_p)
        running = max(running, candidate)
        adjusted[item.comparison_id] = running
    return adjusted


def _rank_with_ties(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: (values[index], index))
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position + 1
        while end < len(order) and values[order[end]] == values[order[position]]:
            end += 1
        average_rank = (position + 1 + end) / 2.0
        for index in order[position:end]:
            ranks[index] = average_rank
        position = end
    return ranks


def _pearson(first: Sequence[float], second: Sequence[float]) -> float | None:
    if len(first) < 2 or len(first) != len(second):
        return None
    first_mean = statistics.fmean(first)
    second_mean = statistics.fmean(second)
    numerator = sum(
        (left - first_mean) * (right - second_mean)
        for left, right in zip(first, second, strict=True)
    )
    first_ss = sum((value - first_mean) ** 2 for value in first)
    second_ss = sum((value - second_mean) ** 2 for value in second)
    denominator = math.sqrt(first_ss * second_ss)
    if denominator == 0:
        return None
    return max(-1.0, min(1.0, numerator / denominator))


def _fidelity_calibrations(
    freeze: DevelopmentSearchFreeze,
    results: Sequence[SearchAssignmentResult],
) -> list[FidelityCalibration]:
    calibrations: list[FidelityCalibration] = []
    for policy in freeze.policies:
        policy_results = [
            item for item in results if item.policy_id == policy.policy_id
        ]
        for low_stage in ("F1", "F2"):
            paired_seed_values: dict[str, list[tuple[float, float]]] = {}
            for result in policy_results:
                if result.selected_candidate_id is None or result.policy_score is None:
                    continue
                matches = [
                    record
                    for record in result.stage_records
                    if record.stage == low_stage
                    and record.candidate_id == result.selected_candidate_id
                    and record.status is StageRecordStatus.EXECUTED
                    and record.objective_score is not None
                ]
                if len(matches) == 1:
                    objective_score = matches[0].objective_score
                    if objective_score is None:
                        continue
                    paired_seed_values.setdefault(result.unit_id, []).append(
                        (objective_score, result.policy_score)
                    )
            low_values = [
                statistics.median(
                    [pair[0] for pair in paired_seed_values[unit_id]]
                )
                for unit_id in sorted(paired_seed_values)
            ]
            high_values = [
                statistics.median(
                    [pair[1] for pair in paired_seed_values[unit_id]]
                )
                for unit_id in sorted(paired_seed_values)
            ]
            rho = _pearson(
                _rank_with_ties(low_values),
                _rank_with_ties(high_values),
            )
            calibrations.append(
                FidelityCalibration.create(
                    policy_id=policy.policy_id,
                    low_stage=low_stage,
                    pair_count=len(low_values),
                    spearman_rho=rho,
                    mean_absolute_error=(
                        statistics.fmean(
                            abs(low - high)
                            for low, high in zip(
                                low_values,
                                high_values,
                                strict=True,
                            )
                        )
                        if low_values
                        else None
                    ),
                )
            )
    return sorted(
        calibrations,
        key=lambda item: (item.policy_id, item.low_stage),
    )


def analyze_development_search(
    freeze: DevelopmentSearchFreeze,
    results: Sequence[SearchAssignmentResult],
) -> DevelopmentSearchAnalysis:
    """Aggregate only at the independent task level and retain all null results."""

    outcomes = _task_outcomes(freeze, results)
    summaries = _policy_summaries(outcomes, results)
    primary = _comparison(
        outcomes,
        comparison_id="portfolio-memory-vs-linear-self-loop",
        role="primary_development",
        policy_a=StudyArm.PORTFOLIO_MEMORY.value,
        policy_b=StudyArm.LINEAR_SELF_LOOP.value,
    )
    arms = [item.value for item in StudyArm]
    secondary_arms: list[DevelopmentPolicyComparison] = []
    for index, first in enumerate(arms):
        for second in arms[index + 1 :]:
            if {first, second} == {
                StudyArm.PORTFOLIO_MEMORY.value,
                StudyArm.LINEAR_SELF_LOOP.value,
            }:
                continue
            secondary_arms.append(
                _comparison(
                    outcomes,
                    comparison_id=f"{first}-vs-{second}",
                    role="secondary_arm",
                    policy_a=first,
                    policy_b=second,
                )
            )
    raw_ablations = [
        _comparison(
            outcomes,
            comparison_id=f"portfolio-memory-vs-ablation-{ablation.value}",
            role="secondary_ablation",
            policy_a=StudyArm.PORTFOLIO_MEMORY.value,
            policy_b=f"ablation-{ablation.value}",
        )
        for ablation in StudyAblation
    ]
    secondary_family = [*secondary_arms, *raw_ablations]
    adjusted = _holm_adjustments(secondary_family)
    adjusted_arms = [
        _comparison(
            outcomes,
            comparison_id=item.comparison_id,
            role="secondary_arm",
            policy_a=item.policy_a,
            policy_b=item.policy_b,
            holm_adjusted_p=adjusted[item.comparison_id],
        )
        for item in secondary_arms
    ]
    adjusted_ablations = [
        _comparison(
            outcomes,
            comparison_id=item.comparison_id,
            role="secondary_ablation",
            policy_a=item.policy_a,
            policy_b=item.policy_b,
            holm_adjusted_p=adjusted[item.comparison_id],
        )
        for item in raw_ablations
    ]
    calibrations = _fidelity_calibrations(freeze, results)
    summary_by_id = {item.policy_id: item for item in summaries}
    memory_summary = summary_by_id[StudyArm.PORTFOLIO_MEMORY.value]
    memory_calibrations = [
        item
        for item in calibrations
        if item.policy_id == StudyArm.PORTFOLIO_MEMORY.value
    ]
    survival_checks = {
        "development_task_success_floor": (
            memory_summary.task_success_count
            >= freeze.minimum_development_task_successes
        ),
        "f1_f3_calibration": any(
            item.low_stage == "F1"
            and item.spearman_rho is not None
            and item.spearman_rho >= freeze.minimum_low_high_spearman
            for item in memory_calibrations
        ),
        "f2_f3_calibration": any(
            item.low_stage == "F2"
            and item.spearman_rho is not None
            and item.spearman_rho >= freeze.minimum_low_high_spearman
            for item in memory_calibrations
        ),
        "nonnegative_primary_risk_difference": (
            primary.risk_difference_a_minus_b >= 0
        ),
        "zero_integrity_or_budget_failures": (
            memory_summary.failure_assignment_count == 0
        ),
    }
    survivors = (
        [StudyArm.PORTFOLIO_MEMORY.value]
        if all(survival_checks.values())
        else []
    )
    return DevelopmentSearchAnalysis.create(
        task_outcomes=outcomes,
        policy_summaries=summaries,
        arm_comparisons=sorted(
            [primary, *adjusted_arms],
            key=lambda item: item.comparison_id,
        ),
        ablation_comparisons=sorted(
            adjusted_ablations,
            key=lambda item: item.comparison_id,
        ),
        fidelity_calibrations=calibrations,
        holm_family_size=len(secondary_family),
        surviving_policy_ids=survivors,
        survival_checks=survival_checks,
    )


DEVELOPMENT_SEARCH_CONTRACT_MODELS = (
    CandidateSpec,
    CandidateInitialization,
    DevelopmentLabels,
    DevelopmentLabelPreparationAudit,
    DevelopmentInput,
    PolicyRealization,
    DevelopmentAssignment,
    DevelopmentBudgetRealization,
    DevelopmentRepairLineage,
    DevelopmentSearchFreeze,
    CandidateEvaluation,
    CandidateStageRecord,
    AssignmentCostAudit,
    SearchAssignmentResult,
    TaskPolicyOutcome,
    PolicyDevelopmentSummary,
    DevelopmentPolicyComparison,
    FidelityCalibration,
    DevelopmentSearchAnalysis,
    DevelopmentSearchReport,
    DevelopmentSearchArtifactManifest,
)


def development_search_json_schemas() -> dict[str, dict[str, Any]]:
    return {
        model.__name__: model.model_json_schema()
        for model in DEVELOPMENT_SEARCH_CONTRACT_MODELS
    }


def render_development_search_markdown(
    report: DevelopmentSearchReport,
) -> str:
    """Render a compact, non-promotional development handoff."""

    report.verify_integrity()
    primary = next(
        item
        for item in report.analysis.arm_comparisons
        if item.role == "primary_development"
    )
    rows = [
        "# Budget-matched multi-branch development search",
        "",
        f"- Status: `{report.status.value}`",
        f"- Report hash: `{report.report_hash}`",
        f"- Complete assignments: `{report.assignment_count}`",
        f"- Retained candidate-stage records: `{report.candidate_stage_record_count}`",
        f"- Unique objective evaluations: `{report.unique_evaluation_count}`",
        f"- Unique evaluation failures: `{report.evaluation_failure_count}`",
        f"- Cache reuses recorded: `{report.evaluation_cache_reuse_count}`",
        "- Independent analysis unit: `OpenML task`; three seeds are repeated measures",
        "- Confirmatory payloads downloaded: `false`",
        "- LLM reviewer score used as scientific evidence: `false`",
        "",
        "## Policy outcomes",
        "",
        "| Policy | Task successes | Rate | Invalid assignments | New CPU seconds |",
        "|---|---:|---:|---:|---:|",
    ]
    rows.extend(
        (
            f"| `{item.policy_id}` | {item.task_success_count}/{item.task_count} | "
            f"{item.task_success_rate:.3f} | {item.failure_assignment_count} | "
            f"{item.newly_executed_cpu_seconds:.3f} |"
        )
        for item in report.analysis.policy_summaries
    )
    rows.extend(
        [
            "",
            "## Frozen primary development comparison",
            "",
            (
                f"`{primary.policy_a}` minus `{primary.policy_b}`: risk difference "
                f"`{primary.risk_difference_a_minus_b:.3f}`, 95% paired task bootstrap "
                f"`[{primary.bootstrap_interval_95[0]:.3f}, "
                f"{primary.bootstrap_interval_95[1]:.3f}]`, exact McNemar "
                f"`p={primary.exact_mcnemar_p:.6f}`."
            ),
            "",
            "This is development evidence only. It is not the preregistered "
            "confirmatory inference.",
            "",
            "## Low-to-high fidelity calibration",
            "",
            "| Policy | Low stage | Pairs | Spearman rho | MAE |",
            "|---|---|---:|---:|---:|",
        ]
    )
    rows.extend(
        "| `{}` | `{}` | {} | {} | {} |".format(
            item.policy_id,
            item.low_stage,
            item.pair_count,
            (
                f"{item.spearman_rho:.3f}"
                if item.spearman_rho is not None
                else "NA"
            ),
            (
                f"{item.mean_absolute_error:.4f}"
                if item.mean_absolute_error is not None
                else "NA"
            ),
        )
        for item in report.analysis.fidelity_calibrations
    )
    rows.extend(["", "## Development survival gate", ""])
    rows.extend(
        f"- `{check_id}`: `{str(passed).lower()}`"
        for check_id, passed in report.analysis.survival_checks.items()
    )
    rows.extend(
        [
            "",
            (
                "Surviving policy: "
                + (
                    f"`{report.analysis.surviving_policy_ids[0]}`."
                    if report.analysis.surviving_policy_ids
                    else "`none`; the valid endpoint is negative development."
                )
            ),
            "",
        ]
    )
    return "\n".join(rows)


def _assignment_result_path(
    output_dir: Path,
    assignment: DevelopmentAssignment,
) -> Path:
    return output_dir / "assignments" / assignment.assignment_id / "result.json"


def _load_assignment_result(path: Path) -> SearchAssignmentResult:
    result = SearchAssignmentResult.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    result.verify_integrity()
    return result


def _verify_exact_assignment_resume(
    freeze: DevelopmentSearchFreeze,
    output_dir: Path,
) -> list[SearchAssignmentResult]:
    policy_by_id = {item.policy_id: item for item in freeze.policies}
    memory_by_policy = {
        item.policy_id: _empty_memory_state() for item in freeze.policies
    }
    seen_evaluation_hashes: set[str] = set()
    results: list[SearchAssignmentResult] = []
    for assignment in freeze.assignments:
        path = _assignment_result_path(output_dir, assignment)
        if not path.exists():
            raise PortfolioIntegrityError(
                f"assignment result is missing: {assignment.assignment_id}"
            )
        result = _load_assignment_result(path)
        if result.assignment_hash != assignment.assignment_hash:
            raise PortfolioIntegrityError("assignment result binds a different row")
        if result.freeze_hash != freeze.freeze_hash:
            raise PortfolioIntegrityError("assignment result binds a different freeze")
        state = memory_by_policy[assignment.policy_id]
        if result.memory_before_hash != _memory_hash(state):
            raise PortfolioIntegrityError(
                "assignment resume memory-before hash mismatch"
            )
        _update_memory_from_result(
            state,
            result,
            enabled=policy_by_id[
                assignment.policy_id
            ].comparative_memory_enabled,
        )
        if result.memory_after_hash != _memory_hash(state):
            raise PortfolioIntegrityError(
                "assignment resume memory-after hash mismatch"
            )
        for record in result.stage_records:
            if record.evaluation_hash is None:
                continue
            expected_reuse = record.evaluation_hash in seen_evaluation_hashes
            if record.cache_reused != expected_reuse:
                raise PortfolioIntegrityError(
                    "assignment logical cache-reuse provenance mismatch"
                )
            seen_evaluation_hashes.add(record.evaluation_hash)
        results.append(result)
    return results


def _evaluation_records(
    output_dir: Path,
) -> list[CandidateEvaluation]:
    records: list[CandidateEvaluation] = []
    cache_root = output_dir / "evaluation-cache"
    if not cache_root.exists():
        return records
    for path in sorted(cache_root.glob("*/evaluation.json")):
        records.append(_load_cached_evaluation(path))
    hashes = [item.evaluation_hash for item in records]
    if len(hashes) != len(set(hashes)):
        raise PortfolioIntegrityError("evaluation cache contains duplicate hashes")
    return records


def _write_development_manifest(
    output_dir: Path,
    freeze: DevelopmentSearchFreeze,
    report: DevelopmentSearchReport,
) -> DevelopmentSearchArtifactManifest:
    manifest_path = output_dir / DEVELOPMENT_MANIFEST_FILENAME
    files = {
        path.relative_to(output_dir).as_posix(): _file_sha256(path)
        for path in sorted(output_dir.rglob("*"))
        if path.is_file()
        and path != manifest_path
        and not path.name.endswith(".tmp")
    }
    manifest = DevelopmentSearchArtifactManifest.create(
        freeze_hash=freeze.freeze_hash,
        report_hash=report.report_hash,
        files=files,
    )
    _write_text_atomic(manifest_path, manifest.canonical_json() + "\n")
    return manifest


def _verify_manifest_files(
    output_dir: Path,
    manifest: DevelopmentSearchArtifactManifest,
) -> None:
    manifest_path = output_dir / DEVELOPMENT_MANIFEST_FILENAME
    current = {
        path.relative_to(output_dir).as_posix()
        for path in output_dir.rglob("*")
        if path.is_file()
        and path != manifest_path
        and not path.name.endswith(".tmp")
    }
    if current != set(manifest.files):
        missing = sorted(set(manifest.files) - current)
        extra = sorted(current - set(manifest.files))
        raise PortfolioIntegrityError(
            f"manifest inventory mismatch; missing={missing}, extra={extra}"
        )
    for relative_path, expected_hash in manifest.files.items():
        if _file_sha256(output_dir / relative_path) != expected_hash:
            raise PortfolioIntegrityError(
                f"development manifest file hash mismatch: {relative_path}"
            )


def run_development_search(
    baseline_dir: Path,
    output_dir: Path,
    *,
    completed_at: datetime | None = None,
    progress: Callable[[str], None] | None = None,
) -> DevelopmentSearchReport:
    """Execute or exactly resume all 189 development assignments."""

    report_path = output_dir / DEVELOPMENT_REPORT_FILENAME
    manifest_path = output_dir / DEVELOPMENT_MANIFEST_FILENAME
    if report_path.exists() or manifest_path.exists():
        if not report_path.exists() or not manifest_path.exists():
            raise PortfolioIntegrityError(
                "partial top-level development report/manifest state"
            )
        report, _, _ = load_development_search_report(output_dir)
        return report

    freeze = load_development_search_freeze(output_dir)
    baseline_report, preregistration, _ = load_baseline_preregistration(
        baseline_dir
    )
    if freeze.baseline_report_hash != baseline_report.report_hash:
        raise PortfolioIntegrityError("development freeze baseline report mismatch")
    if freeze.preregistration_hash != preregistration.preregistration_hash:
        raise PortfolioIntegrityError("development freeze preregistration mismatch")

    policy_by_id = {item.policy_id: item for item in freeze.policies}
    memory_by_policy = {
        item.policy_id: _empty_memory_state() for item in freeze.policies
    }
    seen_evaluation_hashes: set[str] = set()
    for index, assignment in enumerate(freeze.assignments, start=1):
        state = memory_by_policy[assignment.policy_id]
        result_path = _assignment_result_path(output_dir, assignment)
        if result_path.exists():
            result = _load_assignment_result(result_path)
            if result.assignment_hash != assignment.assignment_hash:
                raise PortfolioIntegrityError("partial result assignment mismatch")
            if result.memory_before_hash != _memory_hash(state):
                raise PortfolioIntegrityError("partial result memory order mismatch")
            _update_memory_from_result(
                state,
                result,
                enabled=policy_by_id[
                    assignment.policy_id
                ].comparative_memory_enabled,
            )
            if result.memory_after_hash != _memory_hash(state):
                raise PortfolioIntegrityError(
                    "partial result memory-after mismatch"
                )
            for record in result.stage_records:
                if record.evaluation_hash is None:
                    continue
                expected_reuse = (
                    record.evaluation_hash in seen_evaluation_hashes
                )
                if record.cache_reused != expected_reuse:
                    raise PortfolioIntegrityError(
                        "partial result logical cache provenance mismatch"
                    )
                seen_evaluation_hashes.add(record.evaluation_hash)
            action = "resumed"
        else:
            result = _execute_assignment(
                freeze,
                preregistration,
                assignment,
                state,
                output_dir=output_dir,
                seen_evaluation_hashes=seen_evaluation_hashes,
            )
            _write_text_atomic(
                result_path,
                result.canonical_json() + "\n",
            )
            action = "executed"
        if progress is not None:
            progress(
                f"{index}/{len(freeze.assignments)} {action} "
                f"{assignment.assignment_id} success={result.objective_task_success}"
            )

    results = _verify_exact_assignment_resume(freeze, output_dir)
    if len(results) != len(freeze.assignments):
        raise PortfolioIntegrityError("development assignment matrix is incomplete")
    analysis = analyze_development_search(freeze, results)
    evaluations = _evaluation_records(output_dir)
    referenced_evaluation_hashes = {
        record.evaluation_hash
        for result in results
        for record in result.stage_records
        if record.evaluation_hash is not None
    }
    available_evaluation_hashes = {
        item.evaluation_hash for item in evaluations
    }
    if referenced_evaluation_hashes != available_evaluation_hashes:
        raise PortfolioIntegrityError(
            "assignment/evaluation provenance inventory mismatch"
        )
    if any(
        item.status is EvaluationStatus.SUCCEEDED
        and item.stage == "F3"
        and item.replay_exact is not True
        for item in evaluations
    ):
        raise PortfolioIntegrityError("successful F3 evaluation lacks exact replay")
    assignment_hashes = {
        assignment.assignment_id: result.result_hash
        for assignment, result in zip(
            freeze.assignments,
            results,
            strict=True,
        )
    }
    report = DevelopmentSearchReport.create(
        report_id="task-263.5-budget-matched-development-search",
        freeze_hash=freeze.freeze_hash,
        baseline_report_hash=freeze.baseline_report_hash,
        preregistration_hash=freeze.preregistration_hash,
        status=(
            DevelopmentSearchStatus.READY_FOR_CONFIRMATION
            if analysis.surviving_policy_ids
            else DevelopmentSearchStatus.NEGATIVE_DEVELOPMENT
        ),
        assignment_result_hashes=assignment_hashes,
        assignment_count=len(results),
        candidate_stage_record_count=sum(
            len(item.stage_records) for item in results
        ),
        unique_evaluation_count=len(evaluations),
        evaluation_failure_count=sum(
            item.status is EvaluationStatus.FAILED for item in evaluations
        ),
        evaluation_cache_reuse_count=sum(
            record.cache_reused is True
            for result in results
            for record in result.stage_records
        ),
        analysis=analysis,
        completed_at=completed_at or datetime.now(timezone.utc),
    )
    _write_text_atomic(report_path, report.canonical_json() + "\n")
    _write_text_atomic(
        output_dir / DEVELOPMENT_MARKDOWN_FILENAME,
        render_development_search_markdown(report),
    )
    _write_text_atomic(
        output_dir / DEVELOPMENT_SCHEMA_FILENAME,
        json.dumps(
            development_search_json_schemas(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
    )
    manifest = _write_development_manifest(output_dir, freeze, report)
    _verify_manifest_files(output_dir, manifest)
    return report


def load_development_search_report(
    output_dir: Path,
) -> tuple[
    DevelopmentSearchReport,
    DevelopmentSearchFreeze,
    DevelopmentSearchArtifactManifest,
]:
    """Load and recursively verify a complete Task 263.5 development run."""

    freeze = load_development_search_freeze(output_dir)
    report = DevelopmentSearchReport.model_validate_json(
        (output_dir / DEVELOPMENT_REPORT_FILENAME).read_text(encoding="utf-8")
    )
    manifest = DevelopmentSearchArtifactManifest.model_validate_json(
        (output_dir / DEVELOPMENT_MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    report.verify_integrity()
    manifest.verify_integrity()
    if report.freeze_hash != freeze.freeze_hash:
        raise PortfolioIntegrityError("development report freeze mismatch")
    if manifest.freeze_hash != freeze.freeze_hash:
        raise PortfolioIntegrityError("development manifest freeze mismatch")
    if manifest.report_hash != report.report_hash:
        raise PortfolioIntegrityError("development manifest report mismatch")
    _verify_manifest_files(output_dir, manifest)
    results = _verify_exact_assignment_resume(freeze, output_dir)
    observed_hashes = {
        assignment.assignment_id: result.result_hash
        for assignment, result in zip(
            freeze.assignments,
            results,
            strict=True,
        )
    }
    if observed_hashes != report.assignment_result_hashes:
        raise PortfolioIntegrityError("development report assignment inventory mismatch")
    return report, freeze, manifest


def _cli() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("freeze", "run", "verify"))
    parser.add_argument("--baseline-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--panel",
        type=Path,
        default=Path(
            "runs/manual-live/task26341-open-objective-panel-v1/"
            "open-objective-task-panel.json"
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/campaign/ollama-qwen35-9b.yaml"),
    )
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument(
        "--predecessor-dir",
        type=Path,
        help=(
            "Verified complete diagnostic run whose candidate ordering must be "
            "reused for an evaluator-only repair freeze."
        ),
    )
    args = parser.parse_args()
    if args.action == "freeze":
        freeze = freeze_development_search(
            args.baseline_dir,
            args.output_dir,
            panel_path=args.panel,
            config_path=args.config,
            env_path=args.env,
            predecessor_dir=args.predecessor_dir,
        )
        print(
            json.dumps(
                {
                    "status": "frozen_result_blind",
                    "freeze_hash": freeze.freeze_hash,
                    "assignments": len(freeze.assignments),
                    "candidates": len(freeze.candidates),
                    "confirmatory_payloads_downloaded": False,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return 0
    if args.action == "run":
        report = run_development_search(
            args.baseline_dir,
            args.output_dir,
            progress=lambda message: print(message, flush=True),
        )
        print(
            json.dumps(
                {
                    "status": report.status.value,
                    "report_hash": report.report_hash,
                    "assignments": report.assignment_count,
                    "surviving_policy_ids": (
                        report.analysis.surviving_policy_ids
                    ),
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return 0
    report, freeze, manifest = load_development_search_report(args.output_dir)
    print(
        json.dumps(
            {
                "status": report.status.value,
                "freeze_hash": freeze.freeze_hash,
                "report_hash": report.report_hash,
                "manifest_hash": manifest.manifest_hash,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
