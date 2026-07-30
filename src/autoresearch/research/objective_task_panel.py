"""Publication-gated open objective task panel for Task 263.4.1.

This module narrows the causal claim to bounded tabular ML research tasks.  It
binds each independent task to an immutable dataset, official OpenML split,
source-specific license evidence, a deterministic local evaluator, and a CPU
compute envelope.  Confirmatory payloads and results remain unopened.
"""

from __future__ import annotations

import hashlib
import json
import math
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from autoresearch.kernel.contracts import (
    KernelContract,
    NonEmptyText,
    Sha256,
    StableId,
    canonical_sha256,
)

from .objective_task_registry import (
    OPENML_TERMS_URL,
    PANEL_SELECTION_SEED,
    UCI_LICENSE_EVIDENCE_URL,
    FrozenSourceSpec,
    ObjectiveTaskFamily,
    PanelPartition,
    frozen_panel_partitions,
    frozen_selection_exclusions,
    frozen_source_registry_hash,
    frozen_sources,
)
from .portfolio import PortfolioIntegrityError
from .search_policy_study import ExactPairedPowerScenario

Md5 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]

MAX_INSTANCES = 100_000
MAX_FEATURES = 5_000
MAX_ESTIMATED_DENSE_BYTES = 4_000_000_000
MAX_REPRESENTATIVE_DATA_BYTES = 64 * 1024 * 1024
MAX_REPRESENTATIVE_SPLIT_BYTES = 16 * 1024 * 1024
MAX_REPRESENTATIVE_COMPUTE_SECONDS = 120.0
EVALUATOR_SOURCE_PATH = "src/autoresearch/research/objective_evaluators.py"
PANEL_SELECTION_RULE = (
    "metadata-only SHA-256 rank; deduplicate original source groups; exclude "
    "ambiguous/non-open licenses; reserve 4 classification and 3 regression "
    "development tasks; retain 41 classification and 19 regression "
    "confirmatory tasks"
)
PANEL_CLAIM_SCOPE = (
    "causal effect of budget-matched search policies on objectively evaluated "
    "bounded tabular machine-learning research tasks; no claim of general "
    "autonomous scientific discovery"
)


class ObjectiveMetric(str, Enum):
    """Model-free metric implemented by the pinned evaluator source."""

    BALANCED_ACCURACY = "balanced_accuracy"
    R2 = "r2"


class OpenTaskPanelStatus(str, Enum):
    """Pre-result state of the rebuilt task panel."""

    BLOCKED = "blocked"
    READY_FOR_CLEAN_BASELINE = "ready_for_clean_baseline"


def _source_index() -> dict[tuple[ObjectiveTaskFamily, int], FrozenSourceSpec]:
    return {(source.family, source.task_id): source for source in frozen_sources()}


def _unit_id(source: FrozenSourceSpec) -> str:
    return f"{source.benchmark_id}-task-{source.task_id}"


def _data_url(source: FrozenSourceSpec) -> str:
    return f"https://openml.org/data/v1/download/{source.file_id}/" f"{source.name}.arff"


def _task_metadata_url(source: FrozenSourceSpec) -> str:
    return f"https://www.openml.org/api/v1/json/task/{source.task_id}"


def _data_metadata_url(source: FrozenSourceSpec) -> str:
    return f"https://www.openml.org/api/v1/json/data/{source.data_id}"


def _split_url(source: FrozenSourceSpec) -> str:
    return (
        "https://www.openml.org/api_splits/get/"
        f"{source.task_id}/Task_{source.task_id}_splits.arff"
    )


def _metric_for_family(family: ObjectiveTaskFamily) -> ObjectiveMetric:
    if family is ObjectiveTaskFamily.TABULAR_CLASSIFICATION:
        return ObjectiveMetric.BALANCED_ACCURACY
    return ObjectiveMetric.R2


def _task_type_for_family(family: ObjectiveTaskFamily) -> str:
    if family is ObjectiveTaskFamily.TABULAR_CLASSIFICATION:
        return "Supervised Classification"
    return "Supervised Regression"


def _license_evidence_url(source: FrozenSourceSpec) -> str:
    if source.family is ObjectiveTaskFamily.TABULAR_CLASSIFICATION:
        return UCI_LICENSE_EVIDENCE_URL
    return _data_metadata_url(source)


def _evaluator_id(source: FrozenSourceSpec) -> str:
    return f"{_metric_for_family(source.family).value}:{_unit_id(source)}"


