"""Clean-room baseline and causal preregistration contracts for Task 263.4.2.

The task panel establishes that a study *could* be run.  This module adds the
next non-compensatory gate: a strong open baseline must replay from raw
predictions in two isolated workspaces, and the complete causal design must be
content-addressed before development search begins.

The resulting claim remains deliberately narrow.  It concerns budget-matched
search policies on an objective tabular-ML panel, not general autonomous
science or autonomous publication.
"""

from __future__ import annotations

import hashlib
import json
import math
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from autoresearch.kernel.contracts import (
    KernelContract,
    NonEmptyText,
    Sha256,
    StableId,
    canonical_sha256,
)

from .objective_task_panel import (
    ObjectiveMetric,
    OpenObjectiveTaskPanelReport,
    OpenTaskPanelStatus,
)
from .objective_task_registry import (
    ObjectiveTaskFamily,
    PanelPartition,
    frozen_source_registry_hash,
)
from .portfolio import PortfolioIntegrityError
from .search_policy_study import StudyAblation, StudyArm


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value


BASELINE_ID = "flaml-2.6.0-bounded-automl-v1"
BASELINE_RUNNER_SOURCE_PATH = "src/autoresearch/research/assets/frozen_flaml_baseline_v1.py"
BASELINE_SEED = 263_420_001
FROZEN_WITHIN_UNIT_SEEDS = [1_729, 3_253, 7_919]
FROZEN_ESTIMATOR_LIST = ["lgbm", "xgboost", "rf", "extra_tree"]
FROZEN_MAX_TRIALS = 12
FROZEN_VALIDATION_FRACTION = 0.20
FROZEN_REPLAY_TOLERANCE = 1e-12
FROZEN_DEPENDENCY_VERSIONS = {
    "flaml": "2.6.0",
    "joblib": "1.5.3",
    "lightgbm": "4.7.0",
    "narwhals": "2.24.0",
    "numpy": "2.2.6",
    "pandas": "2.3.3",
    "python-dateutil": "2.9.0.post0",
    "pytz": "2026.3.post1",
    "scikit-learn": "1.7.2",
    "scipy": "1.15.3",
    "six": "1.17.0",
    "threadpoolctl": "3.6.0",
    "tzdata": "2026.3",
    "xgboost": "2.1.4",
}
REQUIRED_BASELINE_SOURCE_KEYS = {
    "flaml-license",
    "flaml-paper",
    "flaml-pypi",
    "scikit-learn-pypi",
}
REQUIRED_DESIGN_SOURCE_KEYS = {
    "ai-scientist-nature",
    "flaml",
    "mars",
    "ml-agent-search",
    "ml-resource-benchmark",
    "mlrc-bench",
    "paperbench",
}
FROZEN_OPERATOR_GRAMMAR = [
    "change one learner family",
    "change one preprocessing decision",
    "change at most two learner hyperparameters",
    "add or remove one ensemble member",
    "revert to one previously valid candidate",
]
FROZEN_SEALED_RUNNER_PERMISSIONS = [
    "deny network and external tools during task execution",
    "expose opaque task and feature identifiers only",
    "read only the assigned task bundle and frozen baseline",
    "withhold confirmatory labels from search policies",
    "deny repository vault prior runs credentials and public leaderboards",
    "write only to the assigned content-addressed artifact directory",
]
FROZEN_STOP_RULES = [
    "stop and invalidate the affected task if evaluator or artifact integrity fails",
    "stop the entire study if confirmatory leakage is detected",
    "stop the affected arm if its preregistered compute or model budget is exceeded",
    "do not stop early for a favorable or unfavorable scientific effect",
    "finish the frozen task-arm-seed matrix before primary analysis",
]
FROZEN_FAILURE_POLICY = (
    "arm-attributable timeout, invalid prediction, missing artifact, or replay "
    "failure counts as task failure; infrastructure-wide task invalidity excludes "
    "that task symmetrically before labels or arm outcomes are inspected"
)
FROZEN_CLAIM_SCOPE = (
    "Under matched candidate, model-call, and compute caps on the frozen open "
    "tabular-ML panel, portfolio-plus-comparative-memory search changes the "
    "probability of objectively confirmed task success relative to a linear "
    "self-loop."
)


class BaselineGateStatus(str, Enum):
    """State of the clean baseline and result-free preregistration gate."""

    BLOCKED = "blocked"
    BASELINE_REPRODUCED = "baseline_reproduced"
    READY_FOR_DEVELOPMENT_SEARCH = "ready_for_development_search"


class PinnedDistribution(KernelContract):
    """One exact wheel admitted to the isolated baseline environment."""

    schema_version: Literal["pinned-distribution-v1"] = "pinned-distribution-v1"
    name: StableId
    version: NonEmptyText
    filename: NonEmptyText
    wheel_sha256: Sha256
    pypi_json_sha256: Sha256
    license_id: NonEmptyText
    distribution_hash: Sha256

    @model_validator(mode="after")
    def _validate_distribution(self) -> PinnedDistribution:
        expected_version = FROZEN_DEPENDENCY_VERSIONS.get(self.name)
        if expected_version is None:
            raise ValueError(f"unapproved baseline dependency: {self.name}")
        if self.version != expected_version:
            raise ValueError(f"{self.name} must remain pinned to {expected_version}")
        if not self.filename.endswith(".whl"):
            raise ValueError("clean baseline dependencies must use wheels")
        if self.distribution_hash != self.calculated_hash():
            raise PortfolioIntegrityError("distribution_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> PinnedDistribution:
        payload = dict(values)
        payload["schema_version"] = "pinned-distribution-v1"
        payload["distribution_hash"] = canonical_sha256(payload)
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"distribution_hash"}))

    def verify_integrity(self) -> None:
        if self.distribution_hash != self.calculated_hash():
            raise PortfolioIntegrityError("distribution_hash mismatch")


class BaselineEnvironmentLock(KernelContract):
    """Exact two-venv environment used by the independent baseline replays."""

    schema_version: Literal["baseline-environment-lock-v1"] = "baseline-environment-lock-v1"
    python_version: NonEmptyText
    platform_tag: NonEmptyText
    base_interpreter_sha256: Sha256
    distributions: list[PinnedDistribution] = Field(min_length=1)
    dependency_lock_hash: Sha256
    virtual_environment_count: Literal[2] = 2
    installation_from_verified_wheelhouse: Literal[True] = True
    execution_network_allowed: Literal[False] = False
    n_jobs: Literal[1] = 1
    environment_hash: Sha256

    @field_validator("distributions")
    @classmethod
    def _sort_distributions(
        cls,
        value: list[PinnedDistribution],
    ) -> list[PinnedDistribution]:
        normalized = sorted(value, key=lambda item: item.name)
        names = [item.name for item in normalized]
        if len(names) != len(set(names)):
            raise ValueError("dependency distributions must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_environment(self) -> BaselineEnvironmentLock:
        if not self.python_version.startswith("3.10."):
            raise ValueError("Task 263.4.2 freezes the compatible Python 3.10 line")
        if {item.name: item.version for item in self.distributions} != (FROZEN_DEPENDENCY_VERSIONS):
            raise ValueError("dependency set does not match the frozen lock")
        for distribution in self.distributions:
            distribution.verify_integrity()
        expected_lock = canonical_sha256(
            [item.model_dump(mode="json") for item in self.distributions]
        )
        if self.dependency_lock_hash != expected_lock:
            raise PortfolioIntegrityError("dependency_lock_hash mismatch")
        if self.environment_hash != self.calculated_hash():
            raise PortfolioIntegrityError("environment_hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        python_version: str,
        platform_tag: str,
        base_interpreter_sha256: str,
        distributions: list[PinnedDistribution],
    ) -> BaselineEnvironmentLock:
        normalized = sorted(distributions, key=lambda item: item.name)
        payload: dict[str, Any] = {
            "schema_version": "baseline-environment-lock-v1",
            "python_version": python_version,
            "platform_tag": platform_tag,
            "base_interpreter_sha256": base_interpreter_sha256,
            "distributions": [item.model_dump(mode="json") for item in normalized],
            "dependency_lock_hash": canonical_sha256(
                [item.model_dump(mode="json") for item in normalized]
            ),
            "virtual_environment_count": 2,
            "installation_from_verified_wheelhouse": True,
            "execution_network_allowed": False,
            "n_jobs": 1,
        }
        payload["environment_hash"] = canonical_sha256(payload)
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"environment_hash"}))

    def verify_integrity(self) -> None:
        for distribution in self.distributions:
            distribution.verify_integrity()
        if self.environment_hash != self.calculated_hash():
            raise PortfolioIntegrityError("environment_hash mismatch")


