"""One-use independent confirmatory evaluation for Task 263.6.

This module freezes the single Task 263.5 survivor before reveal, opens the
60-task panel exactly once, reproduces the paired FLAML baseline in two clean
environments, and delegates the complete nine-policy matrix to a standalone
network-free controller that receives no development path or trajectory.

The scientific endpoint is deterministic and conjunctive.  A failed primary
gate is retained as a credible negative endpoint; it cannot trigger retuning,
panel reuse, or a publication-route switch.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import math
import os
import random
import re
import shutil
import statistics
import subprocess
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal, cast

import requests
from pydantic import Field, field_validator, model_validator
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from autoresearch.kernel.contracts import (
    KernelContract,
    NonEmptyText,
    Sha256,
    StableId,
    canonical_sha256,
)

from .baseline_preregistration import (
    BASELINE_RUNNER_SOURCE_PATH,
    BaselineGateStatus,
    CausalSearchPreregistration,
    FrozenTaskSuccessThreshold,
    load_baseline_preregistration,
)
from .development_search import (
    CandidateSpec,
    DevelopmentSearchStatus,
    PolicyRealization,
    SearchAssignmentResult,
    StageRecordStatus,
    load_development_search_report,
)
from .objective_evaluators import (
    classification_balanced_accuracy,
    regression_r2,
)
from .objective_task_panel import (
    OpenObjectiveTaskUnit,
    load_open_objective_task_panel,
)
from .objective_task_registry import ObjectiveTaskFamily, PanelPartition
from .portfolio import PortfolioIntegrityError
from .search_policy_study import (
    StudyAblation,
    StudyArm,
    exact_two_sided_sign_test_pvalue,
)

CONFIRMATION_FREEZE_FILENAME = "confirmatory-evaluation-freeze.json"
REVEAL_LEDGER_FILENAME = "confirmation-reveal-ledger.json"
EXECUTION_INDEX_FILENAME = "confirmatory-execution-index.json"
CONTROLLER_RESULT_RELATIVE = Path("primary-execution/controller-result.json")
CONFIRMATION_REPORT_FILENAME = "confirmatory-evaluation-report.json"
CONFIRMATION_MARKDOWN_FILENAME = "confirmatory-evaluation-report.md"
CONFIRMATION_MANIFEST_FILENAME = "confirmatory-evaluation-manifest.json"
CONFIRMATION_SCHEMA_FILENAME = "confirmatory-evaluation-schemas.json"
REPLAY_REPORT_FILENAME = "clean-room-replay-report.json"

POLICY_CONTROLLER_SOURCE_PATH = Path(
    "src/autoresearch/research/assets/frozen_confirmation_policy_controller_v1.py"
)
CANDIDATE_RUNNER_SOURCE_PATH = Path(
    "src/autoresearch/research/assets/frozen_tabular_confirmation_runner_v1.py"
)
CANDIDATE_RUNNER_V2_SOURCE_PATH = Path(
    "src/autoresearch/research/assets/frozen_tabular_candidate_runner_v2.py"
)
CANDIDATE_RUNNER_V1_SOURCE_PATH = Path(
    "src/autoresearch/research/assets/frozen_tabular_candidate_runner_v1.py"
)
BASELINE_RUNNER_PATH = Path(BASELINE_RUNNER_SOURCE_PATH)
OBJECTIVE_EVALUATOR_PATH = Path("src/autoresearch/research/objective_evaluators.py")

FORBIDDEN_EXECUTION_IMPORT_ROOTS = {
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
EXPECTED_DEVELOPMENT_FREEZE_HASH = (
    "1120bc27839eafefcf20e042e7b043e344c9d59cc3b2daa657a102c5ff264332"
)
EXPECTED_DEVELOPMENT_REPORT_HASH = (
    "b767a0963d0c4f60a92cbc7c35b835918122028f90bff5bb6b73e43ccecd1123"
)
EXPECTED_DEVELOPMENT_MANIFEST_HASH = (
    "e423e7cc3f82d083c8a0776f572a550da0cad06fd7b70b79b3d2f213fe71eb49"
)
EXACT_INTERVAL_METHOD = (
    "Bonferroni-simultaneous 97.5% Clopper-Pearson component intervals "
    "for favorable and unfavorable paired probabilities; subtract bounds "
    "to obtain a conservative >=95% matched risk-difference interval"
)


def _panel_report_path(path: Path) -> Path:
    return path / "open-objective-task-panel.json" if path.is_dir() else path


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


def _write_bytes_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
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


def audit_independent_execution_source(path: Path) -> bool:
    """Reject network imports, URLs, AutoResearch imports, and dev-run locators."""

    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", maxsplit=1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", maxsplit=1)[0])
    folded = source.casefold()
    return bool(
        not imported.intersection(FORBIDDEN_EXECUTION_IMPORT_ROOTS)
        and "autoresearch" not in imported
        and "http://" not in folded
        and "https://" not in folded
        and "task2635-development-search" not in folded
    )


class ConfirmationAssignment(KernelContract):
    """One immutable task-seed-policy row in the complete confirmation matrix."""

    schema_version: Literal["confirmation-assignment-v1"] = "confirmation-assignment-v1"
    assignment_id: StableId
    sequence_index: int = Field(ge=0)
    unit_id: StableId
    within_unit_seed: int = Field(ge=0)
    policy_id: StableId
    partition: Literal["confirmatory"] = "confirmatory"
    schedule_source: Literal[
        "task-263.4.2-randomization",
        "matched-ablation-confirmation",
    ]
    assignment_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> ConfirmationAssignment:
        if self.assignment_hash != self.calculated_hash():
            raise PortfolioIntegrityError("confirmation assignment_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ConfirmationAssignment:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "confirmation-assignment-v1",
                "partition": "confirmatory",
            }
        )
        return cls.model_validate(_with_canonical_hash(cls, payload, "assignment_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"assignment_hash"}))


ConfirmationMemoryState = dict[str, dict[str, list[float]]]


def _empty_confirmation_memory() -> ConfirmationMemoryState:
    return {"F1": {}, "F2": {}}


def _confirmation_memory_state_hash(state: ConfirmationMemoryState) -> str:
    normalized = {
        stage: {family: list(values) for family, values in sorted(families.items())}
        for stage, families in sorted(state.items())
    }
    return canonical_sha256(normalized)


class FrozenPolicyMemory(KernelContract):
    """Development-learned memory cloned independently into each test task."""

    schema_version: Literal["frozen-policy-memory-v1"] = "frozen-policy-memory-v1"
    policy_id: StableId
    source_partition: Literal["development"] = "development"
    development_assignment_count: Literal[21] = 21
    state: ConfirmationMemoryState
    state_hash: Sha256
    clone_per_confirmatory_unit: Literal[True] = True
    cross_confirmatory_unit_updates_allowed: Literal[False] = False
    within_unit_seed_updates_allowed: Literal[True] = True
    memory_hash: Sha256

    @model_validator(mode="after")
    def _validate_memory(self) -> FrozenPolicyMemory:
        if set(self.state) != {"F1", "F2"}:
            raise ValueError("frozen policy memory requires F1 and F2 states")
        if any(
            not math.isfinite(value)
            for families in self.state.values()
            for values in families.values()
            for value in values
        ):
            raise ValueError("frozen policy memory contains a non-finite value")
        if self.state_hash != _confirmation_memory_state_hash(self.state):
            raise PortfolioIntegrityError("frozen policy memory state_hash mismatch")
        if self.memory_hash != self.calculated_hash():
            raise PortfolioIntegrityError("frozen policy memory_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> FrozenPolicyMemory:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "frozen-policy-memory-v1",
                "source_partition": "development",
                "development_assignment_count": 21,
                "clone_per_confirmatory_unit": True,
                "cross_confirmatory_unit_updates_allowed": False,
                "within_unit_seed_updates_allowed": True,
            }
        )
        payload["state"] = {
            stage: {
                family: sorted(float(value) for value in entries)
                for family, entries in sorted(families.items())
            }
            for stage, families in sorted(payload["state"].items())
        }
        payload["state_hash"] = _confirmation_memory_state_hash(payload["state"])
        return cls.model_validate(_with_canonical_hash(cls, payload, "memory_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"memory_hash"}))


class ConfirmatoryStatisticalPolicy(KernelContract):
    """Prospective statistical and endpoint policy fixed before reveal."""

    schema_version: Literal["confirmatory-statistical-policy-v1"] = (
        "confirmatory-statistical-policy-v1"
    )
    analysis_unit: Literal["independent OpenML task/source group"] = (
        "independent OpenML task/source group"
    )
    independent_task_count: Literal[60] = 60
    seed_role: Literal["within-task repeated measurement"] = "within-task repeated measurement"
    memory_independence_rule: Literal[
        "freeze development-terminal memory, clone it per confirmatory task, "
        "update only across the three within-task seeds, and never across tasks"
    ] = (
        "freeze development-terminal memory, clone it per confirmatory task, "
        "update only across the three within-task seeds, and never across tasks"
    )
    task_aggregation_rule: Literal["at least two of three seed successes"] = (
        "at least two of three seed successes"
    )
    primary_policy_id: Literal["portfolio_memory"] = "portfolio_memory"
    comparator_policy_id: Literal["linear_self_loop"] = "linear_self_loop"
    primary_test: Literal["two-sided exact McNemar/sign test"] = "two-sided exact McNemar/sign test"
    alpha: float = Field(default=0.05, ge=0.05, le=0.05)
    minimum_meaningful_risk_difference: float = Field(
        default=0.25,
        ge=0.25,
        le=0.25,
    )
    exact_interval_method: NonEmptyText = EXACT_INTERVAL_METHOD
    paired_bootstrap_resamples: Literal[20000] = 20_000
    domain_block_bootstrap_resamples: Literal[20000] = 20_000
    secondary_comparison_ids: list[StableId] = Field(min_length=10, max_length=10)
    secondary_multiplicity: Literal["Holm family-wise correction at 0.05"] = (
        "Holm family-wise correction at 0.05"
    )
    null_control_candidate_id: Literal["null-prior"] = "null-prior"
    maximum_null_control_task_successes: Literal[3] = 3
    temporal_endpoint: Literal[
        "not applicable: the frozen benchmark has no prospective temporal field"
    ] = "not applicable: the frozen benchmark has no prospective temporal field"
    ood_endpoint: Literal[
        "all confirmation source groups are disjoint from development; report "
        "benchmark- and domain-block effects descriptively"
    ] = (
        "all confirmation source groups are disjoint from development; report "
        "benchmark- and domain-block effects descriptively"
    )
    positive_endpoint_checks: list[StableId] = Field(min_length=10)
    policy_hash: Sha256

    @field_validator("secondary_comparison_ids", "positive_endpoint_checks")
    @classmethod
    def _normalize_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("statistical-policy list contains duplicates")
        return sorted(value)

    @model_validator(mode="after")
    def _validate_policy(self) -> ConfirmatoryStatisticalPolicy:
        if self.exact_interval_method != EXACT_INTERVAL_METHOD:
            raise ValueError("confirmatory exact interval method changed")
        if self.policy_hash != self.calculated_hash():
            raise PortfolioIntegrityError("confirmatory statistical policy_hash mismatch")
        return self

    @classmethod
    def create(cls) -> ConfirmatoryStatisticalPolicy:
        arms = [item.value for item in StudyArm]
        secondary: list[str] = []
        for index, first in enumerate(arms):
            for second in arms[index + 1 :]:
                if {first, second} == {"portfolio_memory", "linear_self_loop"}:
                    continue
                secondary.append(f"{first}-vs-{second}")
        secondary.extend(f"portfolio-memory-vs-ablation-{item.value}" for item in StudyAblation)
        checks = [
            "all-60-independent-tasks-valid",
            "baseline-a-b-replay-exact",
            "complete-1620-assignment-matrix",
            "primary-risk-difference-at-least-0.25",
            "primary-exact-mcnemar-p-at-most-0.05",
            "primary-exact-interval-lower-above-zero",
            "portfolio-memory-zero-integrity-or-budget-failures",
            "linear-self-loop-zero-integrity-or-budget-failures",
            "null-control-task-successes-at-most-3",
            "null-control-zero-integrity-failures",
            "both-benchmark-family-risk-differences-nonnegative",
            "full-clean-room-scientific-projection-exact",
            "no-confirmatory-leakage-or-post-reveal-retuning",
        ]
        payload: dict[str, Any] = {
            "schema_version": "confirmatory-statistical-policy-v1",
            "secondary_comparison_ids": sorted(secondary),
            "positive_endpoint_checks": sorted(checks),
        }
        return cls.model_validate(_with_canonical_hash(cls, payload, "policy_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"policy_hash"}))


class FrozenConfirmatoryClaim(KernelContract):
    """The sole development survivor and its immutable publication endpoint."""

    schema_version: Literal["frozen-confirmatory-claim-v1"] = "frozen-confirmatory-claim-v1"
    claim_id: Literal["task-263.6-portfolio-memory-confirmation"] = (
        "task-263.6-portfolio-memory-confirmation"
    )
    claim_scope: NonEmptyText
    surviving_policy_id: Literal["portfolio_memory"] = "portfolio_memory"
    primary_comparator_policy_id: Literal["linear_self_loop"] = "linear_self_loop"
    development_freeze_hash: Sha256
    development_report_hash: Sha256
    development_manifest_hash: Sha256
    development_analysis_hash: Sha256
    survivor_policy_hash: Sha256
    comparator_policy_hash: Sha256
    candidate_catalog_hash: Sha256
    repair_lineage_hash: Sha256
    frozen_policy_memory_catalogue_hash: Sha256
    publication_route: Literal["bounded-tabular-search-policy-causal-study"] = (
        "bounded-tabular-search-policy-causal-study"
    )
    result_contingent_route_change_allowed: Literal[False] = False
    post_reveal_retuning_allowed: Literal[False] = False
    claim_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> FrozenConfirmatoryClaim:
        if self.claim_hash != self.calculated_hash():
            raise PortfolioIntegrityError("frozen confirmatory claim_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> FrozenConfirmatoryClaim:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "frozen-confirmatory-claim-v1",
                "claim_id": "task-263.6-portfolio-memory-confirmation",
                "surviving_policy_id": "portfolio_memory",
                "primary_comparator_policy_id": "linear_self_loop",
                "publication_route": "bounded-tabular-search-policy-causal-study",
                "result_contingent_route_change_allowed": False,
                "post_reveal_retuning_allowed": False,
            }
        )
        return cls.model_validate(_with_canonical_hash(cls, payload, "claim_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"claim_hash"}))


class CleanEnvironmentPackageSnapshot(KernelContract):
    """Runtime package catalogue bound to one clean confirmation interpreter."""

    schema_version: Literal["clean-environment-package-snapshot-v1"] = (
        "clean-environment-package-snapshot-v1"
    )
    python_version: NonEmptyText
    implementation: NonEmptyText
    cache_tag: NonEmptyText
    installed_distributions: dict[StableId, NonEmptyText]
    interpreter_sha256: Sha256
    snapshot_hash: Sha256

    @model_validator(mode="after")
    def _validate_snapshot(self) -> CleanEnvironmentPackageSnapshot:
        if not self.installed_distributions:
            raise ValueError("clean environment has no installed distributions")
        if self.snapshot_hash != self.calculated_hash():
            raise PortfolioIntegrityError("clean environment snapshot_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> CleanEnvironmentPackageSnapshot:
        payload = {
            "schema_version": "clean-environment-package-snapshot-v1",
            **values,
        }
        payload["installed_distributions"] = dict(
            sorted(payload["installed_distributions"].items())
        )
        return cls.model_validate(_with_canonical_hash(cls, payload, "snapshot_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"snapshot_hash"}))


class ConfirmatoryEvaluationFreeze(KernelContract):
    """Complete result-free confirmation design written before one-use reveal."""

    schema_version: Literal["confirmatory-evaluation-freeze-v1"] = (
        "confirmatory-evaluation-freeze-v1"
    )
    freeze_id: Literal["task-263.6-one-use-confirmation-v1"] = "task-263.6-one-use-confirmation-v1"
    panel_report_hash: Sha256
    source_registry_hash: Sha256
    baseline_report_hash: Sha256
    preregistration_hash: Sha256
    preregistration_randomization_hash: Sha256
    claim: FrozenConfirmatoryClaim
    statistical_policy: ConfirmatoryStatisticalPolicy
    candidates: list[CandidateSpec] = Field(min_length=12, max_length=12)
    policies: list[PolicyRealization] = Field(min_length=9, max_length=9)
    frozen_policy_memories: list[FrozenPolicyMemory] = Field(
        min_length=9,
        max_length=9,
    )
    memory_cloned_per_confirmatory_unit: Literal[True] = True
    cross_confirmatory_unit_memory_updates_allowed: Literal[False] = False
    within_unit_seed_memory_updates_allowed: Literal[True] = True
    assignments: list[ConfirmationAssignment] = Field(min_length=1620, max_length=1620)
    confirmatory_unit_ids: list[StableId] = Field(min_length=60, max_length=60)
    task_thresholds: list[FrozenTaskSuccessThreshold] = Field(
        min_length=60,
        max_length=60,
    )
    within_unit_seeds: list[int] = Field(min_length=3, max_length=3)
    surviving_policy_id: Literal["portfolio_memory"] = "portfolio_memory"
    primary_comparator_policy_id: Literal["linear_self_loop"] = "linear_self_loop"
    null_control_candidate_id: Literal["null-prior"] = "null-prior"
    fidelity_budget: dict[Literal["F1", "F2", "F3"], dict[str, float | int]]
    maximum_cpu_seconds_per_assignment: Literal[240] = 240
    maximum_memory_mb: Literal[4096] = 4096
    execution_assets: dict[StableId, NonEmptyText]
    clean_interpreter_paths: dict[Literal["primary", "replay"], NonEmptyText]
    clean_interpreter_hashes: dict[Literal["primary", "replay"], Sha256]
    baseline_environment_hash: Sha256
    baseline_dependency_lock_hash: Sha256
    baseline_python_version: NonEmptyText
    locked_distribution_versions: dict[StableId, NonEmptyText]
    clean_environment_snapshots: dict[
        Literal["primary", "replay"],
        CleanEnvironmentPackageSnapshot,
    ]
    clean_environment_lock_verified: Literal[True] = True
    baseline_runner_sha256: Sha256
    objective_evaluator_sha256: Sha256
    independent_runner_static_audit_passed: Literal[True] = True
    development_trajectory_paths_exposed_to_runner: Literal[False] = False
    frozen_development_policy_parameters_exposed_to_runner: Literal[True] = True
    raw_development_outcomes_exposed_to_runner: Literal[False] = False
    development_trajectory_access_authorized: Literal[False] = False
    confirmatory_payloads_downloaded: Literal[False] = False
    confirmatory_results_observed: Literal[False] = False
    result_record_count: Literal[0] = 0
    one_use_reveal_count: Literal[1] = 1
    non_adaptive_stop_rules: list[NonEmptyText]
    external_submission_authorized: Literal[False] = False
    public_release_authorized: Literal[False] = False
    created_at: datetime
    orchestrator_source_hash: Sha256
    freeze_hash: Sha256

    @field_validator("created_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("confirmation freeze time must be timezone-aware")
        return value

    @field_validator("confirmatory_unit_ids")
    @classmethod
    def _sort_units(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("confirmatory units are duplicated")
        return sorted(value)

    @field_validator("within_unit_seeds")
    @classmethod
    def _require_frozen_seeds(cls, value: list[int]) -> list[int]:
        if value != [1729, 3253, 7919]:
            raise ValueError("confirmation within-unit seeds changed")
        return value

    @model_validator(mode="after")
    def _validate_freeze(self) -> ConfirmatoryEvaluationFreeze:
        self.claim.model_validate(self.claim.model_dump())
        self.statistical_policy.model_validate(self.statistical_policy.model_dump())
        candidate_ids = [item.candidate_id for item in self.candidates]
        policy_ids = [item.policy_id for item in self.policies]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("confirmation candidates are duplicated")
        if policy_ids != sorted(policy_ids) or len(policy_ids) != len(set(policy_ids)):
            raise ValueError("confirmation policies must be unique and sorted")
        if [item.policy_id for item in self.frozen_policy_memories] != policy_ids:
            raise ValueError("confirmation frozen memories do not cover all policies")
        if self.claim.frozen_policy_memory_catalogue_hash != canonical_sha256(
            [item.memory_hash for item in self.frozen_policy_memories]
        ):
            raise PortfolioIntegrityError("confirmation claim/frozen-memory catalogue mismatch")
        if [item.unit_id for item in self.task_thresholds] != self.confirmatory_unit_ids:
            raise ValueError("confirmation thresholds do not cover the sealed panel")
        if [item.sequence_index for item in self.assignments] != list(range(1620)):
            raise ValueError("confirmation assignment sequence is not contiguous")
        expected = {
            (unit_id, seed, policy_id)
            for unit_id in self.confirmatory_unit_ids
            for seed in self.within_unit_seeds
            for policy_id in policy_ids
        }
        observed = {
            (item.unit_id, item.within_unit_seed, item.policy_id) for item in self.assignments
        }
        if observed != expected:
            raise ValueError("confirmation assignment matrix is incomplete")
        if len({item.assignment_id for item in self.assignments}) != 1620:
            raise ValueError("confirmation assignment IDs are duplicated")
        if set(self.execution_assets) != {
            "candidate_runner_relative_path",
            "candidate_runner_sha256",
            "candidate_runner_v1_sha256",
            "candidate_runner_v2_sha256",
            "policy_controller_relative_path",
            "policy_controller_sha256",
        }:
            raise ValueError("confirmation execution-asset binding is incomplete")
        if set(self.clean_interpreter_paths) != {"primary", "replay"} or set(
            self.clean_interpreter_hashes
        ) != {"primary", "replay"}:
            raise ValueError("confirmation clean interpreters are incomplete")
        if set(self.clean_environment_snapshots) != {"primary", "replay"}:
            raise ValueError("confirmation clean environment snapshots are incomplete")
        package_catalogues: list[dict[str, str]] = []
        for role, snapshot in self.clean_environment_snapshots.items():
            if snapshot.interpreter_sha256 != self.clean_interpreter_hashes[role]:
                raise PortfolioIntegrityError(
                    f"confirmation {role} interpreter/snapshot binding mismatch"
                )
            if snapshot.python_version != self.baseline_python_version:
                raise PortfolioIntegrityError(
                    f"confirmation {role} Python version differs from the baseline lock"
                )
            observed_locked = {
                name: snapshot.installed_distributions.get(name)
                for name in self.locked_distribution_versions
            }
            if observed_locked != self.locked_distribution_versions:
                raise PortfolioIntegrityError(
                    f"confirmation {role} package versions differ from the baseline lock"
                )
            package_catalogues.append(snapshot.installed_distributions)
        if package_catalogues[0] != package_catalogues[1]:
            raise PortfolioIntegrityError("confirmation primary/replay package catalogues differ")
        if self.freeze_hash != self.calculated_hash():
            raise PortfolioIntegrityError("confirmation freeze_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ConfirmatoryEvaluationFreeze:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "confirmatory-evaluation-freeze-v1",
                "freeze_id": "task-263.6-one-use-confirmation-v1",
                "within_unit_seeds": [1729, 3253, 7919],
                "surviving_policy_id": "portfolio_memory",
                "primary_comparator_policy_id": "linear_self_loop",
                "null_control_candidate_id": "null-prior",
                "memory_cloned_per_confirmatory_unit": True,
                "cross_confirmatory_unit_memory_updates_allowed": False,
                "within_unit_seed_memory_updates_allowed": True,
                "maximum_cpu_seconds_per_assignment": 240,
                "maximum_memory_mb": 4096,
                "independent_runner_static_audit_passed": True,
                "clean_environment_lock_verified": True,
                "development_trajectory_paths_exposed_to_runner": False,
                "frozen_development_policy_parameters_exposed_to_runner": True,
                "raw_development_outcomes_exposed_to_runner": False,
                "development_trajectory_access_authorized": False,
                "confirmatory_payloads_downloaded": False,
                "confirmatory_results_observed": False,
                "result_record_count": 0,
                "one_use_reveal_count": 1,
                "external_submission_authorized": False,
                "public_release_authorized": False,
            }
        )
        payload["confirmatory_unit_ids"] = sorted(payload["confirmatory_unit_ids"])
        payload["task_thresholds"] = sorted(
            payload["task_thresholds"],
            key=lambda item: item.unit_id,
        )
        payload["policies"] = sorted(
            payload["policies"],
            key=lambda item: item.policy_id,
        )
        payload["frozen_policy_memories"] = sorted(
            payload["frozen_policy_memories"],
            key=lambda item: item.policy_id,
        )
        return cls.model_validate(_with_canonical_hash(cls, payload, "freeze_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"freeze_hash"}))

    def verify_integrity(self) -> None:
        if self.freeze_hash != self.calculated_hash():
            raise PortfolioIntegrityError("confirmation freeze_hash mismatch")
        self.claim.model_validate(self.claim.model_dump())
        self.statistical_policy.model_validate(self.statistical_policy.model_dump())
        for memory in self.frozen_policy_memories:
            memory.model_validate(memory.model_dump())
        for candidate in self.candidates:
            candidate.verify_integrity()


def _confirmation_assignments(
    preregistration: CausalSearchPreregistration,
) -> list[ConfirmationAssignment]:
    confirmatory = set(preregistration.confirmatory_unit_ids)
    rows: list[ConfirmationAssignment] = []
    for source in preregistration.randomization_assignments:
        if source.unit_id not in confirmatory:
            continue
        rows.append(
            ConfirmationAssignment.create(
                assignment_id=(
                    f"confirm-{source.unit_id}-{source.within_unit_seed}-" f"{source.arm.value}"
                ),
                sequence_index=len(rows),
                unit_id=source.unit_id,
                within_unit_seed=source.within_unit_seed,
                policy_id=source.arm.value,
                schedule_source="task-263.4.2-randomization",
            )
        )
    for ablation in StudyAblation:
        policy_id = f"ablation-{ablation.value}"
        for unit_id in sorted(confirmatory):
            for seed in preregistration.within_unit_seeds:
                rows.append(
                    ConfirmationAssignment.create(
                        assignment_id=f"confirm-{unit_id}-{seed}-{policy_id}",
                        sequence_index=len(rows),
                        unit_id=unit_id,
                        within_unit_seed=seed,
                        policy_id=policy_id,
                        schedule_source="matched-ablation-confirmation",
                    )
                )
    if len(rows) != 1620:
        raise PortfolioIntegrityError("confirmation assignment schedule is incomplete")
    return rows


def _update_memory_from_development_result(
    state: ConfirmationMemoryState,
    result: SearchAssignmentResult,
    *,
    enabled: bool,
) -> None:
    if (
        not enabled
        or result.selected_candidate_id is None
        or result.selected_candidate_family is None
        or result.policy_score is None
    ):
        return
    for stage in ("F1", "F2"):
        matches = [
            record
            for record in result.stage_records
            if record.stage == stage
            and record.candidate_id == result.selected_candidate_id
            and record.status is StageRecordStatus.EXECUTED
            and record.objective_score is not None
        ]
        if len(matches) != 1:
            continue
        objective_score = matches[0].objective_score
        if objective_score is None:
            continue
        state.setdefault(stage, {}).setdefault(
            result.selected_candidate_family,
            [],
        ).append(result.policy_score - objective_score)


def _freeze_development_terminal_memories(
    development_dir: Path,
    *,
    development_freeze_hash: str,
    assignments: Sequence[Any],
    policies: Sequence[PolicyRealization],
) -> list[FrozenPolicyMemory]:
    policy_by_id = {item.policy_id: item for item in policies}
    states = {policy_id: _empty_confirmation_memory() for policy_id in policy_by_id}
    counts: Counter[str] = Counter()
    for assignment in assignments:
        result_path = development_dir / "assignments" / assignment.assignment_id / "result.json"
        result = SearchAssignmentResult.model_validate_json(result_path.read_text(encoding="utf-8"))
        result.verify_integrity()
        state = states[assignment.policy_id]
        if (
            result.assignment_hash != assignment.assignment_hash
            or result.freeze_hash != development_freeze_hash
            or result.memory_before_hash != _confirmation_memory_state_hash(state)
        ):
            raise PortfolioIntegrityError(
                "development terminal-memory reconstruction binding mismatch"
            )
        _update_memory_from_development_result(
            state,
            result,
            enabled=policy_by_id[assignment.policy_id].comparative_memory_enabled,
        )
        if result.memory_after_hash != _confirmation_memory_state_hash(state):
            raise PortfolioIntegrityError(
                "development terminal-memory reconstruction state mismatch"
            )
        counts[assignment.policy_id] += 1
    if set(counts) != set(policy_by_id) or set(counts.values()) != {21}:
        raise PortfolioIntegrityError(
            "development terminal-memory assignment coverage is incomplete"
        )
    return [
        FrozenPolicyMemory.create(policy_id=policy_id, state=states[policy_id])
        for policy_id in sorted(states)
    ]


def _copy_execution_assets(output_dir: Path) -> dict[str, str]:
    asset_dir = output_dir / "execution-assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    sources = {
        "frozen_confirmation_policy_controller_v1.py": POLICY_CONTROLLER_SOURCE_PATH,
        "frozen_tabular_confirmation_runner_v1.py": CANDIDATE_RUNNER_SOURCE_PATH,
        "frozen_tabular_candidate_runner_v2.py": CANDIDATE_RUNNER_V2_SOURCE_PATH,
        "frozen_tabular_candidate_runner_v1.py": CANDIDATE_RUNNER_V1_SOURCE_PATH,
        "frozen_flaml_baseline_v1.py": BASELINE_RUNNER_PATH,
        "objective_evaluators.py": OBJECTIVE_EVALUATOR_PATH,
    }
    for name, source in sources.items():
        if not source.is_file():
            raise FileNotFoundError(source)
        target = asset_dir / name
        if target.exists():
            if _file_sha256(target) != _file_sha256(source):
                raise PortfolioIntegrityError(f"frozen execution asset drift: {name}")
        else:
            shutil.copy2(source, target)
    return {name: _file_sha256(asset_dir / name) for name in sorted(sources)}


def _clean_interpreters(baseline_dir: Path) -> dict[str, Path]:
    suffix = Path("Scripts/python.exe") if os.name == "nt" else Path("bin/python")
    paths = {
        "primary": (baseline_dir / "clean-venv-a" / suffix).resolve(),
        "replay": (baseline_dir / "clean-venv-b" / suffix).resolve(),
    }
    for path in paths.values():
        if not path.is_file():
            raise FileNotFoundError(path)
    return paths


_ENVIRONMENT_SNAPSHOT_SCRIPT = """
import importlib.metadata as metadata
import json
import platform
import re
import sys