class OpenObjectiveTaskUnit(KernelContract):
    """One independently sampled, metadata-frozen task in the panel."""

    schema_version: Literal["open-objective-task-unit-v1"] = "open-objective-task-unit-v1"
    unit_id: StableId
    family: ObjectiveTaskFamily
    benchmark_id: StableId
    suite_id: int = Field(ge=1)
    upstream_task_id: int = Field(ge=1)
    data_id: int = Field(ge=1)
    dataset_name: NonEmptyText
    domain: StableId
    independence_group: StableId
    partition: PanelPartition
    task_type: Literal["Supervised Classification", "Supervised Regression"]
    target_feature: NonEmptyText
    estimation_procedure_id: int = Field(ge=1)
    task_metadata_url: NonEmptyText
    data_metadata_url: NonEmptyText
    data_url: NonEmptyText
    split_url: NonEmptyText
    data_md5: Md5
    upstream_metadata_hash: Sha256
    upstream_declared_license: NonEmptyText
    effective_license_id: StableId
    license_evidence_url: NonEmptyText
    task_terms_url: NonEmptyText
    source_reference_found: bool
    number_instances: int = Field(ge=1)
    number_features: int = Field(ge=1)
    estimated_dense_bytes: int = Field(ge=1)
    evaluator_id: StableId
    evaluator_source_path: NonEmptyText
    evaluator_source_hash: Sha256
    objective_metric: ObjectiveMetric
    higher_is_better: Literal[True] = True
    output_schema_id: Literal["openml-prediction-row-v1"] = "openml-prediction-row-v1"
    structured_output: Literal[True] = True
    deterministic_evaluator: Literal[True] = True
    model_judge_required: Literal[False] = False
    anonymous_data_available: bool
    fixed_split_available: bool
    compute_bounded: bool
    metadata_only_inventory: Literal[True] = True
    success_threshold_frozen: Literal[False] = False
    study_outcome_observed: Literal[False] = False
    existing_public_run_queried: Literal[False] = False
    eligible_for_panel: bool
    unit_hash: Sha256

    @model_validator(mode="after")
    def _validate_unit(self) -> OpenObjectiveTaskUnit:
        source = _source_index().get((self.family, self.upstream_task_id))
        if source is None:
            raise ValueError("task unit is absent from the frozen source registry")
        assignments = frozen_panel_partitions()
        expected_static = {
            "unit_id": _unit_id(source),
            "benchmark_id": source.benchmark_id,
            "suite_id": source.suite_id,
            "data_id": source.data_id,
            "dataset_name": source.name,
            "domain": source.domain,
            "independence_group": source.source_group,
            "partition": assignments[(source.family, source.task_id)],
            "task_type": _task_type_for_family(source.family),
            "task_metadata_url": _task_metadata_url(source),
            "data_metadata_url": _data_metadata_url(source),
            "data_url": _data_url(source),
            "split_url": _split_url(source),
            "data_md5": source.data_md5,
            "upstream_declared_license": source.declared_license,
            "effective_license_id": source.effective_license_id,
            "license_evidence_url": _license_evidence_url(source),
            "task_terms_url": OPENML_TERMS_URL,
            "evaluator_id": _evaluator_id(source),
            "evaluator_source_path": EVALUATOR_SOURCE_PATH,
            "objective_metric": _metric_for_family(source.family),
        }
        for field_name, expected in expected_static.items():
            if getattr(self, field_name) != expected:
                raise ValueError(f"{field_name} does not match frozen source registry")

        expected_dense_bytes = self.number_instances * self.number_features * 8
        if self.estimated_dense_bytes != expected_dense_bytes:
            raise ValueError("estimated_dense_bytes does not match task qualities")
        expected_compute_bounded = (
            self.number_instances <= MAX_INSTANCES
            and self.number_features <= MAX_FEATURES
            and expected_dense_bytes <= MAX_ESTIMATED_DENSE_BYTES
        )
        if self.compute_bounded != expected_compute_bounded:
            raise ValueError("compute_bounded does not match the frozen envelope")

        expected_eligible = (
            self.source_reference_found
            and self.anonymous_data_available
            and self.fixed_split_available
            and self.compute_bounded
            and bool(self.evaluator_source_hash)
            and self.structured_output
            and self.deterministic_evaluator
            and not self.model_judge_required
            and not self.study_outcome_observed
            and not self.existing_public_run_queried
        )
        if self.eligible_for_panel != expected_eligible:
            raise ValueError("task eligibility does not match the conjunctive gate")
        if self.unit_hash != self.calculated_hash():
            raise PortfolioIntegrityError("open task unit_hash mismatch")
        return self

    @classmethod
    def create_from_source(
        cls,
        source: FrozenSourceSpec,
        *,
        target_feature: str,
        estimation_procedure_id: int,
        number_instances: int,
        number_features: int,
        upstream_metadata_hash: str,
        evaluator_source_hash: str,
        source_reference_found: bool,
        anonymous_data_available: bool,
        fixed_split_available: bool,
    ) -> OpenObjectiveTaskUnit:
        """Bind live metadata to a frozen source without observing outcomes."""

        registered = _source_index().get((source.family, source.task_id))
        if registered != source:
            raise ValueError("source does not match the frozen registry")
        partition = frozen_panel_partitions()[(source.family, source.task_id)]
        estimated_dense_bytes = number_instances * number_features * 8
        compute_bounded = (
            number_instances <= MAX_INSTANCES
            and number_features <= MAX_FEATURES
            and estimated_dense_bytes <= MAX_ESTIMATED_DENSE_BYTES
        )
        eligible = (
            source_reference_found
            and anonymous_data_available
            and fixed_split_available
            and compute_bounded
            and bool(evaluator_source_hash)
        )
        payload: dict[str, Any] = {
            "schema_version": "open-objective-task-unit-v1",
            "unit_id": _unit_id(source),
            "family": source.family,
            "benchmark_id": source.benchmark_id,
            "suite_id": source.suite_id,
            "upstream_task_id": source.task_id,
            "data_id": source.data_id,
            "dataset_name": source.name,
            "domain": source.domain,
            "independence_group": source.source_group,
            "partition": partition,
            "task_type": _task_type_for_family(source.family),
            "target_feature": target_feature,
            "estimation_procedure_id": estimation_procedure_id,
            "task_metadata_url": _task_metadata_url(source),
            "data_metadata_url": _data_metadata_url(source),
            "data_url": _data_url(source),
            "split_url": _split_url(source),
            "data_md5": source.data_md5,
            "upstream_metadata_hash": upstream_metadata_hash,
            "upstream_declared_license": source.declared_license,
            "effective_license_id": source.effective_license_id,
            "license_evidence_url": _license_evidence_url(source),
            "task_terms_url": OPENML_TERMS_URL,
            "source_reference_found": source_reference_found,
            "number_instances": number_instances,
            "number_features": number_features,
            "estimated_dense_bytes": estimated_dense_bytes,
            "evaluator_id": _evaluator_id(source),
            "evaluator_source_path": EVALUATOR_SOURCE_PATH,
            "evaluator_source_hash": evaluator_source_hash,
            "objective_metric": _metric_for_family(source.family),
            "higher_is_better": True,
            "output_schema_id": "openml-prediction-row-v1",
            "structured_output": True,
            "deterministic_evaluator": True,
            "model_judge_required": False,
            "anonymous_data_available": anonymous_data_available,
            "fixed_split_available": fixed_split_available,
            "compute_bounded": compute_bounded,
            "metadata_only_inventory": True,
            "success_threshold_frozen": False,
            "study_outcome_observed": False,
            "existing_public_run_queried": False,
            "eligible_for_panel": eligible,
        }
        payload["unit_hash"] = canonical_sha256(payload)
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the task-unit digest."""

        return canonical_sha256(self.model_dump(mode="json", exclude={"unit_hash"}))

    def verify_integrity(self) -> None:
        """Reject nested or in-memory task-unit tampering."""

        if self.unit_hash != self.calculated_hash():
            raise PortfolioIntegrityError("open task unit_hash mismatch")


class ObjectiveFamilyProbe(KernelContract):
    """Bounded live data, split, license, evaluator, and compute smoke."""

    schema_version: Literal["objective-family-probe-v1"] = "objective-family-probe-v1"
    probe_id: StableId
    family: ObjectiveTaskFamily
    representative_unit_id: StableId
    data_sha256: Sha256
    data_bytes: int = Field(ge=1)
    split_sha256: Sha256
    split_bytes: int = Field(ge=1)
    license_evidence_sha256: Sha256
    evaluator_source_hash: Sha256
    evaluator_score: float
    evaluator_replay_score: float
    rows_evaluated: int = Field(ge=2)
    compute_seconds: float = Field(ge=0)
    data_md5_verified: bool
    split_verified: bool
    license_verified: bool
    task_metadata_verified: bool
    evaluator_replay_verified: bool
    compute_within_envelope: bool
    model_judge_used: Literal[False] = False
    passed: bool
    probe_hash: Sha256

    @model_validator(mode="after")
    def _validate_probe(self) -> ObjectiveFamilyProbe:
        if not math.isfinite(self.evaluator_score) or not math.isfinite(
            self.evaluator_replay_score
        ):
            raise ValueError("family-probe evaluator scores must be finite")
        expected_replay = math.isclose(
            self.evaluator_score,
            self.evaluator_replay_score,
            rel_tol=0.0,
            abs_tol=1e-15,
        )
        if self.evaluator_replay_verified != expected_replay:
            raise ValueError("evaluator replay flag does not match repeated score")
        expected_compute = (
            self.data_bytes <= MAX_REPRESENTATIVE_DATA_BYTES
            and self.split_bytes <= MAX_REPRESENTATIVE_SPLIT_BYTES
            and self.compute_seconds <= MAX_REPRESENTATIVE_COMPUTE_SECONDS
        )
        if self.compute_within_envelope != expected_compute:
            raise ValueError("compute smoke does not match the frozen envelope")
        expected_passed = (
            self.data_md5_verified
            and self.split_verified
            and self.license_verified
            and self.task_metadata_verified
            and self.evaluator_replay_verified
            and self.compute_within_envelope
            and not self.model_judge_used
        )
        if self.passed != expected_passed:
            raise ValueError("family probe passed flag does not match evidence")
        if self.probe_hash != self.calculated_hash():
            raise PortfolioIntegrityError("objective family probe_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ObjectiveFamilyProbe:
        """Derive the family gate and attach a canonical digest."""

        payload = dict(values)
        payload.update(
            {
                "schema_version": "objective-family-probe-v1",
                "model_judge_used": False,
            }
        )
        payload["evaluator_score"] = float(payload["evaluator_score"])
        payload["evaluator_replay_score"] = float(payload["evaluator_replay_score"])
        payload["compute_seconds"] = float(payload["compute_seconds"])
        payload["evaluator_replay_verified"] = math.isclose(
            payload["evaluator_score"],
            payload["evaluator_replay_score"],
            rel_tol=0.0,
            abs_tol=1e-15,
        )
        payload["compute_within_envelope"] = (
            int(payload["data_bytes"]) <= MAX_REPRESENTATIVE_DATA_BYTES
            and int(payload["split_bytes"]) <= MAX_REPRESENTATIVE_SPLIT_BYTES
            and payload["compute_seconds"] <= MAX_REPRESENTATIVE_COMPUTE_SECONDS
        )
        payload["passed"] = all(
            bool(payload[field_name])
            for field_name in (
                "data_md5_verified",
                "split_verified",
                "license_verified",
                "task_metadata_verified",
                "evaluator_replay_verified",
                "compute_within_envelope",
            )
        )
        payload["probe_hash"] = canonical_sha256(payload)
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the family-probe digest."""

        return canonical_sha256(self.model_dump(mode="json", exclude={"probe_hash"}))

    def verify_integrity(self) -> None:
        """Reject nested or in-memory family-probe tampering."""

        if self.probe_hash != self.calculated_hash():
            raise PortfolioIntegrityError("objective family probe_hash mismatch")


