"""Fail-closed feasibility and preregistration contracts for Task 263.4.

The opportunity tournament selects a research track; it does not establish
that the selected benchmark can support a publishable causal study. This
module audits every proposed independent task, uses an exact prospective test
for paired binary outcomes, and refuses to preregister the experiment until a
clean-room baseline is reproduced.

No score can compensate for a missing evaluator, inaccessible data, unclear
license, model-judged output, an underpowered panel, or a failed baseline.
Seeds are within-task repeats and never independent scientific units.
"""

from __future__ import annotations

import hashlib
import json
import math
from enum import Enum
from functools import lru_cache
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

from .portfolio import PortfolioIntegrityError


def _jsonable(value: Any) -> Any:
    """Return the stable JSON representation used for content addressing."""

    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value


class TaskOutputKind(str, Enum):
    """Evaluator-facing output classes used by the objective-evidence gate."""

    STRUCTURED = "structured"
    IMAGE = "image"
    UNKNOWN = "unknown"


class StudyFeasibilityStatus(str, Enum):
    """Scientific state of the selected search-policy study."""

    BLOCKED_REPRODUCTION_DIAGNOSIS = "blocked_reproduction_diagnosis"
    READY_FOR_BASELINE = "ready_for_baseline"
    BASELINE_REPRODUCED = "baseline_reproduced"


class StudyArm(str, Enum):
    """Frozen budget-matched policy arms."""

    ONE_SHOT = "one_shot"
    LINEAR_SELF_LOOP = "linear_self_loop"
    PORTFOLIO = "portfolio"
    PORTFOLIO_MEMORY = "portfolio_memory"


class StudyAblation(str, Enum):
    """Frozen causal ablations required by the research question."""

    CERTIFICATE = "certificate"
    DIVERSITY = "diversity"
    MULTI_FIDELITY = "multi_fidelity"
    REVIEWER = "reviewer"
    MEMORY = "memory"