class CleanBaselineSpecification(KernelContract):
    """Outcome-blind definition of the strong baseline and split protocol."""

    schema_version: Literal["clean-baseline-specification-v1"] = "clean-baseline-specification-v1"
    baseline_id: Literal["flaml-2.6.0-bounded-automl-v1"] = "flaml-2.6.0-bounded-automl-v1"
    panel_report_hash: Sha256
    source_registry_hash: Sha256
    evaluator_source_hash: Sha256
    baseline_source_snapshot_hashes: dict[StableId, Sha256]
    runner_source_path: Literal["src/autoresearch/research/assets/frozen_flaml_baseline_v1.py"] = (
        "src/autoresearch/research/assets/frozen_flaml_baseline_v1.py"
    )
    runner_source_hash: Sha256
    environment_hash: Sha256
    development_unit_ids: list[StableId]
    confirmatory_unit_ids: list[StableId]
    metric_ids: dict[StableId, ObjectiveMetric]
    split_rule: Literal["OpenML repeat=0 fold=0 sample=0"] = "OpenML repeat=0 fold=0 sample=0"
    estimator_list: list[Literal["lgbm", "xgboost", "rf", "extra_tree"]]
    max_trials: Literal[12] = 12
    validation_fraction: float = FROZEN_VALIDATION_FRACTION
    seed: Literal[263420001] = 263420001
    n_jobs: Literal[1] = 1
    replay_tolerance: float = FROZEN_REPLAY_TOLERANCE
    maximum_seconds_per_task_run: Literal[600] = 600
    maximum_memory_mb: Literal[4096] = 4096
    confirmatory_payloads_downloaded: Literal[False] = False
    public_benchmark_runs_queried: Literal[False] = False
    study_outcomes_observed: Literal[False] = False
    specification_hash: Sha256

    @field_validator("development_unit_ids", "confirmatory_unit_ids")
    @classmethod
    def _sort_unique_ids(cls, value: list[str]) -> list[str]:
        normalized = sorted(value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("baseline unit IDs must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_specification(self) -> CleanBaselineSpecification:
        if self.source_registry_hash != frozen_source_registry_hash():
            raise PortfolioIntegrityError("source registry hash mismatch")
        if set(self.baseline_source_snapshot_hashes) != (REQUIRED_BASELINE_SOURCE_KEYS):
            raise ValueError("baseline source snapshot set is incomplete")
        if len(self.development_unit_ids) != 7:
            raise ValueError("baseline reproduction must use all 7 development tasks")
        if len(self.confirmatory_unit_ids) != 60:
            raise ValueError("specification must retain all 60 sealed tasks")
        if set(self.development_unit_ids) & set(self.confirmatory_unit_ids):
            raise ValueError("development and confirmatory tasks overlap")
        if self.metric_ids != {
            ObjectiveTaskFamily.TABULAR_CLASSIFICATION.value: (ObjectiveMetric.BALANCED_ACCURACY),
            ObjectiveTaskFamily.TABULAR_REGRESSION.value: ObjectiveMetric.R2,
        }:
            raise ValueError("baseline metric mapping changed")
        if self.estimator_list != FROZEN_ESTIMATOR_LIST:
            raise ValueError("baseline estimator portfolio changed")
        if abs(self.validation_fraction - FROZEN_VALIDATION_FRACTION) > 1e-15:
            raise ValueError("baseline validation fraction changed")
        if abs(self.replay_tolerance - FROZEN_REPLAY_TOLERANCE) > 1e-18:
            raise ValueError("baseline replay tolerance changed")
        if self.specification_hash != self.calculated_hash():
            raise PortfolioIntegrityError("specification_hash mismatch")
        return self

    @classmethod
    def create_from_panel(
        cls,
        panel: OpenObjectiveTaskPanelReport,
        *,
        baseline_source_snapshot_hashes: dict[str, str],
        runner_source_hash: str,
        environment_hash: str,
    ) -> CleanBaselineSpecification:
        panel.verify_integrity()
        if panel.status is not OpenTaskPanelStatus.READY_FOR_CLEAN_BASELINE:
            raise ValueError("panel does not authorize clean baseline reproduction")
        evaluator_hashes = {unit.evaluator_source_hash for unit in panel.task_units}
        if len(evaluator_hashes) != 1:
            raise ValueError("panel does not bind one evaluator source")
        payload: dict[str, Any] = {
            "schema_version": "clean-baseline-specification-v1",
            "baseline_id": BASELINE_ID,
            "panel_report_hash": panel.report_hash,
            "source_registry_hash": panel.source_registry_hash,
            "evaluator_source_hash": next(iter(evaluator_hashes)),
            "baseline_source_snapshot_hashes": dict(
                sorted(baseline_source_snapshot_hashes.items())
            ),
            "runner_source_path": BASELINE_RUNNER_SOURCE_PATH,
            "runner_source_hash": runner_source_hash,
            "environment_hash": environment_hash,
            "development_unit_ids": sorted(panel.development_unit_ids),
            "confirmatory_unit_ids": sorted(panel.confirmatory_unit_ids),
            "metric_ids": {
                ObjectiveTaskFamily.TABULAR_CLASSIFICATION.value: (
                    ObjectiveMetric.BALANCED_ACCURACY
                ),
                ObjectiveTaskFamily.TABULAR_REGRESSION.value: ObjectiveMetric.R2,
            },
            "split_rule": "OpenML repeat=0 fold=0 sample=0",
            "estimator_list": FROZEN_ESTIMATOR_LIST,
            "max_trials": FROZEN_MAX_TRIALS,
            "validation_fraction": FROZEN_VALIDATION_FRACTION,
            "seed": BASELINE_SEED,
            "n_jobs": 1,
            "replay_tolerance": FROZEN_REPLAY_TOLERANCE,
            "maximum_seconds_per_task_run": 600,
            "maximum_memory_mb": 4096,
            "confirmatory_payloads_downloaded": False,
            "public_benchmark_runs_queried": False,
            "study_outcomes_observed": False,
        }
        payload["specification_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"specification_hash"}))

    def verify_integrity(self) -> None:
        if self.specification_hash != self.calculated_hash():
            raise PortfolioIntegrityError("specification_hash mismatch")


class BaselineTaskReplay(KernelContract):
    """Raw-prediction replay evidence for one development task."""

    schema_version: Literal["baseline-task-replay-v1"] = "baseline-task-replay-v1"
    replay_id: StableId
    unit_id: StableId
    family: ObjectiveTaskFamily
    metric_id: ObjectiveMetric
    data_sha256: Sha256
    split_sha256: Sha256
    input_bundle_hash: Sha256
    runner_source_hash: Sha256
    environment_hash: Sha256
    command_template_hash: Sha256
    seed: Literal[263420001] = 263420001
    run_a_id: StableId
    run_b_id: StableId
    run_a_workspace_hash: Sha256
    run_b_workspace_hash: Sha256
    run_a_process_id: int = Field(ge=1)
    run_b_process_id: int = Field(ge=1)
    run_a_prediction_hash: Sha256
    run_b_prediction_hash: Sha256
    prediction_count: int = Field(ge=1)
    run_a_score: float
    run_b_score: float
    tolerance: float = FROZEN_REPLAY_TOLERANCE
    run_a_trial_count: int = Field(ge=0)
    run_b_trial_count: int = Field(ge=0)
    run_a_seconds: float = Field(ge=0)
    run_b_seconds: float = Field(ge=0)
    maximum_seconds_per_run: Literal[600] = 600
    artifact_hashes: dict[NonEmptyText, Sha256]
    prediction_replay_exact: bool
    score_within_tolerance: bool
    budget_valid: bool
    independent_processes: bool
    passed: bool
    replay_hash: Sha256

    @model_validator(mode="after")
    def _validate_replay(self) -> BaselineTaskReplay:
        if not math.isfinite(self.run_a_score) or not math.isfinite(self.run_b_score):
            raise ValueError("baseline replay scores must be finite")
        expected_metric = (
            ObjectiveMetric.BALANCED_ACCURACY
            if self.family is ObjectiveTaskFamily.TABULAR_CLASSIFICATION
            else ObjectiveMetric.R2
        )
        if self.metric_id is not expected_metric:
            raise ValueError("replay metric does not match task family")
        if self.run_a_id == self.run_b_id:
            raise ValueError("clean replays require distinct run IDs")
        if abs(self.tolerance - FROZEN_REPLAY_TOLERANCE) > 1e-18:
            raise ValueError("baseline replay tolerance changed")
        if list(self.artifact_hashes) != sorted(self.artifact_hashes):
            raise ValueError("replay artifact hashes must be sorted")
        expected_exact = self.run_a_prediction_hash == self.run_b_prediction_hash
        expected_tolerance = abs(self.run_a_score - self.run_b_score) <= self.tolerance + 1e-15
        expected_budget = (
            self.run_a_trial_count == FROZEN_MAX_TRIALS
            and self.run_b_trial_count == FROZEN_MAX_TRIALS
            and self.run_a_seconds <= self.maximum_seconds_per_run
            and self.run_b_seconds <= self.maximum_seconds_per_run
        )
        expected_independent = (
            self.run_a_process_id != self.run_b_process_id
            and self.run_a_workspace_hash != self.run_b_workspace_hash
        )
        if self.prediction_replay_exact != expected_exact:
            raise ValueError("prediction replay flag does not match hashes")
        if self.score_within_tolerance != expected_tolerance:
            raise ValueError("score tolerance flag does not match scores")
        if self.budget_valid != expected_budget:
            raise ValueError("baseline budget flag does not match execution")
        if self.independent_processes != expected_independent:
            raise ValueError("independent process flag does not match evidence")
        expected_passed = (
            expected_exact and expected_tolerance and expected_budget and expected_independent
        )
        if self.passed != expected_passed:
            raise ValueError("baseline replay passed flag does not match evidence")
        if self.replay_hash != self.calculated_hash():
            raise PortfolioIntegrityError("replay_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> BaselineTaskReplay:
        payload = dict(values)
        payload.pop("replay_hash", None)
        payload.update(
            {
                "schema_version": "baseline-task-replay-v1",
                "seed": BASELINE_SEED,
                "tolerance": FROZEN_REPLAY_TOLERANCE,
                "maximum_seconds_per_run": 600,
            }
        )
        payload["artifact_hashes"] = dict(sorted(payload["artifact_hashes"].items()))
        payload["run_a_score"] = float(payload["run_a_score"])
        payload["run_b_score"] = float(payload["run_b_score"])
        payload["run_a_seconds"] = float(payload["run_a_seconds"])
        payload["run_b_seconds"] = float(payload["run_b_seconds"])
        payload["prediction_replay_exact"] = (
            payload["run_a_prediction_hash"] == payload["run_b_prediction_hash"]
        )
        payload["score_within_tolerance"] = (
            abs(payload["run_a_score"] - payload["run_b_score"]) <= FROZEN_REPLAY_TOLERANCE + 1e-15
        )
        payload["budget_valid"] = (
            payload["run_a_trial_count"] == FROZEN_MAX_TRIALS
            and payload["run_b_trial_count"] == FROZEN_MAX_TRIALS
            and payload["run_a_seconds"] <= 600
            and payload["run_b_seconds"] <= 600
        )
        payload["independent_processes"] = (
            payload["run_a_process_id"] != payload["run_b_process_id"]
            and payload["run_a_workspace_hash"] != payload["run_b_workspace_hash"]
        )
        payload["passed"] = all(
            payload[field_name]
            for field_name in (
                "prediction_replay_exact",
                "score_within_tolerance",
                "budget_valid",
                "independent_processes",
            )
        )
        payload["replay_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"replay_hash"}))

    def verify_integrity(self) -> None:
        if self.replay_hash != self.calculated_hash():
            raise PortfolioIntegrityError("replay_hash mismatch")


def _reproduction_blockers(
    *,
    specification: CleanBaselineSpecification,
    environment: BaselineEnvironmentLock,
    task_replays: list[BaselineTaskReplay],
    install_lock_verified: bool,
    runner_static_network_audit_passed: bool,
    workspace_roots_disjoint: bool,
) -> list[str]:
    blockers: set[str] = set()
    if specification.environment_hash != environment.environment_hash:
        blockers.add("baseline-environment-binding-mismatch")
    if not install_lock_verified:
        blockers.add("verified-wheelhouse-install-failed")
    if not runner_static_network_audit_passed:
        blockers.add("baseline-runner-network-audit-failed")
    if not workspace_roots_disjoint:
        blockers.add("clean-workspaces-not-disjoint")
    replay_ids = {item.unit_id for item in task_replays}
    if replay_ids != set(specification.development_unit_ids):
        blockers.add("development-replay-coverage-failed")
    if any(not replay.passed for replay in task_replays):
        blockers.add("baseline-task-replay-failed")
    if any(
        replay.runner_source_hash != specification.runner_source_hash for replay in task_replays
    ):
        blockers.add("baseline-runner-binding-mismatch")
    if any(replay.environment_hash != environment.environment_hash for replay in task_replays):
        blockers.add("baseline-task-environment-mismatch")
    return sorted(blockers)


class BaselineReproductionReport(KernelContract):
    """Conjunctive report over two clean replays of all development tasks."""

    schema_version: Literal["baseline-reproduction-report-v1"] = "baseline-reproduction-report-v1"
    report_id: StableId
    specification: CleanBaselineSpecification
    environment: BaselineEnvironmentLock
    task_replays: list[BaselineTaskReplay] = Field(min_length=1)
    install_lock_verified: bool
    runner_static_network_audit_passed: bool
    workspace_roots_disjoint: bool
    clean_environment: bool
    independent_runner: bool
    blockers: list[NonEmptyText]
    status: BaselineGateStatus
    confirmatory_payloads_downloaded: Literal[False] = False
    confirmatory_results_observed: Literal[False] = False
    public_benchmark_runs_queried: Literal[False] = False
    novelty_search_started: Literal[False] = False
    public_release_authorized: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    report_hash: Sha256

    @field_validator("task_replays")
    @classmethod
    def _sort_replays(
        cls,
        value: list[BaselineTaskReplay],
    ) -> list[BaselineTaskReplay]:
        normalized = sorted(value, key=lambda item: item.unit_id)
        ids = [item.unit_id for item in normalized]
        if len(ids) != len(set(ids)):
            raise ValueError("task replays must be unique")
        return normalized

    @field_validator("blockers")
    @classmethod
    def _sort_blockers(cls, value: list[str]) -> list[str]:
        normalized = sorted(value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("baseline blockers must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_report(self) -> BaselineReproductionReport:
        self.specification.verify_integrity()
        self.environment.verify_integrity()
        for replay in self.task_replays:
            replay.verify_integrity()
        expected_blockers = _reproduction_blockers(
            specification=self.specification,
            environment=self.environment,
            task_replays=self.task_replays,
            install_lock_verified=self.install_lock_verified,
            runner_static_network_audit_passed=(self.runner_static_network_audit_passed),
            workspace_roots_disjoint=self.workspace_roots_disjoint,
        )
        if self.blockers != expected_blockers:
            raise ValueError("baseline blockers do not match evidence")
        expected_clean = (
            self.install_lock_verified
            and self.runner_static_network_audit_passed
            and self.workspace_roots_disjoint
            and self.specification.environment_hash == self.environment.environment_hash
        )
        expected_independent = (
            expected_clean
            and bool(self.task_replays)
            and all(item.independent_processes for item in self.task_replays)
        )
        if self.clean_environment != expected_clean:
            raise ValueError("clean_environment flag does not match evidence")
        if self.independent_runner != expected_independent:
            raise ValueError("independent_runner flag does not match evidence")
        expected_status = (
            BaselineGateStatus.BASELINE_REPRODUCED
            if not expected_blockers
            else BaselineGateStatus.BLOCKED
        )
        if self.status is not expected_status:
            raise ValueError("baseline status does not match blockers")
        if self.report_hash != self.calculated_hash():
            raise PortfolioIntegrityError("baseline report_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> BaselineReproductionReport:
        payload = dict(values)
        specification = payload["specification"]
        if not isinstance(specification, CleanBaselineSpecification):
            specification = CleanBaselineSpecification.model_validate(specification)
        environment = payload["environment"]
        if not isinstance(environment, BaselineEnvironmentLock):
            environment = BaselineEnvironmentLock.model_validate(environment)
        replays = [
            (
                item
                if isinstance(item, BaselineTaskReplay)
                else BaselineTaskReplay.model_validate(item)
            )
            for item in payload["task_replays"]
        ]
        replays = sorted(replays, key=lambda item: item.unit_id)
        blockers = _reproduction_blockers(
            specification=specification,
            environment=environment,
            task_replays=replays,
            install_lock_verified=bool(payload["install_lock_verified"]),
            runner_static_network_audit_passed=bool(payload["runner_static_network_audit_passed"]),
            workspace_roots_disjoint=bool(payload["workspace_roots_disjoint"]),
        )
        clean = (
            bool(payload["install_lock_verified"])
            and bool(payload["runner_static_network_audit_passed"])
            and bool(payload["workspace_roots_disjoint"])
            and specification.environment_hash == environment.environment_hash
        )
        independent = clean and all(item.independent_processes for item in replays)
        payload.update(
            {
                "schema_version": "baseline-reproduction-report-v1",
                "specification": specification.model_dump(mode="json"),
                "environment": environment.model_dump(mode="json"),
                "task_replays": [item.model_dump(mode="json") for item in replays],
                "clean_environment": clean,
                "independent_runner": independent,
                "blockers": blockers,
                "status": (
                    BaselineGateStatus.BASELINE_REPRODUCED
                    if not blockers
                    else BaselineGateStatus.BLOCKED
                ),
                "confirmatory_payloads_downloaded": False,
                "confirmatory_results_observed": False,
                "public_benchmark_runs_queried": False,
                "novelty_search_started": False,
                "public_release_authorized": False,
                "external_submission_authorized": False,
            }
        )
        payload["report_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"report_hash"}))

    def verify_integrity(self) -> None:
        self.specification.verify_integrity()
        self.environment.verify_integrity()
        for replay in self.task_replays:
            replay.verify_integrity()
        if self.report_hash != self.calculated_hash():
            raise PortfolioIntegrityError("baseline report_hash mismatch")


class FrozenTaskSuccessThreshold(KernelContract):
    """Outcome-blind task binding to a paired strong-baseline margin."""

    schema_version: Literal["frozen-task-success-threshold-v1"] = "frozen-task-success-threshold-v1"
    unit_id: StableId
    family: ObjectiveTaskFamily
    metric_id: ObjectiveMetric
    comparator_baseline_id: Literal["flaml-2.6.0-bounded-automl-v1"] = (
        "flaml-2.6.0-bounded-automl-v1"
    )
    minimum_gain: float = Field(gt=0)
    threshold_expression: NonEmptyText
    higher_is_better: Literal[True] = True
    validity_gates: list[
        Literal[
            "artifact_valid",
            "prediction_replay_valid",
            "budget_valid",
            "evaluator_integrity_valid",
        ]
    ]
    baseline_score_observed: Literal[False] = False
    policy_score_observed: Literal[False] = False
    threshold_hash: Sha256

    @model_validator(mode="after")
    def _validate_threshold(self) -> FrozenTaskSuccessThreshold:
        expected_metric = (
            ObjectiveMetric.BALANCED_ACCURACY
            if self.family is ObjectiveTaskFamily.TABULAR_CLASSIFICATION
            else ObjectiveMetric.R2
        )
        expected_gain = 0.005 if self.family is ObjectiveTaskFamily.TABULAR_CLASSIFICATION else 0.01
        expected_expression = (
            f"paired {BASELINE_ID} {expected_metric.value} + " f"{expected_gain:.3f}"
        )
        if self.metric_id is not expected_metric:
            raise ValueError("threshold metric does not match family")
        if abs(self.minimum_gain - expected_gain) > 1e-15:
            raise ValueError("task success margin changed")
        if self.threshold_expression != expected_expression:
            raise ValueError("task success threshold expression changed")
        if self.validity_gates != [
            "artifact_valid",
            "prediction_replay_valid",
            "budget_valid",
            "evaluator_integrity_valid",
        ]:
            raise ValueError("task validity gates changed")
        if self.threshold_hash != self.calculated_hash():
            raise PortfolioIntegrityError("threshold_hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        unit_id: str,
        family: ObjectiveTaskFamily,
    ) -> FrozenTaskSuccessThreshold:
        metric = (
            ObjectiveMetric.BALANCED_ACCURACY
            if family is ObjectiveTaskFamily.TABULAR_CLASSIFICATION
            else ObjectiveMetric.R2
        )
        gain = 0.005 if family is ObjectiveTaskFamily.TABULAR_CLASSIFICATION else 0.01
        payload: dict[str, Any] = {
            "schema_version": "frozen-task-success-threshold-v1",
            "unit_id": unit_id,
            "family": family,
            "metric_id": metric,
            "comparator_baseline_id": BASELINE_ID,
            "minimum_gain": gain,
            "threshold_expression": (f"paired {BASELINE_ID} {metric.value} + {gain:.3f}"),
            "higher_is_better": True,
            "validity_gates": [
                "artifact_valid",
                "prediction_replay_valid",
                "budget_valid",
                "evaluator_integrity_valid",
            ],
            "baseline_score_observed": False,
            "policy_score_observed": False,
        }
        payload["threshold_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"threshold_hash"}))

    def verify_integrity(self) -> None:
        if self.threshold_hash != self.calculated_hash():
            raise PortfolioIntegrityError("threshold_hash mismatch")


class FidelityBudgetStage(KernelContract):
    """One non-adaptive rung shared by every causal arm."""

    stage_id: Literal["F0", "F1", "F2", "F3"]
    candidate_count: int = Field(ge=1)
    training_fraction: float = Field(gt=0, le=1)
    maximum_seconds_per_candidate: int = Field(ge=1)
    survivor_count: int = Field(ge=1)


class CausalArmBudget(KernelContract):
    """Matched candidate/model/compute caps for every arm and ablation."""

    schema_version: Literal["causal-arm-budget-v1"] = "causal-arm-budget-v1"
    candidate_proposals: Literal[12] = 12
    proposal_model_calls: Literal[12] = 12
    reviewer_model_calls: Literal[22] = 22
    reflection_model_calls: Literal[4] = 4
    maximum_total_model_tokens: Literal[60000] = 60_000
    maximum_cpu_seconds_per_task_seed: Literal[240] = 240
    maximum_memory_mb: Literal[4096] = 4_096
    fidelity_stages: list[FidelityBudgetStage]
    unused_budget_reallocation_allowed: Literal[False] = False
    budget_hash: Sha256

    @model_validator(mode="after")
    def _validate_budget(self) -> CausalArmBudget:
        expected = [
            ("F0", 12, 0.125, 5, 6),
            ("F1", 6, 0.25, 10, 3),
            ("F2", 3, 0.50, 20, 1),
            ("F3", 1, 1.00, 60, 1),
        ]
        actual = [
            (
                item.stage_id,
                item.candidate_count,
                item.training_fraction,
                item.maximum_seconds_per_candidate,
                item.survivor_count,
            )
            for item in self.fidelity_stages
        ]
        if actual != expected:
            raise ValueError("causal fidelity budget changed")
        if self.budget_hash != self.calculated_hash():
            raise PortfolioIntegrityError("budget_hash mismatch")
        return self

    @classmethod
    def create(cls) -> CausalArmBudget:
        payload: dict[str, Any] = {
            "schema_version": "causal-arm-budget-v1",
            "candidate_proposals": 12,
            "proposal_model_calls": 12,
            "reviewer_model_calls": 22,
            "reflection_model_calls": 4,
            "maximum_total_model_tokens": 60_000,
            "maximum_cpu_seconds_per_task_seed": 240,
            "maximum_memory_mb": 4_096,
            "fidelity_stages": [
                {
                    "stage_id": "F0",
                    "candidate_count": 12,
                    "training_fraction": 0.125,
                    "maximum_seconds_per_candidate": 5,
                    "survivor_count": 6,
                },
                {
                    "stage_id": "F1",
                    "candidate_count": 6,
                    "training_fraction": 0.25,
                    "maximum_seconds_per_candidate": 10,
                    "survivor_count": 3,
                },
                {
                    "stage_id": "F2",
                    "candidate_count": 3,
                    "training_fraction": 0.50,
                    "maximum_seconds_per_candidate": 20,
                    "survivor_count": 1,
                },
                {
                    "stage_id": "F3",
                    "candidate_count": 1,
                    "training_fraction": 1.00,
                    "maximum_seconds_per_candidate": 60,
                    "survivor_count": 1,
                },
            ],
            "unused_budget_reallocation_allowed": False,
        }
        payload["budget_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"budget_hash"}))

    def verify_integrity(self) -> None:
        if self.budget_hash != self.calculated_hash():
            raise PortfolioIntegrityError("budget_hash mismatch")


_ARM_PROTOCOLS = {
    StudyArm.ONE_SHOT: (
        "twelve proposals generated before any evaluator feedback",
        "flat batch",
        "no memory",
    ),
    StudyArm.LINEAR_SELF_LOOP: (
        "one incumbent followed by eleven serial mutations",
        "single incumbent path",
        "incumbent history only",
    ),
    StudyArm.PORTFOLIO: (
        "twelve diversity-constrained branches with staged survival",
        "branching portfolio",
        "within-branch history only",
    ),
    StudyArm.PORTFOLIO_MEMORY: (
        "twelve diversity-constrained branches with staged survival",
        "branching portfolio",
        "comparative cross-branch memory",
    ),
}


class FrozenArmProtocol(KernelContract):
    """Operational definition of one budget-matched causal arm."""

    schema_version: Literal["frozen-arm-protocol-v1"] = "frozen-arm-protocol-v1"
    arm: StudyArm
    proposal_protocol: NonEmptyText
    search_topology: NonEmptyText
    memory_scope: NonEmptyText
    operator_grammar_hash: Sha256
    budget_hash: Sha256
    task_names_visible: Literal[False] = False
    human_scientific_intervention_allowed: Literal[False] = False
    protocol_hash: Sha256

    @model_validator(mode="after")
    def _validate_protocol(self) -> FrozenArmProtocol:
        expected = _ARM_PROTOCOLS[self.arm]
        if (
            self.proposal_protocol,
            self.search_topology,
            self.memory_scope,
        ) != expected:
            raise ValueError("causal arm protocol changed")
        if self.operator_grammar_hash != canonical_sha256(FROZEN_OPERATOR_GRAMMAR):
            raise PortfolioIntegrityError("operator grammar hash mismatch")
        if self.protocol_hash != self.calculated_hash():
            raise PortfolioIntegrityError("arm protocol_hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        arm: StudyArm,
        budget_hash: str,
    ) -> FrozenArmProtocol:
        proposal, topology, memory = _ARM_PROTOCOLS[arm]
        payload: dict[str, Any] = {
            "schema_version": "frozen-arm-protocol-v1",
            "arm": arm,
            "proposal_protocol": proposal,
            "search_topology": topology,
            "memory_scope": memory,
            "operator_grammar_hash": canonical_sha256(FROZEN_OPERATOR_GRAMMAR),
            "budget_hash": budget_hash,
            "task_names_visible": False,
            "human_scientific_intervention_allowed": False,
        }
        payload["protocol_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"protocol_hash"}))

    def verify_integrity(self) -> None:
        if self.protocol_hash != self.calculated_hash():
            raise PortfolioIntegrityError("arm protocol_hash mismatch")


_ABLATION_COMPONENT = {
    StudyAblation.CERTIFICATE: "research-question certificate",
    StudyAblation.DIVERSITY: "branch diversity constraint",
    StudyAblation.MULTI_FIDELITY: "multi-fidelity survivor schedule",
    StudyAblation.REVIEWER: "artifact-grounded reviewer",
    StudyAblation.MEMORY: "comparative cross-branch memory",
}


class FrozenAblationProtocol(KernelContract):
    """One-at-a-time ablation of the portfolio-plus-memory arm."""

    schema_version: Literal["frozen-ablation-protocol-v1"] = "frozen-ablation-protocol-v1"
    ablation: StudyAblation
    parent_arm: Literal[StudyArm.PORTFOLIO_MEMORY] = StudyArm.PORTFOLIO_MEMORY
    disabled_component: NonEmptyText
    all_other_components_frozen: Literal[True] = True
    unused_budget_reallocated: Literal[False] = False
    budget_hash: Sha256
    protocol_hash: Sha256

    @model_validator(mode="after")
    def _validate_ablation(self) -> FrozenAblationProtocol:
        if self.disabled_component != _ABLATION_COMPONENT[self.ablation]:
            raise ValueError("ablation disabled component changed")
        if self.protocol_hash != self.calculated_hash():
            raise PortfolioIntegrityError("ablation protocol_hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        ablation: StudyAblation,
        budget_hash: str,
    ) -> FrozenAblationProtocol:
        payload: dict[str, Any] = {
            "schema_version": "frozen-ablation-protocol-v1",
            "ablation": ablation,
            "parent_arm": StudyArm.PORTFOLIO_MEMORY,
            "disabled_component": _ABLATION_COMPONENT[ablation],
            "all_other_components_frozen": True,
            "unused_budget_reallocated": False,
            "budget_hash": budget_hash,
        }
        payload["protocol_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"protocol_hash"}))

    def verify_integrity(self) -> None:
        if self.protocol_hash != self.calculated_hash():
            raise PortfolioIntegrityError("ablation protocol_hash mismatch")


class RandomizationAssignment(KernelContract):
    """One result-free run-order assignment within a task/seed block."""

    partition: PanelPartition
    benchmark_id: StableId
    domain: NonEmptyText
    unit_id: StableId
    within_unit_seed: int = Field(ge=0)
    task_order_within_block: int = Field(ge=1)
    arm_order_within_task: int = Field(ge=1, le=4)
    arm: StudyArm


def build_frozen_randomization_schedule(
    panel: OpenObjectiveTaskPanelReport,
) -> list[RandomizationAssignment]:
    """Build the deterministic blocked task and arm execution schedule."""

    panel.verify_integrity()
    rows: list[RandomizationAssignment] = []
    for partition in PanelPartition:
        units = [unit for unit in panel.task_units if unit.partition is partition]
        block_keys = sorted({(unit.benchmark_id, unit.domain) for unit in units})
        for benchmark_id, domain in block_keys:
            block_units = [
                unit
                for unit in units
                if unit.benchmark_id == benchmark_id and unit.domain == domain
            ]
            for seed in FROZEN_WITHIN_UNIT_SEEDS:
                ordered_units = sorted(
                    block_units,
                    key=lambda item: hashlib.sha256(
                        (
                            f"task-263.4.2:{partition.value}:{benchmark_id}:"
                            f"{domain}:{seed}:{item.unit_id}"
                        ).encode()
                    ).hexdigest(),
                )
                for task_order, unit in enumerate(ordered_units, start=1):
                    ordered_arms = sorted(
                        StudyArm,
                        key=lambda arm: hashlib.sha256(
                            (f"task-263.4.2:{unit.unit_id}:{seed}:" f"{arm.value}").encode()
                        ).hexdigest(),
                    )
                    for arm_order, arm in enumerate(ordered_arms, start=1):
                        rows.append(
                            RandomizationAssignment(
                                partition=partition,
                                benchmark_id=benchmark_id,
                                domain=domain,
                                unit_id=unit.unit_id,
                                within_unit_seed=seed,
                                task_order_within_block=task_order,
                                arm_order_within_task=arm_order,
                                arm=arm,
                            )
                        )
    return rows


class CausalSearchPreregistration(KernelContract):
    """Complete result-free causal design admitted after baseline replay."""

    schema_version: Literal["causal-search-preregistration-v1"] = "causal-search-preregistration-v1"
    preregistration_id: StableId
    claim_scope: NonEmptyText = FROZEN_CLAIM_SCOPE
    panel_report_hash: Sha256
    baseline_reproduction: BaselineReproductionReport
    design_source_snapshot_hashes: dict[StableId, Sha256]
    development_unit_ids: list[StableId]
    confirmatory_unit_ids: list[StableId]
    task_thresholds: list[FrozenTaskSuccessThreshold]
    operator_grammar: list[NonEmptyText]
    budget: CausalArmBudget
    arms: list[FrozenArmProtocol]
    ablations: list[FrozenAblationProtocol]
    analysis_unit: Literal["independent task/source group"] = "independent task/source group"
    within_unit_seeds: list[int]
    primary_comparison: list[StudyArm]
    primary_endpoint: Literal["paired difference in objectively confirmed task success"] = (
        "paired difference in objectively confirmed task success"
    )
    primary_test: Literal["two-sided exact McNemar test"] = "two-sided exact McNemar test"
    alpha: float = 0.05
    target_power: float = 0.80
    minimum_effect: float = 0.25
    secondary_multiplicity_control: Literal["Holm family-wise correction at 0.05"] = (
        "Holm family-wise correction at 0.05"
    )
    effect_interval: Literal[
        "exact paired risk-difference interval reported with task-level effects"
    ] = "exact paired risk-difference interval reported with task-level effects"
    blocking_factors: list[Literal["benchmark", "domain"]]
    randomization_assignments: list[RandomizationAssignment]
    randomization_schedule_hash: Sha256
    failure_policy: NonEmptyText
    sealed_runner_permissions: list[NonEmptyText]
    stop_rules: list[NonEmptyText]
    confirmatory_results_sealed: Literal[True] = True
    confirmatory_payloads_downloaded: Literal[False] = False
    development_search_started: Literal[False] = False
    result_record_count: Literal[0] = 0
    public_release_authorized: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    status: Literal[BaselineGateStatus.READY_FOR_DEVELOPMENT_SEARCH] = (
        BaselineGateStatus.READY_FOR_DEVELOPMENT_SEARCH
    )
    preregistration_hash: Sha256

    @field_validator(
        "development_unit_ids",
        "confirmatory_unit_ids",
        "within_unit_seeds",
    )
    @classmethod
    def _sort_unique_values(cls, value: list[Any]) -> list[Any]:
        normalized = sorted(value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("preregistration lists must be unique")
        return normalized

    @field_validator("task_thresholds")
    @classmethod
    def _sort_thresholds(
        cls,
        value: list[FrozenTaskSuccessThreshold],
    ) -> list[FrozenTaskSuccessThreshold]:
        normalized = sorted(value, key=lambda item: item.unit_id)
        ids = [item.unit_id for item in normalized]
        if len(ids) != len(set(ids)):
            raise ValueError("task thresholds must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_preregistration(self) -> CausalSearchPreregistration:
        self.baseline_reproduction.verify_integrity()
        if self.baseline_reproduction.status is not BaselineGateStatus.BASELINE_REPRODUCED:
            raise ValueError("preregistration requires a reproduced baseline")
        specification = self.baseline_reproduction.specification
        if self.panel_report_hash != specification.panel_report_hash:
            raise ValueError("preregistration panel hash mismatch")
        if self.claim_scope != FROZEN_CLAIM_SCOPE:
            raise ValueError("causal claim scope changed")
        if self.development_unit_ids != specification.development_unit_ids:
            raise ValueError("development panel changed after baseline replay")
        if self.confirmatory_unit_ids != specification.confirmatory_unit_ids:
            raise ValueError("confirmatory panel changed after baseline replay")
        if set(self.design_source_snapshot_hashes) != (REQUIRED_DESIGN_SOURCE_KEYS):
            raise ValueError("causal design source snapshot set is incomplete")
        for threshold in self.task_thresholds:
            threshold.verify_integrity()
        if [item.unit_id for item in self.task_thresholds] != (self.confirmatory_unit_ids):
            raise ValueError("thresholds must exactly cover the sealed panel")
        if self.operator_grammar != FROZEN_OPERATOR_GRAMMAR:
            raise ValueError("candidate operator grammar changed")
        self.budget.verify_integrity()
        if [item.arm for item in self.arms] != list(StudyArm):
            raise ValueError("preregistration must contain the four frozen arms")
        for arm in self.arms:
            arm.verify_integrity()
            if arm.budget_hash != self.budget.budget_hash:
                raise ValueError("causal arm budget mismatch")
        if [item.ablation for item in self.ablations] != list(StudyAblation):
            raise ValueError("preregistration must contain five frozen ablations")
        for ablation in self.ablations:
            ablation.verify_integrity()
            if ablation.budget_hash != self.budget.budget_hash:
                raise ValueError("ablation budget mismatch")
        if self.within_unit_seeds != FROZEN_WITHIN_UNIT_SEEDS:
            raise ValueError("within-task seed schedule changed")
        if self.primary_comparison != [
            StudyArm.PORTFOLIO_MEMORY,
            StudyArm.LINEAR_SELF_LOOP,
        ]:
            raise ValueError("primary comparison changed")
        if (self.alpha, self.target_power, self.minimum_effect) != (
            0.05,
            0.80,
            0.25,
        ):
            raise ValueError("prospective exact-power design changed")
        if self.blocking_factors != ["benchmark", "domain"]:
            raise ValueError("blocking factors changed")
        if self.failure_policy != FROZEN_FAILURE_POLICY:
            raise ValueError("failure policy changed")
        if self.sealed_runner_permissions != FROZEN_SEALED_RUNNER_PERMISSIONS:
            raise ValueError("sealed runner permissions changed")
        if self.stop_rules != FROZEN_STOP_RULES:
            raise ValueError("non-adaptive stop rules changed")

        expected_unit_ids = set(self.development_unit_ids + self.confirmatory_unit_ids)
        expected_count = len(expected_unit_ids) * len(FROZEN_WITHIN_UNIT_SEEDS) * len(StudyArm)
        if len(self.randomization_assignments) != expected_count:
            raise ValueError("randomization schedule has incomplete coverage")
        schedule_keys = {
            (item.unit_id, item.within_unit_seed, item.arm)
            for item in self.randomization_assignments
        }
        expected_keys = {
            (unit_id, seed, arm)
            for unit_id in expected_unit_ids
            for seed in FROZEN_WITHIN_UNIT_SEEDS
            for arm in StudyArm
        }
        if schedule_keys != expected_keys:
            raise ValueError("randomization schedule key coverage changed")
        if any(item.unit_id not in expected_unit_ids for item in self.randomization_assignments):
            raise ValueError("randomization schedule references unknown task")
        expected_schedule_hash = canonical_sha256(
            [item.model_dump(mode="json") for item in self.randomization_assignments]
        )
        if self.randomization_schedule_hash != expected_schedule_hash:
            raise PortfolioIntegrityError("randomization schedule hash mismatch")
        if self.preregistration_hash != self.calculated_hash():
            raise PortfolioIntegrityError("preregistration_hash mismatch")
        return self

    @classmethod
    def create_from_reproduction(
        cls,
        *,
        preregistration_id: str,
        panel: OpenObjectiveTaskPanelReport,
        reproduction: BaselineReproductionReport,
        design_source_snapshot_hashes: dict[str, str],
    ) -> CausalSearchPreregistration:
        panel.verify_integrity()
        reproduction.verify_integrity()
        if reproduction.status is not BaselineGateStatus.BASELINE_REPRODUCED:
            raise ValueError("clean baseline did not reproduce")
        if panel.report_hash != reproduction.specification.panel_report_hash:
            raise ValueError("panel does not match baseline reproduction")
        unit_by_id = {unit.unit_id: unit for unit in panel.task_units}
        thresholds = [
            FrozenTaskSuccessThreshold.create(
                unit_id=unit_id,
                family=unit_by_id[unit_id].family,
            )
            for unit_id in sorted(panel.confirmatory_unit_ids)
        ]
        budget = CausalArmBudget.create()
        arms = [
            FrozenArmProtocol.create(
                arm=arm,
                budget_hash=budget.budget_hash,
            )
            for arm in StudyArm
        ]
        ablations = [
            FrozenAblationProtocol.create(
                ablation=ablation,
                budget_hash=budget.budget_hash,
            )
            for ablation in StudyAblation
        ]
        assignments = build_frozen_randomization_schedule(panel)
        payload: dict[str, Any] = {
            "schema_version": "causal-search-preregistration-v1",
            "preregistration_id": preregistration_id,
            "claim_scope": FROZEN_CLAIM_SCOPE,
            "panel_report_hash": panel.report_hash,
            "baseline_reproduction": reproduction.model_dump(mode="json"),
            "design_source_snapshot_hashes": dict(sorted(design_source_snapshot_hashes.items())),
            "development_unit_ids": sorted(panel.development_unit_ids),
            "confirmatory_unit_ids": sorted(panel.confirmatory_unit_ids),
            "task_thresholds": [item.model_dump(mode="json") for item in thresholds],
            "operator_grammar": FROZEN_OPERATOR_GRAMMAR,
            "budget": budget.model_dump(mode="json"),
            "arms": [item.model_dump(mode="json") for item in arms],
            "ablations": [item.model_dump(mode="json") for item in ablations],
            "analysis_unit": "independent task/source group",
            "within_unit_seeds": FROZEN_WITHIN_UNIT_SEEDS,
            "primary_comparison": [
                StudyArm.PORTFOLIO_MEMORY,
                StudyArm.LINEAR_SELF_LOOP,
            ],
            "primary_endpoint": ("paired difference in objectively confirmed task success"),
            "primary_test": "two-sided exact McNemar test",
            "alpha": 0.05,
            "target_power": 0.80,
            "minimum_effect": 0.25,
            "secondary_multiplicity_control": ("Holm family-wise correction at 0.05"),
            "effect_interval": (
                "exact paired risk-difference interval reported with " "task-level effects"
            ),
            "blocking_factors": ["benchmark", "domain"],
            "randomization_assignments": [item.model_dump(mode="json") for item in assignments],
            "randomization_schedule_hash": canonical_sha256(
                [item.model_dump(mode="json") for item in assignments]
            ),
            "failure_policy": FROZEN_FAILURE_POLICY,
            "sealed_runner_permissions": FROZEN_SEALED_RUNNER_PERMISSIONS,
            "stop_rules": FROZEN_STOP_RULES,
            "confirmatory_results_sealed": True,
            "confirmatory_payloads_downloaded": False,
            "development_search_started": False,
            "result_record_count": 0,
            "public_release_authorized": False,
            "external_submission_authorized": False,
            "status": BaselineGateStatus.READY_FOR_DEVELOPMENT_SEARCH,
        }
        payload["preregistration_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"preregistration_hash"}))

    def verify_integrity(self) -> None:
        self.baseline_reproduction.verify_integrity()
        self.budget.verify_integrity()
        for threshold in self.task_thresholds:
            threshold.verify_integrity()
        for arm_protocol in self.arms:
            arm_protocol.verify_integrity()
        for ablation_protocol in self.ablations:
            ablation_protocol.verify_integrity()
        if self.preregistration_hash != self.calculated_hash():
            raise PortfolioIntegrityError("preregistration_hash mismatch")


class BaselinePreregistrationManifest(KernelContract):
    """Content inventory for the Task 263.4.2 research object."""

    schema_version: Literal["baseline-preregistration-manifest-v1"] = (
        "baseline-preregistration-manifest-v1"
    )
    baseline_report_hash: Sha256
    preregistration_hash: Sha256
    files: dict[NonEmptyText, Sha256]
    confirmatory_payloads_included: Literal[False] = False
    result_records_included: Literal[False] = False
    public_release_authorized: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    manifest_hash: Sha256

    @model_validator(mode="after")
    def _validate_manifest(self) -> BaselinePreregistrationManifest:
        if list(self.files) != sorted(self.files):
            raise ValueError("manifest files must be sorted")
        if self.manifest_hash != self.calculated_hash():
            raise PortfolioIntegrityError("manifest_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> BaselinePreregistrationManifest:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "baseline-preregistration-manifest-v1",
                "confirmatory_payloads_included": False,
                "result_records_included": False,
                "public_release_authorized": False,
                "external_submission_authorized": False,
            }
        )
        payload["files"] = dict(sorted(payload["files"].items()))
        payload["manifest_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"manifest_hash"}))

    def verify_integrity(self) -> None:
        if self.manifest_hash != self.calculated_hash():
            raise PortfolioIntegrityError("manifest_hash mismatch")


BASELINE_PREREGISTRATION_MODELS = (
    BaselineEnvironmentLock,
    BaselinePreregistrationManifest,
    BaselineReproductionReport,
    BaselineTaskReplay,
    CausalArmBudget,
    CausalSearchPreregistration,
    CleanBaselineSpecification,
    FrozenAblationProtocol,
    FrozenArmProtocol,
    FrozenTaskSuccessThreshold,
    PinnedDistribution,
)


def baseline_preregistration_json_schemas() -> dict[str, dict[str, Any]]:
    """Return deterministic JSON Schemas for every public Task 263.4.2 model."""

    return {model.__name__: model.model_json_schema() for model in BASELINE_PREREGISTRATION_MODELS}


def render_baseline_reproduction_markdown(
    report: BaselineReproductionReport,
) -> str:
    report.verify_integrity()
    rows = [
        "# Clean baseline reproduction",
        "",
        f"- Status: `{report.status.value}`",
        f"- Report hash: `{report.report_hash}`",
        f"- Baseline: `{report.specification.baseline_id}`",
        f"- Environment hash: `{report.environment.environment_hash}`",
        f"- Development tasks replayed: `{len(report.task_replays)}`",
        "- Confirmatory payloads downloaded: `false`",
        "- Public benchmark runs queried: `false`",
        "- Novelty search started: `false`",
        "",
        "## Development replay",
        "",
        "| Task | Family | Metric A | Metric B | Predictions exact | Trials | Seconds A/B |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for replay in report.task_replays:
        rows.append(
            f"| `{replay.unit_id}` | {replay.family.value} | "
            f"{replay.run_a_score:.9f} | {replay.run_b_score:.9f} | "
            f"{str(replay.prediction_replay_exact).lower()} | "
            f"{replay.run_a_trial_count}/{replay.run_b_trial_count} | "
            f"{replay.run_a_seconds:.3f}/{replay.run_b_seconds:.3f} |"
        )
    rows.extend(
        [
            "",
            "This is baseline-replay evidence, not a positive scientific result.",
            "",
        ]
    )
    return "\n".join(rows)


def render_causal_preregistration_markdown(
    preregistration: CausalSearchPreregistration,
) -> str:
    preregistration.verify_integrity()
    rows = [
        "# Search-policy causal preregistration",
        "",
        f"- Status: `{preregistration.status.value}`",
        f"- Preregistration hash: `{preregistration.preregistration_hash}`",
        f"- Claim: {preregistration.claim_scope}",
        f"- Development tasks: `{len(preregistration.development_unit_ids)}`",
        f"- Sealed confirmatory tasks: `{len(preregistration.confirmatory_unit_ids)}`",
        "- Independent unit: `task/source group`; seeds are repeated measures",
        f"- Primary comparison: `{preregistration.primary_comparison[0].value}` "
        f"vs `{preregistration.primary_comparison[1].value}`",
        f"- Primary analysis: `{preregistration.primary_test}`, "
        f"alpha `{preregistration.alpha}`",
        f"- Frozen randomization hash: " f"`{preregistration.randomization_schedule_hash}`",
        "- Confirmatory results sealed: `true`",
        "- Result records: `0`",
        "- External submission authorized: `false`",
        "",
        "## Arms",
        "",
    ]
    rows.extend(
        f"- `{item.arm.value}`: {item.proposal_protocol}; "
        f"{item.search_topology}; {item.memory_scope}."
        for item in preregistration.arms
    )
    rows.extend(["", "## One-at-a-time ablations", ""])
    rows.extend(
        f"- `{item.ablation.value}` disables only " f"{item.disabled_component}."
        for item in preregistration.ablations
    )
    rows.extend(
        [
            "",
            "Thresholds are frozen as paired-baseline formulas without observing "
            "a confirmatory baseline score or policy score. Development search, "
            "confirmation, release, and submission are separate later gates.",
            "",
        ]
    )
    return "\n".join(rows)


def write_baseline_preregistration(
    output_dir: Path,
    report: BaselineReproductionReport,
    preregistration: CausalSearchPreregistration,
) -> BaselinePreregistrationManifest:
    """Persist verified report/preregistration artifacts and their manifest."""

    report.verify_integrity()
    preregistration.verify_integrity()
    if preregistration.baseline_reproduction.report_hash != report.report_hash:
        raise ValueError("preregistration does not bind the supplied report")
    output_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "baseline-reproduction.json": report.canonical_json() + "\n",
        "baseline-reproduction.md": render_baseline_reproduction_markdown(report),
        "causal-preregistration.json": (preregistration.canonical_json() + "\n"),
        "causal-preregistration.md": (render_causal_preregistration_markdown(preregistration)),
        "baseline-preregistration-schemas.json": (
            json.dumps(
                baseline_preregistration_json_schemas(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ),
    }
    for filename, content in files.items():
        _write_text_atomic(output_dir / filename, content)
    file_hashes = {filename: _file_sha256(output_dir / filename) for filename in files}
    manifest = BaselinePreregistrationManifest.create(
        baseline_report_hash=report.report_hash,
        preregistration_hash=preregistration.preregistration_hash,
        files=file_hashes,
    )
    _write_text_atomic(
        output_dir / "baseline-preregistration-manifest.json",
        manifest.canonical_json() + "\n",
    )
    return manifest


def load_baseline_preregistration(
    output_dir: Path,
) -> tuple[
    BaselineReproductionReport,
    CausalSearchPreregistration,
    BaselinePreregistrationManifest,
]:
    """Load and recursively verify a persisted Task 263.4.2 artifact."""

    report = BaselineReproductionReport.model_validate_json(
        (output_dir / "baseline-reproduction.json").read_text(encoding="utf-8")
    )
    preregistration = CausalSearchPreregistration.model_validate_json(
        (output_dir / "causal-preregistration.json").read_text(encoding="utf-8")
    )
    manifest = BaselinePreregistrationManifest.model_validate_json(
        (output_dir / "baseline-preregistration-manifest.json").read_text(encoding="utf-8")
    )
    report.verify_integrity()
    preregistration.verify_integrity()
    manifest.verify_integrity()
    if manifest.baseline_report_hash != report.report_hash:
        raise PortfolioIntegrityError("manifest baseline report mismatch")
    if manifest.preregistration_hash != preregistration.preregistration_hash:
        raise PortfolioIntegrityError("manifest preregistration mismatch")
    for filename, expected_hash in manifest.files.items():
        if _file_sha256(output_dir / filename) != expected_hash:
            raise PortfolioIntegrityError(f"manifest file hash mismatch: {filename}")
    return report, preregistration, manifest


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_text_atomic(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(path)