def panel_power_scenarios(
    independent_unit_count: int = 60,
) -> list[ExactPairedPowerScenario]:
    """Return the frozen exact McNemar sensitivity set."""

    return [
        ExactPairedPowerScenario.create(
            independent_unit_count=independent_unit_count,
            alpha=0.05,
            target_power=0.80,
            minimum_effect=0.25,
            favorable_probability=0.25 + unfavorable_probability,
            unfavorable_probability=unfavorable_probability,
        )
        for unfavorable_probability in (0.0, 0.05, 0.10)
    ]


def _derived_panel_blockers(
    *,
    task_units: list[OpenObjectiveTaskUnit],
    family_probes: list[ObjectiveFamilyProbe],
    required_confirmatory_count: int,
) -> list[str]:
    blockers: set[str] = set()
    if any(not unit.eligible_for_panel for unit in task_units):
        blockers.add("task-conjunctive-gate-failed")
    confirmatory = [unit for unit in task_units if unit.partition is PanelPartition.CONFIRMATORY]
    if len(confirmatory) < required_confirmatory_count:
        blockers.add("confirmatory-panel-underpowered")
    families = {unit.family for unit in confirmatory}
    if families != set(ObjectiveTaskFamily):
        blockers.add("task-family-coverage-failed")
    family_counts = {
        family: sum(unit.family is family for unit in confirmatory)
        for family in ObjectiveTaskFamily
    }
    if any(count < 15 for count in family_counts.values()):
        blockers.add("task-family-balance-floor-failed")
    for family in ObjectiveTaskFamily:
        domains = {unit.domain for unit in confirmatory if unit.family is family}
        if len(domains) < 3:
            blockers.add(f"{family.value}-domain-coverage-failed")
    probes = {probe.family: probe for probe in family_probes}
    if set(probes) != set(ObjectiveTaskFamily):
        blockers.add("family-live-probe-coverage-failed")
    elif any(not probe.passed for probe in probes.values()):
        blockers.add("family-live-probe-failed")
    return sorted(blockers)