class BenchmarkTaskAudit(KernelContract):
    """Metadata-only audit of one proposed independent benchmark task."""

    schema_version: Literal["benchmark-task-audit-v1"] = "benchmark-task-audit-v1"
    benchmark_id: StableId
    task_id: StableId
    domain: NonEmptyText
    metadata_source_url: NonEmptyText
    output_path: NonEmptyText
    evaluator_name: NonEmptyText
    output_kind: TaskOutputKind
    license_id: NonEmptyText
    license_clear: bool
    data_bundle_available: bool
    evaluator_source_available: bool
    deterministic_evaluator: bool
    model_judge_required: bool
    metadata_only: bool
    gold_result_observed: Literal[False] = False
    evaluation_result_observed: Literal[False] = False
    eligible_for_causal_panel: bool
    audit_hash: Sha256

    @model_validator(mode="after")
    def _validate_audit(self) -> BenchmarkTaskAudit:
        expected_eligible = (
            self.output_kind is TaskOutputKind.STRUCTURED
            and self.license_clear
            and self.data_bundle_available
            and self.evaluator_source_available
            and self.deterministic_evaluator
            and not self.model_judge_required
            and not self.metadata_only
        )
        if self.eligible_for_causal_panel != expected_eligible:
            raise ValueError(
                "task eligibility must equal the conjunctive objective-evidence gate"
            )
        if self.output_kind is TaskOutputKind.IMAGE and not self.model_judge_required:
            raise ValueError(
                "image outputs must remain blocked until an objective evaluator "
                "is independently audited"
            )
        if self.deterministic_evaluator and not self.evaluator_source_available:
            raise ValueError(
                "an unavailable evaluator cannot be asserted deterministic"
            )
        if self.audit_hash != self.calculated_hash():
            raise PortfolioIntegrityError("benchmark task audit_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> BenchmarkTaskAudit:
        """Derive task eligibility and attach a canonical digest."""

        payload = dict(values)
        payload.update(
            {
                "schema_version": "benchmark-task-audit-v1",
                "gold_result_observed": False,
                "evaluation_result_observed": False,
            }
        )
        output_kind = TaskOutputKind(payload["output_kind"])
        payload["eligible_for_causal_panel"] = (
            output_kind is TaskOutputKind.STRUCTURED
            and bool(payload["license_clear"])
            and bool(payload["data_bundle_available"])
            and bool(payload["evaluator_source_available"])
            and bool(payload["deterministic_evaluator"])
            and not bool(payload["model_judge_required"])
            and not bool(payload["metadata_only"])
        )
        payload["audit_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the task-audit digest."""

        return canonical_sha256(self.model_dump(mode="json", exclude={"audit_hash"}))

    def verify_integrity(self) -> None:
        """Reject an in-memory task-audit mutation."""

        if self.audit_hash != self.calculated_hash():
            raise PortfolioIntegrityError("benchmark task audit_hash mismatch")


@lru_cache(maxsize=16_384)
def exact_two_sided_sign_test_pvalue(favorable: int, unfavorable: int) -> float:
    """Return the exact conditional two-sided sign-test p-value."""

    if favorable < 0 or unfavorable < 0:
        raise ValueError("discordant counts must be non-negative")
    discordant = favorable + unfavorable
    if discordant == 0:
        return 1.0
    tail_end = min(favorable, unfavorable)
    tail = sum(math.comb(discordant, index) for index in range(tail_end + 1))
    return float(min(1.0, 2.0 * tail / float(2**discordant)))


@lru_cache(maxsize=16_384)
def exact_mcnemar_power(
    *,
    independent_unit_count: int,
    favorable_probability: float,
    unfavorable_probability: float,
    alpha: float,
) -> float:
    """Enumerate prospective power for paired binary task outcomes exactly."""

    if independent_unit_count < 1:
        raise ValueError("independent_unit_count must be positive")
    if not 0 < alpha < 1:
        raise ValueError("alpha must be between zero and one")
    if not all(
        math.isfinite(value)
        for value in (favorable_probability, unfavorable_probability, alpha)
    ):
        raise ValueError("power inputs must be finite")
    if (
        favorable_probability < 0
        or unfavorable_probability < 0
        or favorable_probability + unfavorable_probability > 1
    ):
        raise ValueError("discordance probabilities must be valid")

    concordant_probability = (
        1.0 - favorable_probability - unfavorable_probability
    )
    power = 0.0
    for favorable in range(independent_unit_count + 1):
        remaining = independent_unit_count - favorable
        for unfavorable in range(remaining + 1):
            if (
                exact_two_sided_sign_test_pvalue(favorable, unfavorable)
                > alpha + 1e-15
            ):
                continue
            concordant = remaining - unfavorable
            coefficient = math.comb(
                independent_unit_count, favorable
            ) * math.comb(remaining, unfavorable)
            probability = float(coefficient)
            probability *= favorable_probability**favorable
            probability *= unfavorable_probability**unfavorable
            probability *= concordant_probability**concordant
            power += probability
    return power


def minimum_exact_mcnemar_sample_size(
    *,
    favorable_probability: float,
    unfavorable_probability: float,
    alpha: float,
    target_power: float,
    maximum_units: int = 10_000,
) -> int:
    """Return the smallest independent-task count meeting target exact power."""

    if not 0 < target_power < 1:
        raise ValueError("target_power must be between zero and one")
    if maximum_units < 1:
        raise ValueError("maximum_units must be positive")
    for unit_count in range(1, maximum_units + 1):
        power = exact_mcnemar_power(
            independent_unit_count=unit_count,
            favorable_probability=favorable_probability,
            unfavorable_probability=unfavorable_probability,
            alpha=alpha,
        )
        if power + 1e-12 >= target_power:
            return unit_count
    raise ValueError("target power was not reached within maximum_units")


class ExactPairedPowerScenario(KernelContract):
    """Prospective exact-power sensitivity for one discordance assumption."""

    schema_version: Literal["exact-paired-power-scenario-v1"] = (
        "exact-paired-power-scenario-v1"
    )
    analysis_unit: Literal["independent research task"] = (
        "independent research task"
    )
    test: Literal["two-sided exact McNemar test"] = (
        "two-sided exact McNemar test"
    )
    independent_unit_count: int = Field(ge=1)
    alpha: float = Field(gt=0, lt=1)
    target_power: float = Field(gt=0, lt=1)
    minimum_effect: float = Field(gt=0, lt=1)
    favorable_probability: float = Field(ge=0, le=1)
    unfavorable_probability: float = Field(ge=0, le=1)
    achieved_power: float = Field(ge=0, le=1)
    required_independent_unit_count: int = Field(ge=1)
    scenario_hash: Sha256

    @model_validator(mode="after")
    def _validate_scenario(self) -> ExactPairedPowerScenario:
        if (
            self.favorable_probability + self.unfavorable_probability
            > 1 + 1e-12
        ):
            raise ValueError("discordance probabilities sum above one")
        observed_effect = (
            self.favorable_probability - self.unfavorable_probability
        )
        if not math.isclose(
            observed_effect, self.minimum_effect, abs_tol=1e-12
        ):
            raise ValueError(
                "favorable minus unfavorable probability must equal minimum_effect"
            )
        expected_power = exact_mcnemar_power(
            independent_unit_count=self.independent_unit_count,
            favorable_probability=self.favorable_probability,
            unfavorable_probability=self.unfavorable_probability,
            alpha=self.alpha,
        )
        if not math.isclose(
            self.achieved_power, expected_power, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise ValueError("achieved_power does not match exact enumeration")
        expected_count = minimum_exact_mcnemar_sample_size(
            favorable_probability=self.favorable_probability,
            unfavorable_probability=self.unfavorable_probability,
            alpha=self.alpha,
            target_power=self.target_power,
        )
        if self.required_independent_unit_count != expected_count:
            raise ValueError(
                "required_independent_unit_count does not match exact enumeration"
            )
        if self.scenario_hash != self.calculated_hash():
            raise PortfolioIntegrityError("exact power scenario_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ExactPairedPowerScenario:
        """Compute exact power and minimum task count before results exist."""

        payload = dict(values)
        payload.update(
            {
                "schema_version": "exact-paired-power-scenario-v1",
                "analysis_unit": "independent research task",
                "test": "two-sided exact McNemar test",
            }
        )
        payload["independent_unit_count"] = int(payload["independent_unit_count"])
        for field_name in (
            "alpha",
            "target_power",
            "minimum_effect",
            "favorable_probability",
            "unfavorable_probability",
        ):
            payload[field_name] = float(payload[field_name])
        payload["achieved_power"] = exact_mcnemar_power(
            independent_unit_count=payload["independent_unit_count"],
            favorable_probability=payload["favorable_probability"],
            unfavorable_probability=payload["unfavorable_probability"],
            alpha=payload["alpha"],
        )
        payload["required_independent_unit_count"] = (
            minimum_exact_mcnemar_sample_size(
                favorable_probability=payload["favorable_probability"],
                unfavorable_probability=payload["unfavorable_probability"],
                alpha=payload["alpha"],
                target_power=payload["target_power"],
            )
        )
        payload["scenario_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the exact-power scenario digest."""

        return canonical_sha256(
            self.model_dump(mode="json", exclude={"scenario_hash"})
        )

    def verify_integrity(self) -> None:
        """Reject an in-memory exact-power mutation."""

        if self.scenario_hash != self.calculated_hash():
            raise PortfolioIntegrityError("exact power scenario_hash mismatch")


class BaselineReproductionAttempt(KernelContract):
    """Full claim-to-prediction binding or pre-execution blocked diagnosis."""

    schema_version: Literal["search-policy-baseline-attempt-v1"] = (
        "search-policy-baseline-attempt-v1"
    )
    baseline_id: StableId
    claim_hash: Sha256
    source_hashes: list[Sha256] = Field(min_length=1)
    code_hash: Sha256 | None = None
    data_hash: Sha256 | None = None
    environment_hash: Sha256 | None = None
    command: list[NonEmptyText] = Field(default_factory=list)
    command_hash: Sha256 | None = None
    seeds: list[int] = Field(default_factory=list)
    raw_prediction_hash: Sha256 | None = None
    metric_id: StableId
    expected_value: float | None = None
    observed_value: float | None = None
    tolerance: float = Field(ge=0)
    attempted: bool
    within_tolerance: bool
    reproduced: bool
    clean_environment: bool
    independent_runner: bool
    blockers: list[NonEmptyText] = Field(default_factory=list)
    attempt_hash: Sha256

    @field_validator("source_hashes", "blockers")
    @classmethod
    def _sort_unique_strings(cls, value: list[str]) -> list[str]:
        normalized = sorted(value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("baseline attempt lists must contain unique values")
        return normalized

    @field_validator("seeds")
    @classmethod
    def _sort_unique_seeds(cls, value: list[int]) -> list[int]:
        normalized = sorted(value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("baseline seeds must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_attempt(self) -> BaselineReproductionAttempt:
        bound_fields = (
            self.code_hash,
            self.data_hash,
            self.environment_hash,
            self.command_hash,
            self.raw_prediction_hash,
            self.expected_value,
            self.observed_value,
        )
        if self.attempted:
            if any(value is None for value in bound_fields):
                raise ValueError(
                    "an attempted reproduction requires code, data, environment, "
                    "command, prediction, expected, and observed bindings"
                )
            assert self.observed_value is not None
            assert self.expected_value is not None
            if not math.isfinite(self.observed_value) or not math.isfinite(
                self.expected_value
            ):
                raise ValueError("baseline metric values must be finite")
            if not self.command or not self.seeds:
                raise ValueError(
                    "an attempted reproduction requires a command and frozen seeds"
                )
            if self.command_hash != canonical_sha256(self.command):
                raise PortfolioIntegrityError(
                    "baseline reproduction command_hash mismatch"
                )
            expected_within = (
                abs(self.observed_value - self.expected_value)
                <= self.tolerance + 1e-12
            )
            if self.within_tolerance != expected_within:
                raise ValueError(
                    "within_tolerance does not match expected/observed evidence"
                )
            if not self.clean_environment or not self.independent_runner:
                raise ValueError(
                    "an attempted publication baseline requires clean independent replay"
                )
        else:
            if any(value is not None for value in bound_fields):
                raise ValueError(
                    "a pre-execution diagnosis cannot contain unobserved bindings"
                )
            if self.command or self.seeds:
                raise ValueError(
                    "a pre-execution diagnosis cannot claim a command or seeds"
                )
            if self.within_tolerance or self.clean_environment or self.independent_runner:
                raise ValueError(
                    "a pre-execution diagnosis cannot claim execution properties"
                )
            if not self.blockers:
                raise ValueError("a blocked pre-execution diagnosis requires blockers")
        expected_reproduced = (
            self.attempted
            and self.within_tolerance
            and self.clean_environment
            and self.independent_runner
            and not self.blockers
        )
        if self.reproduced != expected_reproduced:
            raise ValueError("reproduced does not match bound execution evidence")
        if self.attempt_hash != self.calculated_hash():
            raise PortfolioIntegrityError("baseline attempt_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> BaselineReproductionAttempt:
        """Normalize evidence and attach a canonical digest."""

        payload = dict(values)
        payload["schema_version"] = "search-policy-baseline-attempt-v1"
        payload["source_hashes"] = sorted(payload["source_hashes"])
        payload["blockers"] = sorted(payload.get("blockers", []))
        payload["seeds"] = sorted(payload.get("seeds", []))
        if payload.get("command"):
            payload["command_hash"] = canonical_sha256(payload["command"])
        else:
            payload["command_hash"] = None
        attempted = bool(payload["attempted"])
        payload["tolerance"] = float(payload["tolerance"])
        if attempted:
            payload["expected_value"] = float(payload["expected_value"])
            payload["observed_value"] = float(payload["observed_value"])
            payload["within_tolerance"] = (
                abs(float(payload["observed_value"]) - float(payload["expected_value"]))
                <= float(payload["tolerance"]) + 1e-12
            )
        else:
            for field_name in (
                "code_hash",
                "data_hash",
                "environment_hash",
                "command_hash",
                "raw_prediction_hash",
                "expected_value",
                "observed_value",
            ):
                payload.setdefault(field_name, None)
            payload.setdefault("command", [])
            payload.setdefault("seeds", [])
            payload.setdefault("within_tolerance", False)
            payload.setdefault("clean_environment", False)
            payload.setdefault("independent_runner", False)
        payload["reproduced"] = (
            attempted
            and bool(payload["within_tolerance"])
            and bool(payload["clean_environment"])
            and bool(payload["independent_runner"])
            and not payload["blockers"]
        )
        payload["attempt_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the baseline-attempt digest."""

        return canonical_sha256(
            self.model_dump(mode="json", exclude={"attempt_hash"})
        )

    def verify_integrity(self) -> None:
        """Reject an in-memory baseline-attempt mutation."""

        if self.attempt_hash != self.calculated_hash():
            raise PortfolioIntegrityError("baseline attempt_hash mismatch")


def _derived_feasibility_blockers(
    *,
    tasks: list[BenchmarkTaskAudit],
    confirmatory_task_ids: list[str],
    required_confirmatory_task_count: int,
    reproduction: BaselineReproductionAttempt,
) -> list[str]:
    """Derive non-compensatory blocker codes from underlying evidence."""

    blockers: set[str] = set()
    if any(task.output_kind is not TaskOutputKind.STRUCTURED for task in tasks):
        blockers.add("objective-structured-output-gate-failed")
    if any(task.model_judge_required for task in tasks):
        blockers.add("model-judge-independence-gate-failed")
    if any(not task.license_clear for task in tasks):
        blockers.add("license-gate-failed")
    if any(not task.data_bundle_available for task in tasks):
        blockers.add("benchmark-data-bundle-unavailable")
    if any(not task.evaluator_source_available for task in tasks):
        blockers.add("benchmark-evaluator-source-unavailable")
    if any(not task.deterministic_evaluator for task in tasks):
        blockers.add("deterministic-evaluator-gate-failed")
    if any(task.metadata_only for task in tasks):
        blockers.add("task-artifacts-unverified")
    if len(confirmatory_task_ids) < required_confirmatory_task_count:
        blockers.add("confirmatory-panel-underpowered")
    if reproduction.attempted and not reproduction.reproduced:
        blockers.add("baseline-reproduction-failed")
    return sorted(blockers)


class SearchPolicyFeasibilityReport(KernelContract):
    """Conjunctive preflight for baseline reproduction and causal study entry."""

    schema_version: Literal["search-policy-feasibility-report-v1"] = (
        "search-policy-feasibility-report-v1"
    )
    report_id: StableId
    tournament_report_hash: Sha256
    selected_track_id: Literal["track.search-policy-causality"] = (
        "track.search-policy-causality"
    )
    benchmark_id: StableId
    benchmark_version: NonEmptyText
    metadata_snapshot_hash: Sha256
    task_audits: list[BenchmarkTaskAudit] = Field(min_length=1)
    development_task_ids: list[StableId] = Field(min_length=1)
    confirmatory_task_ids: list[StableId] = Field(min_length=1)
    power_scenarios: list[ExactPairedPowerScenario] = Field(min_length=3)
    required_confirmatory_task_count: int = Field(ge=1)
    reproduction: BaselineReproductionAttempt
    blockers: list[NonEmptyText] = Field(default_factory=list)
    baseline_reproduction_ready: bool
    status: StudyFeasibilityStatus
    novelty_search_started: Literal[False] = False
    confirmatory_results_revealed: Literal[False] = False
    public_release_authorized: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    report_hash: Sha256

    @field_validator(
        "development_task_ids",
        "confirmatory_task_ids",
        "blockers",
    )
    @classmethod
    def _sort_unique_values(cls, value: list[str]) -> list[str]:
        normalized = sorted(value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("feasibility report lists must contain unique values")
        return normalized

    @field_validator("task_audits")
    @classmethod
    def _sort_unique_tasks(
        cls, value: list[BenchmarkTaskAudit]
    ) -> list[BenchmarkTaskAudit]:
        normalized = sorted(value, key=lambda item: item.task_id)
        ids = [item.task_id for item in normalized]
        if len(ids) != len(set(ids)):
            raise ValueError("benchmark task audits must be unique")
        return normalized

    @field_validator("power_scenarios")
    @classmethod
    def _sort_unique_scenarios(
        cls, value: list[ExactPairedPowerScenario]
    ) -> list[ExactPairedPowerScenario]:
        normalized = sorted(
            value,
            key=lambda item: (
                item.unfavorable_probability,
                item.favorable_probability,
            ),
        )
        keys = [
            (item.unfavorable_probability, item.favorable_probability)
            for item in normalized
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("exact-power sensitivity scenarios must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_report(self) -> SearchPolicyFeasibilityReport:
        for task in self.task_audits:
            task.verify_integrity()
            if task.benchmark_id != self.benchmark_id:
                raise ValueError("task audit benchmark_id mismatch")
        for scenario in self.power_scenarios:
            scenario.verify_integrity()
            if scenario.independent_unit_count != len(self.confirmatory_task_ids):
                raise ValueError(
                    "power scenario count must equal confirmatory independent tasks"
                )
        frozen_designs = {
            (
                scenario.alpha,
                scenario.target_power,
                scenario.minimum_effect,
            )
            for scenario in self.power_scenarios
        }
        if frozen_designs != {(0.05, 0.80, 0.25)}:
            raise ValueError(
                "power scenarios must share the frozen alpha, target, and SESOI"
            )
        if [
            scenario.unfavorable_probability
            for scenario in self.power_scenarios
        ] != [0.0, 0.05, 0.10]:
            raise ValueError(
                "power scenarios must equal the frozen discordance sensitivity set"
            )
        self.reproduction.verify_integrity()

        development = set(self.development_task_ids)
        confirmatory = set(self.confirmatory_task_ids)
        if development & confirmatory:
            raise ValueError("development and confirmatory task panels must be disjoint")
        known = {task.task_id for task in self.task_audits}
        if development | confirmatory != known:
            raise ValueError(
                "task audits must exactly cover development and confirmatory panels"
            )

        required_count = max(
            scenario.required_independent_unit_count
            for scenario in self.power_scenarios
        )
        if self.required_confirmatory_task_count != required_count:
            raise ValueError(
                "required task count must use the most conservative frozen scenario"
            )
        expected_blockers = _derived_feasibility_blockers(
            tasks=self.task_audits,
            confirmatory_task_ids=self.confirmatory_task_ids,
            required_confirmatory_task_count=required_count,
            reproduction=self.reproduction,
        )
        if self.blockers != expected_blockers:
            raise ValueError("feasibility blockers do not match underlying evidence")

        expected_ready = not expected_blockers
        if self.baseline_reproduction_ready != expected_ready:
            raise ValueError(
                "baseline readiness must equal the conjunctive scientific gate"
            )
        expected_status = (
            StudyFeasibilityStatus.BASELINE_REPRODUCED
            if self.reproduction.reproduced and expected_ready
            else (
                StudyFeasibilityStatus.READY_FOR_BASELINE
                if expected_ready
                else StudyFeasibilityStatus.BLOCKED_REPRODUCTION_DIAGNOSIS
            )
        )
        if self.status is not expected_status:
            raise ValueError("feasibility status does not match evidence")
        if self.report_hash != self.calculated_hash():
            raise PortfolioIntegrityError("search-policy report_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> SearchPolicyFeasibilityReport:
        """Derive hard blockers, status, and content hash from audited evidence."""

        payload = dict(values)
        payload.update(
            {
                "schema_version": "search-policy-feasibility-report-v1",
                "selected_track_id": "track.search-policy-causality",
                "novelty_search_started": False,
                "confirmatory_results_revealed": False,
                "public_release_authorized": False,
                "external_submission_authorized": False,
            }
        )
        tasks = [
            task
            if isinstance(task, BenchmarkTaskAudit)
            else BenchmarkTaskAudit.model_validate(task)
            for task in payload["task_audits"]
        ]
        scenarios = [
            scenario
            if isinstance(scenario, ExactPairedPowerScenario)
            else ExactPairedPowerScenario.model_validate(scenario)
            for scenario in payload["power_scenarios"]
        ]
        reproduction = payload["reproduction"]
        if not isinstance(reproduction, BaselineReproductionAttempt):
            reproduction = BaselineReproductionAttempt.model_validate(reproduction)
        tasks = sorted(tasks, key=lambda item: item.task_id)
        scenarios = sorted(
            scenarios,
            key=lambda item: (
                item.unfavorable_probability,
                item.favorable_probability,
            ),
        )
        payload["task_audits"] = [
            task.model_dump(mode="json") for task in tasks
        ]
        payload["development_task_ids"] = sorted(payload["development_task_ids"])
        payload["confirmatory_task_ids"] = sorted(
            payload["confirmatory_task_ids"]
        )
        payload["power_scenarios"] = [
            scenario.model_dump(mode="json") for scenario in scenarios
        ]
        payload["reproduction"] = reproduction.model_dump(mode="json")
        required_count = max(
            scenario.required_independent_unit_count for scenario in scenarios
        )
        blockers = _derived_feasibility_blockers(
            tasks=tasks,
            confirmatory_task_ids=payload["confirmatory_task_ids"],
            required_confirmatory_task_count=required_count,
            reproduction=reproduction,
        )
        ready = not blockers
        payload["required_confirmatory_task_count"] = required_count
        payload["blockers"] = blockers
        payload["baseline_reproduction_ready"] = ready
        payload["status"] = (
            StudyFeasibilityStatus.BASELINE_REPRODUCED
            if reproduction.reproduced and ready
            else (
                StudyFeasibilityStatus.READY_FOR_BASELINE
                if ready
                else StudyFeasibilityStatus.BLOCKED_REPRODUCTION_DIAGNOSIS
            )
        )
        payload["report_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the recursively bound feasibility-report digest."""

        return canonical_sha256(self.model_dump(mode="json", exclude={"report_hash"}))

    def verify_integrity(self) -> None:
        """Reject an in-memory report or nested-contract mutation."""

        for task in self.task_audits:
            task.verify_integrity()
        for scenario in self.power_scenarios:
            scenario.verify_integrity()
        self.reproduction.verify_integrity()
        if self.report_hash != self.calculated_hash():
            raise PortfolioIntegrityError("search-policy report_hash mismatch")


FROZEN_ARMS = [
    StudyArm.ONE_SHOT,
    StudyArm.LINEAR_SELF_LOOP,
    StudyArm.PORTFOLIO,
    StudyArm.PORTFOLIO_MEMORY,
]
FROZEN_ABLATIONS = [
    StudyAblation.CERTIFICATE,
    StudyAblation.DIVERSITY,
    StudyAblation.MULTI_FIDELITY,
    StudyAblation.REVIEWER,
    StudyAblation.MEMORY,
]
FROZEN_STOP_RULES = [
    "stop if evaluator integrity or leakage audit fails",
    "stop if equal-budget execution cannot be maintained",
    "stop after the preregistered task and seed matrix completes",
]


class SearchPolicyPreregistration(KernelContract):
    """Frozen causal design, constructible only after baseline reproduction."""

    schema_version: Literal["search-policy-preregistration-v1"] = (
        "search-policy-preregistration-v1"
    )
    preregistration_id: StableId
    feasibility_report_hash: Sha256
    baseline_attempt_hash: Sha256
    analysis_unit: Literal["independent research task"] = (
        "independent research task"
    )
    within_unit_repeat_role: Literal[
        "seeds are repeated measurements, never independent units"
    ] = "seeds are repeated measurements, never independent units"
    arms: list[StudyArm]
    ablations: list[StudyAblation]
    primary_comparison: list[StudyArm]
    primary_endpoint: Literal[
        "paired difference in objectively confirmed task success"
    ] = "paired difference in objectively confirmed task success"
    primary_test: Literal["two-sided exact McNemar test"] = (
        "two-sided exact McNemar test"
    )
    alpha: float = Field(gt=0, lt=1)
    target_power: float = Field(gt=0, lt=1)
    minimum_effect: float = Field(gt=0, lt=1)
    required_confirmatory_task_count: int = Field(ge=1)
    confirmatory_task_ids: list[StableId] = Field(min_length=1)
    randomization_unit: Literal["independent research task"] = (
        "independent research task"
    )
    randomization_seed: int = Field(ge=0)
    blocking_factors: list[Literal["benchmark", "domain"]]
    within_unit_seeds: list[int] = Field(min_length=1)
    equal_budget_required: Literal[True] = True
    stop_rules: list[NonEmptyText]
    confirmatory_results_sealed: Literal[True] = True
    external_submission_authorized: Literal[False] = False
    public_release_authorized: Literal[False] = False
    preregistration_hash: Sha256

    @model_validator(mode="after")
    def _validate_preregistration(self) -> SearchPolicyPreregistration:
        if self.arms != FROZEN_ARMS:
            raise ValueError("study arms must equal the frozen four-arm design")
        if self.ablations != FROZEN_ABLATIONS:
            raise ValueError("study ablations must equal the frozen five-ablation design")
        if self.primary_comparison != [
            StudyArm.PORTFOLIO_MEMORY,
            StudyArm.LINEAR_SELF_LOOP,
        ]:
            raise ValueError("primary comparison must remain portfolio+memory vs loop")
        if self.blocking_factors != ["benchmark", "domain"]:
            raise ValueError("randomization must block by benchmark and domain")
        if self.stop_rules != FROZEN_STOP_RULES:
            raise ValueError("stop rules must equal the frozen non-adaptive rules")
        if (self.alpha, self.target_power, self.minimum_effect) != (
            0.05,
            0.80,
            0.25,
        ):
            raise ValueError("preregistration must retain the frozen power design")
        if len(self.confirmatory_task_ids) < self.required_confirmatory_task_count:
            raise ValueError(
                "confirmatory panel is smaller than the exact-power requirement"
            )
        if self.confirmatory_task_ids != sorted(self.confirmatory_task_ids):
            raise ValueError("confirmatory task IDs must be sorted")
        if len(self.confirmatory_task_ids) != len(set(self.confirmatory_task_ids)):
            raise ValueError("confirmatory task IDs must be unique")
        if self.within_unit_seeds != sorted(self.within_unit_seeds):
            raise ValueError("within-unit seeds must be sorted")
        if len(self.within_unit_seeds) != len(set(self.within_unit_seeds)):
            raise ValueError("within-unit seeds must be unique")
        if self.preregistration_hash != self.calculated_hash():
            raise PortfolioIntegrityError("search-policy preregistration_hash mismatch")
        return self

    @classmethod
    def create_from_report(
        cls,
        report: SearchPolicyFeasibilityReport,
        *,
        preregistration_id: str,
        randomization_seed: int,
        within_unit_seeds: list[int],
    ) -> SearchPolicyPreregistration:
        """Freeze the study only after clean, independent baseline recovery."""

        report.verify_integrity()
        if report.status is not StudyFeasibilityStatus.BASELINE_REPRODUCED:
            raise ValueError(
                "preregistration requires a reproduced clean-room baseline"
            )
        scenario = max(
            report.power_scenarios,
            key=lambda item: item.required_independent_unit_count,
        )
        payload: dict[str, Any] = {
            "schema_version": "search-policy-preregistration-v1",
            "preregistration_id": preregistration_id,
            "feasibility_report_hash": report.report_hash,
            "baseline_attempt_hash": report.reproduction.attempt_hash,
            "analysis_unit": "independent research task",
            "within_unit_repeat_role": (
                "seeds are repeated measurements, never independent units"
            ),
            "arms": FROZEN_ARMS,
            "ablations": FROZEN_ABLATIONS,
            "primary_comparison": [
                StudyArm.PORTFOLIO_MEMORY,
                StudyArm.LINEAR_SELF_LOOP,
            ],
            "primary_endpoint": (
                "paired difference in objectively confirmed task success"
            ),
            "primary_test": "two-sided exact McNemar test",
            "alpha": scenario.alpha,
            "target_power": scenario.target_power,
            "minimum_effect": scenario.minimum_effect,
            "required_confirmatory_task_count": (
                report.required_confirmatory_task_count
            ),
            "confirmatory_task_ids": sorted(report.confirmatory_task_ids),
            "randomization_unit": "independent research task",
            "randomization_seed": randomization_seed,
            "blocking_factors": ["benchmark", "domain"],
            "within_unit_seeds": sorted(within_unit_seeds),
            "equal_budget_required": True,
            "stop_rules": FROZEN_STOP_RULES,
            "confirmatory_results_sealed": True,
            "external_submission_authorized": False,
            "public_release_authorized": False,
        }
        payload["preregistration_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the preregistration digest."""

        return canonical_sha256(
            self.model_dump(mode="json", exclude={"preregistration_hash"})
        )

    def verify_integrity(self) -> None:
        """Reject an in-memory preregistration mutation."""

        if self.preregistration_hash != self.calculated_hash():
            raise PortfolioIntegrityError(
                "search-policy preregistration_hash mismatch"
            )


class SearchPolicyArtifactManifest(KernelContract):
    """Content inventory for the persisted feasibility diagnosis."""

    schema_version: Literal["search-policy-artifact-manifest-v1"] = (
        "search-policy-artifact-manifest-v1"
    )
    report_hash: Sha256
    files: dict[NonEmptyText, Sha256]
    external_submission_authorized: Literal[False] = False
    manifest_hash: Sha256

    @model_validator(mode="after")
    def _validate_manifest(self) -> SearchPolicyArtifactManifest:
        if list(self.files) != sorted(self.files):
            raise ValueError("artifact files must be sorted")
        if self.manifest_hash != self.calculated_hash():
            raise PortfolioIntegrityError("search-policy manifest_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> SearchPolicyArtifactManifest:
        """Normalize the inventory and attach its digest."""

        payload = dict(values)
        payload.update(
            {
                "schema_version": "search-policy-artifact-manifest-v1",
                "external_submission_authorized": False,
            }
        )
        payload["files"] = dict(sorted(payload["files"].items()))
        payload["manifest_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the artifact-manifest digest."""

        return canonical_sha256(
            self.model_dump(mode="json", exclude={"manifest_hash"})
        )

    def verify_integrity(self) -> None:
        """Reject an in-memory artifact-manifest mutation."""

        if self.manifest_hash != self.calculated_hash():
            raise PortfolioIntegrityError("search-policy manifest_hash mismatch")


def render_search_policy_feasibility_markdown(
    report: SearchPolicyFeasibilityReport,
) -> str:
    """Render a reader-facing diagnosis without making a result claim."""

    report.verify_integrity()
    image_count = sum(
        task.output_kind is TaskOutputKind.IMAGE for task in report.task_audits
    )
    structured_count = sum(
        task.output_kind is TaskOutputKind.STRUCTURED
        for task in report.task_audits
    )
    eligible_count = sum(
        task.eligible_for_causal_panel for task in report.task_audits
    )
    rows = [
        "# Search-policy study feasibility diagnosis",
        "",
        f"- Status: `{report.status.value}`",
        f"- Report hash: `{report.report_hash}`",
        f"- Selected track: `{report.selected_track_id}`",
        f"- Benchmark/version: `{report.benchmark_id}` / "
        f"`{report.benchmark_version}`",
        f"- Development tasks: `{len(report.development_task_ids)}`",
        f"- Confirmatory tasks: `{len(report.confirmatory_task_ids)}`",
        f"- Required confirmatory tasks: "
        f"`{report.required_confirmatory_task_count}`",
        f"- Audited outputs: `{image_count}` image, `{structured_count}` structured",
        f"- Currently eligible tasks: `{eligible_count}`",
        "- Analysis: `two-sided exact McNemar test`",
        "- Independent unit: `research task`; seeds are within-task repeats",
        "- Novelty search started: `false`",
        "- Confirmatory results revealed: `false`",
        "- External submission authorized: `false`",
        "",
        "## Hard blockers",
        "",
    ]
    rows.extend(
        [f"- `{blocker}`" for blocker in report.blockers]
        or ["- None; baseline reproduction may start."]
    )
    rows.extend(
        [
            "",
            "## Prospective exact-power sensitivity",
            "",
            "| p(favorable) | p(unfavorable) | n now | exact power | n for target |",
            "|---:|---:|---:|---:|---:|",
        ]
    )
    for scenario in report.power_scenarios:
        rows.append(
            f"| {scenario.favorable_probability:.2f} | "
            f"{scenario.unfavorable_probability:.2f} | "
            f"{scenario.independent_unit_count} | "
            f"{scenario.achieved_power:.6f} | "
            f"{scenario.required_independent_unit_count} |"
        )
    rows.extend(
        [
            "",
            "## Task audit",
            "",
            "| Task | Split | Domain | Output | Model judge | Data | Evaluator | "
            "Deterministic | Eligible |",
            "|---|---|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    development = set(report.development_task_ids)
    for task in report.task_audits:
        rows.append(
            "| "
            + " | ".join(
                [
                    f"`{task.task_id}`",
                    "development" if task.task_id in development else "confirmatory",
                    task.domain,
                    task.output_kind.value,
                    str(task.model_judge_required).lower(),
                    str(task.data_bundle_available).lower(),
                    str(task.evaluator_source_available).lower(),
                    str(task.deterministic_evaluator).lower(),
                    str(task.eligible_for_causal_panel).lower(),
                ]
            )
            + " |"
        )
    rows.extend(
        [
            "",
            "This artifact is a reproduction diagnosis, not a scientific result. "
            "The blocked panel must not proceed to novelty search or causal claims.",
            "",
        ]
    )
    return "\n".join(rows)


SEARCH_POLICY_CONTRACT_MODELS = (
    BaselineReproductionAttempt,
    BenchmarkTaskAudit,
    ExactPairedPowerScenario,
    SearchPolicyArtifactManifest,
    SearchPolicyFeasibilityReport,
    SearchPolicyPreregistration,
)


def search_policy_study_json_schemas() -> dict[str, dict[str, Any]]:
    """Export deterministic schemas for every public study artifact."""

    return {
        model.__name__: model.model_json_schema()
        for model in SEARCH_POLICY_CONTRACT_MODELS
    }


def write_search_policy_feasibility(
    output_dir: Path,
    report: SearchPolicyFeasibilityReport,
) -> SearchPolicyArtifactManifest:
    """Persist verified JSON, Markdown, schemas, and a digest manifest."""

    report.verify_integrity()
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "search-policy-feasibility.json"
    markdown_path = output_dir / "search-policy-feasibility.md"
    schemas_path = output_dir / "search-policy-schemas.json"
    _write_text_atomic(report_path, report.model_dump_json(indent=2) + "\n")
    _write_text_atomic(
        markdown_path,
        render_search_policy_feasibility_markdown(report),
    )
    _write_text_atomic(
        schemas_path,
        json.dumps(
            search_policy_study_json_schemas(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    manifest = SearchPolicyArtifactManifest.create(
        report_hash=report.report_hash,
        files={
            report_path.name: _file_sha256(report_path),
            markdown_path.name: _file_sha256(markdown_path),
            schemas_path.name: _file_sha256(schemas_path),
        },
    )
    _write_text_atomic(
        output_dir / "artifact-manifest.json",
        manifest.model_dump_json(indent=2) + "\n",
    )
    return manifest


def load_search_policy_feasibility(path: Path) -> SearchPolicyFeasibilityReport:
    """Load and recursively verify a persisted feasibility report."""

    report = SearchPolicyFeasibilityReport.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    report.verify_integrity()
    return report


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65_536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_text_atomic(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
