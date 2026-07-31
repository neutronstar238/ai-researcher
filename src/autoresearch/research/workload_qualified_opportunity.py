"""Result-blind mechanism tournament with a real-workload qualification gate.

Task 263.6.4 restarts opportunity selection after a consumed confirmation panel
invalidated the preceding scientific route.  This module compares three
mechanism families without reading that panel or its outcomes:

* structured world-model / evidence-graph coherence;
* Socratic causal, constraint, counterexample, and falsification critics; and
* external data, laboratory, or environment feedback with explicit human
  responsibility.

The central addition is :class:`WorkloadQualificationCertificate`.  A
dependency-free representative workload is calibrated and then repeated across
two independent interpreter installations and every planned concurrency level.
Algorithmic work units are separated from orchestration deadlines, scientific
projections must replay exactly, runtime telemetry is compared only
tolerantly, retries are forbidden, and the certificate is frozen before any
new scientific question or confirmation panel can exist.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
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

from .opportunity_tournament import LiveResourceProbe, ResourceKind
from .portfolio import (
    NearestWorkDelta,
    PortfolioIntegrityError,
    ResearchSource,
)
from .search_policy_study import ExactPairedPowerScenario

ExactProjectionPolicy = Literal[
    "exact scientific projection; tolerant telemetry; no retry"
]
EXACT_PROJECTION_POLICY: ExactProjectionPolicy = (
    "exact scientific projection; tolerant telemetry; no retry"
)
TrackRankingRule = Literal[
    "admitted tracks only; then more accessible independent units, "
    "lower estimated development cost, and lexical track ID"
]
TRACK_RANKING_RULE: TrackRankingRule = (
    "admitted tracks only; then more accessible independent units, "
    "lower estimated development cost, and lexical track ID"
)


def _jsonable(value: Any) -> Any:
    """Convert nested values to the canonical post-validation JSON shape."""

    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        rendered = value.isoformat()
        return rendered[:-6] + "Z" if rendered.endswith("+00:00") else rendered
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value


class MechanismTrackKind(str, Enum):
    """The three non-interchangeable mechanism families in the tournament."""

    STRUCTURED_WORLD_MODEL = "structured-world-model"
    SOCRATIC_FALSIFICATION = "socratic-falsification"
    EXTERNAL_FEEDBACK = "external-feedback"


class WorkloadPhase(str, Enum):
    """Result-blind phases around the frozen workload specification."""

    CALIBRATION = "calibration"
    QUALIFICATION = "qualification"


class InterpreterRuntime(KernelContract):
    """Content-addressed identity of one independent interpreter installation."""

    role_id: StableId
    executable_locator_hash: Sha256
    executable_sha256: Sha256
    python_version: NonEmptyText
    environment_hash: Sha256

    @model_validator(mode="after")
    def _validate_runtime(self) -> InterpreterRuntime:
        expected = canonical_sha256(
            {
                "executable_locator_hash": self.executable_locator_hash,
                "executable_sha256": self.executable_sha256,
                "python_version": self.python_version,
            }
        )
        if self.environment_hash != expected:
            raise PortfolioIntegrityError("interpreter environment_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> InterpreterRuntime:
        payload = dict(values)
        payload["environment_hash"] = canonical_sha256(
            {
                "executable_locator_hash": payload["executable_locator_hash"],
                "executable_sha256": payload["executable_sha256"],
                "python_version": payload["python_version"],
            }
        )
        return cls.model_validate(payload)


class WorkloadProbeObservation(KernelContract):
    """One subprocess observation with scientific and telemetry planes split."""

    schema_version: Literal["workload-probe-observation-v1"] = (
        "workload-probe-observation-v1"
    )
    batch_id: StableId
    track_id: MechanismTrackKind
    phase: WorkloadPhase
    interpreter_role_id: StableId
    interpreter_environment_hash: Sha256
    input_hash: Sha256
    runner_sha256: Sha256
    command_hash: Sha256
    planned_concurrency: int = Field(ge=1, le=16)
    repeat_index: int = Field(ge=0)
    lane_index: int = Field(ge=0)
    algorithmic_work_units: int = Field(ge=0)
    algorithmic_elapsed_seconds: float = Field(ge=0)
    algorithmic_cpu_seconds: float = Field(ge=0)
    peak_traced_bytes: int = Field(ge=0)
    subprocess_wall_seconds: float = Field(ge=0)
    batch_wall_seconds: float = Field(ge=0)
    orchestration_deadline_seconds: float = Field(gt=0)
    exit_code: int | None
    timed_out: bool
    timeout_origin: Literal["none", "orchestration_deadline"]
    telemetry_complete: bool
    output_valid: bool
    projection_hash: Sha256
    stdout_sha256: Sha256
    stderr_sha256: Sha256
    observed_at: datetime
    observation_hash: Sha256

    @model_validator(mode="after")
    def _validate_observation(self) -> WorkloadProbeObservation:
        if self.lane_index >= self.planned_concurrency:
            raise ValueError("lane_index must be below planned_concurrency")
        if self.timed_out != (self.timeout_origin == "orchestration_deadline"):
            raise ValueError("timeout origin does not match timed_out")
        if self.output_valid and (
            self.exit_code != 0
            or self.timed_out
            or not self.telemetry_complete
            or self.algorithmic_work_units < 1
        ):
            raise ValueError("valid workload output contradicts process evidence")
        if self.timed_out and self.exit_code is not None:
            raise ValueError("a timed-out workload cannot have an exit code")
        if not self.timed_out and self.exit_code is None:
            raise ValueError("a completed workload requires an exit code")
        if self.observation_hash != self.calculated_hash():
            raise PortfolioIntegrityError("workload observation_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> WorkloadProbeObservation:
        payload = dict(values)
        payload["schema_version"] = "workload-probe-observation-v1"
        payload["observation_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"observation_hash"})
        )

    def verify_integrity(self) -> None:
        if self.observation_hash != self.calculated_hash():
            raise PortfolioIntegrityError("workload observation_hash mismatch")


class WorkloadProbeSpec(KernelContract):
    """Specification frozen after calibration and before qualification."""

    schema_version: Literal["workload-probe-spec-v1"] = "workload-probe-spec-v1"
    track_id: MechanismTrackKind
    stratum_id: StableId
    input_seed: int = Field(ge=0)
    input_hash: Sha256
    runner_sha256: Sha256
    interpreter_runtimes: list[InterpreterRuntime] = Field(min_length=2)
    planned_concurrency_levels: list[int] = Field(min_length=2)
    qualification_repeat_count: int = Field(ge=3)
    algorithmic_work_units: int = Field(ge=1)
    algorithmic_cpu_seconds_budget: float = Field(gt=0)
    calibration_observation_hashes: list[Sha256] = Field(min_length=2)
    calibration_max_subprocess_wall_seconds: float = Field(gt=0)
    orchestration_deadline_seconds: float = Field(gt=0)
    minimum_timeout_slack_ratio: float = Field(ge=4)
    retry_count: Literal[0] = 0
    comparison_policy: ExactProjectionPolicy = EXACT_PROJECTION_POLICY
    required_telemetry_fields: list[StableId] = Field(min_length=5)
    frozen_at: datetime
    frozen_before_qualification: Literal[True] = True
    development_only: Literal[True] = True
    confirmatory_panel_accessed: Literal[False] = False
    scientific_outcomes_accessed: Literal[False] = False
    spec_hash: Sha256

    @field_validator("interpreter_runtimes")
    @classmethod
    def _normalize_runtimes(
        cls, value: list[InterpreterRuntime]
    ) -> list[InterpreterRuntime]:
        normalized = sorted(value, key=lambda item: item.role_id)
        if len({item.role_id for item in normalized}) != len(normalized):
            raise ValueError("interpreter role IDs must be unique")
        if len({item.executable_locator_hash for item in normalized}) != len(normalized):
            raise ValueError("interpreter installations must have distinct locators")
        return normalized

    @field_validator(
        "planned_concurrency_levels",
        "calibration_observation_hashes",
        "required_telemetry_fields",
    )
    @classmethod
    def _normalize_unique_lists(cls, value: list[Any]) -> list[Any]:
        normalized = sorted(value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("workload specification lists must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_spec(self) -> WorkloadProbeSpec:
        if self.planned_concurrency_levels[:2] != [1, 2]:
            raise ValueError("planned concurrency must include levels one and two")
        input_payload = {
            "algorithmic_work_units": self.algorithmic_work_units,
            "input_seed": self.input_seed,
            "stratum_id": self.stratum_id,
            "track_id": self.track_id.value,
        }
        if self.input_hash != canonical_sha256(input_payload):
            raise PortfolioIntegrityError("workload input_hash mismatch")
        required_deadline = (
            self.calibration_max_subprocess_wall_seconds
            * self.minimum_timeout_slack_ratio
        )
        if self.orchestration_deadline_seconds + 1e-12 < required_deadline:
            raise ValueError("qualification deadline lacks frozen timeout slack")
        if self.spec_hash != self.calculated_hash():
            raise PortfolioIntegrityError("workload spec_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> WorkloadProbeSpec:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "workload-probe-spec-v1",
                "retry_count": 0,
                "comparison_policy": EXACT_PROJECTION_POLICY,
                "frozen_before_qualification": True,
                "development_only": True,
                "confirmatory_panel_accessed": False,
                "scientific_outcomes_accessed": False,
            }
        )
        payload["interpreter_runtimes"] = sorted(
            payload["interpreter_runtimes"],
            key=lambda item: (
                item.role_id
                if isinstance(item, InterpreterRuntime)
                else item["role_id"]
            ),
        )
        for field_name in (
            "planned_concurrency_levels",
            "calibration_observation_hashes",
            "required_telemetry_fields",
        ):
            payload[field_name] = sorted(payload[field_name])
        payload["input_hash"] = canonical_sha256(
            {
                "algorithmic_work_units": payload["algorithmic_work_units"],
                "input_seed": payload["input_seed"],
                "stratum_id": payload["stratum_id"],
                "track_id": (
                    payload["track_id"].value
                    if isinstance(payload["track_id"], MechanismTrackKind)
                    else payload["track_id"]
                ),
            }
        )
        payload["spec_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"spec_hash"}))

    def verify_integrity(self) -> None:
        if self.spec_hash != self.calculated_hash():
            raise PortfolioIntegrityError("workload spec_hash mismatch")


class WorkloadQualificationCertificate(KernelContract):
    """Noncompensating real-workload gate between calibration and science."""

    schema_version: Literal["workload-qualification-certificate-v1"] = (
        "workload-qualification-certificate-v1"
    )
    specification: WorkloadProbeSpec
    calibration_observations: list[WorkloadProbeObservation] = Field(min_length=2)
    qualification_observations: list[WorkloadProbeObservation] = Field(min_length=6)
    exact_projection_hash: Sha256 | None
    checks: dict[StableId, bool]
    qualified: bool
    blockers: list[StableId]
    research_question_certificate_issued: Literal[False] = False
    confirmatory_panel_created: Literal[False] = False
    scientific_freeze_authorized: Literal[False] = False
    certificate_hash: Sha256

    @model_validator(mode="after")
    def _validate_certificate(self) -> WorkloadQualificationCertificate:
        self.specification.verify_integrity()
        for observation in [
            *self.calibration_observations,
            *self.qualification_observations,
        ]:
            observation.verify_integrity()
        expected = _workload_checks(
            specification=self.specification,
            calibration=self.calibration_observations,
            qualification=self.qualification_observations,
        )
        if self.checks != expected:
            raise ValueError("workload qualification checks were not derived")
        expected_blockers = sorted(
            check_id for check_id, passed in expected.items() if not passed
        )
        if self.blockers != expected_blockers:
            raise ValueError("workload blockers do not match failed checks")
        if self.qualified != all(expected.values()):
            raise ValueError("workload qualification is not conjunctive")
        valid_hashes = {
            item.projection_hash
            for item in [*self.calibration_observations, *self.qualification_observations]
            if item.output_valid
        }
        expected_projection = (
            next(iter(valid_hashes))
            if len(valid_hashes) == 1
            and all(
                item.output_valid
                for item in [
                    *self.calibration_observations,
                    *self.qualification_observations,
                ]
            )
            else None
        )
        if self.exact_projection_hash != expected_projection:
            raise ValueError("exact projection hash does not match observations")
        if self.certificate_hash != self.calculated_hash():
            raise PortfolioIntegrityError(
                "workload qualification certificate_hash mismatch"
            )
        return self

    @classmethod
    def create(
        cls,
        *,
        specification: WorkloadProbeSpec,
        calibration_observations: Sequence[WorkloadProbeObservation],
        qualification_observations: Sequence[WorkloadProbeObservation],
    ) -> WorkloadQualificationCertificate:
        calibration = sorted(
            calibration_observations, key=_observation_sort_key
        )
        qualification = sorted(
            qualification_observations, key=_observation_sort_key
        )
        checks = _workload_checks(
            specification=specification,
            calibration=calibration,
            qualification=qualification,
        )
        all_observations = [*calibration, *qualification]
        valid_hashes = {
            item.projection_hash for item in all_observations if item.output_valid
        }
        exact_projection = (
            next(iter(valid_hashes))
            if len(valid_hashes) == 1
            and all(item.output_valid for item in all_observations)
            else None
        )
        payload: dict[str, Any] = {
            "schema_version": "workload-qualification-certificate-v1",
            "specification": specification,
            "calibration_observations": calibration,
            "qualification_observations": qualification,
            "exact_projection_hash": exact_projection,
            "checks": dict(sorted(checks.items())),
            "qualified": all(checks.values()),
            "blockers": sorted(
                check_id for check_id, passed in checks.items() if not passed
            ),
            "research_question_certificate_issued": False,
            "confirmatory_panel_created": False,
            "scientific_freeze_authorized": False,
        }
        payload["certificate_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"certificate_hash"})
        )

    def verify_integrity(self) -> None:
        self.specification.verify_integrity()
        for observation in [
            *self.calibration_observations,
            *self.qualification_observations,
        ]:
            observation.verify_integrity()
        if self.certificate_hash != self.calculated_hash():
            raise PortfolioIntegrityError(
                "workload qualification certificate_hash mismatch"
            )


def _observation_sort_key(
    observation: WorkloadProbeObservation,
) -> tuple[str, int, int, int, str]:
    return (
        observation.interpreter_role_id,
        observation.planned_concurrency,
        observation.repeat_index,
        observation.lane_index,
        observation.batch_id,
    )


def _matrix_complete(
    *,
    observations: Sequence[WorkloadProbeObservation],
    runtimes: Sequence[InterpreterRuntime],
    concurrency_levels: Sequence[int],
    repeat_count: int,
) -> bool:
    expected = {
        (runtime.role_id, concurrency, repeat_index, lane_index)
        for runtime in runtimes
        for concurrency in concurrency_levels
        for repeat_index in range(repeat_count)
        for lane_index in range(concurrency)
    }
    observed = {
        (
            item.interpreter_role_id,
            item.planned_concurrency,
            item.repeat_index,
            item.lane_index,
        )
        for item in observations
    }
    return observed == expected and len(observations) == len(expected)


def _workload_checks(
    *,
    specification: WorkloadProbeSpec,
    calibration: Sequence[WorkloadProbeObservation],
    qualification: Sequence[WorkloadProbeObservation],
) -> dict[str, bool]:
    observations = [*calibration, *qualification]
    runtime_by_role = {
        runtime.role_id: runtime for runtime in specification.interpreter_runtimes
    }
    all_bound = all(
        item.track_id is specification.track_id
        and item.input_hash == specification.input_hash
        and item.runner_sha256 == specification.runner_sha256
        and item.interpreter_role_id in runtime_by_role
        and item.interpreter_environment_hash
        == runtime_by_role[item.interpreter_role_id].environment_hash
        for item in observations
    )
    all_successful = all(
        item.output_valid
        and not item.timed_out
        and item.timeout_origin == "none"
        and item.exit_code == 0
        for item in observations
    )
    telemetry_complete = all(
        item.telemetry_complete
        and item.algorithmic_elapsed_seconds > 0
        and item.algorithmic_cpu_seconds >= 0
        and item.peak_traced_bytes > 0
        and item.subprocess_wall_seconds > 0
        and item.batch_wall_seconds > 0
        for item in observations
    )
    scientific_hashes = {
        item.projection_hash for item in observations if item.output_valid
    }
    calibration_hashes = sorted(item.observation_hash for item in calibration)
    expected_calibration_hashes = specification.calibration_observation_hashes
    phase_order = all(
        item.phase is WorkloadPhase.CALIBRATION
        and item.observed_at <= specification.frozen_at
        for item in calibration
    ) and all(
        item.phase is WorkloadPhase.QUALIFICATION
        and item.observed_at >= specification.frozen_at
        for item in qualification
    )
    qualification_deadlines = all(
        math.isclose(
            item.orchestration_deadline_seconds,
            specification.orchestration_deadline_seconds,
            rel_tol=0,
            abs_tol=1e-12,
        )
        and item.subprocess_wall_seconds
        <= specification.orchestration_deadline_seconds
        for item in qualification
    )
    return dict(
        sorted(
            {
                "algorithmic_compute_budget_respected": all(
                    item.algorithmic_work_units
                    == specification.algorithmic_work_units
                    and item.algorithmic_cpu_seconds
                    <= specification.algorithmic_cpu_seconds_budget
                    for item in observations
                ),
                "calibration_evidence_bound": (
                    calibration_hashes == expected_calibration_hashes
                ),
                "calibration_matrix_complete": _matrix_complete(
                    observations=calibration,
                    runtimes=specification.interpreter_runtimes,
                    concurrency_levels=specification.planned_concurrency_levels,
                    repeat_count=1,
                ),
                "cross_interpreter_installations_distinct": (
                    len(
                        {
                            item.executable_locator_hash
                            for item in specification.interpreter_runtimes
                        }
                    )
                    == len(specification.interpreter_runtimes)
                ),
                "exact_scientific_projection_replay": (
                    len(scientific_hashes) == 1
                    and len(observations) > 0
                    and all(item.output_valid for item in observations)
                ),
                "frozen_before_qualification": phase_order,
                "no_retry_and_split_comparison_policy": (
                    specification.retry_count == 0
                    and specification.comparison_policy == EXACT_PROJECTION_POLICY
                ),
                "orchestration_deadline_respected": qualification_deadlines,
                "qualification_matrix_complete": _matrix_complete(
                    observations=qualification,
                    runtimes=specification.interpreter_runtimes,
                    concurrency_levels=specification.planned_concurrency_levels,
                    repeat_count=specification.qualification_repeat_count,
                ),
                "runner_input_environment_bound": all_bound,
                "subprocesses_succeeded_without_timeout": all_successful,
                "telemetry_complete": telemetry_complete,
                "timeout_slack_frozen": (
                    specification.orchestration_deadline_seconds
                    + 1e-12
                    >= specification.calibration_max_subprocess_wall_seconds
                    * specification.minimum_timeout_slack_ratio
                ),
            }.items()
        )
    )


class ResultBlindnessAudit(KernelContract):
    """Evidence that consumed scientific outcomes did not enter selection."""

    schema_version: Literal["result-blindness-audit-v1"] = (
        "result-blindness-audit-v1"
    )
    forbidden_lineage_hashes: list[Sha256] = Field(min_length=1)
    accessed_input_hashes: list[Sha256] = Field(min_length=1)
    consumed_confirmatory_panel_reads: Literal[0] = 0
    consumed_outcome_reads: Literal[0] = 0
    confirmation_ids_present: Literal[False] = False
    scientific_result_values_present: Literal[False] = False
    ranking_uses_outcomes: Literal[False] = False
    development_evidence_only: Literal[True] = True
    audit_hash: Sha256

    @field_validator("forbidden_lineage_hashes", "accessed_input_hashes")
    @classmethod
    def _normalize_hashes(cls, value: list[str]) -> list[str]:
        normalized = sorted(value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("result-blindness hashes must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_audit(self) -> ResultBlindnessAudit:
        if self.audit_hash != self.calculated_hash():
            raise PortfolioIntegrityError("result-blindness audit_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ResultBlindnessAudit:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "result-blindness-audit-v1",
                "consumed_confirmatory_panel_reads": 0,
                "consumed_outcome_reads": 0,
                "confirmation_ids_present": False,
                "scientific_result_values_present": False,
                "ranking_uses_outcomes": False,
                "development_evidence_only": True,
            }
        )
        payload["forbidden_lineage_hashes"] = sorted(
            payload["forbidden_lineage_hashes"]
        )
        payload["accessed_input_hashes"] = sorted(payload["accessed_input_hashes"])
        payload["audit_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"audit_hash"}))

    def verify_integrity(self) -> None:
        if self.audit_hash != self.calculated_hash():
            raise PortfolioIntegrityError("result-blindness audit_hash mismatch")


class TrackResourceAudit(KernelContract):
    """Open-resource, evaluator, baseline, license, compute, and duty audit."""

    schema_version: Literal["track-resource-audit-v1"] = (
        "track-resource-audit-v1"
    )
    track_id: MechanismTrackKind
    strong_baseline_id: StableId
    strong_baseline_description: NonEmptyText
    strong_baseline_spec_sha256: Sha256
    strong_baseline_reference_available: bool
    strong_baseline_implementation_verified: Literal[False] = False
    objective_evaluator_id: StableId
    objective_evaluator_description: NonEmptyText
    objective_evaluator_sha256: Sha256
    objective_evaluator_specification_available: bool
    objective_evaluator_implementation_verified: Literal[False] = False
    deterministic_evaluator: Literal[True] = True
    llm_judge_is_gate: Literal[False] = False
    dataset_id: StableId
    dataset_inventory_sha256: Sha256
    data_access_verified: bool
    accessible_independent_unit_count: int = Field(ge=0)
    independence_grouping_basis: NonEmptyText
    scientific_independence_audit_complete: Literal[False] = False
    reference_code_license: NonEmptyText
    dataset_license: NonEmptyText
    reference_code_license_verified: bool
    dataset_license_verified: bool
    clean_room_implementation_required: Literal[True] = True
    estimated_development_cost_usd: float = Field(ge=0)
    estimated_development_walltime_hours: float = Field(gt=0)
    required_compute: NonEmptyText
    available_compute: NonEmptyText
    compute_feasible: bool
    human_responsibility_boundary: NonEmptyText
    excluded_resource_reasons: list[NonEmptyText] = Field(min_length=1)
    repository_probe_ids: list[StableId] = Field(min_length=1)
    dataset_probe_ids: list[StableId] = Field(min_length=1)
    license_probe_ids: list[StableId] = Field(min_length=1)
    audit_hash: Sha256

    @field_validator(
        "excluded_resource_reasons",
        "repository_probe_ids",
        "dataset_probe_ids",
        "license_probe_ids",
    )
    @classmethod
    def _normalize_resource_lists(cls, value: list[str]) -> list[str]:
        normalized = sorted(value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("resource audit lists must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_resource_audit(self) -> TrackResourceAudit:
        if self.audit_hash != self.calculated_hash():
            raise PortfolioIntegrityError("track resource audit_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> TrackResourceAudit:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "track-resource-audit-v1",
                "deterministic_evaluator": True,
                "llm_judge_is_gate": False,
                "strong_baseline_implementation_verified": False,
                "objective_evaluator_implementation_verified": False,
                "scientific_independence_audit_complete": False,
                "clean_room_implementation_required": True,
            }
        )
        for field_name in (
            "excluded_resource_reasons",
            "repository_probe_ids",
            "dataset_probe_ids",
            "license_probe_ids",
        ):
            payload[field_name] = sorted(payload[field_name])
        payload["audit_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"audit_hash"}))

    def verify_integrity(self) -> None:
        if self.audit_hash != self.calculated_hash():
            raise PortfolioIntegrityError("track resource audit_hash mismatch")


class TrackProspectivePowerPlan(KernelContract):
    """Exact paired-power sensitivity on independent source groups."""

    schema_version: Literal["track-prospective-power-plan-v1"] = (
        "track-prospective-power-plan-v1"
    )
    track_id: MechanismTrackKind
    analysis_unit: Literal["independent source group"] = "independent source group"
    endpoint: NonEmptyText
    primary_minimum_effect: float = Field(default=0.2, gt=0, lt=1)
    alpha: float = Field(default=0.05, gt=0, le=0.05)
    target_power: float = Field(default=0.8, ge=0.8, lt=1)
    accessible_independent_unit_count: int = Field(ge=0)
    primary_required_independent_unit_count: int = Field(ge=1)
    scenarios: list[ExactPairedPowerScenario] = Field(min_length=3)
    sensitivity_effects: list[float] = Field(min_length=3)
    seed_or_runtime_repeats_are_independent_units: Literal[False] = False
    prospective: Literal[True] = True
    scientific_outcomes_accessed: Literal[False] = False
    power_target_met: bool
    plan_hash: Sha256

    @field_validator("scenarios")
    @classmethod
    def _normalize_scenarios(
        cls, value: list[ExactPairedPowerScenario]
    ) -> list[ExactPairedPowerScenario]:
        normalized = sorted(value, key=lambda item: item.minimum_effect)
        if len({item.minimum_effect for item in normalized}) != len(normalized):
            raise ValueError("power effects must be unique")
        return normalized

    @field_validator("sensitivity_effects")
    @classmethod
    def _normalize_effects(cls, value: list[float]) -> list[float]:
        normalized = sorted(value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("sensitivity effects must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_power_plan(self) -> TrackProspectivePowerPlan:
        if not math.isclose(self.primary_minimum_effect, 0.2, abs_tol=1e-12):
            raise ValueError("primary minimum effect must remain frozen at .20")
        if not math.isclose(self.alpha, 0.05, abs_tol=1e-12):
            raise ValueError("alpha must remain frozen at .05")
        if not math.isclose(self.target_power, 0.8, abs_tol=1e-12):
            raise ValueError("target power must remain frozen at .80")
        scenario_effects = [item.minimum_effect for item in self.scenarios]
        if any(
            not math.isclose(left, right, abs_tol=1e-12)
            for left, right in zip(
                scenario_effects, self.sensitivity_effects, strict=True
            )
        ) or len(scenario_effects) != len(self.sensitivity_effects):
            raise ValueError("power sensitivity effects do not match scenarios")
        if self.sensitivity_effects != [0.15, 0.2, 0.25]:
            raise ValueError("power sensitivity must freeze effects .15/.20/.25")
        primary = next(
            item
            for item in self.scenarios
            if math.isclose(item.minimum_effect, 0.2, abs_tol=1e-12)
        )
        if self.primary_required_independent_unit_count != (
            primary.required_independent_unit_count
        ):
            raise ValueError("primary required unit count does not match exact power")
        expected_met = (
            self.accessible_independent_unit_count
            >= self.primary_required_independent_unit_count
            and primary.achieved_power + 1e-12 >= self.target_power
        )
        if self.power_target_met != expected_met:
            raise ValueError("power_target_met was not derived prospectively")
        if any(
            item.independent_unit_count
            != max(1, self.accessible_independent_unit_count)
            for item in self.scenarios
        ):
            raise ValueError("power scenarios do not bind accessible unit count")
        if self.plan_hash != self.calculated_hash():
            raise PortfolioIntegrityError("track power plan_hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        track_id: MechanismTrackKind,
        endpoint: str,
        accessible_independent_unit_count: int,
        scenarios: Sequence[ExactPairedPowerScenario],
    ) -> TrackProspectivePowerPlan:
        normalized = sorted(scenarios, key=lambda item: item.minimum_effect)
        primary = next(
            item
            for item in normalized
            if math.isclose(item.minimum_effect, 0.2, abs_tol=1e-12)
        )
        payload: dict[str, Any] = {
            "schema_version": "track-prospective-power-plan-v1",
            "track_id": track_id,
            "analysis_unit": "independent source group",
            "endpoint": endpoint,
            "primary_minimum_effect": 0.2,
            "alpha": 0.05,
            "target_power": 0.8,
            "accessible_independent_unit_count": accessible_independent_unit_count,
            "primary_required_independent_unit_count": (
                primary.required_independent_unit_count
            ),
            "scenarios": normalized,
            "sensitivity_effects": [item.minimum_effect for item in normalized],
            "seed_or_runtime_repeats_are_independent_units": False,
            "prospective": True,
            "scientific_outcomes_accessed": False,
            "power_target_met": (
                accessible_independent_unit_count
                >= primary.required_independent_unit_count
                and primary.achieved_power + 1e-12 >= 0.8
            ),
        }
        payload["plan_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"plan_hash"}))

    def verify_integrity(self) -> None:
        for scenario in self.scenarios:
            scenario.verify_integrity()
        if self.plan_hash != self.calculated_hash():
            raise PortfolioIntegrityError("track power plan_hash mismatch")


class MechanismTrackPlan(KernelContract):
    """One mechanism-grounded, objectively falsifiable development track."""

    schema_version: Literal["mechanism-track-plan-v1"] = "mechanism-track-plan-v1"
    track_id: MechanismTrackKind
    literature_cutoff: date
    main_claim: NonEmptyText
    mechanism: NonEmptyText
    primary_endpoint: NonEmptyText
    smallest_effect_of_interest: float = Field(default=0.2, gt=0, lt=1)
    strong_baseline_comparison: NonEmptyText
    falsification_rule: NonEmptyText
    failure_case_update: NonEmptyText
    required_ablations: list[NonEmptyText] = Field(min_length=2)
    sources: list[ResearchSource] = Field(min_length=3)
    nearest_work: list[NearestWorkDelta] = Field(min_length=3)
    source_probes: list[LiveResourceProbe] = Field(min_length=3)
    resource_probes: list[LiveResourceProbe] = Field(min_length=3)
    resource_audit: TrackResourceAudit
    power_plan: TrackProspectivePowerPlan
    workload_certificate: WorkloadQualificationCertificate
    result_blindness_audit: ResultBlindnessAudit
    result_blind_publication_endpoint: NonEmptyText
    authorized_next_step: Literal[
        "development-only clean-room baseline and evaluator construction"
    ] = "development-only clean-room baseline and evaluator construction"
    plan_hash: Sha256

    @field_validator("required_ablations")
    @classmethod
    def _normalize_ablations(cls, value: list[str]) -> list[str]:
        normalized = sorted(value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("required ablations must be unique")
        return normalized

    @field_validator("sources")
    @classmethod
    def _normalize_sources(cls, value: list[ResearchSource]) -> list[ResearchSource]:
        normalized = sorted(value, key=lambda item: item.source_id)
        if len({item.source_id for item in normalized}) != len(normalized):
            raise ValueError("research sources must be unique")
        return normalized

    @field_validator("nearest_work")
    @classmethod
    def _normalize_nearest_work(
        cls, value: list[NearestWorkDelta]
    ) -> list[NearestWorkDelta]:
        normalized = sorted(value, key=lambda item: item.source_id)
        if len({item.source_id for item in normalized}) != len(normalized):
            raise ValueError("nearest-work rows must be unique")
        return normalized

    @field_validator("source_probes", "resource_probes")
    @classmethod
    def _normalize_probes(
        cls, value: list[LiveResourceProbe]
    ) -> list[LiveResourceProbe]:
        normalized = sorted(value, key=lambda item: item.resource_id)
        if len({item.resource_id for item in normalized}) != len(normalized):
            raise ValueError("live probes must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_plan(self) -> MechanismTrackPlan:
        if not math.isclose(
            self.smallest_effect_of_interest, 0.2, abs_tol=1e-12
        ):
            raise ValueError("track SESOI must remain frozen at .20")
        if self.resource_audit.track_id is not self.track_id:
            raise ValueError("resource audit track mismatch")
        if self.power_plan.track_id is not self.track_id:
            raise ValueError("power plan track mismatch")
        if self.workload_certificate.specification.track_id is not self.track_id:
            raise ValueError("workload certificate track mismatch")
        source_ids = {item.source_id for item in self.sources}
        if {item.source_id for item in self.nearest_work} != source_ids:
            raise ValueError("nearest-work matrix must cover every source exactly")
        probes_by_id = {item.resource_id: item for item in self.source_probes}
        if set(probes_by_id) != source_ids:
            raise ValueError("source probes must cover every research source")
        for source in self.sources:
            probe = probes_by_id[source.source_id]
            probe.verify_integrity()
            if probe.kind is not ResourceKind.LITERATURE:
                raise ValueError("source probes must be literature probes")
            if source.source_url != probe.requested_url:
                raise ValueError("source URL does not bind its live probe")
            if source.source_fingerprint != probe.sample_sha256:
                raise ValueError("source fingerprint does not bind its live probe")
        resource_by_id = {item.resource_id: item for item in self.resource_probes}
        required = {
            *self.resource_audit.repository_probe_ids,
            *self.resource_audit.dataset_probe_ids,
            *self.resource_audit.license_probe_ids,
        }
        if not required.issubset(resource_by_id):
            raise ValueError("resource audit references missing probes")
        if any(
            item.kind is ResourceKind.LITERATURE for item in self.resource_probes
        ):
            raise ValueError("resource probes cannot be literature probes")
        if (
            self.resource_audit.accessible_independent_unit_count
            != self.power_plan.accessible_independent_unit_count
        ):
            raise ValueError("resource and power independent-unit counts differ")
        if self.plan_hash != self.calculated_hash():
            raise PortfolioIntegrityError("mechanism track plan_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> MechanismTrackPlan:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "mechanism-track-plan-v1",
                "smallest_effect_of_interest": 0.2,
                "authorized_next_step": (
                    "development-only clean-room baseline and evaluator construction"
                ),
            }
        )
        payload["required_ablations"] = sorted(payload["required_ablations"])
        payload["sources"] = sorted(
            payload["sources"],
            key=lambda item: (
                item.source_id if isinstance(item, ResearchSource) else item["source_id"]
            ),
        )
        payload["nearest_work"] = sorted(
            payload["nearest_work"],
            key=lambda item: (
                item.source_id
                if isinstance(item, NearestWorkDelta)
                else item["source_id"]
            ),
        )
        for field_name in ("source_probes", "resource_probes"):
            payload[field_name] = sorted(
                payload[field_name],
                key=lambda item: (
                    item.resource_id
                    if isinstance(item, LiveResourceProbe)
                    else item["resource_id"]
                ),
            )
        payload["plan_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"plan_hash"}))

    def verify_integrity(self) -> None:
        self.resource_audit.verify_integrity()
        self.power_plan.verify_integrity()
        self.workload_certificate.verify_integrity()
        self.result_blindness_audit.verify_integrity()
        for probe in [*self.source_probes, *self.resource_probes]:
            probe.verify_integrity()
        if self.plan_hash != self.calculated_hash():
            raise PortfolioIntegrityError("mechanism track plan_hash mismatch")


class WorkloadQualifiedTrackAssessment(KernelContract):
    """A conjunctive, no-score assessment that can reject every track."""

    schema_version: Literal["workload-qualified-track-assessment-v1"] = (
        "workload-qualified-track-assessment-v1"
    )
    track_id: MechanismTrackKind
    checks: dict[StableId, bool]
    admitted: bool
    blockers: list[StableId]
    assessment_hash: Sha256

    @model_validator(mode="after")
    def _validate_assessment(self) -> WorkloadQualifiedTrackAssessment:
        if list(self.checks) != sorted(self.checks):
            raise ValueError("track assessment checks must be sorted")
        expected_blockers = sorted(
            check_id for check_id, passed in self.checks.items() if not passed
        )
        if self.blockers != expected_blockers:
            raise ValueError("track blockers do not match failed checks")
        if self.admitted != all(self.checks.values()):
            raise ValueError("track admission must be conjunctive")
        if self.assessment_hash != self.calculated_hash():
            raise PortfolioIntegrityError("track assessment_hash mismatch")
        return self

    @classmethod
    def create(
        cls, plan: MechanismTrackPlan
    ) -> WorkloadQualifiedTrackAssessment:
        resource = plan.resource_audit
        required_resource_ids = {
            *resource.repository_probe_ids,
            *resource.dataset_probe_ids,
            *resource.license_probe_ids,
        }
        resource_by_id = {item.resource_id: item for item in plan.resource_probes}
        checks = dict(
            sorted(
                {
                    "compute_feasible": resource.compute_feasible,
                    "data_access_verified": resource.data_access_verified,
                    "dataset_license_verified": resource.dataset_license_verified,
                    "independent_unit_power_sufficient": plan.power_plan.power_target_met,
                    "literature_cutoff_respected": all(
                        source.year <= plan.literature_cutoff.year
                        for source in plan.sources
                    ),
                    "live_primary_sources_reachable": all(
                        item.reachable for item in plan.source_probes
                    ),
                    "objective_evaluator_specification_available": (
                        resource.objective_evaluator_specification_available
                        and resource.deterministic_evaluator
                        and not resource.llm_judge_is_gate
                    ),
                    "open_resources_reachable": all(
                        resource_by_id.get(resource_id) is not None
                        and resource_by_id[resource_id].reachable
                        for resource_id in required_resource_ids
                    ),
                    "reference_code_license_verified": (
                        resource.reference_code_license_verified
                    ),
                    "result_blindness_verified": (
                        plan.result_blindness_audit.consumed_confirmatory_panel_reads
                        == 0
                        and plan.result_blindness_audit.consumed_outcome_reads == 0
                        and not plan.result_blindness_audit.ranking_uses_outcomes
                    ),
                    "strong_baseline_reference_available": (
                        resource.strong_baseline_reference_available
                    ),
                    "workload_qualified": plan.workload_certificate.qualified,
                }.items()
            )
        )
        payload: dict[str, Any] = {
            "schema_version": "workload-qualified-track-assessment-v1",
            "track_id": plan.track_id,
            "checks": checks,
            "admitted": all(checks.values()),
            "blockers": sorted(
                check_id for check_id, passed in checks.items() if not passed
            ),
        }
        payload["assessment_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"assessment_hash"})
        )

    def verify_integrity(self) -> None:
        if self.assessment_hash != self.calculated_hash():
            raise PortfolioIntegrityError("track assessment_hash mismatch")


class WorkloadQualifiedOpportunityEntry(KernelContract):
    """A track plan bound to its derived no-score assessment."""

    schema_version: Literal["workload-qualified-opportunity-entry-v1"] = (
        "workload-qualified-opportunity-entry-v1"
    )
    plan: MechanismTrackPlan
    assessment: WorkloadQualifiedTrackAssessment
    entry_hash: Sha256

    @model_validator(mode="after")
    def _validate_entry(self) -> WorkloadQualifiedOpportunityEntry:
        if self.assessment.track_id is not self.plan.track_id:
            raise ValueError("track assessment does not bind its plan")
        expected = WorkloadQualifiedTrackAssessment.create(self.plan)
        if self.assessment != expected:
            raise ValueError("track assessment was not derived from its plan")
        if self.entry_hash != self.calculated_hash():
            raise PortfolioIntegrityError("opportunity entry_hash mismatch")
        return self

    @classmethod
    def create(
        cls, plan: MechanismTrackPlan
    ) -> WorkloadQualifiedOpportunityEntry:
        payload: dict[str, Any] = {
            "schema_version": "workload-qualified-opportunity-entry-v1",
            "plan": plan,
            "assessment": WorkloadQualifiedTrackAssessment.create(plan),
        }
        payload["entry_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"entry_hash"}))

    def verify_integrity(self) -> None:
        self.plan.verify_integrity()
        self.assessment.verify_integrity()
        if self.entry_hash != self.calculated_hash():
            raise PortfolioIntegrityError("opportunity entry_hash mismatch")


class WorkloadQualifiedOpportunityReport(KernelContract):
    """Result-blind tournament report that authorizes development only."""

    schema_version: Literal["workload-qualified-opportunity-report-v1"] = (
        "workload-qualified-opportunity-report-v1"
    )
    tournament_id: StableId
    created_at: datetime
    entries: list[WorkloadQualifiedOpportunityEntry] = Field(min_length=3)
    eligible_track_ids: list[MechanismTrackKind]
    ranked_track_ids: list[MechanismTrackKind]
    selected_track_id: MechanismTrackKind | None
    ranking_rule: TrackRankingRule = TRACK_RANKING_RULE
    weighted_score_used: Literal[False] = False
    hardcoded_winner_used: Literal[False] = False
    all_tracks_may_fail: Literal[True] = True
    research_question_certificate_issued: Literal[False] = False
    confirmatory_panel_created: Literal[False] = False
    novelty_search_started: Literal[False] = False
    public_release_authorized: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    human_publication_review_required: Literal[True] = True
    selected_track_authorization: Literal[
        "development-only clean-room baseline and evaluator construction"
    ] = "development-only clean-room baseline and evaluator construction"
    report_hash: Sha256

    @field_validator("entries")
    @classmethod
    def _normalize_entries(
        cls, value: list[WorkloadQualifiedOpportunityEntry]
    ) -> list[WorkloadQualifiedOpportunityEntry]:
        normalized = sorted(value, key=lambda item: item.plan.track_id.value)
        if len({item.plan.track_id for item in normalized}) != len(normalized):
            raise ValueError("tournament track IDs must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_report(self) -> WorkloadQualifiedOpportunityReport:
        expected_tracks = set(MechanismTrackKind)
        actual_tracks = {item.plan.track_id for item in self.entries}
        if actual_tracks != expected_tracks:
            raise ValueError("tournament must contain exactly the three frozen tracks")
        for entry in self.entries:
            entry.verify_integrity()
        expected_eligible = sorted(
            (
                item.plan.track_id
                for item in self.entries
                if item.assessment.admitted
            ),
            key=lambda item: item.value,
        )
        if self.eligible_track_ids != expected_eligible:
            raise ValueError("eligible track IDs do not match admissions")
        ranked = _rank_workload_qualified_entries(self.entries)
        if self.ranked_track_ids != ranked:
            raise ValueError("ranked tracks do not match the frozen rule")
        expected_selected = ranked[0] if ranked else None
        if self.selected_track_id is not expected_selected:
            raise ValueError("selected track does not match deterministic ranking")
        if self.report_hash != self.calculated_hash():
            raise PortfolioIntegrityError("opportunity report_hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        tournament_id: str,
        created_at: datetime,
        entries: Sequence[WorkloadQualifiedOpportunityEntry],
    ) -> WorkloadQualifiedOpportunityReport:
        normalized = sorted(entries, key=lambda item: item.plan.track_id.value)
        eligible = sorted(
            (
                item.plan.track_id
                for item in normalized
                if item.assessment.admitted
            ),
            key=lambda item: item.value,
        )
        ranked = _rank_workload_qualified_entries(normalized)
        payload: dict[str, Any] = {
            "schema_version": "workload-qualified-opportunity-report-v1",
            "tournament_id": tournament_id,
            "created_at": created_at,
            "entries": normalized,
            "eligible_track_ids": eligible,
            "ranked_track_ids": ranked,
            "selected_track_id": ranked[0] if ranked else None,
            "ranking_rule": TRACK_RANKING_RULE,
            "weighted_score_used": False,
            "hardcoded_winner_used": False,
            "all_tracks_may_fail": True,
            "research_question_certificate_issued": False,
            "confirmatory_panel_created": False,
            "novelty_search_started": False,
            "public_release_authorized": False,
            "external_submission_authorized": False,
            "human_publication_review_required": True,
            "selected_track_authorization": (
                "development-only clean-room baseline and evaluator construction"
            ),
        }
        payload["report_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"report_hash"}))

    def verify_integrity(self) -> None:
        for entry in self.entries:
            entry.verify_integrity()
        if self.report_hash != self.calculated_hash():
            raise PortfolioIntegrityError("opportunity report_hash mismatch")


def _rank_workload_qualified_entries(
    entries: Sequence[WorkloadQualifiedOpportunityEntry],
) -> list[MechanismTrackKind]:
    admitted = [item for item in entries if item.assessment.admitted]
    return [
        item.plan.track_id
        for item in sorted(
            admitted,
            key=lambda item: (
                -item.plan.resource_audit.accessible_independent_unit_count,
                item.plan.resource_audit.estimated_development_cost_usd,
                item.plan.track_id.value,
            ),
        )
    ]


class WorkloadQualifiedArtifactManifest(KernelContract):
    """Content inventory for report, reader view, and contract schemas."""

    schema_version: Literal["workload-qualified-artifact-manifest-v1"] = (
        "workload-qualified-artifact-manifest-v1"
    )
    tournament_id: StableId
    report_hash: Sha256
    files: dict[NonEmptyText, Sha256]
    public_release_authorized: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    manifest_hash: Sha256

    @model_validator(mode="after")
    def _validate_manifest(self) -> WorkloadQualifiedArtifactManifest:
        if list(self.files) != sorted(self.files):
            raise ValueError("artifact manifest files must be sorted")
        if self.manifest_hash != self.calculated_hash():
            raise PortfolioIntegrityError("artifact manifest_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> WorkloadQualifiedArtifactManifest:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "workload-qualified-artifact-manifest-v1",
                "public_release_authorized": False,
                "external_submission_authorized": False,
            }
        )
        payload["files"] = dict(sorted(payload["files"].items()))
        payload["manifest_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"manifest_hash"})
        )


def probe_interpreter_runtime(
    *, role_id: str, executable: Path
) -> InterpreterRuntime:
    """Fingerprint one interpreter without persisting its private local path."""

    resolved = executable.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"interpreter does not exist: {resolved}")
    version_run = subprocess.run(
        [str(resolved), "--version"],
        capture_output=True,
        check=False,
        timeout=30,
    )
    if version_run.returncode != 0:
        raise RuntimeError(f"interpreter version probe failed: {role_id}")
    version = (version_run.stdout or version_run.stderr).decode(
        "utf-8", errors="replace"
    ).strip()
    return InterpreterRuntime.create(
        role_id=role_id,
        executable_locator_hash=canonical_sha256(str(resolved).casefold()),
        executable_sha256=_file_sha256(resolved),
        python_version=version,
    )


def run_workload_qualification(
    *,
    track_id: MechanismTrackKind,
    stratum_id: str,
    runner_path: Path,
    interpreters: Mapping[str, Path],
    input_seed: int = 26_364,
    algorithmic_work_units: int = 20_000,
    algorithmic_cpu_seconds_budget: float = 5.0,
    concurrency_levels: Sequence[int] = (1, 2),
    qualification_repeat_count: int = 3,
    calibration_deadline_seconds: float = 30.0,
    minimum_timeout_slack_ratio: float = 8.0,
    minimum_qualification_deadline_seconds: float = 2.0,
) -> WorkloadQualificationCertificate:
    """Calibrate, freeze, and qualify one representative mechanism workload."""

    if len(interpreters) < 2:
        raise ValueError("workload qualification requires two interpreters")
    if sorted(concurrency_levels)[:2] != [1, 2]:
        raise ValueError("concurrency levels must include one and two")
    if qualification_repeat_count < 3:
        raise ValueError("qualification requires at least three repeats")
    runner = runner_path.resolve()
    runner_sha256 = _file_sha256(runner)
    runtime_paths = {
        role_id: executable.resolve()
        for role_id, executable in sorted(interpreters.items())
    }
    if len(set(runtime_paths.values())) != len(runtime_paths):
        raise ValueError("interpreter paths must be distinct installations")
    runtimes = [
        probe_interpreter_runtime(role_id=role_id, executable=executable)
        for role_id, executable in runtime_paths.items()
    ]
    input_hash = canonical_sha256(
        {
            "algorithmic_work_units": algorithmic_work_units,
            "input_seed": input_seed,
            "stratum_id": stratum_id,
            "track_id": track_id.value,
        }
    )
    calibration: list[WorkloadProbeObservation] = []
    for runtime in runtimes:
        for concurrency in sorted(concurrency_levels):
            calibration.extend(
                _run_probe_batch(
                    track_id=track_id,
                    phase=WorkloadPhase.CALIBRATION,
                    runtime=runtime,
                    executable=runtime_paths[runtime.role_id],
                    runner=runner,
                    runner_sha256=runner_sha256,
                    input_hash=input_hash,
                    input_seed=input_seed,
                    algorithmic_work_units=algorithmic_work_units,
                    concurrency=concurrency,
                    repeat_index=0,
                    deadline_seconds=calibration_deadline_seconds,
                )
            )
    max_wall = max(item.subprocess_wall_seconds for item in calibration)
    qualification_deadline = max(
        minimum_qualification_deadline_seconds,
        math.ceil(max_wall * minimum_timeout_slack_ratio * 1_000) / 1_000,
    )
    frozen_at = datetime.now(timezone.utc)
    specification = WorkloadProbeSpec.create(
        track_id=track_id,
        stratum_id=stratum_id,
        input_seed=input_seed,
        runner_sha256=runner_sha256,
        interpreter_runtimes=runtimes,
        planned_concurrency_levels=list(concurrency_levels),
        qualification_repeat_count=qualification_repeat_count,
        algorithmic_work_units=algorithmic_work_units,
        algorithmic_cpu_seconds_budget=algorithmic_cpu_seconds_budget,
        calibration_observation_hashes=[
            item.observation_hash for item in calibration
        ],
        calibration_max_subprocess_wall_seconds=max_wall,
        orchestration_deadline_seconds=qualification_deadline,
        minimum_timeout_slack_ratio=minimum_timeout_slack_ratio,
        required_telemetry_fields=[
            "algorithmic_cpu_seconds",
            "algorithmic_elapsed_seconds",
            "batch_wall_seconds",
            "peak_traced_bytes",
            "subprocess_wall_seconds",
        ],
        frozen_at=frozen_at,
    )
    qualification: list[WorkloadProbeObservation] = []
    for runtime in runtimes:
        for concurrency in sorted(concurrency_levels):
            for repeat_index in range(qualification_repeat_count):
                qualification.extend(
                    _run_probe_batch(
                        track_id=track_id,
                        phase=WorkloadPhase.QUALIFICATION,
                        runtime=runtime,
                        executable=runtime_paths[runtime.role_id],
                        runner=runner,
                        runner_sha256=runner_sha256,
                        input_hash=input_hash,
                        input_seed=input_seed,
                        algorithmic_work_units=algorithmic_work_units,
                        concurrency=concurrency,
                        repeat_index=repeat_index,
                        deadline_seconds=qualification_deadline,
                    )
                )
    return WorkloadQualificationCertificate.create(
        specification=specification,
        calibration_observations=calibration,
        qualification_observations=qualification,
    )


def _run_probe_batch(
    *,
    track_id: MechanismTrackKind,
    phase: WorkloadPhase,
    runtime: InterpreterRuntime,
    executable: Path,
    runner: Path,
    runner_sha256: str,
    input_hash: str,
    input_seed: int,
    algorithmic_work_units: int,
    concurrency: int,
    repeat_index: int,
    deadline_seconds: float,
) -> list[WorkloadProbeObservation]:
    batch_id = (
        f"{track_id.value}-{phase.value}-{runtime.role_id}-"
        f"c{concurrency}-r{repeat_index}"
    )
    batch_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [
            pool.submit(
                _execute_probe,
                executable=executable,
                runner=runner,
                track_id=track_id,
                input_seed=input_seed,
                algorithmic_work_units=algorithmic_work_units,
                deadline_seconds=deadline_seconds,
            )
            for _ in range(concurrency)
        ]
        raw_results = [future.result() for future in futures]
    batch_wall = time.perf_counter() - batch_started
    observations = []
    for lane_index, raw in enumerate(raw_results):
        observations.append(
            WorkloadProbeObservation.create(
                batch_id=batch_id,
                track_id=track_id,
                phase=phase,
                interpreter_role_id=runtime.role_id,
                interpreter_environment_hash=runtime.environment_hash,
                input_hash=input_hash,
                runner_sha256=runner_sha256,
                planned_concurrency=concurrency,
                repeat_index=repeat_index,
                lane_index=lane_index,
                batch_wall_seconds=batch_wall,
                orchestration_deadline_seconds=deadline_seconds,
                observed_at=datetime.now(timezone.utc),
                **raw,
            )
        )
    return observations


def _execute_probe(
    *,
    executable: Path,
    runner: Path,
    track_id: MechanismTrackKind,
    input_seed: int,
    algorithmic_work_units: int,
    deadline_seconds: float,
) -> dict[str, Any]:
    command = [
        str(executable),
        str(runner),
        "--track-id",
        track_id.value,
        "--work-units",
        str(algorithmic_work_units),
        "--seed",
        str(input_seed),
    ]
    environment = dict(os.environ)
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
        }
    )
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            env=environment,
            timeout=deadline_seconds,
        )
        subprocess_wall = time.perf_counter() - started
        stdout = completed.stdout
        stderr = completed.stderr
        timed_out = False
        exit_code: int | None = completed.returncode
    except subprocess.TimeoutExpired as exc:
        subprocess_wall = time.perf_counter() - started
        stdout = _as_bytes(exc.stdout)
        stderr = _as_bytes(exc.stderr)
        timed_out = True
        exit_code = None
    projection_hash = hashlib.sha256(b"").hexdigest()
    output_valid = False
    telemetry_complete = False
    work_units = 0
    elapsed_seconds = 0.0
    cpu_seconds = 0.0
    peak_bytes = 0
    if not timed_out and exit_code == 0:
        try:
            parsed = json.loads(stdout.decode("utf-8"))
            projection = parsed["projection"]
            telemetry = parsed["telemetry"]
            projection_hash = str(parsed["projection_hash"])
            expected_projection_hash = canonical_sha256(projection)
            work_units = int(parsed["algorithmic_work_units"])
            elapsed_seconds = float(telemetry["algorithmic_elapsed_seconds"])
            cpu_seconds = float(telemetry["algorithmic_cpu_seconds"])
            peak_bytes = int(telemetry["peak_traced_bytes"])
            telemetry_complete = (
                elapsed_seconds > 0 and cpu_seconds >= 0 and peak_bytes > 0
            )
            output_valid = (
                parsed["schema_version"] == "mechanism-workload-output-v1"
                and parsed["track_id"] == track_id.value
                and work_units == algorithmic_work_units
                and projection_hash == expected_projection_hash
                and telemetry_complete
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            output_valid = False
    return {
        "command_hash": canonical_sha256(
            {
                "executable_locator_hash": canonical_sha256(
                    str(executable.resolve()).casefold()
                ),
                "runner_sha256": _file_sha256(runner),
                "track_id": track_id.value,
                "work_units": algorithmic_work_units,
                "seed": input_seed,
            }
        ),
        "algorithmic_work_units": work_units,
        "algorithmic_elapsed_seconds": elapsed_seconds,
        "algorithmic_cpu_seconds": cpu_seconds,
        "peak_traced_bytes": peak_bytes,
        "subprocess_wall_seconds": subprocess_wall,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "timeout_origin": (
            "orchestration_deadline" if timed_out else "none"
        ),
        "telemetry_complete": telemetry_complete,
        "output_valid": output_valid,
        "projection_hash": projection_hash,
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
    }


def _as_bytes(value: bytes | str | None) -> bytes:
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    return value.encode("utf-8", errors="replace")


def render_workload_qualified_opportunity_markdown(
    report: WorkloadQualifiedOpportunityReport,
) -> str:
    """Render the selection boundary and every failed noncompensating gate."""

    report.verify_integrity()
    rows = [
        "# Workload-Qualified AI-Scientist Opportunity Tournament",
        "",
        f"- Tournament: `{report.tournament_id}`",
        f"- Report hash: `{report.report_hash}`",
        f"- Selected development track: `{report.selected_track_id.value if report.selected_track_id else 'none'}`",
        "- Authorization: `development-only clean-room baseline and evaluator construction`",
        "- Research Question Certificate issued: `false`",
        "- Confirmatory panel created: `false`",
        "- Novelty search started: `false`",
        "- External submission authorized: `false`",
        "",
        "| Track | Admit | Workload | Candidate units | Required | Power feasibility | Evaluator specification | License | Compute | Blockers |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    details: list[str] = []
    for entry in report.entries:
        plan = entry.plan
        resource = plan.resource_audit
        power = plan.power_plan
        blockers = ", ".join(entry.assessment.blockers) or "none"
        rows.append(
            "| "
            + " | ".join(
                [
                    f"`{plan.track_id.value}`",
                    str(entry.assessment.admitted).lower(),
                    str(plan.workload_certificate.qualified).lower(),
                    str(power.accessible_independent_unit_count),
                    str(power.primary_required_independent_unit_count),
                    str(power.power_target_met).lower(),
                    str(
                        resource.objective_evaluator_specification_available
                    ).lower(),
                    str(
                        resource.reference_code_license_verified
                        and resource.dataset_license_verified
                    ).lower(),
                    str(resource.compute_feasible).lower(),
                    blockers,
                ]
            )
            + " |"
        )
        details.extend(
            [
                "",
                f"## {plan.track_id.value}",
                "",
                f"- Claim under consideration: {plan.main_claim}",
                f"- Mechanism: {plan.mechanism}",
                f"- Primary endpoint: {plan.primary_endpoint}",
                f"- SESOI: `{plan.smallest_effect_of_interest:.2f}` paired risk difference",
                f"- Strong baseline: `{resource.strong_baseline_id}`",
                "- Strong-baseline implementation verified: `false`",
                "- Objective-evaluator implementation verified: `false`",
                "- Scientific independence audit complete: `false`",
                f"- Provisional grouping basis: {resource.independence_grouping_basis}",
                f"- Workload certificate: `{plan.workload_certificate.certificate_hash}`",
                f"- Exact workload projection: `{plan.workload_certificate.exact_projection_hash or 'none'}`",
                f"- Orchestration deadline: `{plan.workload_certificate.specification.orchestration_deadline_seconds:.3f}s`",
                f"- Algorithmic budget: `{plan.workload_certificate.specification.algorithmic_work_units}` work units and `{plan.workload_certificate.specification.algorithmic_cpu_seconds_budget:.3f}s` CPU",
                f"- Decision: `{'admit to development-only construction' if entry.assessment.admitted else 'reject at track gate'}`",
                f"- Blockers: `{blockers}`",
                f"- Falsification rule: {plan.falsification_rule}",
                f"- Failure-case update: {plan.failure_case_update}",
                "",
                "### Nearest-work delta",
                "",
                "| Source | Shared scope | Claimed delta | Overlap risk | Decisive comparison |",
                "|---|---|---|---|---|",
            ]
        )
        sources = {source.source_id: source for source in plan.sources}
        for delta in plan.nearest_work:
            source = sources[delta.source_id]
            details.append(
                "| "
                + " | ".join(
                    [
                        f"[{source.title}]({source.source_url}) ({source.year})",
                        delta.shared_scope,
                        delta.claimed_delta,
                        delta.overlap_risk,
                        delta.decisive_comparison,
                    ]
                )
                + " |"
            )
    rows.extend(details)
    rows.extend(
        [
            "",
            "No scientific result, confirmation identifier, or consumed-panel outcome "
            "participated in this tournament. A selected track is not a novelty claim "
            "and cannot enter confirmation until new development evidence passes the "
            "baseline, evaluator, workload, power, and human-review gates.",
        ]
    )
    return "\n".join(rows).rstrip() + "\n"


def write_workload_qualified_opportunity(
    output_dir: Path,
    report: WorkloadQualifiedOpportunityReport,
) -> WorkloadQualifiedArtifactManifest:
    """Write verified JSON, Markdown, schemas, and a content inventory."""

    report.verify_integrity()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "workload-qualified-opportunity.json"
    markdown_path = output_dir / "workload-qualified-opportunity.md"
    schemas_path = output_dir / "workload-qualified-opportunity-schemas.json"
    _write_text_atomic(json_path, report.model_dump_json(indent=2) + "\n")
    _write_text_atomic(
        markdown_path,
        render_workload_qualified_opportunity_markdown(report),
    )
    _write_text_atomic(
        schemas_path,
        json.dumps(
            workload_qualified_opportunity_json_schemas(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    manifest = WorkloadQualifiedArtifactManifest.create(
        tournament_id=report.tournament_id,
        report_hash=report.report_hash,
        files={
            json_path.name: _file_sha256(json_path),
            markdown_path.name: _file_sha256(markdown_path),
            schemas_path.name: _file_sha256(schemas_path),
        },
    )
    _write_text_atomic(
        output_dir / "artifact-manifest.json",
        manifest.model_dump_json(indent=2) + "\n",
    )
    return manifest


def load_workload_qualified_opportunity(
    path: Path,
) -> WorkloadQualifiedOpportunityReport:
    """Load and recursively verify one persisted tournament."""

    report = WorkloadQualifiedOpportunityReport.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    report.verify_integrity()
    return report


WORKLOAD_QUALIFIED_CONTRACT_MODELS = (
    InterpreterRuntime,
    MechanismTrackPlan,
    ResultBlindnessAudit,
    TrackProspectivePowerPlan,
    TrackResourceAudit,
    WorkloadProbeObservation,
    WorkloadProbeSpec,
    WorkloadQualificationCertificate,
    WorkloadQualifiedArtifactManifest,
    WorkloadQualifiedOpportunityEntry,
    WorkloadQualifiedOpportunityReport,
    WorkloadQualifiedTrackAssessment,
)


def workload_qualified_opportunity_json_schemas() -> dict[str, dict[str, Any]]:
    """Export deterministic JSON schemas for all public contracts."""

    return {
        model.__name__: model.model_json_schema()
        for model in WORKLOAD_QUALIFIED_CONTRACT_MODELS
    }


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