class OpenObjectiveTaskPanelReport(KernelContract):
    """Conjunctive, pre-result audit of the rebuilt independent-task panel."""

    schema_version: Literal["open-objective-task-panel-report-v1"] = (
        "open-objective-task-panel-report-v1"
    )
    report_id: StableId
    feasibility_diagnosis_hash: Sha256
    source_registry_hash: Sha256
    selection_seed: Literal["task-263.4.1-open-objective-panel-v1"] = (
        "task-263.4.1-open-objective-panel-v1"
    )
    selection_rule: NonEmptyText
    claim_scope: NonEmptyText
    source_suite_snapshot_hashes: dict[StableId, Sha256]
    selection_exclusions: dict[StableId, NonEmptyText]
    evaluator_code_license_id: Literal["Apache-2.0"] = "Apache-2.0"
    evaluator_code_license_hash: Sha256
    task_units: list[OpenObjectiveTaskUnit] = Field(min_length=1)
    family_probes: list[ObjectiveFamilyProbe] = Field(min_length=1)
    power_scenarios: list[ExactPairedPowerScenario] = Field(min_length=3)
    development_unit_ids: list[StableId]
    confirmatory_unit_ids: list[StableId]
    family_confirmatory_counts: dict[StableId, int]
    required_confirmatory_task_count: int = Field(ge=1)
    blocking_factors: list[Literal["benchmark", "domain"]]
    within_unit_repeat_role: Literal[
        "seeds and trajectories are repeated measurements, never independent units"
    ] = "seeds and trajectories are repeated measurements, never independent units"
    confirmatory_payloads_downloaded: Literal[False] = False
    study_outcomes_observed: Literal[False] = False
    existing_public_runs_queried: Literal[False] = False
    data_redistributed: Literal[False] = False
    blockers: list[NonEmptyText]
    baseline_reproduction_authorized: bool
    status: OpenTaskPanelStatus
    novelty_search_started: Literal[False] = False
    public_release_authorized: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    report_hash: Sha256

    @field_validator(
        "development_unit_ids",
        "confirmatory_unit_ids",
        "blockers",
    )
    @classmethod
    def _sort_unique_strings(cls, value: list[str]) -> list[str]:
        normalized = sorted(value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("panel lists must contain unique values")
        return normalized

    @field_validator("task_units")
    @classmethod
    def _sort_unique_units(
        cls,
        value: list[OpenObjectiveTaskUnit],
    ) -> list[OpenObjectiveTaskUnit]:
        normalized = sorted(value, key=lambda item: item.unit_id)
        ids = [item.unit_id for item in normalized]
        if len(ids) != len(set(ids)):
            raise ValueError("task units must be unique")
        return normalized

    @field_validator("family_probes")
    @classmethod
    def _sort_unique_probes(
        cls,
        value: list[ObjectiveFamilyProbe],
    ) -> list[ObjectiveFamilyProbe]:
        normalized = sorted(value, key=lambda item: item.family.value)
        families = [item.family for item in normalized]
        if len(families) != len(set(families)):
            raise ValueError("family probes must be unique")
        return normalized

    @field_validator("power_scenarios")
    @classmethod
    def _sort_unique_scenarios(
        cls,
        value: list[ExactPairedPowerScenario],
    ) -> list[ExactPairedPowerScenario]:
        normalized = sorted(
            value,
            key=lambda item: (
                item.unfavorable_probability,
                item.favorable_probability,
            ),
        )
        if len(
            {(item.unfavorable_probability, item.favorable_probability) for item in normalized}
        ) != len(normalized):
            raise ValueError("power scenarios must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_report(self) -> OpenObjectiveTaskPanelReport:
        if self.source_registry_hash != frozen_source_registry_hash():
            raise PortfolioIntegrityError("source registry hash mismatch")
        if self.selection_seed != PANEL_SELECTION_SEED:
            raise ValueError("selection seed changed")
        if self.selection_rule != PANEL_SELECTION_RULE:
            raise ValueError("selection rule changed")
        if self.claim_scope != PANEL_CLAIM_SCOPE:
            raise ValueError("claim scope changed")
        if set(self.source_suite_snapshot_hashes) != {
            "openml-cc18",
            "openml-ctr23",
        }:
            raise ValueError("both frozen OpenML suite snapshots are required")
        if self.selection_exclusions != frozen_selection_exclusions():
            raise ValueError("selection exclusions changed")
        if self.blocking_factors != ["benchmark", "domain"]:
            raise ValueError("randomization must block by benchmark and domain")

        for unit in self.task_units:
            unit.verify_integrity()
        expected_source_keys = {(source.family, source.task_id) for source in frozen_sources()}
        actual_source_keys = {(unit.family, unit.upstream_task_id) for unit in self.task_units}
        if actual_source_keys != expected_source_keys:
            raise ValueError("task units do not exactly match the frozen registry")
        if len({unit.data_id for unit in self.task_units}) != len(self.task_units):
            raise ValueError("task panel repeats an OpenML dataset")
        if len({unit.independence_group for unit in self.task_units}) != len(self.task_units):
            raise ValueError("task panel repeats an independence group")

        development = sorted(
            unit.unit_id for unit in self.task_units if unit.partition is PanelPartition.DEVELOPMENT
        )
        confirmatory = sorted(
            unit.unit_id
            for unit in self.task_units
            if unit.partition is PanelPartition.CONFIRMATORY
        )
        if self.development_unit_ids != development:
            raise ValueError("development IDs do not match frozen partitions")
        if self.confirmatory_unit_ids != confirmatory:
            raise ValueError("confirmatory IDs do not match frozen partitions")
        if set(development) & set(confirmatory):
            raise ValueError("development and confirmation must be disjoint")
        if (len(development), len(confirmatory)) != (7, 60):
            raise ValueError("frozen panel must contain 7 development and 60 tasks")

        expected_family_counts = {
            family.value: sum(
                unit.family is family and unit.partition is PanelPartition.CONFIRMATORY
                for unit in self.task_units
            )
            for family in ObjectiveTaskFamily
        }
        if self.family_confirmatory_counts != expected_family_counts:
            raise ValueError("family confirmation counts do not match task units")
        if expected_family_counts != {
            ObjectiveTaskFamily.TABULAR_CLASSIFICATION.value: 41,
            ObjectiveTaskFamily.TABULAR_REGRESSION.value: 19,
        }:
            raise ValueError("frozen family allocation changed")

        unit_by_id = {unit.unit_id: unit for unit in self.task_units}
        for probe in self.family_probes:
            probe.verify_integrity()
            representative = unit_by_id.get(probe.representative_unit_id)
            if representative is None:
                raise ValueError("family probe representative is absent")
            if representative.partition is not PanelPartition.DEVELOPMENT:
                raise ValueError("live probes may download development tasks only")
            if representative.family is not probe.family:
                raise ValueError("family probe representative family mismatch")
            if representative.evaluator_source_hash != probe.evaluator_source_hash:
                raise ValueError("family probe evaluator hash mismatch")

        for scenario in self.power_scenarios:
            scenario.verify_integrity()
            if scenario.independent_unit_count != len(confirmatory):
                raise ValueError("power scenario must use independent tasks")
        if [scenario.unfavorable_probability for scenario in self.power_scenarios] != [
            0.0,
            0.05,
            0.10,
        ]:
            raise ValueError("power sensitivity set changed")
        if {
            (scenario.alpha, scenario.target_power, scenario.minimum_effect)
            for scenario in self.power_scenarios
        } != {(0.05, 0.80, 0.25)}:
            raise ValueError("power design changed")
        required = max(
            scenario.required_independent_unit_count for scenario in self.power_scenarios
        )
        if self.required_confirmatory_task_count != required:
            raise ValueError("required task count does not match exact power")
        if required != 60:
            raise ValueError("frozen conservative sensitivity must require 60 tasks")

        expected_blockers = _derived_panel_blockers(
            task_units=self.task_units,
            family_probes=self.family_probes,
            required_confirmatory_count=required,
        )
        if self.blockers != expected_blockers:
            raise ValueError("panel blockers do not match evidence")
        expected_ready = not expected_blockers
        if self.baseline_reproduction_authorized != expected_ready:
            raise ValueError("baseline authorization does not match panel gate")
        expected_status = (
            OpenTaskPanelStatus.READY_FOR_CLEAN_BASELINE
            if expected_ready
            else OpenTaskPanelStatus.BLOCKED
        )
        if self.status is not expected_status:
            raise ValueError("panel status does not match evidence")
        if self.report_hash != self.calculated_hash():
            raise PortfolioIntegrityError("open task panel report_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> OpenObjectiveTaskPanelReport:
        """Derive partitions, power requirement, blockers, and report hash."""

        payload = dict(values)
        units = [
            (
                unit
                if isinstance(unit, OpenObjectiveTaskUnit)
                else OpenObjectiveTaskUnit.model_validate(unit)
            )
            for unit in payload["task_units"]
        ]
        probes = [
            (
                probe
                if isinstance(probe, ObjectiveFamilyProbe)
                else ObjectiveFamilyProbe.model_validate(probe)
            )
            for probe in payload["family_probes"]
        ]
        scenarios = [
            (
                scenario
                if isinstance(scenario, ExactPairedPowerScenario)
                else ExactPairedPowerScenario.model_validate(scenario)
            )
            for scenario in payload["power_scenarios"]
        ]
        units = sorted(units, key=lambda item: item.unit_id)
        probes = sorted(probes, key=lambda item: item.family.value)
        scenarios = sorted(
            scenarios,
            key=lambda item: (
                item.unfavorable_probability,
                item.favorable_probability,
            ),
        )
        development_ids = sorted(
            unit.unit_id for unit in units if unit.partition is PanelPartition.DEVELOPMENT
        )
        confirmatory_ids = sorted(
            unit.unit_id for unit in units if unit.partition is PanelPartition.CONFIRMATORY
        )
        required = max(scenario.required_independent_unit_count for scenario in scenarios)
        blockers = _derived_panel_blockers(
            task_units=units,
            family_probes=probes,
            required_confirmatory_count=required,
        )
        payload.update(
            {
                "schema_version": "open-objective-task-panel-report-v1",
                "source_registry_hash": frozen_source_registry_hash(),
                "selection_seed": PANEL_SELECTION_SEED,
                "selection_rule": PANEL_SELECTION_RULE,
                "claim_scope": PANEL_CLAIM_SCOPE,
                "selection_exclusions": frozen_selection_exclusions(),
                "evaluator_code_license_id": "Apache-2.0",
                "task_units": [unit.model_dump(mode="json") for unit in units],
                "family_probes": [probe.model_dump(mode="json") for probe in probes],
                "power_scenarios": [scenario.model_dump(mode="json") for scenario in scenarios],
                "development_unit_ids": development_ids,
                "confirmatory_unit_ids": confirmatory_ids,
                "family_confirmatory_counts": {
                    family.value: sum(
                        unit.family is family and unit.partition is PanelPartition.CONFIRMATORY
                        for unit in units
                    )
                    for family in ObjectiveTaskFamily
                },
                "required_confirmatory_task_count": required,
                "blocking_factors": ["benchmark", "domain"],
                "within_unit_repeat_role": (
                    "seeds and trajectories are repeated measurements, never " "independent units"
                ),
                "confirmatory_payloads_downloaded": False,
                "study_outcomes_observed": False,
                "existing_public_runs_queried": False,
                "data_redistributed": False,
                "blockers": blockers,
                "baseline_reproduction_authorized": not blockers,
                "status": (
                    OpenTaskPanelStatus.READY_FOR_CLEAN_BASELINE
                    if not blockers
                    else OpenTaskPanelStatus.BLOCKED
                ),
                "novelty_search_started": False,
                "public_release_authorized": False,
                "external_submission_authorized": False,
            }
        )
        payload["source_suite_snapshot_hashes"] = dict(
            sorted(payload["source_suite_snapshot_hashes"].items())
        )
        payload["selection_exclusions"] = dict(sorted(payload["selection_exclusions"].items()))
        payload["family_confirmatory_counts"] = dict(
            sorted(payload["family_confirmatory_counts"].items())
        )
        payload["report_hash"] = canonical_sha256(payload)
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the recursively bound report digest."""

        return canonical_sha256(self.model_dump(mode="json", exclude={"report_hash"}))

    def verify_integrity(self) -> None:
        """Reject nested or in-memory report tampering."""

        for unit in self.task_units:
            unit.verify_integrity()
        for probe in self.family_probes:
            probe.verify_integrity()
        for scenario in self.power_scenarios:
            scenario.verify_integrity()
        if self.report_hash != self.calculated_hash():
            raise PortfolioIntegrityError("open task panel report_hash mismatch")


class OpenObjectiveTaskPanelManifest(KernelContract):
    """Content inventory for a persisted Task 263.4.1 panel audit."""

    schema_version: Literal["open-objective-task-panel-manifest-v1"] = (
        "open-objective-task-panel-manifest-v1"
    )
    report_hash: Sha256
    files: dict[NonEmptyText, Sha256]
    confirmatory_payloads_included: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    manifest_hash: Sha256

    @model_validator(mode="after")
    def _validate_manifest(self) -> OpenObjectiveTaskPanelManifest:
        if list(self.files) != sorted(self.files):
            raise ValueError("manifest files must be sorted")
        if self.manifest_hash != self.calculated_hash():
            raise PortfolioIntegrityError("open task panel manifest_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> OpenObjectiveTaskPanelManifest:
        """Normalize the inventory and attach its digest."""

        payload = dict(values)
        payload.update(
            {
                "schema_version": "open-objective-task-panel-manifest-v1",
                "confirmatory_payloads_included": False,
                "external_submission_authorized": False,
            }
        )
        payload["files"] = dict(sorted(payload["files"].items()))
        payload["manifest_hash"] = canonical_sha256(payload)
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the artifact-manifest digest."""

        return canonical_sha256(self.model_dump(mode="json", exclude={"manifest_hash"}))

    def verify_integrity(self) -> None:
        """Reject an in-memory artifact-manifest mutation."""

        if self.manifest_hash != self.calculated_hash():
            raise PortfolioIntegrityError("open task panel manifest_hash mismatch")


def render_open_objective_task_panel_markdown(
    report: OpenObjectiveTaskPanelReport,
) -> str:
    """Render a compact pre-result panel audit."""

    report.verify_integrity()
    rows = [
        "# Open objective task panel",
        "",
        f"- Status: `{report.status.value}`",
        f"- Report hash: `{report.report_hash}`",
        f"- Registry hash: `{report.source_registry_hash}`",
        f"- Claim scope: {report.claim_scope}",
        f"- Development tasks: `{len(report.development_unit_ids)}`",
        f"- Confirmatory tasks: `{len(report.confirmatory_unit_ids)}`",
        f"- Required confirmatory tasks: " f"`{report.required_confirmatory_task_count}`",
        "- Confirmatory payloads downloaded: `false`",
        "- Study outcomes observed: `false`",
        "- Existing public runs queried: `false`",
        "- Novelty search started: `false`",
        "- Public release / external submission: `false` / `false`",
        "",
        "## Family allocation and live probes",
        "",
        "| Family | Confirmatory n | Representative | Probe |",
        "|---|---:|---|---:|",
    ]
    probes = {probe.family: probe for probe in report.family_probes}
    for family in ObjectiveTaskFamily:
        probe = probes[family]
        rows.append(
            f"| {family.value} | "
            f"{report.family_confirmatory_counts[family.value]} | "
            f"`{probe.representative_unit_id}` | "
            f"{str(probe.passed).lower()} |"
        )
    rows.extend(
        [
            "",
            "## Exact prospective power",
            "",
            "| p(favorable) | p(unfavorable) | n | power | n for 80% |",
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
            "## Task registry",
            "",
            "| Unit | Split | Family | Domain | Data | License | Rows | Features |",
            "|---|---|---|---|---:|---|---:|---:|",
        ]
    )
    for unit in report.task_units:
        rows.append(
            f"| `{unit.unit_id}` | {unit.partition.value} | "
            f"{unit.family.value} | {unit.domain} | `{unit.data_id}` | "
            f"{unit.effective_license_id} | {unit.number_instances} | "
            f"{unit.number_features} |"
        )
    rows.extend(
        [
            "",
            "## Hard blockers",
            "",
        ]
    )
    rows.extend(
        [f"- `{blocker}`" for blocker in report.blockers]
        or ["- None; Task 263.4.2 may start clean baseline reproduction."]
    )
    rows.extend(
        [
            "",
            "This panel tests a narrow tabular-ML search-policy claim. It does "
            "not establish general autonomous-science capability, novelty, or "
            "publication readiness.",
            "",
        ]
    )
    return "\n".join(rows)


OPEN_OBJECTIVE_PANEL_MODELS = (
    ObjectiveFamilyProbe,
    OpenObjectiveTaskPanelManifest,
    OpenObjectiveTaskPanelReport,
    OpenObjectiveTaskUnit,
)


def open_objective_task_panel_json_schemas() -> dict[str, dict[str, Any]]:
    """Export deterministic JSON Schemas for public panel artifacts."""

    return {model.__name__: model.model_json_schema() for model in OPEN_OBJECTIVE_PANEL_MODELS}


def write_open_objective_task_panel(
    output_dir: Path,
    report: OpenObjectiveTaskPanelReport,
) -> OpenObjectiveTaskPanelManifest:
    """Persist verified JSON, Markdown, schemas, and a digest manifest."""

    report.verify_integrity()
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "open-objective-task-panel.json"
    markdown_path = output_dir / "open-objective-task-panel.md"
    schemas_path = output_dir / "open-objective-task-panel-schemas.json"
    _write_text_atomic(report_path, report.model_dump_json(indent=2) + "\n")
    _write_text_atomic(
        markdown_path,
        render_open_objective_task_panel_markdown(report),
    )
    _write_text_atomic(
        schemas_path,
        json.dumps(
            open_objective_task_panel_json_schemas(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    manifest = OpenObjectiveTaskPanelManifest.create(
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


def load_open_objective_task_panel(
    path: Path,
) -> OpenObjectiveTaskPanelReport:
    """Load and recursively verify a persisted task-panel report."""

    report = OpenObjectiveTaskPanelReport.model_validate_json(path.read_text(encoding="utf-8"))
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