packages = []
for distribution in metadata.distributions():
    raw_name = distribution.metadata.get("Name")
    if not raw_name:
        raise RuntimeError("installed distribution lacks a name")
    name = re.sub(r"[-_.]+", "-", str(raw_name)).casefold()
    packages.append([name, str(distribution.version)])
print(
    json.dumps(
        {
            "python_version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "cache_tag": sys.implementation.cache_tag,
            "packages": sorted(packages),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
)
""".strip()


def _clean_environment_snapshot(
    interpreter: Path,
) -> CleanEnvironmentPackageSnapshot:
    completed = subprocess.run(
        [interpreter.as_posix(), "-c", _ENVIRONMENT_SNAPSHOT_SCRIPT],
        cwd=interpreter.parent,
        env=_baseline_environment(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "clean environment package snapshot failed: "
            f"{completed.stderr.strip() or completed.returncode}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise PortfolioIntegrityError("clean environment package snapshot is not JSON") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("packages"), list):
        raise PortfolioIntegrityError("clean environment package snapshot has invalid shape")
    pairs = payload["packages"]
    if any(
        not isinstance(item, list)
        or len(item) != 2
        or not all(isinstance(value, str) and value for value in item)
        for item in pairs
    ):
        raise PortfolioIntegrityError(
            "clean environment package snapshot contains an invalid distribution"
        )
    package_names = [item[0] for item in pairs]
    if len(package_names) != len(set(package_names)):
        raise PortfolioIntegrityError(
            "clean environment package snapshot contains duplicate distributions"
        )
    return CleanEnvironmentPackageSnapshot.create(
        python_version=payload.get("python_version"),
        implementation=payload.get("implementation"),
        cache_tag=payload.get("cache_tag"),
        installed_distributions={item[0]: item[1] for item in pairs},
        interpreter_sha256=_file_sha256(interpreter),
    )


def freeze_confirmatory_evaluation(
    panel_dir: Path,
    baseline_dir: Path,
    development_dir: Path,
    output_dir: Path,
    *,
    created_at: datetime | None = None,
) -> ConfirmatoryEvaluationFreeze:
    """Freeze the sole survivor and complete analysis before any payload reveal."""

    output_dir = output_dir.resolve()
    freeze_path = output_dir / CONFIRMATION_FREEZE_FILENAME
    if freeze_path.exists():
        return load_confirmatory_freeze(output_dir)
    if any(
        (output_dir / name).exists()
        for name in (
            REVEAL_LEDGER_FILENAME,
            EXECUTION_INDEX_FILENAME,
            CONFIRMATION_REPORT_FILENAME,
            "source-cache",
            "task-bundles",
            "baseline-replay",
            "primary-execution",
            "clean-room-replay",
        )
    ):
        raise PortfolioIntegrityError("confirmation artifacts exist without a freeze")

    panel = load_open_objective_task_panel(_panel_report_path(panel_dir))
    baseline, preregistration, _ = load_baseline_preregistration(baseline_dir)
    development, development_freeze, development_manifest = load_development_search_report(
        development_dir
    )
    if panel.confirmatory_payloads_downloaded or panel.study_outcomes_observed:
        raise ValueError("panel was already revealed before confirmation freeze")
    if preregistration.confirmatory_payloads_downloaded:
        raise ValueError("preregistration indicates prior payload access")
    if baseline.status is not BaselineGateStatus.BASELINE_REPRODUCED:
        raise ValueError("confirmation requires the reproduced strong baseline")
    if development.status is not DevelopmentSearchStatus.READY_FOR_CONFIRMATION:
        raise ValueError("development did not admit a confirmation survivor")
    if development.analysis.surviving_policy_ids != ["portfolio_memory"]:
        raise ValueError("confirmation requires exactly the sole frozen survivor")
    if (
        development_freeze.freeze_hash != EXPECTED_DEVELOPMENT_FREEZE_HASH
        or development.report_hash != EXPECTED_DEVELOPMENT_REPORT_HASH
        or development_manifest.manifest_hash != EXPECTED_DEVELOPMENT_MANIFEST_HASH
    ):
        raise PortfolioIntegrityError("Task 263.5 terminal hashes changed")
    if development.confirmatory_payloads_downloaded or development.confirmatory_results_visible:
        raise ValueError("development crossed the confirmation seal")
    if development_freeze.repair_lineage is None:
        raise ValueError("confirmation is missing the frozen v2 repair lineage")
    if panel.report_hash != preregistration.panel_report_hash:
        raise PortfolioIntegrityError("confirmation panel/preregistration mismatch")
    if baseline.report_hash != development.baseline_report_hash:
        raise PortfolioIntegrityError("confirmation baseline/development mismatch")
    if preregistration.preregistration_hash != development.preregistration_hash:
        raise PortfolioIntegrityError("confirmation preregistration/development mismatch")
    if not audit_independent_execution_source(POLICY_CONTROLLER_SOURCE_PATH):
        raise ValueError("independent policy controller failed static isolation audit")
    if not audit_independent_execution_source(CANDIDATE_RUNNER_SOURCE_PATH):
        raise ValueError("confirmation candidate runner failed static isolation audit")

    frozen_memories = _freeze_development_terminal_memories(
        development_dir,
        development_freeze_hash=development_freeze.freeze_hash,
        assignments=development_freeze.assignments,
        policies=development_freeze.policies,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    asset_hashes = _copy_execution_assets(output_dir)
    interpreters = _clean_interpreters(baseline_dir)
    clean_environment_snapshots = {
        role: _clean_environment_snapshot(path) for role, path in interpreters.items()
    }
    policies = {item.policy_id: item for item in development_freeze.policies}
    claim = FrozenConfirmatoryClaim.create(
        claim_scope=preregistration.claim_scope,
        development_freeze_hash=development_freeze.freeze_hash,
        development_report_hash=development.report_hash,
        development_manifest_hash=development_manifest.manifest_hash,
        development_analysis_hash=development.analysis.analysis_hash,
        survivor_policy_hash=policies["portfolio_memory"].policy_hash,
        comparator_policy_hash=policies["linear_self_loop"].policy_hash,
        candidate_catalog_hash=development_freeze.initialization.candidate_catalog_hash,
        repair_lineage_hash=development_freeze.repair_lineage.lineage_hash,
        frozen_policy_memory_catalogue_hash=canonical_sha256(
            [item.memory_hash for item in frozen_memories]
        ),
    )
    fidelity_budget = {
        item.stage_id: {
            "training_fraction": item.training_fraction,
            "maximum_seconds": item.maximum_seconds_per_candidate,
        }
        for item in preregistration.budget.fidelity_stages
        if item.stage_id in {"F1", "F2", "F3"}
    }
    freeze = ConfirmatoryEvaluationFreeze.create(
        panel_report_hash=panel.report_hash,
        source_registry_hash=panel.source_registry_hash,
        baseline_report_hash=baseline.report_hash,
        preregistration_hash=preregistration.preregistration_hash,
        preregistration_randomization_hash=preregistration.randomization_schedule_hash,
        claim=claim,
        statistical_policy=ConfirmatoryStatisticalPolicy.create(),
        candidates=development_freeze.candidates,
        policies=development_freeze.policies,
        frozen_policy_memories=frozen_memories,
        assignments=_confirmation_assignments(preregistration),
        confirmatory_unit_ids=preregistration.confirmatory_unit_ids,
        task_thresholds=preregistration.task_thresholds,
        fidelity_budget=fidelity_budget,
        execution_assets={
            "candidate_runner_relative_path": (
                "execution-assets/frozen_tabular_confirmation_runner_v1.py"
            ),
            "candidate_runner_sha256": asset_hashes["frozen_tabular_confirmation_runner_v1.py"],
            "candidate_runner_v1_sha256": asset_hashes["frozen_tabular_candidate_runner_v1.py"],
            "candidate_runner_v2_sha256": asset_hashes["frozen_tabular_candidate_runner_v2.py"],
            "policy_controller_relative_path": (
                "execution-assets/frozen_confirmation_policy_controller_v1.py"
            ),
            "policy_controller_sha256": asset_hashes["frozen_confirmation_policy_controller_v1.py"],
        },
        clean_interpreter_paths={role: path.as_posix() for role, path in interpreters.items()},
        clean_interpreter_hashes={role: _file_sha256(path) for role, path in interpreters.items()},
        baseline_environment_hash=baseline.environment.environment_hash,
        baseline_dependency_lock_hash=baseline.environment.dependency_lock_hash,
        baseline_python_version=baseline.environment.python_version,
        locked_distribution_versions={
            item.name: item.version for item in baseline.environment.distributions
        },
        clean_environment_snapshots=clean_environment_snapshots,
        baseline_runner_sha256=asset_hashes["frozen_flaml_baseline_v1.py"],
        objective_evaluator_sha256=asset_hashes["objective_evaluators.py"],
        non_adaptive_stop_rules=[
            "stop the entire study if confirmatory leakage is detected",
            "resume the same frozen row after infrastructure interruption without changing any scientific field",
            "invalidate an affected task symmetrically before outcomes only when evaluator or source integrity is impossible",
            "do not stop early for a favorable or unfavorable scientific effect",
            "finish all 1620 policy assignments and 180 null controls before primary analysis",
            "clone the frozen development-terminal memory per confirmatory task and never update it across tasks",
            "do not refreeze, retune, switch claims, or switch publication routes after reveal",
        ],
        created_at=created_at or datetime.now(timezone.utc),
        orchestrator_source_hash=_file_sha256(Path(__file__).resolve()),
    )
    _write_text_atomic(freeze_path, freeze.canonical_json() + "\n")
    return freeze


def load_confirmatory_freeze(output_dir: Path) -> ConfirmatoryEvaluationFreeze:
    freeze = ConfirmatoryEvaluationFreeze.model_validate_json(
        (output_dir / CONFIRMATION_FREEZE_FILENAME).read_text(encoding="utf-8")
    )
    freeze.verify_integrity()
    asset_bindings = (
        (
            "policy_controller_sha256",
            freeze.execution_assets["policy_controller_relative_path"],
            freeze.execution_assets["policy_controller_sha256"],
        ),
        (
            "candidate_runner_sha256",
            freeze.execution_assets["candidate_runner_relative_path"],
            freeze.execution_assets["candidate_runner_sha256"],
        ),
        (
            "candidate_runner_v1_sha256",
            "execution-assets/frozen_tabular_candidate_runner_v1.py",
            freeze.execution_assets["candidate_runner_v1_sha256"],
        ),
        (
            "candidate_runner_v2_sha256",
            "execution-assets/frozen_tabular_candidate_runner_v2.py",
            freeze.execution_assets["candidate_runner_v2_sha256"],
        ),
        (
            "baseline_runner_sha256",
            "execution-assets/frozen_flaml_baseline_v1.py",
            freeze.baseline_runner_sha256,
        ),
        (
            "objective_evaluator_sha256",
            "execution-assets/objective_evaluators.py",
            freeze.objective_evaluator_sha256,
        ),
    )
    for key, relative, expected in asset_bindings:
        if _file_sha256(output_dir / relative) != expected:
            raise PortfolioIntegrityError(f"confirmation execution asset mismatch: {key}")
    for role, path_text in freeze.clean_interpreter_paths.items():
        interpreter = Path(path_text)
        if _file_sha256(interpreter) != freeze.clean_interpreter_hashes[role]:
            raise PortfolioIntegrityError(f"confirmation clean interpreter changed: {role}")
        observed_snapshot = _clean_environment_snapshot(interpreter)
        if (
            observed_snapshot.snapshot_hash
            != freeze.clean_environment_snapshots[role].snapshot_hash
        ):
            raise PortfolioIntegrityError(f"confirmation clean environment package drift: {role}")
    if _file_sha256(Path(__file__).resolve()) != freeze.orchestrator_source_hash:
        raise PortfolioIntegrityError("confirmation orchestrator source changed after freeze")
    return freeze


class ConfirmationRevealLedger(KernelContract):
    """Immutable evidence that the single reveal opened after a valid freeze."""

    schema_version: Literal["confirmation-reveal-ledger-v1"] = "confirmation-reveal-ledger-v1"
    reveal_id: Literal["task-263.6-one-use-reveal"] = "task-263.6-one-use-reveal"
    freeze_hash: Sha256
    preregistration_hash: Sha256
    confirmatory_unit_ids: list[StableId] = Field(min_length=60, max_length=60)
    expected_source_url_count: Literal[120] = 120
    result_record_count_at_open: Literal[0] = 0
    reveal_ordinal: Literal[1] = 1
    previous_reveal_exists: Literal[False] = False
    outcome_adaptive_change_authorized: Literal[False] = False
    public_release_authorized: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    opened_at: datetime
    reveal_hash: Sha256

    @field_validator("opened_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("confirmation reveal time must be timezone-aware")
        return value

    @field_validator("confirmatory_unit_ids")
    @classmethod
    def _normalize_units(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("confirmation reveal units are duplicated")
        return sorted(value)

    @model_validator(mode="after")
    def _validate_hash(self) -> ConfirmationRevealLedger:
        if self.reveal_hash != self.calculated_hash():
            raise PortfolioIntegrityError("confirmation reveal_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ConfirmationRevealLedger:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "confirmation-reveal-ledger-v1",
                "reveal_id": "task-263.6-one-use-reveal",
                "expected_source_url_count": 120,
                "result_record_count_at_open": 0,
                "reveal_ordinal": 1,
                "previous_reveal_exists": False,
                "outcome_adaptive_change_authorized": False,
                "public_release_authorized": False,
                "external_submission_authorized": False,
            }
        )
        payload["confirmatory_unit_ids"] = sorted(payload["confirmatory_unit_ids"])
        return cls.model_validate(_with_canonical_hash(cls, payload, "reveal_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"reveal_hash"}))


class ConfirmatoryLabels(KernelContract):
    """One-use evaluator-only labels bound to the reveal and frozen task."""

    schema_version: Literal["confirmatory-labels-v1"] = "confirmatory-labels-v1"
    unit_id: StableId
    opaque_unit_id: StableId
    family: Literal["tabular_classification", "tabular_regression"]
    partition: Literal["confirmatory"] = "confirmatory"
    one_use_reveal: Literal[True] = True
    confirmation_freeze_hash: Sha256
    reveal_hash: Sha256
    row_ids: list[int] = Field(min_length=1)
    labels: list[str | float] = Field(min_length=1)
    data_sha256: Sha256
    split_sha256: Sha256
    source_data_md5: str = Field(pattern=r"^[0-9a-f]{32}$")
    label_hash: Sha256

    @model_validator(mode="after")
    def _validate_labels(self) -> ConfirmatoryLabels:
        if len(self.row_ids) != len(self.labels):
            raise ValueError("confirmation row IDs and labels differ in length")
        if self.row_ids != sorted(self.row_ids) or len(self.row_ids) != len(set(self.row_ids)):
            raise ValueError("confirmation label row IDs must be sorted and unique")
        if self.family == "tabular_classification" and not all(
            isinstance(item, str) for item in self.labels
        ):
            raise ValueError("classification confirmation labels must be strings")
        if self.family == "tabular_regression" and not all(
            isinstance(item, float) for item in self.labels
        ):
            raise ValueError("regression confirmation labels must be floats")
        if self.label_hash != self.calculated_hash():
            raise PortfolioIntegrityError("confirmation label_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ConfirmatoryLabels:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "confirmatory-labels-v1",
                "partition": "confirmatory",
                "one_use_reveal": True,
            }
        )
        return cls.model_validate(_with_canonical_hash(cls, payload, "label_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"label_hash"}))


class BaselineConfirmatoryReplay(KernelContract):
    """Paired clean-environment FLAML baseline evidence for one revealed task."""

    schema_version: Literal["baseline-confirmatory-replay-v1"] = "baseline-confirmatory-replay-v1"
    unit_id: StableId
    opaque_unit_id: StableId
    family: Literal["tabular_classification", "tabular_regression"]
    metric_id: Literal["balanced_accuracy", "r2"]
    input_manifest_sha256: Sha256
    train_sha256: Sha256
    test_sha256: Sha256
    labels_sha256: Sha256
    baseline_runner_sha256: Sha256
    objective_evaluator_sha256: Sha256
    primary_interpreter_sha256: Sha256
    replay_interpreter_sha256: Sha256
    primary_prediction_sha256: Sha256
    replay_prediction_sha256: Sha256
    prediction_count: int = Field(ge=1)
    primary_score: float
    replay_score: float
    replay_tolerance: float = Field(default=1e-12, ge=1e-12, le=1e-12)
    trial_count_primary: Literal[12] = 12
    trial_count_replay: Literal[12] = 12
    prediction_replay_exact: Literal[True] = True
    score_replay_within_tolerance: Literal[True] = True
    network_accessed: Literal[False] = False
    replay_hash: Sha256

    @model_validator(mode="after")
    def _validate_replay(self) -> BaselineConfirmatoryReplay:
        if self.primary_prediction_sha256 != self.replay_prediction_sha256:
            raise ValueError("confirmatory baseline predictions are not exact")
        if not math.isclose(
            self.primary_score,
            self.replay_score,
            rel_tol=0.0,
            abs_tol=self.replay_tolerance,
        ):
            raise ValueError("confirmatory baseline scores exceed tolerance")
        if self.replay_hash != self.calculated_hash():
            raise PortfolioIntegrityError("baseline confirmation replay_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> BaselineConfirmatoryReplay:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "baseline-confirmatory-replay-v1",
                "replay_tolerance": 1e-12,
                "trial_count_primary": 12,
                "trial_count_replay": 12,
                "prediction_replay_exact": True,
                "score_replay_within_tolerance": True,
                "network_accessed": False,
            }
        )
        return cls.model_validate(_with_canonical_hash(cls, payload, "replay_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"replay_hash"}))


class ConfirmatoryTaskInput(KernelContract):
    """One revealed task bundle delivered to the independent controller."""

    schema_version: Literal["confirmatory-task-input-v1"] = "confirmatory-task-input-v1"
    unit_id: StableId
    opaque_unit_id: StableId
    family: Literal["tabular_classification", "tabular_regression"]
    benchmark_id: StableId
    domain: StableId
    independence_group: StableId
    train_path: NonEmptyText
    test_path: NonEmptyText
    labels_path: NonEmptyText
    train_sha256: Sha256
    test_sha256: Sha256
    labels_sha256: Sha256
    data_sha256: Sha256
    split_sha256: Sha256
    source_data_md5: str = Field(pattern=r"^[0-9a-f]{32}$")
    train_row_count: int = Field(ge=1)
    test_row_count: int = Field(ge=1)
    feature_count: int = Field(ge=1)
    metric_id: Literal["balanced_accuracy", "r2"]
    baseline_score: float
    minimum_gain: float = Field(gt=0)
    threshold_hash: Sha256
    baseline_replay: BaselineConfirmatoryReplay
    baseline_replay_exact: Literal[True] = True
    reveal_hash: Sha256
    confirmation_freeze_hash: Sha256
    task_input_hash: Sha256

    @model_validator(mode="after")
    def _validate_input(self) -> ConfirmatoryTaskInput:
        if self.baseline_replay.unit_id != self.unit_id:
            raise ValueError("task input baseline replay binds another unit")
        if self.baseline_replay.primary_score != self.baseline_score:
            raise ValueError("task input baseline score differs from replay")
        if self.task_input_hash != self.calculated_hash():
            raise PortfolioIntegrityError("confirmation task_input_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ConfirmatoryTaskInput:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "confirmatory-task-input-v1",
                "baseline_replay_exact": True,
            }
        )
        return cls.model_validate(_with_canonical_hash(cls, payload, "task_input_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"task_input_hash"}))


class ConfirmatoryExecutionIndex(KernelContract):
    """Post-reveal input inventory; it contains no policy outcome."""

    schema_version: Literal["confirmatory-execution-index-v1"] = "confirmatory-execution-index-v1"
    freeze_hash: Sha256
    reveal_hash: Sha256
    interpreter_role: Literal["primary", "replay"]
    tasks: list[ConfirmatoryTaskInput] = Field(min_length=60, max_length=60)
    source_urls: list[NonEmptyText] = Field(min_length=120, max_length=120)
    source_url_count: Literal[120] = 120
    data_payload_count: Literal[60] = 60
    baseline_run_count: Literal[120] = 120
    all_data_md5_verified: Literal[True] = True
    all_baseline_replays_exact: Literal[True] = True
    development_trajectory_paths_exposed: Literal[False] = False
    policy_result_record_count: Literal[0] = 0
    external_submission_authorized: Literal[False] = False
    public_release_authorized: Literal[False] = False
    execution_index_hash: Sha256

    @field_validator("source_urls")
    @classmethod
    def _normalize_urls(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("confirmation source URLs are duplicated")
        return sorted(value)

    @model_validator(mode="after")
    def _validate_index(self) -> ConfirmatoryExecutionIndex:
        if [item.unit_id for item in self.tasks] != sorted(item.unit_id for item in self.tasks):
            raise ValueError("confirmation task inputs must be unit-sorted")
        if any(
            item.confirmation_freeze_hash != self.freeze_hash
            or item.reveal_hash != self.reveal_hash
            for item in self.tasks
        ):
            raise ValueError("confirmation task input binding mismatch")
        if self.execution_index_hash != self.calculated_hash():
            raise PortfolioIntegrityError("confirmation execution_index_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ConfirmatoryExecutionIndex:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "confirmatory-execution-index-v1",
                "source_url_count": 120,
                "data_payload_count": 60,
                "baseline_run_count": 120,
                "all_data_md5_verified": True,
                "all_baseline_replays_exact": True,
                "development_trajectory_paths_exposed": False,
                "policy_result_record_count": 0,
                "external_submission_authorized": False,
                "public_release_authorized": False,
            }
        )
        payload["tasks"] = sorted(payload["tasks"], key=lambda item: item.unit_id)
        payload["source_urls"] = sorted(payload["source_urls"])
        return cls.model_validate(_with_canonical_hash(cls, payload, "execution_index_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"execution_index_hash"}))


def open_confirmation_reveal(
    output_dir: Path,
    *,
    opened_at: datetime | None = None,
) -> ConfirmationRevealLedger:
    """Open the one-use ledger only after recursively validating the freeze."""

    freeze = load_confirmatory_freeze(output_dir)
    path = output_dir / REVEAL_LEDGER_FILENAME
    if path.exists():
        ledger = ConfirmationRevealLedger.model_validate_json(path.read_text(encoding="utf-8"))
        if ledger.freeze_hash != freeze.freeze_hash:
            raise PortfolioIntegrityError("reveal ledger binds another freeze")
        return ledger
    if any(
        (output_dir / relative).exists()
        for relative in (
            EXECUTION_INDEX_FILENAME,
            CONTROLLER_RESULT_RELATIVE,
            CONFIRMATION_REPORT_FILENAME,
            Path("source-cache"),
            Path("task-bundles"),
            Path("baseline-replay"),
            Path("primary-execution"),
            Path("clean-room-replay"),
        )
    ):
        raise PortfolioIntegrityError("result artifact exists before reveal ledger")
    ledger = ConfirmationRevealLedger.create(
        freeze_hash=freeze.freeze_hash,
        preregistration_hash=freeze.preregistration_hash,
        confirmatory_unit_ids=freeze.confirmatory_unit_ids,
        opened_at=opened_at or datetime.now(timezone.utc),
    )
    _write_text_atomic(path, ledger.canonical_json() + "\n")
    return ledger


_ATTRIBUTE_PATTERN = re.compile(
    r"""^@attribute\s+(?:'([^']+)'|"([^"]+)"|([^\s]+))\s+(.+)$""",
    flags=re.IGNORECASE,
)


def _parse_arff_values(line: str) -> list[str]:
    values: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False
    for character in line:
        if escaped:
            current.append(character)
            escaped = False
            continue
        if character == "\\" and quote is not None:
            escaped = True
            continue
        if quote is not None:
            if character == quote:
                quote = None
            else:
                current.append(character)
            continue
        if character in {"'", '"'}:
            quote = character
        elif character == ",":
            values.append("".join(current).strip())
            current = []
        else:
            current.append(character)
    if quote is not None:
        raise ValueError("ARFF row contains an unterminated quoted value")
    values.append("".join(current).strip())
    return values


def _sparse_arff_default(attribute_type: str) -> str:
    normalized = attribute_type.strip()
    if normalized.casefold() in {"numeric", "real", "integer"}:
        return "0"
    if normalized.startswith("{") and normalized.endswith("}"):
        values = _parse_arff_values(normalized[1:-1])
        if not values:
            raise ValueError("sparse ARFF nominal attribute has no values")
        return values[0]
    return "?"


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
                name = next(value for value in match.groups()[:3] if value is not None)
                attributes.append((name, match.group(4).strip()))
            if line.casefold() == "@data":
                in_data = True
            continue
        data_lines.append(line)
    if not attributes or not data_lines:
        raise ValueError("ARFF payload lacks attributes or data")
    rows: list[list[str]] = []
    for line in data_lines:
        if line.startswith("{"):
            if not line.endswith("}"):
                raise ValueError("sparse ARFF row is malformed")
            row = [_sparse_arff_default(attribute_type) for _, attribute_type in attributes]
            sparse_body = line[1:-1].strip()
            entries = _parse_arff_values(sparse_body) if sparse_body else []
            for entry in entries:
                parts = entry.strip().split(maxsplit=1)
                if len(parts) != 2:
                    raise ValueError("sparse ARFF entry is malformed")
                index = int(parts[0])
                if not 0 <= index < len(attributes):
                    raise ValueError("sparse ARFF index is out of range")
                row[index] = parts[1].strip()
            rows.append(row)
            continue
        rows.append(_parse_arff_values(line))
    if any(len(row) != len(attributes) for row in rows):
        raise ValueError("ARFF row width differs from attributes")
    return attributes, rows


def _split_rows(content: bytes) -> tuple[list[int], list[int]]:
    attributes, rows = _decode_arff(content)
    index = {name.casefold(): position for position, (name, _) in enumerate(attributes)}
    if not {"type", "rowid", "repeat", "fold"}.issubset(index):
        raise ValueError("OpenML split ARFF lacks required fields")
    train: list[int] = []
    test: list[int] = []
    for row in rows:
        if int(float(row[index["repeat"]])) != 0:
            continue
        if int(float(row[index["fold"]])) != 0:
            continue
        row_id = int(float(row[index["rowid"]]))
        kind = row[index["type"]].casefold()
        if kind == "train":
            train.append(row_id)
        elif kind == "test":
            test.append(row_id)
        else:
            raise ValueError(f"unknown OpenML split type: {kind}")
    train = sorted(train)
    test = sorted(test)
    if not train or not test or set(train).intersection(test):
        raise ValueError("OpenML split is empty or overlapping")
    return train, test


def _write_csv(path: Path, header: list[str], rows: Sequence[Sequence[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    temporary.replace(path)


def _csv_data_row_count(path: Path) -> int:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return max(0, sum(1 for _ in csv.reader(handle)) - 1)


def _requests_session() -> requests.Session:
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        status=4,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": "AutoResearch-Task263.6/1.0"})
    return session


def _bounded_get(url: str, maximum_bytes: int, timeout: int) -> bytes:
    session = _requests_session()
    try:
        response = session.get(url, timeout=(10, timeout), stream=True)
        response.raise_for_status()
        chunks: list[bytes] = []
        observed = 0
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if not chunk:
                continue
            observed += len(chunk)
            if observed > maximum_bytes:
                raise ValueError(f"confirmation source exceeds byte cap: {url}")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        session.close()


def _score_prediction_rows(
    *,
    family: str,
    row_ids: list[int],
    labels: Sequence[str | float],
    prediction_path: Path,
) -> tuple[float, str, int]:
    payload = json.loads(prediction_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("baseline prediction artifact is not an array")
    if [int(item["row_id"]) for item in payload] != row_ids:
        raise ValueError("baseline predictions do not align with confirmation rows")
    predictions = [item["prediction"] for item in payload]
    if family == "tabular_classification":
        score = classification_balanced_accuracy(
            [str(value) for value in labels],
            [str(value) for value in predictions],
        )
        metric_id = "balanced_accuracy"
    else:
        score = regression_r2(
            [float(value) for value in labels],
            [float(value) for value in predictions],
        )
        metric_id = "r2"
    return score, metric_id, len(predictions)


def _baseline_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for key in (
        "PYTHONHOME",
        "PYTHONINSPECT",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "VIRTUAL_ENV",
    ):
        environment.pop(key, None)
    environment.update(
        {
            "PYTHONHASHSEED": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "HTTP_PROXY": "http://127.0.0.1:9",
            "HTTPS_PROXY": "http://127.0.0.1:9",
            "ALL_PROXY": "http://127.0.0.1:9",
            "NO_PROXY": "",
        }
    )
    for key in list(environment):
        if any(
            term in key.upper() for term in ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
        ):
            environment.pop(key)
    return environment


def _run_baseline_once(
    *,
    role: str,
    unit_id: str,
    bundle_dir: Path,
    output_dir: Path,
    interpreter: Path,
    runner_source: Path,
    timeout: int,
) -> tuple[dict[str, Any], Path]:
    workspace = output_dir / "baseline-replay" / role / unit_id
    input_dir = workspace / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    for name in ("input-manifest.json", "train.csv", "test.csv"):
        source = bundle_dir / name
        target = input_dir / name
        if target.exists():
            if _file_sha256(target) != _file_sha256(source):
                raise PortfolioIntegrityError(
                    f"partial baseline input changed: {role}/{unit_id}/{name}"
                )
        else:
            shutil.copy2(source, target)
    runner_path = workspace / "runner.py"
    if runner_path.exists():
        if _file_sha256(runner_path) != _file_sha256(runner_source):
            raise PortfolioIntegrityError(f"partial baseline runner changed: {role}/{unit_id}")
    else:
        shutil.copy2(runner_source, runner_path)

    attempts_root = workspace / "attempts"
    attempts_root.mkdir(parents=True, exist_ok=True)
    for attempt_number in range(1, 4):
        attempt_dir = attempts_root / f"attempt-{attempt_number:02d}"
        result_dir = attempt_dir / "result"
        result_path = result_dir / "runner-result.json"
        status_path = attempt_dir / "attempt-status.json"
        if result_path.exists():
            if not status_path.exists():
                continue
            status = json.loads(status_path.read_text(encoding="utf-8"))
            if not isinstance(status, dict):
                raise PortfolioIntegrityError(
                    f"baseline attempt status is not an object: {role}/{unit_id}"
                )
            if (
                status.get("return_code") == 0
                and status.get("timed_out") is False
                and status.get("result_exists") is True
            ):
                result = json.loads(result_path.read_text(encoding="utf-8"))
                if isinstance(result, dict):
                    return result, attempt_dir
                raise PortfolioIntegrityError(f"baseline result is not an object: {role}/{unit_id}")
            continue
        if attempt_dir.exists():
            continue
        attempt_dir.mkdir(parents=True)
        command = [
            interpreter.as_posix(),
            runner_path.as_posix(),
            "--manifest",
            (input_dir / "input-manifest.json").as_posix(),
            "--output",
            result_dir.as_posix(),
        ]
        return_code: int | None = None
        stdout = ""
        stderr = ""
        timed_out = False
        try:
            completed = subprocess.run(
                command,
                cwd=attempt_dir,
                env=_baseline_environment(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
            return_code = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        except OSError as exc:
            stderr = f"{type(exc).__name__}: {exc}"
        _write_text_atomic(attempt_dir / "runner.stdout.log", stdout)
        _write_text_atomic(attempt_dir / "runner.stderr.log", stderr)
        _write_text_atomic(
            status_path,
            json.dumps(
                {
                    "return_code": return_code,
                    "timed_out": timed_out,
                    "result_exists": result_path.exists(),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
        )
        if return_code == 0 and result_path.exists():
            result = json.loads(result_path.read_text(encoding="utf-8"))
            if isinstance(result, dict):
                return result, attempt_dir
    raise RuntimeError(f"clean baseline {role}/{unit_id} exhausted three exact technical attempts")


def _prepare_task_bundle(
    *,
    unit: OpenObjectiveTaskUnit,
    threshold: FrozenTaskSuccessThreshold,
    freeze: ConfirmatoryEvaluationFreeze,
    ledger: ConfirmationRevealLedger,
    output_dir: Path,
    interpreters: Mapping[str, Path],
    fetch: Callable[[str, int, int], bytes],
) -> ConfirmatoryTaskInput:
    opaque_id = "opaque-" + hashlib.sha256(unit.unit_id.encode()).hexdigest()[:16]
    cache_dir = output_dir / "source-cache" / opaque_id
    data_path = cache_dir / "data.arff"
    split_path = cache_dir / "split.arff"
    if data_path.exists():
        data_bytes = data_path.read_bytes()
    else:
        data_bytes = fetch(unit.data_url, 512 * 1024 * 1024, 180)
        _write_bytes_atomic(data_path, data_bytes)
    if split_path.exists():
        split_bytes = split_path.read_bytes()
    else:
        split_bytes = fetch(unit.split_url, 64 * 1024 * 1024, 120)
        _write_bytes_atomic(split_path, split_bytes)
    observed_md5 = hashlib.md5(data_bytes).hexdigest()
    if observed_md5 != unit.data_md5:
        raise PortfolioIntegrityError(f"{unit.unit_id} OpenML data MD5 mismatch")
    data_sha = hashlib.sha256(data_bytes).hexdigest()
    split_sha = hashlib.sha256(split_bytes).hexdigest()

    bundle_dir = output_dir / "task-bundles" / opaque_id
    labels_path = bundle_dir / "labels.json"
    train_path = bundle_dir / "train.csv"
    test_path = bundle_dir / "test.csv"
    manifest_path = bundle_dir / "input-manifest.json"
    if not all(path.exists() for path in (labels_path, train_path, test_path, manifest_path)):
        attributes, rows = _decode_arff(data_bytes)
        names = [name for name, _ in attributes]
        target_index = next(
            index
            for index, name in enumerate(names)
            if name.casefold() == unit.target_feature.casefold()
        )
        feature_indexes = [index for index in range(len(attributes)) if index != target_index]
        feature_columns = [f"x_{position:04d}" for position in range(len(feature_indexes))]
        numeric_columns = [
            feature_columns[position]
            for position, source_index in enumerate(feature_indexes)
            if attributes[source_index][1].casefold() in {"numeric", "real", "integer"}
        ]
        categorical_columns = [
            column for column in feature_columns if column not in numeric_columns
        ]
        train_ids, test_ids = _split_rows(split_bytes)
        if max([*train_ids, *test_ids]) >= len(rows):
            raise ValueError(f"{unit.unit_id} split references an absent row")
        train_rows = [
            [rows[row_id][index] for index in feature_indexes] + [rows[row_id][target_index]]
            for row_id in train_ids
        ]
        test_rows = [
            [str(row_id)] + [rows[row_id][index] for index in feature_indexes]
            for row_id in test_ids
        ]
        _write_csv(train_path, [*feature_columns, "target"], train_rows)
        _write_csv(test_path, ["row_id", *feature_columns], test_rows)
        raw_labels: list[str | float]
        if unit.family is ObjectiveTaskFamily.TABULAR_CLASSIFICATION:
            raw_labels = [str(rows[row_id][target_index]) for row_id in test_ids]
        else:
            raw_labels = [float(rows[row_id][target_index]) for row_id in test_ids]
        labels = ConfirmatoryLabels.create(
            unit_id=unit.unit_id,
            opaque_unit_id=opaque_id,
            family=unit.family.value,
            confirmation_freeze_hash=freeze.freeze_hash,
            reveal_hash=ledger.reveal_hash,
            row_ids=test_ids,
            labels=raw_labels,
            data_sha256=data_sha,
            split_sha256=split_sha,
            source_data_md5=unit.data_md5,
        )
        _write_text_atomic(labels_path, labels.canonical_json() + "\n")
        input_manifest = {
            "schema_version": "clean-baseline-input-v1",
            "unit_id": opaque_id,
            "family": unit.family.value,
            "feature_columns": feature_columns,
            "numeric_columns": numeric_columns,
            "categorical_columns": categorical_columns,
            "target_column": "target",
            "train_file": "train.csv",
            "test_file": "test.csv",
            "train_sha256": _file_sha256(train_path),
            "test_sha256": _file_sha256(test_path),
            "seed": 263420001,
            "max_trials": 12,
            "validation_fraction": 0.2,
            "estimator_list": ["lgbm", "xgboost", "rf", "extra_tree"],
            "n_jobs": 1,
            "network_allowed": False,
        }
        _write_text_atomic(
            manifest_path,
            json.dumps(
                input_manifest,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
        )
    labels = ConfirmatoryLabels.model_validate_json(labels_path.read_text(encoding="utf-8"))
    if (
        labels.confirmation_freeze_hash != freeze.freeze_hash
        or labels.reveal_hash != ledger.reveal_hash
        or labels.data_sha256 != data_sha
        or labels.split_sha256 != split_sha
    ):
        raise PortfolioIntegrityError(f"{unit.unit_id} cached label binding mismatch")

    runner_source = output_dir / "execution-assets/frozen_flaml_baseline_v1.py"
    runs: dict[str, tuple[dict[str, Any], Path]] = {}
    for role in ("primary", "replay"):
        runs[role] = _run_baseline_once(
            role=role,
            unit_id=opaque_id,
            bundle_dir=bundle_dir,
            output_dir=output_dir,
            interpreter=interpreters[role],
            runner_source=runner_source,
            timeout=600,
        )
    scored: dict[str, tuple[float, str, int]] = {}
    for role, (result, workspace) in runs.items():
        if (
            result.get("network_allowed") is not False
            or result.get("runner_sha256") != freeze.baseline_runner_sha256
            or int(result.get("trial_count", -1)) != 12
            or result.get("train_sha256") != _file_sha256(train_path)
            or result.get("test_sha256") != _file_sha256(test_path)
        ):
            raise PortfolioIntegrityError(f"{unit.unit_id} {role} baseline binding failed")
        scored[role] = _score_prediction_rows(
            family=unit.family.value,
            row_ids=labels.row_ids,
            labels=labels.labels,
            prediction_path=workspace / "result/predictions.json",
        )
    primary_score, metric_id, prediction_count = scored["primary"]
    replay_score, replay_metric, replay_count = scored["replay"]
    primary_prediction = _file_sha256(runs["primary"][1] / "result/predictions.json")
    replay_prediction = _file_sha256(runs["replay"][1] / "result/predictions.json")
    if metric_id != replay_metric or prediction_count != replay_count:
        raise PortfolioIntegrityError(f"{unit.unit_id} baseline replay shape mismatch")
    replay = BaselineConfirmatoryReplay.create(
        unit_id=unit.unit_id,
        opaque_unit_id=opaque_id,
        family=unit.family.value,
        metric_id=metric_id,
        input_manifest_sha256=_file_sha256(manifest_path),
        train_sha256=_file_sha256(train_path),
        test_sha256=_file_sha256(test_path),
        labels_sha256=_file_sha256(labels_path),
        baseline_runner_sha256=freeze.baseline_runner_sha256,
        objective_evaluator_sha256=freeze.objective_evaluator_sha256,
        primary_interpreter_sha256=freeze.clean_interpreter_hashes["primary"],
        replay_interpreter_sha256=freeze.clean_interpreter_hashes["replay"],
        primary_prediction_sha256=primary_prediction,
        replay_prediction_sha256=replay_prediction,
        prediction_count=prediction_count,
        primary_score=primary_score,
        replay_score=replay_score,
    )
    return ConfirmatoryTaskInput.create(
        unit_id=unit.unit_id,
        opaque_unit_id=opaque_id,
        family=unit.family.value,
        benchmark_id=unit.benchmark_id,
        domain=unit.domain,
        independence_group=unit.independence_group,
        train_path=train_path.resolve().as_posix(),
        test_path=test_path.resolve().as_posix(),
        labels_path=labels_path.resolve().as_posix(),
        train_sha256=_file_sha256(train_path),
        test_sha256=_file_sha256(test_path),
        labels_sha256=_file_sha256(labels_path),
        data_sha256=data_sha,
        split_sha256=split_sha,
        source_data_md5=unit.data_md5,
        train_row_count=_csv_data_row_count(train_path),
        test_row_count=_csv_data_row_count(test_path),
        feature_count=len(feature_columns),
        metric_id=metric_id,
        baseline_score=primary_score,
        minimum_gain=threshold.minimum_gain,
        threshold_hash=threshold.threshold_hash,
        baseline_replay=replay,
        reveal_hash=ledger.reveal_hash,
        confirmation_freeze_hash=freeze.freeze_hash,
    )


def prepare_confirmatory_inputs(
    panel_dir: Path,
    baseline_dir: Path,
    output_dir: Path,
    *,
    fetch: Callable[[str, int, int], bytes] = _bounded_get,
    progress: Callable[[str], None] | None = None,
) -> ConfirmatoryExecutionIndex:
    """Download all 60 payloads only after reveal and reproduce paired baselines."""

    index_path = output_dir / EXECUTION_INDEX_FILENAME
    if index_path.exists():
        return load_confirmatory_execution_index(output_dir)
    freeze = load_confirmatory_freeze(output_dir)
    ledger = open_confirmation_reveal(output_dir)
    panel = load_open_objective_task_panel(_panel_report_path(panel_dir))
    baseline, preregistration, _ = load_baseline_preregistration(baseline_dir)
    if (
        panel.report_hash != freeze.panel_report_hash
        or baseline.report_hash != freeze.baseline_report_hash
        or preregistration.preregistration_hash != freeze.preregistration_hash
    ):
        raise PortfolioIntegrityError("confirmation input source binding changed")
    units = {
        item.unit_id: item
        for item in panel.task_units
        if item.partition is PanelPartition.CONFIRMATORY
    }
    thresholds = {item.unit_id: item for item in freeze.task_thresholds}
    if set(units) != set(freeze.confirmatory_unit_ids):
        raise PortfolioIntegrityError("confirmation panel membership changed")
    interpreters: dict[str, Path] = {
        role: Path(path).resolve() for role, path in freeze.clean_interpreter_paths.items()
    }
    tasks: list[ConfirmatoryTaskInput] = []
    for position, unit_id in enumerate(freeze.confirmatory_unit_ids, start=1):
        task = _prepare_task_bundle(
            unit=units[unit_id],
            threshold=thresholds[unit_id],
            freeze=freeze,
            ledger=ledger,
            output_dir=output_dir,
            interpreters=interpreters,
            fetch=fetch,
        )
        tasks.append(task)
        if progress is not None:
            progress(f"{position}/60 prepared {unit_id} " f"baseline={task.baseline_score:.12g}")
    source_urls = sorted(
        [
            locator
            for unit_id in freeze.confirmatory_unit_ids
            for locator in (units[unit_id].data_url, units[unit_id].split_url)
        ]
    )
    index = ConfirmatoryExecutionIndex.create(
        freeze_hash=freeze.freeze_hash,
        reveal_hash=ledger.reveal_hash,
        interpreter_role="primary",
        tasks=tasks,
        source_urls=source_urls,
    )
    _write_text_atomic(index_path, index.canonical_json() + "\n")
    return index


def load_confirmatory_execution_index(
    output_dir: Path,
) -> ConfirmatoryExecutionIndex:
    output_dir = output_dir.resolve()
    freeze = load_confirmatory_freeze(output_dir)
    ledger = ConfirmationRevealLedger.model_validate_json(
        (output_dir / REVEAL_LEDGER_FILENAME).read_text(encoding="utf-8")
    )
    index = ConfirmatoryExecutionIndex.model_validate_json(
        (output_dir / EXECUTION_INDEX_FILENAME).read_text(encoding="utf-8")
    )
    if (
        ledger.freeze_hash != freeze.freeze_hash
        or index.freeze_hash != freeze.freeze_hash
        or index.reveal_hash != ledger.reveal_hash
        or [item.unit_id for item in index.tasks] != freeze.confirmatory_unit_ids
    ):
        raise PortfolioIntegrityError("confirmation execution-index binding mismatch")
    if len({item.independence_group for item in index.tasks}) != 60:
        raise PortfolioIntegrityError("confirmation task inputs are not independent source groups")
    thresholds = {item.unit_id: item for item in freeze.task_thresholds}
    for task in index.tasks:
        if (
            task.threshold_hash != thresholds[task.unit_id].threshold_hash
            or task.minimum_gain != thresholds[task.unit_id].minimum_gain
            or task.baseline_replay.baseline_runner_sha256 != freeze.baseline_runner_sha256
            or task.baseline_replay.objective_evaluator_sha256 != freeze.objective_evaluator_sha256
        ):
            raise PortfolioIntegrityError(
                f"confirmation threshold/baseline binding mismatch: {task.unit_id}"
            )
        for path_text, expected in (
            (task.train_path, task.train_sha256),
            (task.test_path, task.test_sha256),
            (task.labels_path, task.labels_sha256),
        ):
            path = Path(path_text).resolve()
            try:
                path.relative_to(output_dir)
            except ValueError as exc:
                raise PortfolioIntegrityError(
                    f"confirmation task input escaped workspace: {task.unit_id}"
                ) from exc
            if _file_sha256(path) != expected:
                raise PortfolioIntegrityError(
                    f"confirmation task input file mismatch: {task.unit_id}"
                )
        labels = ConfirmatoryLabels.model_validate_json(
            Path(task.labels_path).read_text(encoding="utf-8")
        )
        if (
            labels.unit_id != task.unit_id
            or labels.opaque_unit_id != task.opaque_unit_id
            or labels.confirmation_freeze_hash != freeze.freeze_hash
            or labels.reveal_hash != ledger.reveal_hash
            or labels.data_sha256 != task.data_sha256
            or labels.split_sha256 != task.split_sha256
            or len(labels.labels) != task.test_row_count
        ):
            raise PortfolioIntegrityError(
                f"confirmation evaluator-label binding mismatch: {task.unit_id}"
            )
    return index


class ConfirmatoryTaskPolicyOutcome(KernelContract):
    """Three repeated seeds collapsed to one independent task outcome."""

    schema_version: Literal["confirmatory-task-policy-outcome-v1"] = (
        "confirmatory-task-policy-outcome-v1"
    )
    unit_id: StableId
    policy_id: StableId
    family: Literal["tabular_classification", "tabular_regression"]
    benchmark_id: StableId
    domain: StableId
    seed_successes: dict[StableId, bool]
    seed_margins: dict[StableId, float | None]
    successful_seed_count: int = Field(ge=0, le=3)
    task_success: bool
    median_margin: float | None = None
    attributable_failure_seed_count: int = Field(ge=0, le=3)
    outcome_hash: Sha256

    @model_validator(mode="after")
    def _validate_outcome(self) -> ConfirmatoryTaskPolicyOutcome:
        if list(self.seed_successes) != sorted(self.seed_successes):
            raise ValueError("confirmatory seed successes must be sorted")
        if list(self.seed_margins) != sorted(self.seed_margins):
            raise ValueError("confirmatory seed margins must be sorted")
        if set(self.seed_successes) != set(self.seed_margins):
            raise ValueError("confirmatory seed keys differ")
        if len(self.seed_successes) != 3:
            raise ValueError("confirmatory task requires exactly three seeds")
        observed = sum(self.seed_successes.values())
        if observed != self.successful_seed_count or self.task_success != (observed >= 2):
            raise ValueError("confirmatory two-of-three aggregation mismatch")
        margins = [value for value in self.seed_margins.values() if value is not None]
        expected_median = float(statistics.median(margins)) if margins else None
        if self.median_margin != expected_median:
            raise ValueError("confirmatory median margin mismatch")
        if self.outcome_hash != self.calculated_hash():
            raise PortfolioIntegrityError("confirmatory outcome_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ConfirmatoryTaskPolicyOutcome:
        payload = dict(values)
        payload["schema_version"] = "confirmatory-task-policy-outcome-v1"
        payload["seed_successes"] = dict(sorted(payload["seed_successes"].items()))
        payload["seed_margins"] = dict(sorted(payload["seed_margins"].items()))
        return cls.model_validate(_with_canonical_hash(cls, payload, "outcome_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"outcome_hash"}))


class ConfirmatoryPolicySummary(KernelContract):
    """Task, failure, cost, and candidate-selection summary for one policy."""

    policy_id: StableId
    task_count: Literal[60] = 60
    task_success_count: int = Field(ge=0, le=60)
    task_success_rate: float = Field(ge=0, le=1)
    assignment_count: Literal[180] = 180
    assignment_integrity_success_count: int = Field(ge=0, le=180)
    failure_assignment_count: int = Field(ge=0, le=180)
    failure_code_counts: dict[StableId, int]
    selected_candidate_counts: dict[StableId, int]
    reserved_cpu_seconds: int = Field(ge=0)
    newly_executed_cpu_seconds: float = Field(ge=0)
    newly_executed_wall_seconds: float = Field(ge=0)
    maximum_peak_rss_mb: float = Field(ge=0)
    summary_hash: Sha256

    @model_validator(mode="after")
    def _validate_summary(self) -> ConfirmatoryPolicySummary:
        if not math.isclose(
            self.task_success_rate,
            self.task_success_count / 60,
            rel_tol=0.0,
            abs_tol=1e-15,
        ):
            raise ValueError("confirmatory policy success rate mismatch")
        if self.assignment_integrity_success_count + self.failure_assignment_count != 180:
            raise ValueError("confirmatory assignment counts do not sum")
        if list(self.failure_code_counts) != sorted(self.failure_code_counts):
            raise ValueError("confirmatory failure counts must be sorted")
        if list(self.selected_candidate_counts) != sorted(self.selected_candidate_counts):
            raise ValueError("confirmatory selected-candidate counts must be sorted")
        if self.summary_hash != self.calculated_hash():
            raise PortfolioIntegrityError("confirmatory policy summary_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ConfirmatoryPolicySummary:
        payload = dict(values)
        payload["task_count"] = 60
        payload["assignment_count"] = 180
        payload["failure_code_counts"] = dict(sorted(payload["failure_code_counts"].items()))
        payload["selected_candidate_counts"] = dict(
            sorted(payload["selected_candidate_counts"].items())
        )
        return cls.model_validate(_with_canonical_hash(cls, payload, "summary_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"summary_hash"}))


class ConfirmatoryPolicyComparison(KernelContract):
    """A paired independent-task comparison with exact and sensitivity inference."""

    comparison_id: StableId
    role: Literal["primary", "secondary_arm", "secondary_ablation"]
    policy_a: StableId
    policy_b: StableId
    task_count: Literal[60] = 60
    favorable_to_a: int = Field(ge=0, le=60)
    unfavorable_to_a: int = Field(ge=0, le=60)
    tied: int = Field(ge=0, le=60)
    risk_difference_a_minus_b: float = Field(ge=-1, le=1)
    exact_risk_difference_interval_95: tuple[float, float]
    paired_bootstrap_interval_95: tuple[float, float]
    domain_block_bootstrap_interval_95: tuple[float, float]
    exact_mcnemar_p: float = Field(ge=0, le=1)
    holm_adjusted_p: float | None = Field(default=None, ge=0, le=1)
    interval_method: NonEmptyText = EXACT_INTERVAL_METHOD
    comparison_hash: Sha256

    @model_validator(mode="after")
    def _validate_comparison(self) -> ConfirmatoryPolicyComparison:
        if self.favorable_to_a + self.unfavorable_to_a + self.tied != 60:
            raise ValueError("confirmatory paired counts do not sum to 60")
        for interval in (
            self.exact_risk_difference_interval_95,
            self.paired_bootstrap_interval_95,
            self.domain_block_bootstrap_interval_95,
        ):
            if interval[0] > interval[1]:
                raise ValueError("confirmatory comparison interval is reversed")
        if self.role == "primary" and self.holm_adjusted_p is not None:
            raise ValueError("primary comparison cannot enter secondary Holm family")
        if self.role != "primary" and self.holm_adjusted_p is None:
            raise ValueError("secondary comparison lacks Holm adjustment")
        if self.comparison_hash != self.calculated_hash():
            raise PortfolioIntegrityError("confirmatory comparison_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ConfirmatoryPolicyComparison:
        payload = dict(values)
        payload.update(
            {
                "task_count": 60,
                "interval_method": EXACT_INTERVAL_METHOD,
            }
        )
        return cls.model_validate(_with_canonical_hash(cls, payload, "comparison_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"comparison_hash"}))


class ConfirmatoryFidelityCalibration(KernelContract):
    """Selection-conditioned low-to-full fidelity calibration on task units."""

    policy_id: StableId
    low_stage: Literal["F1", "F2"]
    pair_count: int = Field(ge=0, le=60)
    spearman_rho: float | None = Field(default=None, ge=-1, le=1)
    mean_absolute_error: float | None = Field(default=None, ge=0)
    analysis_unit: Literal["independent task"] = "independent task"
    selection_conditioned: Literal[True] = True
    calibration_hash: Sha256

    @model_validator(mode="after")
    def _validate_calibration(self) -> ConfirmatoryFidelityCalibration:
        if self.pair_count < 2 and self.spearman_rho is not None:
            raise ValueError("confirmatory Spearman needs at least two tasks")
        if self.pair_count == 0 and self.mean_absolute_error is not None:
            raise ValueError("empty calibration cannot report error")
        if self.calibration_hash != self.calculated_hash():
            raise PortfolioIntegrityError("confirmatory calibration_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ConfirmatoryFidelityCalibration:
        payload = dict(values)
        payload.update(
            {
                "analysis_unit": "independent task",
                "selection_conditioned": True,
            }
        )
        return cls.model_validate(_with_canonical_hash(cls, payload, "calibration_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"calibration_hash"}))


class ConfirmatoryNullControlSummary(KernelContract):
    """Prospectively executed prior/mean negative control."""

    candidate_id: Literal["null-prior"] = "null-prior"
    assignment_count: Literal[180] = 180
    task_count: Literal[60] = 60
    task_success_count: int = Field(ge=0, le=60)
    task_success_rate: float = Field(ge=0, le=1)
    integrity_failure_count: int = Field(ge=0, le=180)
    maximum_allowed_task_successes: Literal[3] = 3
    behavior_gate_passed: bool
    integrity_gate_passed: bool
    result_hashes: dict[StableId, Sha256]
    summary_hash: Sha256

    @model_validator(mode="after")
    def _validate_summary(self) -> ConfirmatoryNullControlSummary:
        if len(self.result_hashes) != 180:
            raise ValueError("null-control result inventory is incomplete")
        if not math.isclose(
            self.task_success_rate,
            self.task_success_count / 60,
            rel_tol=0.0,
            abs_tol=1e-15,
        ):
            raise ValueError("null-control task success rate mismatch")
        if self.behavior_gate_passed != (self.task_success_count <= 3):
            raise ValueError("null-control behavior gate mismatch")
        if self.integrity_gate_passed != (self.integrity_failure_count == 0):
            raise ValueError("null-control integrity gate mismatch")
        if self.summary_hash != self.calculated_hash():
            raise PortfolioIntegrityError("null-control summary_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ConfirmatoryNullControlSummary:
        payload = dict(values)
        payload.update(
            {
                "candidate_id": "null-prior",
                "assignment_count": 180,
                "task_count": 60,
                "maximum_allowed_task_successes": 3,
            }
        )
        payload["result_hashes"] = dict(sorted(payload["result_hashes"].items()))
        return cls.model_validate(_with_canonical_hash(cls, payload, "summary_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"summary_hash"}))


class ConfirmatoryBlockEffect(KernelContract):
    """Descriptive OOD robustness projection for one frozen benchmark/domain block."""

    block_type: Literal["benchmark", "domain"]
    block_id: StableId
    task_count: int = Field(ge=1, le=60)
    favorable_to_primary: int = Field(ge=0)
    unfavorable_to_primary: int = Field(ge=0)
    tied: int = Field(ge=0)
    risk_difference: float = Field(ge=-1, le=1)
    inferential_claim: Literal[False] = False
    effect_hash: Sha256

    @model_validator(mode="after")
    def _validate_effect(self) -> ConfirmatoryBlockEffect:
        if self.favorable_to_primary + self.unfavorable_to_primary + self.tied != self.task_count:
            raise ValueError("block-effect task counts do not sum")
        if self.effect_hash != self.calculated_hash():
            raise PortfolioIntegrityError("confirmation block effect_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ConfirmatoryBlockEffect:
        payload = dict(values)
        payload["inferential_claim"] = False
        return cls.model_validate(_with_canonical_hash(cls, payload, "effect_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"effect_hash"}))


class ConfirmatoryCostFailureAudit(KernelContract):
    """Complete failure, resource, cache, and intervention accounting."""

    assignment_count: Literal[1620] = 1620
    null_control_assignment_count: Literal[180] = 180
    candidate_stage_record_count: Literal[77760] = 77_760
    unique_evaluation_count: int = Field(ge=1)
    evaluation_failure_count: int = Field(ge=0)
    logical_cache_reuse_count: int = Field(ge=0)
    failure_code_counts: dict[StableId, int]
    reserved_cpu_seconds: int = Field(ge=0)
    newly_executed_cpu_seconds: float = Field(ge=0)
    newly_executed_wall_seconds: float = Field(ge=0)
    maximum_peak_rss_mb: float = Field(ge=0)
    model_call_count: Literal[0] = 0
    model_token_count: Literal[0] = 0
    human_intervention_count: Literal[0] = 0
    outcome_adaptive_intervention_count: Literal[0] = 0
    unused_budget_reallocated: Literal[False] = False
    audit_hash: Sha256

    @model_validator(mode="after")
    def _validate_audit(self) -> ConfirmatoryCostFailureAudit:
        if list(self.failure_code_counts) != sorted(self.failure_code_counts):
            raise ValueError("confirmatory failure code counts must be sorted")
        if self.audit_hash != self.calculated_hash():
            raise PortfolioIntegrityError("confirmatory cost/failure audit_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ConfirmatoryCostFailureAudit:
        payload = dict(values)
        payload.update(
            {
                "assignment_count": 1620,
                "null_control_assignment_count": 180,
                "candidate_stage_record_count": 77_760,
                "model_call_count": 0,
                "model_token_count": 0,
                "human_intervention_count": 0,
                "outcome_adaptive_intervention_count": 0,
                "unused_budget_reallocated": False,
            }
        )
        payload["failure_code_counts"] = dict(sorted(payload["failure_code_counts"].items()))
        return cls.model_validate(_with_canonical_hash(cls, payload, "audit_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"audit_hash"}))


class ConfirmatoryAnalysis(KernelContract):
    """Deterministic primary, secondary, control, OOD, and cost adjudication."""

    schema_version: Literal["confirmatory-analysis-v1"] = "confirmatory-analysis-v1"
    analysis_unit: Literal["independent OpenML task/source group"] = (
        "independent OpenML task/source group"
    )
    seed_role: Literal["within-task repeated measurement"] = "within-task repeated measurement"
    task_outcomes: list[ConfirmatoryTaskPolicyOutcome] = Field(min_length=540, max_length=540)
    policy_summaries: list[ConfirmatoryPolicySummary] = Field(min_length=9, max_length=9)
    primary_comparison: ConfirmatoryPolicyComparison
    secondary_arm_comparisons: list[ConfirmatoryPolicyComparison] = Field(
        min_length=5,
        max_length=5,
    )
    ablation_comparisons: list[ConfirmatoryPolicyComparison] = Field(
        min_length=5,
        max_length=5,
    )
    fidelity_calibrations: list[ConfirmatoryFidelityCalibration] = Field(
        min_length=18,
        max_length=18,
    )
    null_control: ConfirmatoryNullControlSummary
    block_effects: list[ConfirmatoryBlockEffect] = Field(min_length=36)
    benchmark_family_risk_differences: dict[StableId, float]
    ood_assessment: NonEmptyText
    temporal_assessment: NonEmptyText
    cost_failure_audit: ConfirmatoryCostFailureAudit
    prospective_power: float = Field(
        default=0.801422,
        ge=0.801422,
        le=0.801422,
    )
    observed_power_reported: Literal[False] = False
    secondary_holm_family_size: Literal[10] = 10
    endpoint_checks_before_clean_replay: dict[StableId, bool]
    analysis_hash: Sha256

    @model_validator(mode="after")
    def _validate_analysis(self) -> ConfirmatoryAnalysis:
        if [item.policy_id for item in self.policy_summaries] != sorted(
            item.policy_id for item in self.policy_summaries
        ):
            raise ValueError("confirmatory policy summaries must be sorted")
        if list(self.endpoint_checks_before_clean_replay) != sorted(
            self.endpoint_checks_before_clean_replay
        ):
            raise ValueError("confirmatory endpoint checks must be sorted")
        secondary = [*self.secondary_arm_comparisons, *self.ablation_comparisons]
        if len(secondary) != 10 or any(item.holm_adjusted_p is None for item in secondary):
            raise ValueError("confirmatory Holm family is incomplete")
        if self.analysis_hash != self.calculated_hash():
            raise PortfolioIntegrityError("confirmatory analysis_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ConfirmatoryAnalysis:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "confirmatory-analysis-v1",
                "analysis_unit": "independent OpenML task/source group",
                "seed_role": "within-task repeated measurement",
                "prospective_power": 0.801422,
                "observed_power_reported": False,
                "secondary_holm_family_size": 10,
            }
        )
        payload["endpoint_checks_before_clean_replay"] = dict(
            sorted(payload["endpoint_checks_before_clean_replay"].items())
        )
        payload["benchmark_family_risk_differences"] = dict(
            sorted(payload["benchmark_family_risk_differences"].items())
        )
        return cls.model_validate(_with_canonical_hash(cls, payload, "analysis_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"analysis_hash"}))


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise ValueError("percentile requires values")
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _binomial_cdf(k: int, n: int, probability: float) -> float:
    if probability <= 0:
        return 1.0
    if probability >= 1:
        return 1.0 if k >= n else 0.0
    return sum(
        math.comb(n, value) * probability**value * (1.0 - probability) ** (n - value)
        for value in range(k + 1)
    )


def _binomial_sf(k_minus_one: int, n: int, probability: float) -> float:
    return 1.0 - _binomial_cdf(k_minus_one, n, probability)


def _clopper_pearson_interval(
    successes: int,
    trials: int,
    *,
    confidence: float,
) -> tuple[float, float]:
    if not 0 <= successes <= trials or not 0 < confidence < 1:
        raise ValueError("invalid Clopper-Pearson inputs")
    tail = (1.0 - confidence) / 2.0
    if successes == 0:
        lower = 0.0
    else:
        lo, hi = 0.0, 1.0
        for _ in range(100):
            mid = (lo + hi) / 2.0
            if _binomial_sf(successes - 1, trials, mid) < tail:
                lo = mid
            else:
                hi = mid
        lower = (lo + hi) / 2.0
    if successes == trials:
        upper = 1.0
    else:
        lo, hi = 0.0, 1.0
        for _ in range(100):
            mid = (lo + hi) / 2.0
            if _binomial_cdf(successes, trials, mid) > tail:
                lo = mid
            else:
                hi = mid
        upper = (lo + hi) / 2.0
    return lower, upper


def exact_paired_risk_difference_interval(
    favorable: int,
    unfavorable: int,
    *,
    task_count: int = 60,
) -> tuple[float, float]:
    """Return a conservative exact >=95% interval for paired risk difference."""

    favorable_interval = _clopper_pearson_interval(
        favorable,
        task_count,
        confidence=0.975,
    )
    unfavorable_interval = _clopper_pearson_interval(
        unfavorable,
        task_count,
        confidence=0.975,
    )
    return (
        max(-1.0, favorable_interval[0] - unfavorable_interval[1]),
        min(1.0, favorable_interval[1] - unfavorable_interval[0]),
    )


def _paired_bootstrap(
    differences: Sequence[float],
    *,
    seed_material: str,
    resamples: int = 20_000,
) -> tuple[float, float]:
    rng = random.Random(int(canonical_sha256(seed_material)[:16], 16))
    size = len(differences)
    estimates = [
        statistics.fmean(differences[rng.randrange(size)] for _ in range(size))
        for _ in range(resamples)
    ]
    return _percentile(estimates, 0.025), _percentile(estimates, 0.975)


def _domain_block_bootstrap(
    differences: Mapping[str, float],
    domains: Mapping[str, str],
    *,
    seed_material: str,
    resamples: int = 20_000,
) -> tuple[float, float]:
    by_domain: dict[str, list[float]] = {}
    for unit_id, difference in differences.items():
        by_domain.setdefault(domains[unit_id], []).append(difference)
    domain_ids = sorted(by_domain)
    rng = random.Random(int(canonical_sha256(seed_material)[:16], 16))
    estimates: list[float] = []
    for _ in range(resamples):
        sample = [domain_ids[rng.randrange(len(domain_ids))] for _ in range(len(domain_ids))]
        values = [value for domain_id in sample for value in by_domain[domain_id]]
        estimates.append(statistics.fmean(values))
    return _percentile(estimates, 0.025), _percentile(estimates, 0.975)


def _rank_with_ties(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: (values[index], index))
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position + 1
        while end < len(order) and values[order[end]] == values[order[position]]:
            end += 1
        average = (position + 1 + end) / 2.0
        for index in order[position:end]:
            ranks[index] = average
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
    denominator = math.sqrt(
        sum((value - first_mean) ** 2 for value in first)
        * sum((value - second_mean) ** 2 for value in second)
    )
    if denominator == 0:
        return None
    return max(-1.0, min(1.0, numerator / denominator))


def _load_hashed_json(path: Path, field: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise PortfolioIntegrityError(f"{path} is not a JSON object")
    _verify_json_hash(payload, field)
    return payload


def run_independent_confirmation_controller(
    output_dir: Path,
    *,
    timeout_seconds: int = 43_200,
) -> dict[str, Any]:
    """Run or exactly resume the path-confined standalone primary controller."""

    freeze = load_confirmatory_freeze(output_dir)
    index = load_confirmatory_execution_index(output_dir)
    if index.interpreter_role != "primary":
        raise ValueError("primary execution index has the wrong interpreter role")
    controller_path = output_dir / freeze.execution_assets["policy_controller_relative_path"]
    result_path = output_dir / CONTROLLER_RESULT_RELATIVE
    if result_path.exists():
        result = _load_hashed_json(result_path, "result_hash")
        _verify_controller_result(result, freeze, index)
        return result
    command = [
        freeze.clean_interpreter_paths["primary"],
        controller_path.resolve().as_posix(),
        "--design",
        (output_dir / CONFIRMATION_FREEZE_FILENAME).resolve().as_posix(),
        "--input-index",
        (output_dir / EXECUTION_INDEX_FILENAME).resolve().as_posix(),
        "--output",
        (output_dir / "primary-execution").resolve().as_posix(),
        "--python",
        freeze.clean_interpreter_paths["primary"],
        "--allowed-root",
        output_dir.resolve().as_posix(),
        "--progress",
        (output_dir / "primary-execution/progress.txt").resolve().as_posix(),
    ]
    completed = subprocess.run(
        command,
        cwd=output_dir,
        env=_baseline_environment(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        check=False,
    )
    _write_text_atomic(
        output_dir / "primary-execution/controller.stdout.log",
        completed.stdout,
    )
    _write_text_atomic(
        output_dir / "primary-execution/controller.stderr.log",
        completed.stderr,
    )
    if completed.returncode != 0 or not result_path.exists():
        raise RuntimeError(
            f"independent confirmation controller failed with "
            f"{completed.returncode}: {completed.stderr[-3000:]}"
        )
    result = _load_hashed_json(result_path, "result_hash")
    _verify_controller_result(result, freeze, index)
    return result


def _verify_controller_result(
    result: Mapping[str, Any],
    freeze: ConfirmatoryEvaluationFreeze,
    index: ConfirmatoryExecutionIndex,
) -> None:
    if (
        result.get("freeze_hash") != freeze.freeze_hash
        or result.get("reveal_hash") != index.reveal_hash
        or result.get("execution_index_hash") != index.execution_index_hash
    ):
        raise PortfolioIntegrityError("confirmation controller binding mismatch")
    if (
        result.get("assignment_count") != 1620
        or result.get("null_control_count") != 180
        or result.get("full_matrix_complete") is not True
    ):
        raise PortfolioIntegrityError("confirmation controller matrix is incomplete")
    if (
        result.get("frozen_policy_memory_catalogue_hash")
        != canonical_sha256([item.memory_hash for item in freeze.frozen_policy_memories])
        or result.get("memory_cloned_per_confirmatory_unit") is not True
        or result.get("cross_confirmatory_unit_memory_updates_allowed") is not False
        or result.get("within_unit_seed_memory_updates_allowed") is not True
    ):
        raise PortfolioIntegrityError(
            "confirmation controller changed the task-independence memory rule"
        )
    if (
        result.get("network_accessed") is not False
        or result.get("development_trajectory_accessed") is not False
        or result.get("frozen_development_policy_parameters_used") is not True
        or result.get("raw_development_outcomes_accessed") is not False
        or result.get("external_submission_authorized") is not False
        or result.get("public_release_authorized") is not False
    ):
        raise PortfolioIntegrityError("confirmation controller crossed a permission boundary")


def _update_memory_from_confirmation_result(
    state: ConfirmationMemoryState,
    result: Mapping[str, Any],
    *,
    enabled: bool,
) -> None:
    if (
        not enabled
        or result["selected_candidate_id"] is None
        or result["selected_candidate_family"] is None
        or result["policy_score"] is None
    ):
        return
    for stage in ("F1", "F2"):
        matches = [
            record
            for record in result["stage_records"]
            if record["stage"] == stage
            and record["candidate_id"] == result["selected_candidate_id"]
            and record["status"] == "executed"
            and record["objective_score"] is not None
        ]
        if len(matches) != 1:
            continue
        state.setdefault(stage, {}).setdefault(
            str(result["selected_candidate_family"]),
            [],
        ).append(float(result["policy_score"]) - float(matches[0]["objective_score"]))


def _assignment_results(
    output_dir: Path,
    freeze: ConfirmatoryEvaluationFreeze,
    index: ConfirmatoryExecutionIndex,
    controller: Mapping[str, Any],
    *,
    execution_relative: Path = Path("primary-execution"),
) -> list[dict[str, Any]]:
    task_by_id = {item.unit_id: item for item in index.tasks}
    candidate_ids = [item.candidate_id for item in freeze.candidates]
    policies = {item.policy_id: item for item in freeze.policies}
    initial_memory = {item.policy_id: item.state for item in freeze.frozen_policy_memories}
    expected_memory = {
        (policy_id, unit_id): json.loads(json.dumps(initial_memory[policy_id]))
        for policy_id in policies
        for unit_id in freeze.confirmatory_unit_ids
    }
    results: list[dict[str, Any]] = []
    hashes = controller["assignment_result_hashes"]
    if not isinstance(hashes, dict) or len(hashes) != 1620:
        raise PortfolioIntegrityError("controller assignment hash inventory is incomplete")
    for assignment in freeze.assignments:
        path = (
            output_dir
            / execution_relative
            / "assignments"
            / assignment.assignment_id
            / "result.json"
        )
        result = _load_hashed_json(path, "result_hash")
        if (
            result["result_hash"] != hashes.get(assignment.assignment_id)
            or result["assignment_hash"] != assignment.assignment_hash
            or result["freeze_hash"] != freeze.freeze_hash
            or result["reveal_hash"] != index.reveal_hash
            or result["unit_id"] != assignment.unit_id
            or result["within_unit_seed"] != assignment.within_unit_seed
            or result["policy_id"] != assignment.policy_id
        ):
            raise PortfolioIntegrityError(
                f"confirmation assignment binding mismatch: {assignment.assignment_id}"
            )
        records = result.get("stage_records")
        if not isinstance(records, list) or len(records) != 48:
            raise PortfolioIntegrityError("confirmation assignment lacks 48 stage rows")
        for stage in ("F0", "F1", "F2", "F3"):
            stage_candidates = [
                str(item["candidate_id"]) for item in records if item["stage"] == stage
            ]
            if stage_candidates != candidate_ids:
                raise PortfolioIntegrityError(
                    f"confirmation candidate/stage retention changed: {assignment.assignment_id}"
                )
        task = task_by_id[assignment.unit_id]
        if (
            result["baseline_score"] != task.baseline_score
            or result["minimum_gain"] != task.minimum_gain
        ):
            raise PortfolioIntegrityError("confirmation threshold binding changed")
        gates = (
            bool(result["artifact_valid"]),
            bool(result["prediction_replay_valid"]),
            bool(result["budget_valid"]),
            bool(result["evaluator_integrity_valid"]),
        )
        expected_success = bool(
            result["normalized_margin"] is not None
            and float(result["normalized_margin"]) >= 1.0
            and all(gates)
        )
        if bool(result["objective_task_success"]) != expected_success:
            raise PortfolioIntegrityError("confirmation task success was miscomputed")
        memory_key = (assignment.policy_id, assignment.unit_id)
        state = expected_memory[memory_key]
        if result["memory_before_hash"] != _confirmation_memory_state_hash(state):
            raise PortfolioIntegrityError("confirmation memory lineage is discontinuous")
        _update_memory_from_confirmation_result(
            state,
            result,
            enabled=policies[assignment.policy_id].comparative_memory_enabled,
        )
        if result["memory_after_hash"] != _confirmation_memory_state_hash(state):
            raise PortfolioIntegrityError("confirmation within-task memory update mismatch")
        if result.get("llm_reviewer_score_used") is not False:
            raise PortfolioIntegrityError("LLM reviewer score entered confirmation")
        if result.get("intervention_ids") != []:
            raise PortfolioIntegrityError("unregistered confirmation intervention observed")
        results.append(result)
    return results


def _null_results(
    output_dir: Path,
    freeze: ConfirmatoryEvaluationFreeze,
    index: ConfirmatoryExecutionIndex,
    controller: Mapping[str, Any],
    *,
    execution_relative: Path = Path("primary-execution"),
) -> list[dict[str, Any]]:
    hashes = controller["null_control_result_hashes"]
    if not isinstance(hashes, dict) or len(hashes) != 180:
        raise PortfolioIntegrityError("controller null-control inventory is incomplete")
    results: list[dict[str, Any]] = []
    for unit_id in freeze.confirmatory_unit_ids:
        for seed in freeze.within_unit_seeds:
            control_id = f"null-{unit_id}-{seed}"
            path = output_dir / execution_relative / "null-controls" / control_id / "result.json"
            result = _load_hashed_json(path, "result_hash")
            if (
                result["result_hash"] != hashes.get(control_id)
                or result["freeze_hash"] != freeze.freeze_hash
                or result["reveal_hash"] != index.reveal_hash
                or result["unit_id"] != unit_id
                or result["within_unit_seed"] != seed
                or result["candidate_id"] != "null-prior"
            ):
                raise PortfolioIntegrityError(
                    f"confirmation null-control binding mismatch: {control_id}"
                )
            results.append(result)
    return results


def _scientific_projection_hash(
    freeze: ConfirmatoryEvaluationFreeze,
    index: ConfirmatoryExecutionIndex,
    assignments: Sequence[Mapping[str, Any]],
    null_results: Sequence[Mapping[str, Any]],
) -> str:
    assignment_rows = []
    for result in assignments:
        assignment_rows.append(
            {
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
        )
    null_rows = [
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
        for result in null_results
    ]
    return canonical_sha256(
        {
            "freeze_hash": freeze.freeze_hash,
            "reveal_hash": index.reveal_hash,
            "assignments": assignment_rows,
            "null_controls": null_rows,
        }
    )


def _task_policy_outcomes(
    index: ConfirmatoryExecutionIndex,
    results: Sequence[Mapping[str, Any]],
) -> list[ConfirmatoryTaskPolicyOutcome]:
    task_by_id = {item.unit_id: item for item in index.tasks}
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for result in results:
        grouped.setdefault((str(result["policy_id"]), str(result["unit_id"])), []).append(result)
    outcomes: list[ConfirmatoryTaskPolicyOutcome] = []
    for (policy_id, unit_id), rows in sorted(grouped.items()):
        rows = sorted(rows, key=lambda item: int(item["within_unit_seed"]))
        successes = {
            str(item["within_unit_seed"]): bool(item["objective_task_success"]) for item in rows
        }
        margins = {
            str(item["within_unit_seed"]): (
                float(item["normalized_margin"]) if item["normalized_margin"] is not None else None
            )
            for item in rows
        }
        observed_margins = [value for value in margins.values() if value is not None]
        task = task_by_id[unit_id]
        outcomes.append(
            ConfirmatoryTaskPolicyOutcome.create(
                unit_id=unit_id,
                policy_id=policy_id,
                family=task.family,
                benchmark_id=task.benchmark_id,
                domain=task.domain,
                seed_successes=successes,
                seed_margins=margins,
                successful_seed_count=sum(successes.values()),
                task_success=sum(successes.values()) >= 2,
                median_margin=(
                    float(statistics.median(observed_margins)) if observed_margins else None
                ),
                attributable_failure_seed_count=sum(bool(item["failure_codes"]) for item in rows),
            )
        )
    if len(outcomes) != 540:
        raise PortfolioIntegrityError("confirmation task-policy matrix is incomplete")
    return outcomes


def _policy_summaries(
    outcomes: Sequence[ConfirmatoryTaskPolicyOutcome],
    results: Sequence[Mapping[str, Any]],
) -> list[ConfirmatoryPolicySummary]:
    summaries: list[ConfirmatoryPolicySummary] = []
    for policy_id in sorted({str(item["policy_id"]) for item in results}):
        policy_outcomes = [item for item in outcomes if item.policy_id == policy_id]
        policy_results = [item for item in results if item["policy_id"] == policy_id]
        failure_counts: Counter[str] = Counter()
        selected_counts: Counter[str] = Counter()
        for result in policy_results:
            failure_counts.update(str(code) for code in result["failure_codes"])
            if result["selected_candidate_id"] is not None:
                selected_counts.update([str(result["selected_candidate_id"])])
        integrity_success = sum(
            all(
                (
                    bool(item["artifact_valid"]),
                    bool(item["prediction_replay_valid"]),
                    bool(item["budget_valid"]),
                    bool(item["evaluator_integrity_valid"]),
                )
            )
            for item in policy_results
        )
        task_successes = sum(item.task_success for item in policy_outcomes)
        summaries.append(
            ConfirmatoryPolicySummary.create(
                policy_id=policy_id,
                task_success_count=task_successes,
                task_success_rate=task_successes / 60,
                assignment_integrity_success_count=integrity_success,
                failure_assignment_count=180 - integrity_success,
                failure_code_counts=dict(failure_counts),
                selected_candidate_counts=dict(selected_counts),
                reserved_cpu_seconds=sum(
                    int(item["cost"]["reserved_cpu_seconds"]) for item in policy_results
                ),
                newly_executed_cpu_seconds=sum(
                    float(item["cost"]["newly_executed_cpu_seconds"]) for item in policy_results
                ),
                newly_executed_wall_seconds=sum(
                    float(item["cost"]["newly_executed_wall_seconds"]) for item in policy_results
                ),
                maximum_peak_rss_mb=max(
                    float(item["cost"]["peak_rss_mb"]) for item in policy_results
                ),
            )
        )
    return summaries


def _raw_comparison_values(
    outcomes: Sequence[ConfirmatoryTaskPolicyOutcome],
    *,
    policy_a: str,
    policy_b: str,
) -> tuple[dict[str, float], dict[str, str]]:
    by_key = {(item.policy_id, item.unit_id): item for item in outcomes}
    unit_ids = sorted(item.unit_id for item in outcomes if item.policy_id == policy_a)
    differences = {
        unit_id: float(
            int(by_key[(policy_a, unit_id)].task_success)
            - int(by_key[(policy_b, unit_id)].task_success)
        )
        for unit_id in unit_ids
    }
    domains = {unit_id: by_key[(policy_a, unit_id)].domain for unit_id in unit_ids}
    return differences, domains


def _comparison(
    outcomes: Sequence[ConfirmatoryTaskPolicyOutcome],
    *,
    comparison_id: str,
    role: Literal["primary", "secondary_arm", "secondary_ablation"],
    policy_a: str,
    policy_b: str,
    holm_adjusted_p: float | None = None,
) -> ConfirmatoryPolicyComparison:
    differences, domains = _raw_comparison_values(
        outcomes,
        policy_a=policy_a,
        policy_b=policy_b,
    )
    values = list(differences.values())
    favorable = sum(value > 0 for value in values)
    unfavorable = sum(value < 0 for value in values)
    tied = sum(value == 0 for value in values)
    return ConfirmatoryPolicyComparison.create(
        comparison_id=comparison_id,
        role=role,
        policy_a=policy_a,
        policy_b=policy_b,
        favorable_to_a=favorable,
        unfavorable_to_a=unfavorable,
        tied=tied,
        risk_difference_a_minus_b=statistics.fmean(values),
        exact_risk_difference_interval_95=exact_paired_risk_difference_interval(
            favorable,
            unfavorable,
        ),
        paired_bootstrap_interval_95=_paired_bootstrap(
            values,
            seed_material=f"paired:{comparison_id}",
        ),
        domain_block_bootstrap_interval_95=_domain_block_bootstrap(
            differences,
            domains,
            seed_material=f"domain:{comparison_id}",
        ),
        exact_mcnemar_p=exact_two_sided_sign_test_pvalue(
            favorable,
            unfavorable,
        ),
        holm_adjusted_p=holm_adjusted_p,
    )


def _holm_adjustments(
    comparisons: Sequence[ConfirmatoryPolicyComparison],
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


def _fidelity_calibrations(
    freeze: ConfirmatoryEvaluationFreeze,
    results: Sequence[Mapping[str, Any]],
) -> list[ConfirmatoryFidelityCalibration]:
    calibrations: list[ConfirmatoryFidelityCalibration] = []
    for policy in freeze.policies:
        policy_results = [item for item in results if item["policy_id"] == policy.policy_id]
        for low_stage in ("F1", "F2"):
            pairs_by_task: dict[str, list[tuple[float, float]]] = {}
            for result in policy_results:
                if result["selected_candidate_id"] is None or result["policy_score"] is None:
                    continue
                matches = [
                    record
                    for record in result["stage_records"]
                    if record["stage"] == low_stage
                    and record["candidate_id"] == result["selected_candidate_id"]
                    and record["status"] == "executed"
                    and record["objective_score"] is not None
                ]
                if len(matches) == 1:
                    pairs_by_task.setdefault(str(result["unit_id"]), []).append(
                        (
                            float(matches[0]["objective_score"]),
                            float(result["policy_score"]),
                        )
                    )
            low_values = [
                float(statistics.median([pair[0] for pair in pairs_by_task[unit_id]]))
                for unit_id in sorted(pairs_by_task)
            ]
            high_values = [
                float(statistics.median([pair[1] for pair in pairs_by_task[unit_id]]))
                for unit_id in sorted(pairs_by_task)
            ]
            calibrations.append(
                ConfirmatoryFidelityCalibration.create(
                    policy_id=policy.policy_id,
                    low_stage=low_stage,
                    pair_count=len(low_values),
                    spearman_rho=_pearson(
                        _rank_with_ties(low_values),
                        _rank_with_ties(high_values),
                    ),
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
    return sorted(calibrations, key=lambda item: (item.policy_id, item.low_stage))


def _null_control_summary(
    null_results: Sequence[Mapping[str, Any]],
) -> ConfirmatoryNullControlSummary:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    result_hashes: dict[str, str] = {}
    for result in null_results:
        grouped.setdefault(str(result["unit_id"]), []).append(result)
        key = f"null-{result['unit_id']}-{result['within_unit_seed']}"
        result_hashes[key] = str(result["result_hash"])
    task_successes = 0
    for unit_id, rows in sorted(grouped.items()):
        if len(rows) != 3:
            raise PortfolioIntegrityError(f"null control lacks three seeds: {unit_id}")
        task_successes += sum(bool(item["objective_task_success"]) for item in rows) >= 2
    integrity_failures = sum(
        not all(
            (
                bool(item["artifact_valid"]),
                bool(item["prediction_replay_valid"]),
                bool(item["evaluator_integrity_valid"]),
            )
        )
        for item in null_results
    )
    return ConfirmatoryNullControlSummary.create(
        task_success_count=task_successes,
        task_success_rate=task_successes / 60,
        integrity_failure_count=integrity_failures,
        behavior_gate_passed=task_successes <= 3,
        integrity_gate_passed=integrity_failures == 0,
        result_hashes=result_hashes,
    )


def _block_effects(
    outcomes: Sequence[ConfirmatoryTaskPolicyOutcome],
) -> tuple[list[ConfirmatoryBlockEffect], dict[str, float]]:
    differences, _ = _raw_comparison_values(
        outcomes,
        policy_a="portfolio_memory",
        policy_b="linear_self_loop",
    )
    primary = {item.unit_id: item for item in outcomes if item.policy_id == "portfolio_memory"}
    effects: list[ConfirmatoryBlockEffect] = []
    family_differences: dict[str, float] = {}
    for block_type, key_getter in (
        ("benchmark", lambda item: item.benchmark_id),
        ("domain", lambda item: item.domain),
    ):
        grouped: dict[str, list[float]] = {}
        for unit_id, difference in differences.items():
            grouped.setdefault(key_getter(primary[unit_id]), []).append(difference)
        for block_id, values in sorted(grouped.items()):
            effects.append(
                ConfirmatoryBlockEffect.create(
                    block_type=block_type,
                    block_id=block_id,
                    task_count=len(values),
                    favorable_to_primary=sum(value > 0 for value in values),
                    unfavorable_to_primary=sum(value < 0 for value in values),
                    tied=sum(value == 0 for value in values),
                    risk_difference=statistics.fmean(values),
                )
            )
            if block_type == "benchmark":
                family_differences[block_id] = statistics.fmean(values)
    return effects, dict(sorted(family_differences.items()))


def _runner_scientific_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
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
        "confirmation_freeze_hash",
        "reveal_hash",
        "seed",
        "training_fraction",
        "memory_valid",
        "network_allowed",
    )
    return {key: payload.get(key) for key in keys}


def _evaluation_records(
    output_dir: Path,
    freeze: ConfirmatoryEvaluationFreeze,
    index: ConfirmatoryExecutionIndex,
    *,
    execution_relative: Path = Path("primary-execution"),
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    cache = output_dir / execution_relative / "evaluation-cache"
    tasks = {item.unit_id: item for item in index.tasks}
    candidates = {item.candidate_id: item for item in freeze.candidates}
    runner_path = (output_dir / freeze.execution_assets["candidate_runner_relative_path"]).resolve()
    for path in sorted(cache.glob("*/evaluation.json")):
        item = _load_hashed_json(path, "evaluation_hash")
        unit_id = str(item["unit_id"])
        candidate_id = str(item["candidate_id"])
        stage = str(item["stage"])
        if (
            unit_id not in tasks
            or candidate_id not in candidates
            or stage not in {"F1", "F2", "F3"}
            or int(item["within_unit_seed"]) not in freeze.within_unit_seeds
        ):
            raise PortfolioIntegrityError(
                "confirmation evaluation references an unknown frozen key"
            )
        task = tasks[unit_id]
        candidate = candidates[candidate_id]
        stage_key = cast(Literal["F1", "F2", "F3"], stage)
        expected_id = (
            "confirm-eval-"
            + canonical_sha256(
                {
                    "freeze_hash": freeze.freeze_hash,
                    "unit_id": task.unit_id,
                    "train_sha256": task.train_sha256,
                    "test_sha256": task.test_sha256,
                    "labels_sha256": task.labels_sha256,
                    "candidate_hash": candidate.candidate_hash,
                    "seed": int(item["within_unit_seed"]),
                    "stage": stage,
                }
            )[:24]
        )
        evaluation_dir = path.parent
        config_path = evaluation_dir / "execution-config.json"
        result_path = evaluation_dir / "runner-result.json"
        replay_path = evaluation_dir / "runner-replay.json"
        stdout_path = evaluation_dir / "runner.stdout.log"
        stderr_path = evaluation_dir / "runner.stderr.log"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if (
            item["evaluation_id"] != expected_id
            or evaluation_dir.name != expected_id
            or item["candidate_hash"] != candidate.candidate_hash
            or item["train_sha256"] != task.train_sha256
            or item["test_sha256"] != task.test_sha256
            or item["labels_sha256"] != task.labels_sha256
            or item["runner_source_hash"] != freeze.execution_assets["candidate_runner_sha256"]
            or int(item["maximum_seconds"])
            != int(freeze.fidelity_budget[stage_key]["maximum_seconds"])
            or int(item["maximum_memory_mb"]) != freeze.maximum_memory_mb
            or item["config_hash"] != canonical_sha256(config)
            or config.get("execution_id") != expected_id
            or config.get("confirmation_freeze_hash") != freeze.freeze_hash
            or config.get("reveal_hash") != index.reveal_hash
            or config.get("allowed_root") != output_dir.resolve().as_posix()
            or config.get("train_path") != task.train_path
            or config.get("test_path") != task.test_path
            or config.get("labels_path") != task.labels_path
        ):
            raise PortfolioIntegrityError(
                f"confirmation evaluation binding mismatch: {expected_id}"
            )
        command = [
            freeze.clean_interpreter_paths[index.interpreter_role],
            runner_path.as_posix(),
            "--config",
            config_path.resolve().as_posix(),
            "--output",
            result_path.resolve().as_posix(),
        ]
        if item["command_hash"] != canonical_sha256(command):
            raise PortfolioIntegrityError(
                f"confirmation evaluation command mismatch: {expected_id}"
            )
        for artifact_path, hash_field in (
            (stdout_path, "stdout_sha256"),
            (stderr_path, "stderr_sha256"),
        ):
            if _file_sha256(artifact_path) != item[hash_field]:
                raise PortfolioIntegrityError(
                    f"confirmation evaluation log mismatch: {expected_id}"
                )
        for artifact_path, hash_field in (
            (result_path, "result_file_sha256"),
            (replay_path, "replay_file_sha256"),
        ):
            expected_hash = item[hash_field]
            if expected_hash is not None and (
                not artifact_path.is_file() or _file_sha256(artifact_path) != expected_hash
            ):
                raise PortfolioIntegrityError(
                    f"confirmation evaluation artifact mismatch: {expected_id}"
                )
        if item["status"] == "succeeded":
            runner = _load_hashed_json(result_path, "result_hash")
            if (
                runner.get("candidate_hash") != candidate.candidate_hash
                or runner.get("confirmation_freeze_hash") != freeze.freeze_hash
                or runner.get("reveal_hash") != index.reveal_hash
                or runner.get("network_allowed") is not False
                or runner.get("memory_valid") is not True
                or runner.get("score") != item["score"]
                or runner.get("prediction_sha256") != item["prediction_sha256"]
                or item["artifact_valid"] is not True
                or item["evaluator_integrity_valid"] is not True
                or item["memory_valid"] is not True
                or item["failure_code"] is not None
            ):
                raise PortfolioIntegrityError(
                    f"confirmation successful evaluation is invalid: {expected_id}"
                )
            if stage == "F3":
                replay = _load_hashed_json(replay_path, "result_hash")
                if (
                    item["replay_required"] is not True
                    or item["replay_exact"] is not True
                    or _runner_scientific_projection(runner)
                    != _runner_scientific_projection(replay)
                ):
                    raise PortfolioIntegrityError(f"confirmation F3 replay differs: {expected_id}")
        records.append(item)
    hashes = [str(item["evaluation_hash"]) for item in records]
    if len(hashes) != len(set(hashes)):
        raise PortfolioIntegrityError("confirmation evaluation cache duplicates hashes")
    return records


def _cost_failure_audit(
    results: Sequence[Mapping[str, Any]],
    null_results: Sequence[Mapping[str, Any]],
    evaluations: Sequence[Mapping[str, Any]],
) -> ConfirmatoryCostFailureAudit:
    failure_counts: Counter[str] = Counter()
    for result in results:
        failure_counts.update(str(code) for code in result["failure_codes"])
    for result in null_results:
        if result["failure_code"] is not None:
            failure_counts.update([str(result["failure_code"])])
    assignment_evaluation_hashes = {
        str(record["evaluation_hash"])
        for result in results
        for record in result["stage_records"]
        if record["evaluation_hash"] is not None
    }
    null_only_evaluations = [
        item
        for item in evaluations
        if str(item["evaluation_hash"]) not in assignment_evaluation_hashes
    ]
    return ConfirmatoryCostFailureAudit.create(
        unique_evaluation_count=len(evaluations),
        evaluation_failure_count=sum(item["status"] == "failed" for item in evaluations),
        logical_cache_reuse_count=sum(
            record["cache_reused"] is True
            for result in results
            for record in result["stage_records"]
        ),
        failure_code_counts=dict(failure_counts),
        reserved_cpu_seconds=sum(int(item["cost"]["reserved_cpu_seconds"]) for item in results)
        + 180 * 60,
        newly_executed_cpu_seconds=sum(
            float(item["cost"]["newly_executed_cpu_seconds"]) for item in results
        )
        + sum(float(item["cpu_seconds"]) for item in null_only_evaluations),
        newly_executed_wall_seconds=sum(
            float(item["cost"]["newly_executed_wall_seconds"]) for item in results
        )
        + sum(float(item["wall_seconds"]) for item in null_only_evaluations),
        maximum_peak_rss_mb=max(
            [float(item["cost"]["peak_rss_mb"]) for item in results]
            + [float(item["peak_rss_mb"]) for item in evaluations],
            default=0.0,
        ),
    )


def analyze_confirmatory_evaluation(
    output_dir: Path,
    *,
    controller: Mapping[str, Any] | None = None,
) -> tuple[
    ConfirmatoryAnalysis,
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Independently reconstruct all prospective analyses from raw row artifacts."""

    freeze = load_confirmatory_freeze(output_dir)
    index = load_confirmatory_execution_index(output_dir)
    controller_result = (
        dict(controller)
        if controller is not None
        else _load_hashed_json(
            output_dir / CONTROLLER_RESULT_RELATIVE,
            "result_hash",
        )
    )
    _verify_controller_result(controller_result, freeze, index)
    results = _assignment_results(output_dir, freeze, index, controller_result)
    null_results = _null_results(output_dir, freeze, index, controller_result)
    projection_hash = _scientific_projection_hash(
        freeze,
        index,
        results,
        null_results,
    )
    if projection_hash != controller_result["scientific_projection_hash"]:
        raise PortfolioIntegrityError("independent confirmation scientific projection mismatch")
    outcomes = _task_policy_outcomes(index, results)
    summaries = _policy_summaries(outcomes, results)
    primary = _comparison(
        outcomes,
        comparison_id="portfolio-memory-vs-linear-self-loop",
        role="primary",
        policy_a="portfolio_memory",
        policy_b="linear_self_loop",
    )

    arms = [item.value for item in StudyArm]
    raw_arms: list[ConfirmatoryPolicyComparison] = []
    for position, first in enumerate(arms):
        for second in arms[position + 1 :]:
            if {first, second} == {"portfolio_memory", "linear_self_loop"}:
                continue
            raw_arms.append(
                _comparison(
                    outcomes,
                    comparison_id=f"{first}-vs-{second}",
                    role="secondary_arm",
                    policy_a=first,
                    policy_b=second,
                    holm_adjusted_p=1.0,
                )
            )
    raw_ablations = [
        _comparison(
            outcomes,
            comparison_id=f"portfolio-memory-vs-ablation-{ablation.value}",
            role="secondary_ablation",
            policy_a="portfolio_memory",
            policy_b=f"ablation-{ablation.value}",
            holm_adjusted_p=1.0,
        )
        for ablation in StudyAblation
    ]
    observed_secondary_ids = {item.comparison_id for item in [*raw_arms, *raw_ablations]}
    if observed_secondary_ids != set(freeze.statistical_policy.secondary_comparison_ids):
        raise PortfolioIntegrityError(
            "confirmatory secondary comparisons differ from the frozen Holm family"
        )
    adjusted = _holm_adjustments([*raw_arms, *raw_ablations])
    secondary_arms = [
        _comparison(
            outcomes,
            comparison_id=item.comparison_id,
            role="secondary_arm",
            policy_a=item.policy_a,
            policy_b=item.policy_b,
            holm_adjusted_p=adjusted[item.comparison_id],
        )
        for item in raw_arms
    ]
    ablations = [
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
    null_control = _null_control_summary(null_results)
    block_effects, family_differences = _block_effects(outcomes)
    evaluations = _evaluation_records(output_dir, freeze, index)
    referenced = {
        str(record["evaluation_hash"])
        for result in results
        for record in result["stage_records"]
        if record["evaluation_hash"] is not None
    }.union(str(item["evaluation_hash"]) for item in null_results)
    available = {str(item["evaluation_hash"]) for item in evaluations}
    if referenced != available:
        raise PortfolioIntegrityError(
            "confirmation result/evaluation provenance inventory mismatch"
        )
    summary_by_id = {item.policy_id: item for item in summaries}
    baseline_valid = bool(
        len(index.tasks) == 60
        and all(
            item.baseline_replay_exact
            and item.baseline_replay.prediction_replay_exact
            and item.baseline_replay.score_replay_within_tolerance
            for item in index.tasks
        )
    )
    checks = {
        "all-60-independent-tasks-valid": len(index.tasks) == 60,
        "baseline-a-b-replay-exact": baseline_valid,
        "both-benchmark-family-risk-differences-nonnegative": all(
            value >= 0 for value in family_differences.values()
        ),
        "complete-1620-assignment-matrix": (
            len(results) == 1620 and controller_result["full_matrix_complete"] is True
        ),
        "linear-self-loop-zero-integrity-or-budget-failures": (
            summary_by_id["linear_self_loop"].failure_assignment_count == 0
        ),
        "no-confirmatory-leakage-or-post-reveal-retuning": (
            controller_result["development_trajectory_accessed"] is False
            and controller_result["network_accessed"] is False
            and freeze.development_trajectory_access_authorized is False
            and freeze.claim.post_reveal_retuning_allowed is False
            and freeze.claim.result_contingent_route_change_allowed is False
        ),
        "null-control-task-successes-at-most-3": null_control.behavior_gate_passed,
        "null-control-zero-integrity-failures": null_control.integrity_gate_passed,
        "portfolio-memory-zero-integrity-or-budget-failures": (
            summary_by_id["portfolio_memory"].failure_assignment_count == 0
        ),
        "primary-exact-interval-lower-above-zero": (
            primary.exact_risk_difference_interval_95[0] > 0
        ),
        "primary-exact-mcnemar-p-at-most-0.05": primary.exact_mcnemar_p <= 0.05,
        "primary-risk-difference-at-least-0.25": (primary.risk_difference_a_minus_b >= 0.25),
    }
    analysis = ConfirmatoryAnalysis.create(
        task_outcomes=outcomes,
        policy_summaries=summaries,
        primary_comparison=primary,
        secondary_arm_comparisons=sorted(
            secondary_arms,
            key=lambda item: item.comparison_id,
        ),
        ablation_comparisons=sorted(
            ablations,
            key=lambda item: item.comparison_id,
        ),
        fidelity_calibrations=_fidelity_calibrations(freeze, results),
        null_control=null_control,
        block_effects=sorted(
            block_effects,
            key=lambda item: (item.block_type, item.block_id),
        ),
        benchmark_family_risk_differences=family_differences,
        ood_assessment=(
            "All 60 confirmation source groups are disjoint from the seven "
            "development source groups by the frozen panel registry. Benchmark "
            "and domain effects are reported descriptively without creating new "
            "independent units. Development-terminal policy memory is frozen, "
            "cloned separately for every confirmation task, and updated only "
            "across that task's three within-unit seeds."
        ),
        temporal_assessment=(
            "Not applicable: the frozen CC18/CTR23 task registry contains no "
            "prospective temporal field, so no temporal claim is made."
        ),
        cost_failure_audit=_cost_failure_audit(
            results,
            null_results,
            evaluations,
        ),
        endpoint_checks_before_clean_replay=checks,
    )
    return analysis, results, null_results


class CleanRoomConfirmationReplay(KernelContract):
    """Full second-controller replay in a clean directory and interpreter."""

    schema_version: Literal["clean-room-confirmation-replay-v1"] = (
        "clean-room-confirmation-replay-v1"
    )
    freeze_hash: Sha256
    reveal_hash: Sha256
    primary_execution_index_hash: Sha256
    replay_execution_index_hash: Sha256
    primary_controller_result_hash: Sha256
    replay_controller_result_hash: Sha256
    primary_scientific_projection_hash: Sha256
    replay_scientific_projection_hash: Sha256
    assignment_count: Literal[1620] = 1620
    null_control_count: Literal[180] = 180
    input_files_copied: Literal[180] = 180
    replay_interpreter_role: Literal["replay"] = "replay"
    scientific_projection_exact: Literal[True] = True
    primary_results_visible_to_replay_controller: Literal[False] = False
    development_trajectories_visible_to_replay_controller: Literal[False] = False
    network_accessed: Literal[False] = False
    replay_hash: Sha256

    @model_validator(mode="after")
    def _validate_replay(self) -> CleanRoomConfirmationReplay:
        if self.primary_scientific_projection_hash != self.replay_scientific_projection_hash:
            raise ValueError("clean-room confirmation projection is not exact")
        if self.replay_hash != self.calculated_hash():
            raise PortfolioIntegrityError("clean-room confirmation replay_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> CleanRoomConfirmationReplay:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "clean-room-confirmation-replay-v1",
                "assignment_count": 1620,
                "null_control_count": 180,
                "input_files_copied": 180,
                "replay_interpreter_role": "replay",
                "scientific_projection_exact": True,
                "primary_results_visible_to_replay_controller": False,
                "development_trajectories_visible_to_replay_controller": False,
                "network_accessed": False,
            }
        )
        return cls.model_validate(_with_canonical_hash(cls, payload, "replay_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"replay_hash"}))

    def verify_integrity(self) -> None:
        if self.replay_hash != self.calculated_hash():
            raise PortfolioIntegrityError("clean-room confirmation replay_hash mismatch")


def _prepare_clean_replay_index(
    output_dir: Path,
    freeze: ConfirmatoryEvaluationFreeze,
    primary_index: ConfirmatoryExecutionIndex,
) -> tuple[Path, ConfirmatoryExecutionIndex]:
    replay_root = output_dir / "clean-room-replay"
    index_path = replay_root / EXECUTION_INDEX_FILENAME
    if index_path.exists():
        return (
            replay_root,
            ConfirmatoryExecutionIndex.model_validate_json(index_path.read_text(encoding="utf-8")),
        )
    replay_root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        output_dir / CONFIRMATION_FREEZE_FILENAME,
        replay_root / CONFIRMATION_FREEZE_FILENAME,
    )
    shutil.copytree(
        output_dir / "execution-assets",
        replay_root / "execution-assets",
        dirs_exist_ok=True,
    )
    tasks: list[ConfirmatoryTaskInput] = []
    for source in primary_index.tasks:
        bundle_dir = replay_root / "task-bundles" / source.opaque_unit_id
        bundle_dir.mkdir(parents=True, exist_ok=True)
        copied: dict[str, Path] = {}
        for field, name in (
            ("train_path", "train.csv"),
            ("test_path", "test.csv"),
            ("labels_path", "labels.json"),
        ):
            target = bundle_dir / name
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
        freeze_hash=freeze.freeze_hash,
        reveal_hash=primary_index.reveal_hash,
        interpreter_role="replay",
        tasks=tasks,
        source_urls=primary_index.source_urls,
    )
    _write_text_atomic(index_path, index.canonical_json() + "\n")
    return replay_root, index


def run_clean_room_confirmation_replay(
    output_dir: Path,
    primary_controller: Mapping[str, Any],
    *,
    timeout_seconds: int = 43_200,
) -> CleanRoomConfirmationReplay:
    """Re-execute the full matrix without exposing primary result paths."""

    report_path = output_dir / REPLAY_REPORT_FILENAME
    if report_path.exists():
        return CleanRoomConfirmationReplay.model_validate_json(
            report_path.read_text(encoding="utf-8")
        )
    freeze = load_confirmatory_freeze(output_dir)
    primary_index = load_confirmatory_execution_index(output_dir)
    replay_root, replay_index = _prepare_clean_replay_index(
        output_dir,
        freeze,
        primary_index,
    )
    controller_path = replay_root / freeze.execution_assets["policy_controller_relative_path"]
    controller_result_path = replay_root / "replay-execution/controller-result.json"
    if not controller_result_path.exists():
        command = [
            freeze.clean_interpreter_paths["replay"],
            controller_path.resolve().as_posix(),
            "--design",
            (replay_root / CONFIRMATION_FREEZE_FILENAME).resolve().as_posix(),
            "--input-index",
            (replay_root / EXECUTION_INDEX_FILENAME).resolve().as_posix(),
            "--output",
            (replay_root / "replay-execution").resolve().as_posix(),
            "--python",
            freeze.clean_interpreter_paths["replay"],
            "--allowed-root",
            replay_root.resolve().as_posix(),
            "--progress",
            (replay_root / "replay-execution/progress.txt").resolve().as_posix(),
        ]
        completed = subprocess.run(
            command,
            cwd=replay_root,
            env=_baseline_environment(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        _write_text_atomic(
            replay_root / "replay-execution/controller.stdout.log",
            completed.stdout,
        )
        _write_text_atomic(
            replay_root / "replay-execution/controller.stderr.log",
            completed.stderr,
        )
        if completed.returncode != 0 or not controller_result_path.exists():
            raise RuntimeError(
                f"clean-room confirmation controller failed with "
                f"{completed.returncode}: {completed.stderr[-3000:]}"
            )
    replay_controller = _load_hashed_json(
        controller_result_path,
        "result_hash",
    )
    _verify_controller_result(replay_controller, freeze, replay_index)
    replay_freeze = load_confirmatory_freeze(replay_root)
    replay_assignments = _assignment_results(
        replay_root,
        replay_freeze,
        replay_index,
        replay_controller,
        execution_relative=Path("replay-execution"),
    )
    replay_null = _null_results(
        replay_root,
        replay_freeze,
        replay_index,
        replay_controller,
        execution_relative=Path("replay-execution"),
    )
    _evaluation_records(
        replay_root,
        replay_freeze,
        replay_index,
        execution_relative=Path("replay-execution"),
    )
    reconstructed = _scientific_projection_hash(
        replay_freeze,
        replay_index,
        replay_assignments,
        replay_null,
    )
    if reconstructed != replay_controller["scientific_projection_hash"]:
        raise PortfolioIntegrityError(
            "clean-room controller projection failed independent reconstruction"
        )
    if reconstructed != primary_controller["scientific_projection_hash"]:
        raise PortfolioIntegrityError(
            "clean-room scientific projection differs from primary execution"
        )
    replay = CleanRoomConfirmationReplay.create(
        freeze_hash=freeze.freeze_hash,
        reveal_hash=primary_index.reveal_hash,
        primary_execution_index_hash=primary_index.execution_index_hash,
        replay_execution_index_hash=replay_index.execution_index_hash,
        primary_controller_result_hash=primary_controller["result_hash"],
        replay_controller_result_hash=replay_controller["result_hash"],
        primary_scientific_projection_hash=primary_controller["scientific_projection_hash"],
        replay_scientific_projection_hash=reconstructed,
    )
    _write_text_atomic(report_path, replay.canonical_json() + "\n")
    return replay


class ConfirmationStatus(str, Enum):
    """Terminal status of a fully preserved Task 263.6 endpoint."""

    POSITIVE_CONFIRMATION = "positive_confirmation"
    CREDIBLE_NEGATIVE_CONFIRMATION = "credible_negative_confirmation"
    INVALID_CONFIRMATION = "invalid_confirmation"


def confirmation_status(
    endpoint_checks: Mapping[str, bool],
    validity_checks: Mapping[str, bool],
) -> ConfirmationStatus:
    valid = all(validity_checks.values())
    if valid and all(endpoint_checks.values()):
        return ConfirmationStatus.POSITIVE_CONFIRMATION
    if valid:
        return ConfirmationStatus.CREDIBLE_NEGATIVE_CONFIRMATION
    return ConfirmationStatus.INVALID_CONFIRMATION


class ConfirmatoryEvaluationReport(KernelContract):
    """Top-level immutable positive, credible-negative, or invalid endpoint."""

    schema_version: Literal["confirmatory-evaluation-report-v1"] = (
        "confirmatory-evaluation-report-v1"
    )
    report_id: Literal["task-263.6-independent-confirmatory-evaluation"] = (
        "task-263.6-independent-confirmatory-evaluation"
    )
    freeze_hash: Sha256
    reveal_hash: Sha256
    execution_index_hash: Sha256
    controller_result_hash: Sha256
    controller_scientific_projection_hash: Sha256
    analysis: ConfirmatoryAnalysis
    clean_room_replay: CleanRoomConfirmationReplay
    endpoint_checks: dict[StableId, bool]
    validity_checks: dict[StableId, bool]
    status: ConfirmationStatus
    credible_negative_endpoint: bool
    complete_confirmatory_matrix: Literal[True] = True
    all_outcomes_retained: Literal[True] = True
    one_use_reveal_completed: Literal[True] = True
    post_reveal_retuning_authorized: Literal[False] = False
    confirmation_panel_reopen_authorized: Literal[False] = False
    result_contingent_route_change_authorized: Literal[False] = False
    public_release_authorized: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    completed_at: datetime
    report_hash: Sha256

    @field_validator("completed_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("confirmation report time must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _validate_report(self) -> ConfirmatoryEvaluationReport:
        if list(self.endpoint_checks) != sorted(self.endpoint_checks):
            raise ValueError("confirmation endpoint checks must be sorted")
        if list(self.validity_checks) != sorted(self.validity_checks):
            raise ValueError("confirmation validity checks must be sorted")
        expected = confirmation_status(
            self.endpoint_checks,
            self.validity_checks,
        )
        if self.status is not expected:
            raise ValueError("confirmation report status differs from conjunction")
        if self.credible_negative_endpoint != (
            self.status is ConfirmationStatus.CREDIBLE_NEGATIVE_CONFIRMATION
        ):
            raise ValueError("credible-negative flag differs from status")
        if self.report_hash != self.calculated_hash():
            raise PortfolioIntegrityError("confirmation report_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ConfirmatoryEvaluationReport:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "confirmatory-evaluation-report-v1",
                "report_id": "task-263.6-independent-confirmatory-evaluation",
                "complete_confirmatory_matrix": True,
                "all_outcomes_retained": True,
                "one_use_reveal_completed": True,
                "post_reveal_retuning_authorized": False,
                "confirmation_panel_reopen_authorized": False,
                "result_contingent_route_change_authorized": False,
                "public_release_authorized": False,
                "external_submission_authorized": False,
            }
        )
        payload["endpoint_checks"] = dict(sorted(payload["endpoint_checks"].items()))
        payload["validity_checks"] = dict(sorted(payload["validity_checks"].items()))
        return cls.model_validate(_with_canonical_hash(cls, payload, "report_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"report_hash"}))

    def verify_integrity(self) -> None:
        if self.report_hash != self.calculated_hash():
            raise PortfolioIntegrityError("confirmation report_hash mismatch")


class ConfirmatoryArtifactManifest(KernelContract):
    """Content inventory for the internal one-use confirmation research object."""

    schema_version: Literal["confirmatory-artifact-manifest-v1"] = (
        "confirmatory-artifact-manifest-v1"
    )
    freeze_hash: Sha256
    reveal_hash: Sha256
    report_hash: Sha256
    files: dict[NonEmptyText, Sha256]
    internal_confirmatory_payloads_included: Literal[True] = True
    development_trajectories_included: Literal[False] = False
    public_release_authorized: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    manifest_hash: Sha256

    @model_validator(mode="after")
    def _validate_manifest(self) -> ConfirmatoryArtifactManifest:
        if list(self.files) != sorted(self.files):
            raise ValueError("confirmation manifest files must be sorted")
        if self.manifest_hash != self.calculated_hash():
            raise PortfolioIntegrityError("confirmation manifest_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ConfirmatoryArtifactManifest:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "confirmatory-artifact-manifest-v1",
                "internal_confirmatory_payloads_included": True,
                "development_trajectories_included": False,
                "public_release_authorized": False,
                "external_submission_authorized": False,
            }
        )
        payload["files"] = dict(sorted(payload["files"].items()))
        return cls.model_validate(_with_canonical_hash(cls, payload, "manifest_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"manifest_hash"}))

    def verify_integrity(self) -> None:
        if self.manifest_hash != self.calculated_hash():
            raise PortfolioIntegrityError("confirmation manifest_hash mismatch")


CONFIRMATORY_CONTRACT_MODELS = (
    ConfirmationAssignment,
    FrozenPolicyMemory,
    ConfirmatoryStatisticalPolicy,
    FrozenConfirmatoryClaim,
    CleanEnvironmentPackageSnapshot,
    ConfirmatoryEvaluationFreeze,
    ConfirmationRevealLedger,
    ConfirmatoryLabels,
    BaselineConfirmatoryReplay,
    ConfirmatoryTaskInput,
    ConfirmatoryExecutionIndex,
    ConfirmatoryTaskPolicyOutcome,
    ConfirmatoryPolicySummary,
    ConfirmatoryPolicyComparison,
    ConfirmatoryFidelityCalibration,
    ConfirmatoryNullControlSummary,
    ConfirmatoryBlockEffect,
    ConfirmatoryCostFailureAudit,
    ConfirmatoryAnalysis,
    CleanRoomConfirmationReplay,
    ConfirmatoryEvaluationReport,
    ConfirmatoryArtifactManifest,
)


def confirmatory_json_schemas() -> dict[str, dict[str, Any]]:
    return {model.__name__: model.model_json_schema() for model in CONFIRMATORY_CONTRACT_MODELS}


def render_confirmatory_markdown(report: ConfirmatoryEvaluationReport) -> str:
    primary = report.analysis.primary_comparison
    rows = [
        "# Independent confirmatory evaluation",
        "",
        f"- Status: `{report.status.value}`",
        f"- Independent tasks: `{primary.task_count}`",
        "- Seeds: within-task repeats; task success requires at least 2 of 3.",
        f"- Primary risk difference: `{primary.risk_difference_a_minus_b:.6f}`",
        (
            "- Conservative exact 95% interval: "
            f"`[{primary.exact_risk_difference_interval_95[0]:.6f}, "
            f"{primary.exact_risk_difference_interval_95[1]:.6f}]`"
        ),
        f"- Exact two-sided McNemar p: `{primary.exact_mcnemar_p:.12g}`",
        (
            "- Paired task bootstrap 95% interval: "
            f"`[{primary.paired_bootstrap_interval_95[0]:.6f}, "
            f"{primary.paired_bootstrap_interval_95[1]:.6f}]`"
        ),
        (
            "- Domain-block bootstrap 95% interval: "
            f"`[{primary.domain_block_bootstrap_interval_95[0]:.6f}, "
            f"{primary.domain_block_bootstrap_interval_95[1]:.6f}]`"
        ),
        (
            "- Null-control task successes: "
            f"`{report.analysis.null_control.task_success_count}/60`"
        ),
        (
            "- Memory independence: frozen development-terminal state cloned "
            "per task; no cross-task confirmation update."
        ),
        (
            "- Full clean-room scientific replay: "
            f"`{report.clean_room_replay.scientific_projection_exact}`"
        ),
        "",
        "## Endpoint checks",
        "",
    ]
    rows.extend(f"- `{key}`: `{value}`" for key, value in report.endpoint_checks.items())
    rows.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            (
                "This endpoint concerns a frozen bounded tabular-ML search policy. "
                "It is not evidence of general autonomous scientific discovery. "
                "A negative endpoint is retained without retuning the panel; a "
                "positive endpoint still requires Task 263.7 novelty, claim, Open "
                "Science, human authorship, license, venue, and submission review."
            ),
            "",
            "Public release and external submission remain unauthorized.",
            "",
        ]
    )
    return "\n".join(rows)


def _write_confirmatory_manifest(
    output_dir: Path,
    freeze: ConfirmatoryEvaluationFreeze,
    ledger: ConfirmationRevealLedger,
    report: ConfirmatoryEvaluationReport,
) -> ConfirmatoryArtifactManifest:
    manifest_path = output_dir / CONFIRMATION_MANIFEST_FILENAME
    files = {
        path.relative_to(output_dir).as_posix(): _file_sha256(path)
        for path in sorted(output_dir.rglob("*"))
        if path.is_file() and path != manifest_path and not path.name.endswith(".tmp")
    }
    manifest = ConfirmatoryArtifactManifest.create(
        freeze_hash=freeze.freeze_hash,
        reveal_hash=ledger.reveal_hash,
        report_hash=report.report_hash,
        files=files,
    )
    _write_text_atomic(manifest_path, manifest.canonical_json() + "\n")
    return manifest


def _verify_confirmatory_manifest_files(
    output_dir: Path,
    manifest: ConfirmatoryArtifactManifest,
) -> None:
    manifest_path = output_dir / CONFIRMATION_MANIFEST_FILENAME
    current = {
        path.relative_to(output_dir).as_posix()
        for path in output_dir.rglob("*")
        if path.is_file() and path != manifest_path and not path.name.endswith(".tmp")
    }
    if current != set(manifest.files):
        missing = sorted(set(manifest.files) - current)
        extra = sorted(current - set(manifest.files))
        raise PortfolioIntegrityError(
            "confirmation manifest inventory mismatch; " f"missing={missing}, extra={extra}"
        )
    for relative, expected in manifest.files.items():
        if _file_sha256(output_dir / relative) != expected:
            raise PortfolioIntegrityError(f"confirmation manifest file hash mismatch: {relative}")


def _confirmation_validity_checks(
    freeze: ConfirmatoryEvaluationFreeze,
    ledger: ConfirmationRevealLedger,
    index: ConfirmatoryExecutionIndex,
    controller: Mapping[str, Any],
    analysis: ConfirmatoryAnalysis,
    replay: CleanRoomConfirmationReplay,
) -> dict[str, bool]:
    unresolved_integrity_codes = {
        "evaluator_integrity_failure",
        "prediction_replay_failure",
        "runner_artifact_invalid",
        "runner_artifact_missing",
        "runner_infrastructure_error",
    }
    return {
        "all-frozen-assets-interpreters-and-package-locks-content-addressed": (
            freeze.clean_environment_lock_verified and len(freeze.clean_environment_snapshots) == 2
        ),
        "all-source-payload-md5-and-task-bundle-hashes-valid": (
            index.all_data_md5_verified
            and len(index.tasks) == 60
            and len({item.independence_group for item in index.tasks}) == 60
        ),
        "baseline-a-b-replay-exact": analysis.endpoint_checks_before_clean_replay[
            "baseline-a-b-replay-exact"
        ],
        "complete-matrix-and-provenance-inventory": (
            controller["full_matrix_complete"] is True
            and controller["assignment_count"] == 1620
            and controller["null_control_count"] == 180
            and analysis.cost_failure_audit.candidate_stage_record_count == 77_760
        ),
        "full-clean-room-scientific-projection-exact": (
            replay.scientific_projection_exact
            and replay.primary_scientific_projection_hash
            == replay.replay_scientific_projection_hash
        ),
        "independent-controller-network-and-development-isolation": (
            freeze.independent_runner_static_audit_passed
            and controller["network_accessed"] is False
            and controller["development_trajectory_accessed"] is False
            and controller["frozen_development_policy_parameters_used"] is True
            and controller["raw_development_outcomes_accessed"] is False
            and index.development_trajectory_paths_exposed is False
        ),
        "null-control-integrity-valid": analysis.null_control.integrity_gate_passed,
        "no-unresolved-infrastructure-or-evaluator-integrity-failures": not any(
            analysis.cost_failure_audit.failure_code_counts.get(code, 0)
            for code in unresolved_integrity_codes
        ),
        "task-independent-memory-clones-valid": (
            freeze.memory_cloned_per_confirmatory_unit
            and freeze.cross_confirmatory_unit_memory_updates_allowed is False
            and freeze.within_unit_seed_memory_updates_allowed
            and controller["memory_cloned_per_confirmatory_unit"] is True
            and controller["cross_confirmatory_unit_memory_updates_allowed"] is False
            and controller["within_unit_seed_memory_updates_allowed"] is True
        ),
        "one-use-reveal-opened-after-freeze": (
            ledger.reveal_ordinal == 1
            and ledger.previous_reveal_exists is False
            and ledger.opened_at >= freeze.created_at
            and ledger.result_record_count_at_open == 0
        ),
        "prospective-statistical-policy-and-route-unchanged": (
            freeze.claim.post_reveal_retuning_allowed is False
            and freeze.claim.result_contingent_route_change_allowed is False
            and ledger.outcome_adaptive_change_authorized is False
        ),
    }


def run_confirmatory_evaluation(
    panel_dir: Path,
    baseline_dir: Path,
    output_dir: Path,
    *,
    completed_at: datetime | None = None,
    controller_timeout_seconds: int = 172_800,
    progress: Callable[[str], None] | None = None,
) -> ConfirmatoryEvaluationReport:
    """Execute or exactly resume the frozen one-use confirmation endpoint."""

    output_dir = output_dir.resolve()
    report_path = output_dir / CONFIRMATION_REPORT_FILENAME
    manifest_path = output_dir / CONFIRMATION_MANIFEST_FILENAME
    if report_path.exists() or manifest_path.exists():
        if not report_path.exists() or not manifest_path.exists():
            raise PortfolioIntegrityError("partial top-level confirmation report/manifest state")
        report, _, _ = load_confirmatory_evaluation_report(output_dir)
        return report

    freeze = load_confirmatory_freeze(output_dir)
    if progress is not None:
        progress("confirmation freeze verified; opening one-use reveal")
    index = prepare_confirmatory_inputs(
        panel_dir,
        baseline_dir,
        output_dir,
        progress=progress,
    )
    ledger = ConfirmationRevealLedger.model_validate_json(
        (output_dir / REVEAL_LEDGER_FILENAME).read_text(encoding="utf-8")
    )
    if progress is not None:
        progress("60 task bundles and 120 baseline replays verified")
    controller = run_independent_confirmation_controller(
        output_dir,
        timeout_seconds=controller_timeout_seconds,
    )
    if progress is not None:
        progress("primary 1,620-row matrix and 180 null controls completed")
    analysis, _, _ = analyze_confirmatory_evaluation(
        output_dir,
        controller=controller,
    )
    replay = run_clean_room_confirmation_replay(
        output_dir,
        controller,
        timeout_seconds=controller_timeout_seconds,
    )
    if progress is not None:
        progress("full clean-room scientific projection replay verified")

    endpoint_checks = dict(analysis.endpoint_checks_before_clean_replay)
    endpoint_checks["full-clean-room-scientific-projection-exact"] = (
        replay.scientific_projection_exact
    )
    if set(endpoint_checks) != set(freeze.statistical_policy.positive_endpoint_checks):
        raise PortfolioIntegrityError(
            "confirmation endpoint set differs from the prospective policy"
        )
    validity_checks = _confirmation_validity_checks(
        freeze,
        ledger,
        index,
        controller,
        analysis,
        replay,
    )
    status = confirmation_status(endpoint_checks, validity_checks)
    report = ConfirmatoryEvaluationReport.create(
        freeze_hash=freeze.freeze_hash,
        reveal_hash=ledger.reveal_hash,
        execution_index_hash=index.execution_index_hash,
        controller_result_hash=controller["result_hash"],
        controller_scientific_projection_hash=controller["scientific_projection_hash"],
        analysis=analysis,
        clean_room_replay=replay,
        endpoint_checks=endpoint_checks,
        validity_checks=validity_checks,
        status=status,
        credible_negative_endpoint=(status is ConfirmationStatus.CREDIBLE_NEGATIVE_CONFIRMATION),
        completed_at=completed_at or datetime.now(timezone.utc),
    )
    _write_text_atomic(report_path, report.canonical_json() + "\n")
    _write_text_atomic(
        output_dir / CONFIRMATION_MARKDOWN_FILENAME,
        render_confirmatory_markdown(report),
    )
    _write_text_atomic(
        output_dir / CONFIRMATION_SCHEMA_FILENAME,
        json.dumps(
            confirmatory_json_schemas(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
    )
    manifest = _write_confirmatory_manifest(
        output_dir,
        freeze,
        ledger,
        report,
    )
    _verify_confirmatory_manifest_files(output_dir, manifest)
    return report


def load_confirmatory_evaluation_report(
    output_dir: Path,
) -> tuple[
    ConfirmatoryEvaluationReport,
    ConfirmatoryEvaluationFreeze,
    ConfirmatoryArtifactManifest,
]:
    """Recursively verify a complete Task 263.6 endpoint and all raw evidence."""

    output_dir = output_dir.resolve()
    freeze = load_confirmatory_freeze(output_dir)
    ledger = ConfirmationRevealLedger.model_validate_json(
        (output_dir / REVEAL_LEDGER_FILENAME).read_text(encoding="utf-8")
    )
    index = load_confirmatory_execution_index(output_dir)
    report = ConfirmatoryEvaluationReport.model_validate_json(
        (output_dir / CONFIRMATION_REPORT_FILENAME).read_text(encoding="utf-8")
    )
    manifest = ConfirmatoryArtifactManifest.model_validate_json(
        (output_dir / CONFIRMATION_MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    report.verify_integrity()
    manifest.verify_integrity()
    report.clean_room_replay.verify_integrity()
    if (
        ledger.freeze_hash != freeze.freeze_hash
        or index.freeze_hash != freeze.freeze_hash
        or report.freeze_hash != freeze.freeze_hash
        or manifest.freeze_hash != freeze.freeze_hash
        or report.reveal_hash != ledger.reveal_hash
        or manifest.reveal_hash != ledger.reveal_hash
        or manifest.report_hash != report.report_hash
    ):
        raise PortfolioIntegrityError("confirmation top-level binding mismatch")
    if set(report.endpoint_checks) != set(freeze.statistical_policy.positive_endpoint_checks):
        raise PortfolioIntegrityError("confirmation report endpoint set changed")
    _verify_confirmatory_manifest_files(output_dir, manifest)
    controller = _load_hashed_json(
        output_dir / CONTROLLER_RESULT_RELATIVE,
        "result_hash",
    )
    _verify_controller_result(controller, freeze, index)
    analysis, _, _ = analyze_confirmatory_evaluation(
        output_dir,
        controller=controller,
    )
    if (
        controller["result_hash"] != report.controller_result_hash
        or controller["scientific_projection_hash"] != report.controller_scientific_projection_hash
        or analysis.analysis_hash != report.analysis.analysis_hash
    ):
        raise PortfolioIntegrityError(
            "confirmation report differs from independent raw reconstruction"
        )
    replay_controller = _load_hashed_json(
        output_dir / "clean-room-replay/replay-execution/controller-result.json",
        "result_hash",
    )
    if (
        replay_controller["result_hash"] != report.clean_room_replay.replay_controller_result_hash
        or replay_controller["scientific_projection_hash"]
        != report.controller_scientific_projection_hash
    ):
        raise PortfolioIntegrityError("confirmation clean-room controller binding mismatch")
    return report, freeze, manifest


def _cli() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("freeze", "run", "verify"))
    parser.add_argument(
        "--panel-dir",
        type=Path,
        default=Path("runs/manual-live/task26341-open-objective-panel-v1"),
    )
    parser.add_argument(
        "--baseline-dir",
        type=Path,
        default=Path("runs/manual-live/task26342-clean-baseline-preregistration-v2"),
    )
    parser.add_argument(
        "--development-dir",
        type=Path,
        default=Path("runs/manual-live/task2635-development-search-v2"),
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--controller-timeout-seconds",
        type=int,
        default=172_800,
    )
    args = parser.parse_args()
    if args.action == "freeze":
        freeze = freeze_confirmatory_evaluation(
            args.panel_dir,
            args.baseline_dir,
            args.development_dir,
            args.output_dir,
        )
        print(
            json.dumps(
                {
                    "status": "frozen_result_blind",
                    "freeze_hash": freeze.freeze_hash,
                    "assignments": len(freeze.assignments),
                    "null_controls": 180,
                    "confirmatory_payloads_downloaded": False,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return 0
    if args.action == "run":
        report = run_confirmatory_evaluation(
            args.panel_dir,
            args.baseline_dir,
            args.output_dir,
            controller_timeout_seconds=args.controller_timeout_seconds,
            progress=lambda message: print(message, flush=True),
        )
        print(
            json.dumps(
                {
                    "status": report.status.value,
                    "report_hash": report.report_hash,
                    "primary_risk_difference": (
                        report.analysis.primary_comparison.risk_difference_a_minus_b
                    ),
                    "primary_exact_p": (report.analysis.primary_comparison.exact_mcnemar_p),
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return 0
    report, freeze, manifest = load_confirmatory_evaluation_report(args.output_dir)
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
