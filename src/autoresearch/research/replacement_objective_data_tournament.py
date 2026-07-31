"""Result-blind objective-data admission tournament for Task 263.6.6.

The prior scientific route failed before model execution because provisional
folders did not provide enough independent reserve groups. This module asks a
more fundamental question before another evaluator or agent is built: does any
replacement benchmark simultaneously provide independently lineaged units,
per-source rights, a deterministic executable primary endpoint, a reproducible
strong baseline, bounded local workload, and 30 development plus 84 sealed
reserve groups?

Four mandatory candidates are audited at exact official revisions:

* AutoSDT-5K, grouped by source repository;
* ScienceAgentBench, bounded by source repository/publication lineage;
* CORE-Bench, grouped by paper/capsule rather than difficulty variant; and
* QRData, grouped by shared data-file set rather than question.

Only result-blind identifiers and gate observations enter a frozen,
dependency-free two-interpreter replay. Prompts, answers, reference programs,
model outputs, evaluator outputs, and reserve labels are excluded. The
tournament has no hardcoded winner and explicitly permits every candidate to
fail.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import subprocess
import zipfile
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import requests
from pydantic import BaseModel, Field, field_validator, model_validator

from autoresearch.kernel.contracts import (
    KernelContract,
    NonEmptyText,
    Sha256,
    StableId,
    canonical_sha256,
)

from .opportunity_tournament import LiveResourceProbe
from .portfolio import (
    NearestWorkDelta,
    PortfolioIntegrityError,
    ResearchSource,
)
from .workload_qualified_opportunity import InterpreterRuntime, probe_interpreter_runtime

AUTOSDT_DATASET_ID: Literal["osunlp/AutoSDT-5K"] = "osunlp/AutoSDT-5K"
AUTOSDT_DATASET_REVISION = "659b60f3fabdfc5d6b80ef08176f602f4cfb24a6"
AUTOSDT_REPOSITORY_REVISION = "744a3c70a49c6e53effae65a93d2a7ad9ce923ba"

SCIENCE_AGENT_BENCH_DATASET_ID: Literal["osunlp/ScienceAgentBench"] = (
    "osunlp/ScienceAgentBench"
)
SCIENCE_AGENT_BENCH_DATASET_REVISION = (
    "9c6e96c9e74572e979b0930ee735041cef528cb7"
)
SCIENCE_AGENT_BENCH_REPOSITORY_REVISION = (
    "c26e151ed601ba109dc4d35e057ff8e73fec469d"
)

CORE_BENCH_DATASET_ID: Literal["siegelz/core-bench"] = "siegelz/core-bench"
CORE_BENCH_DATASET_REVISION = "18ac8edf2532d9edb9d13ae71f715410de6ee5a0"
CORE_BENCH_REPOSITORY_REVISION = "e32a2980e72fe6eb04ee04eb749458f570625663"

QRDATA_REPOSITORY_REVISION = "de450af45ff7101b328bb064c6b475f73414a7ed"

REQUIRED_DEVELOPMENT_GROUPS: Literal[30] = 30
REQUIRED_RESERVE_GROUPS: Literal[84] = 84
REQUIRED_TOTAL_GROUPS = REQUIRED_DEVELOPMENT_GROUPS + REQUIRED_RESERVE_GROUPS

REPLACEMENT_RUNNER_SOURCE_PATH = Path(
    "src/autoresearch/research/assets/"
    "frozen_replacement_objective_data_probe_v1.py"
)
REPLACEMENT_REPORT_FILENAME: Literal[
    "replacement-objective-data-tournament.json"
] = "replacement-objective-data-tournament.json"
REPLACEMENT_MARKDOWN_FILENAME: Literal[
    "replacement-objective-data-tournament.md"
] = "replacement-objective-data-tournament.md"
REPLACEMENT_SCHEMA_FILENAME: Literal[
    "replacement-objective-data-tournament-schemas.json"
] = "replacement-objective-data-tournament-schemas.json"
REPLACEMENT_MANIFEST_FILENAME: Literal[
    "replacement-objective-data-tournament-manifest.json"
] = "replacement-objective-data-tournament-manifest.json"
REPLACEMENT_REPLAY_INPUT_FILENAME: Literal[
    "replacement-objective-data-replay-input.json"
] = "replacement-objective-data-replay-input.json"

_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SENSITIVE_JSON_FIELDS = {
    "answer",
    "data_description",
    "domain_knowledge",
    "input",
    "instruction",
    "multiple_choices",
    "output",
    "question",
    "task_inst",
    "task_prompt",
}


def _jsonable(value: Any) -> Any:
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


def _canonical_json_text(value: Any) -> str:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        allow_nan=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


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


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _discard_sensitive_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    for key, value in pairs:
        if key in _SENSITIVE_JSON_FIELDS:
            continue
        if key == "results":
            if not isinstance(value, list):
                raise ValueError("CORE-Bench results must be a list")
            projected["technical_variant_count"] = len(value)
            continue
        projected[key] = value
    return projected


def _projection_json(raw: bytes) -> Any:
    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_discard_sensitive_pairs,
    )


class ReplacementCandidateId(str, Enum):
    AUTOSDT_5K = "autosdt-5k"
    SCIENCE_AGENT_BENCH = "scienceagentbench"
    CORE_BENCH = "core-bench"
    QRDATA = "qrdata"


class CandidateConstruct(str, Enum):
    SCIENTIFIC_CODING_TRAINING = "scientific-coding-training"
    SCIENTIFIC_PROGRAM_SYNTHESIS = "scientific-program-synthesis"
    COMPUTATIONAL_REPRODUCIBILITY = "computational-reproducibility"
    STATISTICAL_CAUSAL_REASONING = "statistical-causal-reasoning"


class RightsScope(str, Enum):
    LOCAL_EXECUTION = "local-execution"
    SOFTWARE_REUSE = "software-reuse"
    DERIVATIVE_CREATION = "derivative-creation"
    CONTENT_REDISTRIBUTION = "content-redistribution"


class RightsStatus(str, Enum):
    VERIFIED = "verified"
    PARTIAL = "partial"
    BLOCKED = "blocked"


class EndpointKind(str, Enum):
    REFERENCE_PROGRAM_CORPUS = "reference-program-corpus"
    MIXED_EXECUTION_AND_LLM_VISUAL_JUDGE = "mixed-execution-and-llm-visual-judge"
    DETERMINISTIC_REPRODUCTION_QA = "deterministic-reproduction-qa"
    DETERMINISTIC_NUMERIC_AND_MULTIPLE_CHOICE = (
        "deterministic-numeric-and-multiple-choice"
    )


class ReplacementTournamentStatus(str, Enum):
    ALL_CANDIDATES_REJECTED = "all-candidates-rejected"
    CANDIDATE_QUALIFIED_FOR_BASELINE_REPRODUCTION = (
        "candidate-qualified-for-baseline-reproduction"
    )


class FrozenResourceArtifact(KernelContract):
    """One exact official file used by a candidate audit."""

    schema_version: Literal["frozen-resource-artifact-v1"] = (
        "frozen-resource-artifact-v1"
    )
    artifact_id: StableId
    role: StableId
    url: NonEmptyText
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    sha256: Sha256
    byte_count: int = Field(ge=0)
    outcome_bearing: bool
    outcome_fields_projected: Literal[False] = False
    artifact_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> FrozenResourceArtifact:
        if self.artifact_hash != self.calculated_hash():
            raise PortfolioIntegrityError("resource artifact_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> FrozenResourceArtifact:
        payload = dict(values)
        payload["schema_version"] = "frozen-resource-artifact-v1"
        payload["outcome_fields_projected"] = False
        payload["artifact_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"artifact_hash"})
        )


class CandidateResourceSnapshot(KernelContract):
    """Content-addressed official resource snapshot for one candidate."""

    schema_version: Literal["candidate-resource-snapshot-v1"] = (
        "candidate-resource-snapshot-v1"
    )
    candidate_id: ReplacementCandidateId
    repository_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    dataset_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    last_modified: NonEmptyText
    artifacts: list[FrozenResourceArtifact] = Field(min_length=1)
    snapshot_hash: Sha256

    @model_validator(mode="after")
    def _validate_snapshot(self) -> CandidateResourceSnapshot:
        ids = [item.artifact_id for item in self.artifacts]
        if len(set(ids)) != len(ids):
            raise ValueError("resource artifact identifiers must be unique")
        self.artifacts = sorted(self.artifacts, key=lambda item: item.artifact_id)
        if self.snapshot_hash != self.calculated_hash():
            raise PortfolioIntegrityError("resource snapshot_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> CandidateResourceSnapshot:
        payload = dict(values)
        payload["schema_version"] = "candidate-resource-snapshot-v1"
        payload["artifacts"] = sorted(
            payload["artifacts"], key=lambda item: item.artifact_id
        )
        payload["snapshot_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"snapshot_hash"})
        )


class TaskLineageRecord(KernelContract):
    """Result-blind task-to-source/generator projection."""

    task_id: StableId
    source_group_id: StableId
    source_locator_sha256: Sha256
    generator_template_sha256: Sha256
    license_label: NonEmptyText
    technical_variant_count: int = Field(default=1, ge=1)


class CandidateLineageInventory(KernelContract):
    """Independent-unit inventory without prompt, label, or result values."""

    schema_version: Literal["candidate-lineage-inventory-v1"] = (
        "candidate-lineage-inventory-v1"
    )
    candidate_id: ReplacementCandidateId
    task_count: int = Field(ge=1)
    declared_unlineaged_task_count: int = Field(ge=0)
    declared_unlineaged_group_upper_bound: int = Field(ge=0)
    source_revisions_pinned: bool
    outcome_values_projected: Literal[False] = False
    task_records: list[TaskLineageRecord] = Field(min_length=1)
    source_group_ids: list[StableId] = Field(min_length=1)
    lineage_hash: Sha256

    @model_validator(mode="after")
    def _validate_inventory(self) -> CandidateLineageInventory:
        task_ids = [item.task_id for item in self.task_records]
        if len(set(task_ids)) != len(task_ids):
            raise ValueError("task lineage identifiers must be unique")
        observed_groups = sorted({item.source_group_id for item in self.task_records})
        if observed_groups != self.source_group_ids:
            raise ValueError("source_group_ids do not match task lineage records")
        represented = sum(item.technical_variant_count for item in self.task_records)
        if represented + self.declared_unlineaged_task_count != self.task_count:
            raise ValueError("task lineage does not account for the declared task count")
        self.task_records = sorted(self.task_records, key=lambda item: item.task_id)
        if self.lineage_hash != self.calculated_hash():
            raise PortfolioIntegrityError("lineage_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> CandidateLineageInventory:
        payload = dict(values)
        payload["schema_version"] = "candidate-lineage-inventory-v1"
        payload["outcome_values_projected"] = False
        payload["task_records"] = sorted(
            payload["task_records"], key=lambda item: item.task_id
        )
        payload["source_group_ids"] = sorted(
            {item.source_group_id for item in payload["task_records"]}
        )
        payload["lineage_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"lineage_hash"})
        )


@dataclass(frozen=True)
class ParsedCandidateLineage:
    inventory: CandidateLineageInventory
    group_license_labels: Mapping[str, str]
    auxiliary_counts: Mapping[str, int]


class RightsScopeDecision(KernelContract):
    """Observed rights boundary for one use, not legal advice."""

    scope: RightsScope
    status: RightsStatus
    covered_group_count: int = Field(ge=0)
    required_group_count: int = Field(ge=0)
    license_ids: list[NonEmptyText] = Field(default_factory=list)
    evidence_hashes: list[Sha256] = Field(default_factory=list)
    interpretation: NonEmptyText

    @model_validator(mode="after")
    def _validate_scope(self) -> RightsScopeDecision:
        if self.covered_group_count > self.required_group_count:
            raise ValueError("rights coverage exceeds required source groups")
        if self.status is RightsStatus.VERIFIED and (
            self.covered_group_count != self.required_group_count
        ):
            raise ValueError("verified rights scope requires complete coverage")
        return self


class CandidateLicenseAudit(KernelContract):
    """Per-source evidence coverage across four distinct use scopes."""

    schema_version: Literal["candidate-license-audit-v1"] = (
        "candidate-license-audit-v1"
    )
    candidate_id: ReplacementCandidateId
    required_group_count: int = Field(ge=1)
    declared_license_group_counts: dict[str, int]
    exact_source_license_object_group_count: int = Field(ge=0)
    missing_or_unbound_group_count: int = Field(ge=0)
    scopes: list[RightsScopeDecision] = Field(min_length=4, max_length=4)
    gate_passed: bool
    blockers: list[StableId]
    audit_hash: Sha256

    @field_validator("declared_license_group_counts")
    @classmethod
    def _validate_counts(cls, value: dict[str, int]) -> dict[str, int]:
        if not value or any(count < 0 for count in value.values()):
            raise ValueError("declared license counts must be non-negative")
        return dict(sorted(value.items()))

    @model_validator(mode="after")
    def _validate_audit(self) -> CandidateLicenseAudit:
        if {item.scope for item in self.scopes} != set(RightsScope):
            raise ValueError("all four license use scopes are required")
        expected_gate = all(
            item.status is RightsStatus.VERIFIED
            and item.covered_group_count == item.required_group_count
            for item in self.scopes
        ) and self.exact_source_license_object_group_count == self.required_group_count
        if self.gate_passed != expected_gate:
            raise ValueError("license gate does not match exact scope coverage")
        self.scopes = sorted(self.scopes, key=lambda item: item.scope.value)
        self.blockers = sorted(set(self.blockers))
        if self.audit_hash != self.calculated_hash():
            raise PortfolioIntegrityError("license audit_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> CandidateLicenseAudit:
        payload = dict(values)
        payload["schema_version"] = "candidate-license-audit-v1"
        payload["declared_license_group_counts"] = dict(
            sorted(payload["declared_license_group_counts"].items())
        )
        payload["scopes"] = sorted(
            payload["scopes"], key=lambda item: item.scope.value
        )
        payload["blockers"] = sorted(set(payload["blockers"]))
        payload["audit_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"audit_hash"})
        )


class CandidateEndpointAudit(KernelContract):
    """Primary endpoint and construct audit."""

    schema_version: Literal["candidate-endpoint-audit-v1"] = (
        "candidate-endpoint-audit-v1"
    )
    candidate_id: ReplacementCandidateId
    construct_kind: CandidateConstruct
    endpoint_kind: EndpointKind
    deterministic: bool
    executable: bool
    llm_or_post_result_human_primary: bool
    best_of_attempts_primary: bool
    packaged_executable_scorer: bool
    construct_coherent: bool
    gate_passed: bool
    evidence_artifact_hashes: list[Sha256]
    interpretation: NonEmptyText
    audit_hash: Sha256

    @model_validator(mode="after")
    def _validate_endpoint(self) -> CandidateEndpointAudit:
        expected = (
            self.deterministic
            and self.executable
            and not self.llm_or_post_result_human_primary
            and not self.best_of_attempts_primary
            and self.packaged_executable_scorer
            and self.construct_coherent
        )
        if self.gate_passed != expected:
            raise ValueError("endpoint gate does not match endpoint properties")
        if self.audit_hash != self.calculated_hash():
            raise PortfolioIntegrityError("endpoint audit_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> CandidateEndpointAudit:
        payload = dict(values)
        payload["schema_version"] = "candidate-endpoint-audit-v1"
        payload["evidence_artifact_hashes"] = sorted(
            set(payload["evidence_artifact_hashes"])
        )
        payload["audit_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"audit_hash"})
        )


class StrongBaselineAvailabilityAudit(KernelContract):
    """Availability audit performed without executing a candidate model."""

    schema_version: Literal["strong-baseline-availability-audit-v1"] = (
        "strong-baseline-availability-audit-v1"
    )
    candidate_id: ReplacementCandidateId
    published_comparison_available: bool
    official_baseline_code_available: bool
    exact_reproduction_command_available: bool
    candidate_model_calls_run: Literal[False] = False
    gate_passed: bool
    interpretation: NonEmptyText
    audit_hash: Sha256

    @model_validator(mode="after")
    def _validate_baseline(self) -> StrongBaselineAvailabilityAudit:
        expected = (
            self.published_comparison_available
            and self.official_baseline_code_available
            and self.exact_reproduction_command_available
        )
        if self.gate_passed != expected:
            raise ValueError("baseline availability gate mismatch")
        if self.audit_hash != self.calculated_hash():
            raise PortfolioIntegrityError("baseline audit_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> StrongBaselineAvailabilityAudit:
        payload = dict(values)
        payload["schema_version"] = "strong-baseline-availability-audit-v1"
        payload["candidate_model_calls_run"] = False
        payload["audit_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"audit_hash"})
        )


class CandidateComputeAudit(KernelContract):
    """Bounded local workload audit without executing candidate models."""

    schema_version: Literal["candidate-compute-audit-v1"] = (
        "candidate-compute-audit-v1"
    )
    candidate_id: ReplacementCandidateId
    audited_download_bytes: int = Field(ge=0)
    audited_expanded_bytes: int = Field(ge=0)
    docker_required: bool
    privileged_container_required: bool
    gpu_tasks_present: bool
    mutable_external_service_required: bool
    bounded_local_execution: bool
    candidate_model_calls_run: Literal[False] = False
    interpretation: NonEmptyText
    audit_hash: Sha256

    @model_validator(mode="after")
    def _validate_compute(self) -> CandidateComputeAudit:
        if self.privileged_container_required and not self.docker_required:
            raise ValueError("privileged container requires Docker")
        if self.audit_hash != self.calculated_hash():
            raise PortfolioIntegrityError("compute audit_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> CandidateComputeAudit:
        payload = dict(values)
        payload["schema_version"] = "candidate-compute-audit-v1"
        payload["candidate_model_calls_run"] = False
        payload["audit_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"audit_hash"})
        )


class ReplacementGateVector(KernelContract):
    revision: bool
    lineage: bool
    license: bool
    objective_endpoint: bool
    construct_coherence: bool
    strong_baseline: bool
    bounded_local_compute: bool
    reserve_seal: bool


class CandidateReplayInput(KernelContract):
    """Only the result-blind fields visible to the frozen runner."""

    candidate_id: StableId
    task_count: int = Field(ge=1)
    capacity_group_ids: list[StableId] = Field(min_length=1)
    declared_unlineaged_group_upper_bound: int = Field(ge=0)
    development_group_capacity: int = Field(ge=0)
    potential_reserve_group_capacity: int = Field(ge=0)
    sealed_reserve_group_capacity: int = Field(ge=0)
    gates: ReplacementGateVector

    @model_validator(mode="after")
    def _validate_replay_input(self) -> CandidateReplayInput:
        if len(set(self.capacity_group_ids)) != len(self.capacity_group_ids):
            raise ValueError("capacity group identifiers must be unique")
        self.capacity_group_ids = sorted(self.capacity_group_ids)
        upper = (
            len(self.capacity_group_ids)
            + self.declared_unlineaged_group_upper_bound
        )
        if upper > self.task_count:
            raise ValueError("independent group upper bound exceeds task count")
        if (
            self.development_group_capacity
            + self.potential_reserve_group_capacity
            > upper
        ):
            raise ValueError("development plus reserve exceeds group upper bound")
        if (
            self.sealed_reserve_group_capacity
            > self.potential_reserve_group_capacity
        ):
            raise ValueError("sealed reserve exceeds potential reserve")
        if self.gates.lineage and self.declared_unlineaged_group_upper_bound:
            raise ValueError("lineage cannot pass with unlineaged groups")
        if self.gates.reserve_seal and (
            self.sealed_reserve_group_capacity
            != self.potential_reserve_group_capacity
        ):
            raise ValueError("reserve seal cannot pass for a partial reserve")
        return self


class ReplacementCandidateAudit(KernelContract):
    """Conjunctive pre-model audit for one candidate."""

    schema_version: Literal["replacement-candidate-audit-v1"] = (
        "replacement-candidate-audit-v1"
    )
    candidate_id: ReplacementCandidateId
    resource_snapshot: CandidateResourceSnapshot
    lineage: CandidateLineageInventory
    license_audit: CandidateLicenseAudit
    endpoint_audit: CandidateEndpointAudit
    baseline_audit: StrongBaselineAvailabilityAudit
    compute_audit: CandidateComputeAudit
    replay_input: CandidateReplayInput
    notes: list[NonEmptyText]
    audit_hash: Sha256

    @model_validator(mode="after")
    def _validate_candidate(self) -> ReplacementCandidateAudit:
        candidate_values = {
            self.resource_snapshot.candidate_id,
            self.lineage.candidate_id,
            self.license_audit.candidate_id,
            self.endpoint_audit.candidate_id,
            self.baseline_audit.candidate_id,
            self.compute_audit.candidate_id,
        }
        if candidate_values != {self.candidate_id}:
            raise ValueError("candidate audit components disagree on candidate_id")
        if self.replay_input.candidate_id != self.candidate_id.value:
            raise ValueError("replay candidate_id mismatch")
        if self.replay_input.task_count != self.lineage.task_count:
            raise ValueError("replay task_count mismatch")
        if not set(self.replay_input.capacity_group_ids).issubset(
            set(self.lineage.source_group_ids)
        ):
            raise ValueError("capacity groups must be lineaged source groups")
        expected_gates = ReplacementGateVector(
            revision=True,
            lineage=(
                self.lineage.source_revisions_pinned
                and self.replay_input.declared_unlineaged_group_upper_bound == 0
            ),
            license=self.license_audit.gate_passed,
            objective_endpoint=self.endpoint_audit.gate_passed,
            construct_coherence=self.endpoint_audit.construct_coherent,
            strong_baseline=self.baseline_audit.gate_passed,
            bounded_local_compute=self.compute_audit.bounded_local_execution,
            reserve_seal=self.replay_input.gates.reserve_seal,
        )
        if self.replay_input.gates != expected_gates:
            raise ValueError("candidate replay gate vector mismatch")
        self.notes = sorted(set(self.notes))
        if self.audit_hash != self.calculated_hash():
            raise PortfolioIntegrityError("candidate audit_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ReplacementCandidateAudit:
        payload = dict(values)
        payload["schema_version"] = "replacement-candidate-audit-v1"
        payload["notes"] = sorted(set(payload["notes"]))
        payload["audit_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"audit_hash"})
        )


class ReplacementCandidateProjection(KernelContract):
    schema_version: Literal["replacement-candidate-projection-v1"] = (
        "replacement-candidate-projection-v1"
    )
    candidate_id: StableId
    task_count: int = Field(ge=1)
    lineaged_capacity_group_count: int = Field(ge=1)
    declared_unlineaged_group_upper_bound: int = Field(ge=0)
    independent_group_upper_bound: int = Field(ge=1)
    development_group_capacity: int = Field(ge=0)
    potential_reserve_group_capacity: int = Field(ge=0)
    sealed_reserve_group_capacity: int = Field(ge=0)
    required_development_groups: Literal[30] = REQUIRED_DEVELOPMENT_GROUPS
    required_reserve_groups: Literal[84] = REQUIRED_RESERVE_GROUPS
    passed_gate_count: int = Field(ge=0, le=8)
    gates: ReplacementGateVector
    blockers: list[StableId]
    eligible: bool
    projection_sha256: Sha256

    @model_validator(mode="after")
    def _validate_projection(self) -> ReplacementCandidateProjection:
        if self.independent_group_upper_bound != (
            self.lineaged_capacity_group_count
            + self.declared_unlineaged_group_upper_bound
        ):
            raise ValueError("candidate independent group upper bound mismatch")
        if self.passed_gate_count != sum(
            bool(value)
            for value in self.gates.model_dump(mode="python").values()
        ):
            raise ValueError("candidate passed gate count mismatch")
        if self.eligible != (not self.blockers):
            raise ValueError("candidate eligibility mismatch")
        if self.projection_sha256 != self.calculated_hash():
            raise PortfolioIntegrityError("candidate projection hash mismatch")
        return self

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"projection_sha256"})
        )


class ReplacementTournamentDecision(KernelContract):
    schema_version: Literal["replacement-tournament-decision-v1"] = (
        "replacement-tournament-decision-v1"
    )
    status: ReplacementTournamentStatus
    selected_candidate_id: StableId | None
    eligible_candidate_ids: list[StableId]
    ranked_candidate_ids: list[StableId] = Field(min_length=4)
    candidate_projection_hashes: dict[str, Sha256]
    baseline_reproduction_authorized: bool
    evaluator_or_critic_construction_authorized: Literal[False] = False
    provider_credentials_collected: Literal[False] = False
    research_question_issued: Literal[False] = False
    confirmation_panel_created_or_read: Literal[False] = False
    heterogeneous_post_result_combination_authorized: Literal[False] = False
    publication_claim_authorized: Literal[False] = False
    public_release_authorized: Literal[False] = False
    submission_authorized: Literal[False] = False
    next_action: StableId
    decision_sha256: Sha256

    @model_validator(mode="after")
    def _validate_decision(self) -> ReplacementTournamentDecision:
        if len(set(self.ranked_candidate_ids)) != len(self.ranked_candidate_ids):
            raise ValueError("ranked candidate identifiers must be unique")
        if set(self.ranked_candidate_ids) != set(
            self.candidate_projection_hashes
        ):
            raise ValueError("decision projection hash coverage mismatch")
        if self.status is ReplacementTournamentStatus.ALL_CANDIDATES_REJECTED:
            if self.selected_candidate_id is not None or self.eligible_candidate_ids:
                raise ValueError("all-candidate rejection cannot select a candidate")
            if self.baseline_reproduction_authorized:
                raise ValueError("rejection cannot authorize baseline reproduction")
        else:
            if self.selected_candidate_id is None:
                raise ValueError("qualified decision requires a selected candidate")
            if self.selected_candidate_id not in self.eligible_candidate_ids:
                raise ValueError("selected candidate must be eligible")
            if not self.baseline_reproduction_authorized:
                raise ValueError("qualified decision should authorize baseline replay")
        if self.decision_sha256 != self.calculated_hash():
            raise PortfolioIntegrityError("tournament decision hash mismatch")
        return self

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"decision_sha256"})
        )


class ReplacementTournamentProjection(KernelContract):
    schema_version: Literal["replacement-tournament-projection-v1"] = (
        "replacement-tournament-projection-v1"
    )
    candidate_projections: list[ReplacementCandidateProjection] = Field(
        min_length=4
    )
    decision: ReplacementTournamentDecision
    projection_sha256: Sha256

    @model_validator(mode="after")
    def _validate_projection(self) -> ReplacementTournamentProjection:
        ids = [item.candidate_id for item in self.candidate_projections]
        if len(set(ids)) != len(ids):
            raise ValueError("candidate projections must be unique")
        self.candidate_projections = sorted(
            self.candidate_projections, key=lambda item: item.candidate_id
        )
        if self.projection_sha256 != self.calculated_hash():
            raise PortfolioIntegrityError("tournament projection hash mismatch")
        return self

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"projection_sha256"})
        )


class ReplacementReplayObservation(KernelContract):
    schema_version: Literal["replacement-replay-observation-v1"] = (
        "replacement-replay-observation-v1"
    )
    role_id: StableId
    interpreter_environment_hash: Sha256
    command_hash: Sha256
    input_sha256: Sha256
    runner_sha256: Sha256
    stdout_sha256: Sha256
    stderr_sha256: Sha256
    projection_sha256: Sha256
    observed_at: datetime
    observation_hash: Sha256

    @model_validator(mode="after")
    def _validate_observation(self) -> ReplacementReplayObservation:
        if self.observation_hash != self.calculated_hash():
            raise PortfolioIntegrityError("replay observation hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ReplacementReplayObservation:
        payload = dict(values)
        payload["schema_version"] = "replacement-replay-observation-v1"
        payload["observation_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"observation_hash"})
        )


class ReplacementReplayCertificate(KernelContract):
    schema_version: Literal["replacement-replay-certificate-v1"] = (
        "replacement-replay-certificate-v1"
    )
    runner_sha256: Sha256
    input_sha256: Sha256
    interpreter_runtimes: list[InterpreterRuntime] = Field(min_length=2)
    observations: list[ReplacementReplayObservation] = Field(min_length=2)
    expected_projection_sha256: Sha256
    exact: bool
    retry_count: Literal[0] = 0
    certificate_hash: Sha256

    @model_validator(mode="after")
    def _validate_certificate(self) -> ReplacementReplayCertificate:
        runtime_roles = {item.role_id for item in self.interpreter_runtimes}
        observation_roles = {item.role_id for item in self.observations}
        if runtime_roles != observation_roles or len(runtime_roles) < 2:
            raise ValueError("two matching interpreter roles are required")
        observed = {item.projection_sha256 for item in self.observations}
        expected_exact = observed == {self.expected_projection_sha256}
        if self.exact != expected_exact:
            raise ValueError("replay exactness mismatch")
        if not self.exact:
            raise PortfolioIntegrityError("replacement replay must be exact")
        if self.certificate_hash != self.calculated_hash():
            raise PortfolioIntegrityError("replay certificate hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ReplacementReplayCertificate:
        payload = dict(values)
        payload["schema_version"] = "replacement-replay-certificate-v1"
        payload["retry_count"] = 0
        payload["interpreter_runtimes"] = sorted(
            payload["interpreter_runtimes"], key=lambda item: item.role_id
        )
        payload["observations"] = sorted(
            payload["observations"], key=lambda item: item.role_id
        )
        payload["certificate_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"certificate_hash"})
        )


class ReplacementObjectiveDataTournamentReport(KernelContract):
    """Formal pre-model tournament report."""

    schema_version: Literal["replacement-objective-data-tournament-v1"] = (
        "replacement-objective-data-tournament-v1"
    )
    study_id: StableId
    created_at: datetime
    literature_cutoff: date
    research_questions: list[NonEmptyText] = Field(min_length=3, max_length=3)
    intended_reader: NonEmptyText
    review_angle: NonEmptyText
    sources: list[ResearchSource] = Field(min_length=4)
    nearest_work: list[NearestWorkDelta] = Field(min_length=4)
    source_probes: list[LiveResourceProbe] = Field(min_length=4)
    candidate_audits: list[ReplacementCandidateAudit] = Field(min_length=4)
    projection: ReplacementTournamentProjection
    replay_certificate: ReplacementReplayCertificate
    candidate_model_calls_run: Literal[False] = False
    outcome_values_projected: Literal[False] = False
    report_hash: Sha256

    @model_validator(mode="after")
    def _validate_report(self) -> ReplacementObjectiveDataTournamentReport:
        candidate_ids = [item.candidate_id for item in self.candidate_audits]
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("candidate audits must be unique")
        projection_ids = {
            item.candidate_id for item in self.projection.candidate_projections
        }
        if projection_ids != {item.value for item in candidate_ids}:
            raise ValueError("candidate audits and projections disagree")
        if (
            self.replay_certificate.expected_projection_sha256
            != self.projection.projection_sha256
        ):
            raise ValueError("report replay projection mismatch")
        self.candidate_audits = sorted(
            self.candidate_audits, key=lambda item: item.candidate_id.value
        )
        if self.report_hash != self.calculated_hash():
            raise PortfolioIntegrityError("replacement report_hash mismatch")
        return self

    @classmethod
    def create(
        cls, **values: Any
    ) -> ReplacementObjectiveDataTournamentReport:
        payload = dict(values)
        payload["schema_version"] = "replacement-objective-data-tournament-v1"
        payload["candidate_model_calls_run"] = False
        payload["outcome_values_projected"] = False
        payload["candidate_audits"] = sorted(
            payload["candidate_audits"],
            key=lambda item: item.candidate_id.value,
        )
        payload["report_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"report_hash"})
        )


class ReplacementTournamentArtifactManifest(KernelContract):
    schema_version: Literal["replacement-tournament-artifact-manifest-v1"] = (
        "replacement-tournament-artifact-manifest-v1"
    )
    report_sha256: Sha256
    markdown_sha256: Sha256
    schema_sha256: Sha256
    replay_input_sha256: Sha256
    runner_sha256: Sha256
    candidate_revisions: dict[str, str]
    manifest_hash: Sha256

    @field_validator("candidate_revisions")
    @classmethod
    def _validate_revisions(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) < 4 or any(not _GIT_SHA_RE.fullmatch(item) for item in value.values()):
            raise ValueError("at least four exact candidate revisions are required")
        return dict(sorted(value.items()))

    @model_validator(mode="after")
    def _validate_manifest(self) -> ReplacementTournamentArtifactManifest:
        if self.manifest_hash != self.calculated_hash():
            raise PortfolioIntegrityError("replacement manifest_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ReplacementTournamentArtifactManifest:
        payload = dict(values)
        payload["schema_version"] = "replacement-tournament-artifact-manifest-v1"
        payload["candidate_revisions"] = dict(
            sorted(payload["candidate_revisions"].items())
        )
        payload["manifest_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"manifest_hash"})
        )


def normalize_repository_url(value: str) -> str:
    """Normalize a GitHub repository URL without treating a branch as a revision."""

    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError(f"unsupported repository URL: {value}")
    host = parsed.netloc.lower()
    path = parsed.path.strip("/")
    if host not in {"github.com", "www.github.com"}:
        raise ValueError(f"non-GitHub repository URL: {value}")
    parts = path.split("/")
    if len(parts) < 2:
        raise ValueError(f"repository URL lacks owner/repository: {value}")
    repository = parts[1][:-4] if parts[1].lower().endswith(".git") else parts[1]
    return f"https://github.com/{parts[0].lower()}/{repository.lower()}"


def _group_id(prefix: str, material: str) -> str:
    return f"{prefix}-{_sha_text(material)}"


def parse_autosdt_lineage(
    raw: bytes,
    *,
    expected_task_count: int | None = None,
) -> ParsedCandidateLineage:
    """Project AutoSDT task/source/license fields and discard program contents."""

    rows = _projection_json(raw)
    if not isinstance(rows, list) or not rows:
        raise ValueError("AutoSDT payload must be a non-empty list")
    if expected_task_count is not None and len(rows) != expected_task_count:
        raise ValueError("AutoSDT task count changed")
    records: list[TaskLineageRecord] = []
    group_labels: dict[str, str] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError("AutoSDT rows must be objects")
        repository_url = normalize_repository_url(str(row.get("repository_url", "")))
        source_url = str(row.get("source_file_url", "")).strip()
        license_label = str(row.get("license", "")).strip()
        if not source_url or not license_label:
            raise ValueError("AutoSDT source URL and license label are required")
        group_id = _group_id("autosdt-repo", repository_url)
        previous = group_labels.setdefault(group_id, license_label)
        if previous != license_label:
            raise ValueError("AutoSDT repository has conflicting license labels")
        records.append(
            TaskLineageRecord(
                task_id=f"autosdt-task-{index:05d}",
                source_group_id=group_id,
                source_locator_sha256=_sha_text(repository_url),
                generator_template_sha256=_sha_text(source_url),
                license_label=license_label,
            )
        )
    inventory = CandidateLineageInventory.create(
        candidate_id=ReplacementCandidateId.AUTOSDT_5K,
        task_count=len(records),
        declared_unlineaged_task_count=0,
        declared_unlineaged_group_upper_bound=0,
        source_revisions_pinned=False,
        task_records=records,
    )
    counts = Counter(group_labels.values())
    return ParsedCandidateLineage(
        inventory=inventory,
        group_license_labels=dict(sorted(group_labels.items())),
        auxiliary_counts={
            f"license:{key}": value for key, value in sorted(counts.items())
        },
    )


def parse_scienceagentbench_lineage(
    raw: bytes,
    *,
    declared_publication_count: int = 44,
    expected_task_count: int | None = None,
) -> ParsedCandidateLineage:
    """Project task-to-repository lineage without reading task instructions."""

    reader = csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise ValueError("ScienceAgentBench CSV is empty") from exc
    required = {
        "instance_id",
        "github_name",
        "src_file_or_path",
        "eval_script_name",
        "gold_program_name",
    }
    if not required.issubset(header):
        raise ValueError("ScienceAgentBench lineage columns are missing")
    indices = {name: header.index(name) for name in required}
    special_upstream_ids = {"3", "32", "46", "53", "54", "84"}
    records: list[TaskLineageRecord] = []
    group_labels: dict[str, str] = {}
    for values in reader:
        if len(values) != len(header):
            raise ValueError("ScienceAgentBench CSV row width changed")
        instance_id = values[indices["instance_id"]].strip()
        repository = values[indices["github_name"]].strip().lower()
        source_path = values[indices["src_file_or_path"]].strip()
        eval_name = values[indices["eval_script_name"]].strip()
        gold_name = values[indices["gold_program_name"]].strip()
        if not instance_id or not repository or not eval_name or not gold_name:
            raise ValueError("ScienceAgentBench lineage row is incomplete")
        group_id = _group_id("sab-repo", repository)
        label = (
            "upstream-special-license-unbound"
            if instance_id in special_upstream_ids
            else "CC-BY-4.0-claimed"
        )
        previous = group_labels.setdefault(group_id, label)
        if previous != label:
            group_labels[group_id] = "mixed-task-license-claims"
        records.append(
            TaskLineageRecord(
                task_id=f"sab-task-{int(instance_id):03d}",
                source_group_id=group_id,
                source_locator_sha256=_sha_text(repository),
                generator_template_sha256=_sha_text(
                    f"{source_path}|{gold_name}|{eval_name}"
                ),
                license_label=label,
            )
        )
    if expected_task_count is not None and len(records) != expected_task_count:
        raise ValueError("ScienceAgentBench task count changed")
    repository_count = len({item.source_group_id for item in records})
    if declared_publication_count < repository_count:
        raise ValueError("declared publications cannot be below repository groups")
    inventory = CandidateLineageInventory.create(
        candidate_id=ReplacementCandidateId.SCIENCE_AGENT_BENCH,
        task_count=len(records),
        declared_unlineaged_task_count=0,
        declared_unlineaged_group_upper_bound=(
            declared_publication_count - repository_count
        ),
        source_revisions_pinned=False,
        task_records=records,
    )
    return ParsedCandidateLineage(
        inventory=inventory,
        group_license_labels=dict(sorted(group_labels.items())),
        auxiliary_counts={
            "declared_publications": declared_publication_count,
            "repository_groups": repository_count,
        },
    )


def parse_core_bench_lineage(
    train_raw: bytes,
    *,
    declared_total_papers: int = 90,
    expected_train_papers: int | None = None,
) -> ParsedCandidateLineage:
    """Group CORE-Bench difficulty variants at paper/capsule level."""

    rows = _projection_json(train_raw)
    if not isinstance(rows, list) or not rows:
        raise ValueError("CORE-Bench train payload must be a non-empty list")
    if expected_train_papers is not None and len(rows) != expected_train_papers:
        raise ValueError("CORE-Bench train paper count changed")
    if declared_total_papers < len(rows):
        raise ValueError("declared CORE-Bench paper count is inconsistent")
    records: list[TaskLineageRecord] = []
    group_labels: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("CORE-Bench rows must be objects")
        capsule_id = str(row.get("capsule_id", "")).strip()
        doi = str(row.get("capsule_doi", "")).strip()
        variants = int(row.get("technical_variant_count", 0))
        if not capsule_id or not doi or variants != 3:
            raise ValueError("CORE-Bench requires three variants per paper capsule")
        group_id = _group_id("core-paper", capsule_id)
        group_labels[group_id] = "capsule-license-unbound"
        records.append(
            TaskLineageRecord(
                task_id=f"core-{capsule_id}",
                source_group_id=group_id,
                source_locator_sha256=_sha_text(doi),
                generator_template_sha256=_sha_text(capsule_id),
                license_label="capsule-license-unbound",
                technical_variant_count=variants,
            )
        )
    train_task_count = sum(item.technical_variant_count for item in records)
    unlineaged_papers = declared_total_papers - len(records)
    inventory = CandidateLineageInventory.create(
        candidate_id=ReplacementCandidateId.CORE_BENCH,
        task_count=declared_total_papers * 3,
        declared_unlineaged_task_count=unlineaged_papers * 3,
        declared_unlineaged_group_upper_bound=unlineaged_papers,
        source_revisions_pinned=False,
        task_records=records,
    )
    return ParsedCandidateLineage(
        inventory=inventory,
        group_license_labels=dict(sorted(group_labels.items())),
        auxiliary_counts={
            "train_papers": len(records),
            "train_technical_variants": train_task_count,
            "sealed_declared_test_papers": unlineaged_papers,
        },
    )


def parse_qrdata_lineage(
    questions_raw: bytes,
    data_zip_raw: bytes,
    *,
    expected_task_count: int | None = None,
) -> ParsedCandidateLineage:
    """Group QRData questions by the exact shared data-file set."""

    rows = _projection_json(questions_raw)
    if not isinstance(rows, list) or not rows:
        raise ValueError("QRData payload must be a non-empty list")
    if expected_task_count is not None and len(rows) != expected_task_count:
        raise ValueError("QRData task count changed")
    with zipfile.ZipFile(io.BytesIO(data_zip_raw)) as archive:
        entries = [item for item in archive.infolist() if not item.is_dir()]
        names = [item.filename for item in entries]
        if len(set(names)) != len(names):
            raise ValueError("QRData archive contains duplicate paths")
        if any(
            Path(name).is_absolute() or ".." in Path(name).parts for name in names
        ):
            raise ValueError("QRData archive contains an unsafe path")
        archive_basenames = {Path(name).name for name in names}
        expanded_bytes = sum(item.file_size for item in entries)

    records: list[TaskLineageRecord] = []
    referenced_files: set[str] = set()
    group_labels: dict[str, str] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError("QRData rows must be objects")
        data_files = row.get("data_files")
        metadata = row.get("meta_data")
        if (
            not isinstance(data_files, list)
            or not data_files
            or not all(isinstance(item, str) and item for item in data_files)
            or not isinstance(metadata, dict)
        ):
            raise ValueError("QRData lineage fields are incomplete")
        normalized_files = sorted(set(data_files))
        if len(normalized_files) != len(data_files):
            raise ValueError("QRData task repeats a data file")
        reference = str(metadata.get("reference", "")).strip()
        question_type = str(metadata.get("question_type", "")).strip()
        if not reference or question_type not in {"numerical", "multiple_choice"}:
            raise ValueError("QRData reference or question type changed")
        referenced_files.update(normalized_files)
        source_material = "|".join(normalized_files)
        group_id = _group_id("qrdata-sheet", source_material)
        group_labels[group_id] = "CC-BY-NC-4.0-global-upstream-unbound"
        records.append(
            TaskLineageRecord(
                task_id=f"qrdata-task-{index:03d}",
                source_group_id=group_id,
                source_locator_sha256=_sha_text(source_material),
                generator_template_sha256=_sha_text(reference),
                license_label="CC-BY-NC-4.0-global-upstream-unbound",
            )
        )
    if referenced_files != archive_basenames:
        raise ValueError("QRData task/archive file lineage is incomplete")
    inventory = CandidateLineageInventory.create(
        candidate_id=ReplacementCandidateId.QRDATA,
        task_count=len(records),
        declared_unlineaged_task_count=0,
        declared_unlineaged_group_upper_bound=0,
        source_revisions_pinned=True,
        task_records=records,
    )
    return ParsedCandidateLineage(
        inventory=inventory,
        group_license_labels=dict(sorted(group_labels.items())),
        auxiliary_counts={
            "archive_file_count": len(archive_basenames),
            "archive_expanded_bytes": expanded_bytes,
            "shared_data_file_set_groups": len(group_labels),
        },
    )


@dataclass(frozen=True)
class _ArtifactSpec:
    role: str
    url: str
    revision: str
    expected_sha256: str
    expected_bytes: int
    outcome_bearing: bool


@dataclass(frozen=True)
class OfficialCandidateMaterial:
    candidate_id: ReplacementCandidateId
    repository_revision: str
    dataset_revision: str
    last_modified: str
    artifact_specs: tuple[_ArtifactSpec, ...]
    raw_by_role: Mapping[str, bytes]

    def snapshot(self) -> CandidateResourceSnapshot:
        artifacts = [
            FrozenResourceArtifact.create(
                artifact_id=f"{self.candidate_id.value}-{spec.role}",
                role=spec.role,
                url=spec.url,
                revision=spec.revision,
                sha256=hashlib.sha256(self.raw_by_role[spec.role]).hexdigest(),
                byte_count=len(self.raw_by_role[spec.role]),
                outcome_bearing=spec.outcome_bearing,
            )
            for spec in self.artifact_specs
        ]
        return CandidateResourceSnapshot.create(
            candidate_id=self.candidate_id,
            repository_revision=self.repository_revision,
            dataset_revision=self.dataset_revision,
            last_modified=self.last_modified,
            artifacts=artifacts,
        )


def _artifact_specs() -> dict[ReplacementCandidateId, tuple[_ArtifactSpec, ...]]:
    auto_data = (
        "https://huggingface.co/datasets/osunlp/AutoSDT-5K/resolve/"
        f"{AUTOSDT_DATASET_REVISION}/AutoSDT_5k_with_license.json"
    )
    sab_base = (
        "https://huggingface.co/datasets/osunlp/ScienceAgentBench/resolve/"
        f"{SCIENCE_AGENT_BENCH_DATASET_REVISION}"
    )
    core_base = (
        "https://huggingface.co/datasets/siegelz/core-bench/resolve/"
        f"{CORE_BENCH_DATASET_REVISION}"
    )
    qr_base = (
        "https://raw.githubusercontent.com/xxxiaol/QRData/"
        f"{QRDATA_REPOSITORY_REVISION}"
    )
    return {
        ReplacementCandidateId.AUTOSDT_5K: (
            _ArtifactSpec(
                role="dataset-json",
                url=auto_data,
                revision=AUTOSDT_DATASET_REVISION,
                expected_sha256=(
                    "b98ff415f0cf1827546359b5bf850e6097a8b63baf2bd27909cbf87a85fa4d88"
                ),
                expected_bytes=61_366_662,
                outcome_bearing=True,
            ),
            _ArtifactSpec(
                role="repository-readme",
                url=(
                    "https://raw.githubusercontent.com/OSU-NLP-Group/AutoSDT/"
                    f"{AUTOSDT_REPOSITORY_REVISION}/README.md"
                ),
                revision=AUTOSDT_REPOSITORY_REVISION,
                expected_sha256=(
                    "2847b68d35111787371a6ddcc5a46be2029bbdce9c4947a9a04c6670e7327f3a"
                ),
                expected_bytes=8_417,
                outcome_bearing=False,
            ),
            _ArtifactSpec(
                role="repository-license",
                url=(
                    "https://raw.githubusercontent.com/OSU-NLP-Group/AutoSDT/"
                    f"{AUTOSDT_REPOSITORY_REVISION}/LICENSE"
                ),
                revision=AUTOSDT_REPOSITORY_REVISION,
                expected_sha256=(
                    "93b43d692b033b76129504448695bfe76ef22d18b11e51352bfab4b5622e5aaa"
                ),
                expected_bytes=1_088,
                outcome_bearing=False,
            ),
        ),
        ReplacementCandidateId.SCIENCE_AGENT_BENCH: (
            _ArtifactSpec(
                role="annotation-csv",
                url=f"{sab_base}/ScienceAgentBench.csv",
                revision=SCIENCE_AGENT_BENCH_DATASET_REVISION,
                expected_sha256=(
                    "7f490f17f721a9c7e9415d3608a1a37d1a5315a26862cf556e3096ac4062face"
                ),
                expected_bytes=278_626,
                outcome_bearing=False,
            ),
            _ArtifactSpec(
                role="verified-parquet",
                url=f"{sab_base}/data/verified-00000-of-00001.parquet",
                revision=SCIENCE_AGENT_BENCH_DATASET_REVISION,
                expected_sha256=(
                    "c6f937863a220bd1762a00c20a0f79cc8dfca900b819bdb552150310731ae147"
                ),
                expected_bytes=129_086,
                outcome_bearing=False,
            ),
            _ArtifactSpec(
                role="repository-readme",
                url=(
                    "https://raw.githubusercontent.com/OSU-NLP-Group/"
                    "ScienceAgentBench/"
                    f"{SCIENCE_AGENT_BENCH_REPOSITORY_REVISION}/README.md"
                ),
                revision=SCIENCE_AGENT_BENCH_REPOSITORY_REVISION,
                expected_sha256=(
                    "0696fe4ffa234ea30346901d9d61263d20d548e58810049c873b2049ac1a04b1"
                ),
                expected_bytes=12_039,
                outcome_bearing=False,
            ),
            _ArtifactSpec(
                role="repository-license",
                url=(
                    "https://raw.githubusercontent.com/OSU-NLP-Group/"
                    "ScienceAgentBench/"
                    f"{SCIENCE_AGENT_BENCH_REPOSITORY_REVISION}/LICENSE"
                ),
                revision=SCIENCE_AGENT_BENCH_REPOSITORY_REVISION,
                expected_sha256=(
                    "93b43d692b033b76129504448695bfe76ef22d18b11e51352bfab4b5622e5aaa"
                ),
                expected_bytes=1_088,
                outcome_bearing=False,
            ),
        ),
        ReplacementCandidateId.CORE_BENCH: (
            _ArtifactSpec(
                role="train-json",
                url=f"{core_base}/core_train.json",
                revision=CORE_BENCH_DATASET_REVISION,
                expected_sha256=(
                    "3df47f1b3fa1cb60045018eb1a0f1ad4ecf6a53f72318c845a879ce0313b0730"
                ),
                expected_bytes=54_907,
                outcome_bearing=True,
            ),
            _ArtifactSpec(
                role="encrypted-test-json",
                url=f"{core_base}/core_test.json.gpg",
                revision=CORE_BENCH_DATASET_REVISION,
                expected_sha256=(
                    "cebf204bc8fd0b2e1b6e65ab762b7edbf906313ff3718780492633aeb4d972f2"
                ),
                expected_bytes=8_615,
                outcome_bearing=True,
            ),
            _ArtifactSpec(
                role="repository-readme",
                url=(
                    "https://raw.githubusercontent.com/siegelz/core-bench/"
                    f"{CORE_BENCH_REPOSITORY_REVISION}/README.md"
                ),
                revision=CORE_BENCH_REPOSITORY_REVISION,
                expected_sha256=(
                    "8c0f6086d0aad6871b516e441ad28f0428991779446cc2370f91bfe4ecef73ba"
                ),
                expected_bytes=10_603,
                outcome_bearing=False,
            ),
            _ArtifactSpec(
                role="repository-license",
                url=(
                    "https://raw.githubusercontent.com/siegelz/core-bench/"
                    f"{CORE_BENCH_REPOSITORY_REVISION}/LICENSE"
                ),
                revision=CORE_BENCH_REPOSITORY_REVISION,
                expected_sha256=(
                    "fa800fc3033ad315e2bf2949afca5c6bcb9f19ad6331d1db996e7dfca1e0eeb8"
                ),
                expected_bytes=1_071,
                outcome_bearing=False,
            ),
        ),
        ReplacementCandidateId.QRDATA: (
            _ArtifactSpec(
                role="questions-json",
                url=f"{qr_base}/benchmark/QRData.json",
                revision=QRDATA_REPOSITORY_REVISION,
                expected_sha256=(
                    "e076d960f19434adf728aab70480ce34808c06066fcea48eaa38b145d1a111a1"
                ),
                expected_bytes=465_740,
                outcome_bearing=True,
            ),
            _ArtifactSpec(
                role="data-zip",
                url=f"{qr_base}/benchmark/data.zip",
                revision=QRDATA_REPOSITORY_REVISION,
                expected_sha256=(
                    "3c3a97cca6fdd96f6856f7856b5f8bc786a31d1a9be78c9f610ef3070783e970"
                ),
                expected_bytes=20_589_968,
                outcome_bearing=False,
            ),
            _ArtifactSpec(
                role="evaluator",
                url=f"{qr_base}/benchmark/eval.py",
                revision=QRDATA_REPOSITORY_REVISION,
                expected_sha256=(
                    "d6e5c1f7535ac9413951996c15544beb6f184244acb2da56e1fcd0942837e33d"
                ),
                expected_bytes=1_652,
                outcome_bearing=False,
            ),
            _ArtifactSpec(
                role="repository-readme",
                url=f"{qr_base}/README.md",
                revision=QRDATA_REPOSITORY_REVISION,
                expected_sha256=(
                    "06502fa2794f620549413a90947ff08dcde2ee458128bec42a0ee5d05e135817"
                ),
                expected_bytes=1_803,
                outcome_bearing=False,
            ),
            _ArtifactSpec(
                role="repository-license",
                url=f"{qr_base}/LICENSE",
                revision=QRDATA_REPOSITORY_REVISION,
                expected_sha256=(
                    "176fdd712458a69435102791f06cf14bc66f86089351415c9df9c3c263798631"
                ),
                expected_bytes=17_689,
                outcome_bearing=False,
            ),
        ),
    }


def _get_json(
    session: requests.Session,
    url: str,
    *,
    timeout_seconds: float,
) -> Mapping[str, Any]:
    response = session.get(url, timeout=timeout_seconds)
    response.raise_for_status()
    value = response.json()
    if not isinstance(value, dict):
        raise ValueError(f"official metadata is not an object: {url}")
    return value


def _fetch_exact_artifact(
    session: requests.Session,
    spec: _ArtifactSpec,
    *,
    timeout_seconds: float,
) -> bytes:
    response = session.get(spec.url, timeout=timeout_seconds)
    response.raise_for_status()
    raw = response.content
    observed_sha = hashlib.sha256(raw).hexdigest()
    if len(raw) != spec.expected_bytes or observed_sha != spec.expected_sha256:
        raise PortfolioIntegrityError(
            f"official artifact changed at frozen revision: {spec.role}"
        )
    return raw


def fetch_replacement_candidate_materials(
    *,
    session: requests.Session,
    timeout_seconds: float = 300,
) -> dict[ReplacementCandidateId, OfficialCandidateMaterial]:
    """Fetch exact official resources without calling a candidate model."""

    metadata_specs = {
        ReplacementCandidateId.AUTOSDT_5K: (
            f"https://huggingface.co/api/datasets/{AUTOSDT_DATASET_ID}",
            AUTOSDT_DATASET_REVISION,
            AUTOSDT_REPOSITORY_REVISION,
        ),
        ReplacementCandidateId.SCIENCE_AGENT_BENCH: (
            "https://huggingface.co/api/datasets/"
            f"{SCIENCE_AGENT_BENCH_DATASET_ID}",
            SCIENCE_AGENT_BENCH_DATASET_REVISION,
            SCIENCE_AGENT_BENCH_REPOSITORY_REVISION,
        ),
        ReplacementCandidateId.CORE_BENCH: (
            f"https://huggingface.co/api/datasets/{CORE_BENCH_DATASET_ID}",
            CORE_BENCH_DATASET_REVISION,
            CORE_BENCH_REPOSITORY_REVISION,
        ),
    }
    metadata_by_candidate: dict[
        ReplacementCandidateId, tuple[str, str, str]
    ] = {}
    for candidate_id, (url, expected_revision, repository_revision) in (
        metadata_specs.items()
    ):
        metadata = _get_json(session, url, timeout_seconds=timeout_seconds)
        if metadata.get("sha") != expected_revision:
            raise PortfolioIntegrityError(
                f"{candidate_id.value} dataset head changed; explicit re-audit required"
            )
        metadata_by_candidate[candidate_id] = (
            repository_revision,
            expected_revision,
            str(metadata.get("lastModified", "")),
        )
    metadata_by_candidate[ReplacementCandidateId.QRDATA] = (
        QRDATA_REPOSITORY_REVISION,
        QRDATA_REPOSITORY_REVISION,
        "2025-02-18T04:38:57Z",
    )

    materials: dict[ReplacementCandidateId, OfficialCandidateMaterial] = {}
    for candidate_id, specs in _artifact_specs().items():
        raw_by_role = {
            spec.role: _fetch_exact_artifact(
                session, spec, timeout_seconds=timeout_seconds
            )
            for spec in specs
        }
        repository_revision, dataset_revision, last_modified = (
            metadata_by_candidate[candidate_id]
        )
        if not last_modified:
            raise ValueError(f"{candidate_id.value} lastModified is missing")
        materials[candidate_id] = OfficialCandidateMaterial(
            candidate_id=candidate_id,
            repository_revision=repository_revision,
            dataset_revision=dataset_revision,
            last_modified=last_modified,
            artifact_specs=specs,
            raw_by_role=raw_by_role,
        )
    return materials


def _artifact_hash(snapshot: CandidateResourceSnapshot, role: str) -> str:
    matches = [item.artifact_hash for item in snapshot.artifacts if item.role == role]
    if len(matches) != 1:
        raise ValueError(f"resource snapshot lacks unique role: {role}")
    return matches[0]


def _scope(
    *,
    scope: RightsScope,
    status: RightsStatus,
    covered: int,
    required: int,
    license_ids: list[str],
    evidence_hashes: list[str],
    interpretation: str,
) -> RightsScopeDecision:
    return RightsScopeDecision(
        scope=scope,
        status=status,
        covered_group_count=covered,
        required_group_count=required,
        license_ids=license_ids,
        evidence_hashes=evidence_hashes,
        interpretation=interpretation,
    )


def _build_autosdt_audit(
    material: OfficialCandidateMaterial,
) -> ReplacementCandidateAudit:
    snapshot = material.snapshot()
    parsed = parse_autosdt_lineage(
        material.raw_by_role["dataset-json"],
        expected_task_count=5_148,
    )
    inventory = parsed.inventory
    if len(inventory.source_group_ids) != 1_317:
        raise ValueError("AutoSDT repository grouping changed")
    license_counts = Counter(parsed.group_license_labels.values())
    if license_counts["None"] != 315:
        raise ValueError("AutoSDT no-license repository count changed")
    declared_groups = sorted(
        group_id
        for group_id, label in parsed.group_license_labels.items()
        if label != "None"
    )
    if len(declared_groups) != 1_002:
        raise ValueError("AutoSDT declared-license group count changed")
    dataset_hash = _artifact_hash(snapshot, "dataset-json")
    repository_license_hash = _artifact_hash(snapshot, "repository-license")
    license_audit = CandidateLicenseAudit.create(
        candidate_id=ReplacementCandidateId.AUTOSDT_5K,
        required_group_count=len(declared_groups),
        declared_license_group_counts=dict(sorted(license_counts.items())),
        exact_source_license_object_group_count=0,
        missing_or_unbound_group_count=len(inventory.source_group_ids),
        scopes=[
            _scope(
                scope=RightsScope.LOCAL_EXECUTION,
                status=RightsStatus.PARTIAL,
                covered=0,
                required=len(declared_groups),
                license_ids=["mixed-coarse-labels"],
                evidence_hashes=[dataset_hash],
                interpretation=(
                    "The dataset records one coarse license label per repository, "
                    "but does not pin upstream license files or package task data and "
                    "dependencies for complete local execution."
                ),
            ),
            _scope(
                scope=RightsScope.SOFTWARE_REUSE,
                status=RightsStatus.BLOCKED,
                covered=0,
                required=len(declared_groups),
                license_ids=["MIT-harness-only"],
                evidence_hashes=[repository_license_hash],
                interpretation=(
                    "The AutoSDT repository MIT file licenses its pipeline, not all "
                    "source programs represented by the training rows."
                ),
            ),
            _scope(
                scope=RightsScope.DERIVATIVE_CREATION,
                status=RightsStatus.BLOCKED,
                covered=0,
                required=len(declared_groups),
                license_ids=["unresolved-per-source"],
                evidence_hashes=[dataset_hash],
                interpretation=(
                    "Generic GNU, BSD, CC, Custom, and other labels do not identify "
                    "the exact upstream terms or attribution obligations."
                ),
            ),
            _scope(
                scope=RightsScope.CONTENT_REDISTRIBUTION,
                status=RightsStatus.BLOCKED,
                covered=0,
                required=len(declared_groups),
                license_ids=["unresolved-per-source"],
                evidence_hashes=[dataset_hash],
                interpretation=(
                    "Academic-use assumptions and public repository visibility are "
                    "not redistribution permission."
                ),
            ),
        ],
        gate_passed=False,
        blockers=[
            "coarse-license-labels-not-license-objects",
            "source-revisions-not-pinned",
            "no-license-groups-excluded",
        ],
    )
    endpoint = CandidateEndpointAudit.create(
        candidate_id=ReplacementCandidateId.AUTOSDT_5K,
        construct_kind=CandidateConstruct.SCIENTIFIC_CODING_TRAINING,
        endpoint_kind=EndpointKind.REFERENCE_PROGRAM_CORPUS,
        deterministic=False,
        executable=False,
        llm_or_post_result_human_primary=False,
        best_of_attempts_primary=False,
        packaged_executable_scorer=False,
        construct_coherent=True,
        gate_passed=False,
        evidence_artifact_hashes=[dataset_hash],
        interpretation=(
            "Rows contain synthesized reference programs for training, but no "
            "frozen per-task data capsule, test program, or deterministic success "
            "threshold. Expert review of a subset is not an executable endpoint."
        ),
    )
    baseline = StrongBaselineAvailabilityAudit.create(
        candidate_id=ReplacementCandidateId.AUTOSDT_5K,
        published_comparison_available=True,
        official_baseline_code_available=False,
        exact_reproduction_command_available=False,
        gate_passed=False,
        interpretation=(
            "Published downstream ScienceAgentBench/DiscoveryBench comparisons do "
            "not supply a strong baseline for scoring AutoSDT rows themselves."
        ),
    )
    downloaded = sum(len(value) for value in material.raw_by_role.values())
    compute = CandidateComputeAudit.create(
        candidate_id=ReplacementCandidateId.AUTOSDT_5K,
        audited_download_bytes=downloaded,
        audited_expanded_bytes=downloaded,
        docker_required=False,
        privileged_container_required=False,
        gpu_tasks_present=True,
        mutable_external_service_required=True,
        bounded_local_execution=False,
        interpretation=(
            "The 61 MB corpus is locally downloadable, but source tasks span 756 "
            "packages and do not include a frozen executable task workspace or "
            "bounded evaluator workload."
        ),
    )
    replay = CandidateReplayInput(
        candidate_id=ReplacementCandidateId.AUTOSDT_5K.value,
        task_count=inventory.task_count,
        capacity_group_ids=declared_groups,
        declared_unlineaged_group_upper_bound=0,
        development_group_capacity=30,
        potential_reserve_group_capacity=len(declared_groups) - 30,
        sealed_reserve_group_capacity=0,
        gates=ReplacementGateVector(
            revision=True,
            lineage=False,
            license=False,
            objective_endpoint=False,
            construct_coherence=True,
            strong_baseline=False,
            bounded_local_compute=False,
            reserve_seal=False,
        ),
    )
    return ReplacementCandidateAudit.create(
        candidate_id=ReplacementCandidateId.AUTOSDT_5K,
        resource_snapshot=snapshot,
        lineage=inventory,
        license_audit=license_audit,
        endpoint_audit=endpoint,
        baseline_audit=baseline,
        compute_audit=compute,
        replay_input=replay,
        notes=[
            "The frozen file contains 5,148 rows and 1,317 normalized repositories.",
            (
                "The card claims 5,404 tasks, 1,325 repositories, and 317 "
                "no-license repositories; the frozen released file contains "
                "5,148, 1,317, and 315 respectively."
            ),
            "Reference programs are public in the same corpus, so no reserve is sealed.",
        ],
    )


def _build_scienceagentbench_audit(
    material: OfficialCandidateMaterial,
) -> ReplacementCandidateAudit:
    snapshot = material.snapshot()
    parsed = parse_scienceagentbench_lineage(
        material.raw_by_role["annotation-csv"],
        declared_publication_count=44,
        expected_task_count=102,
    )
    inventory = parsed.inventory
    if len(inventory.source_group_ids) != 30:
        raise ValueError("ScienceAgentBench repository grouping changed")
    required = len(inventory.source_group_ids)
    readme_hash = _artifact_hash(snapshot, "repository-readme")
    license_hash = _artifact_hash(snapshot, "repository-license")
    license_audit = CandidateLicenseAudit.create(
        candidate_id=ReplacementCandidateId.SCIENCE_AGENT_BENCH,
        required_group_count=required,
        declared_license_group_counts={
            "CC-BY-4.0-claimed-tasks": 96,
            "upstream-special-license-tasks": 6,
        },
        exact_source_license_object_group_count=0,
        missing_or_unbound_group_count=required,
        scopes=[
            _scope(
                scope=RightsScope.LOCAL_EXECUTION,
                status=RightsStatus.PARTIAL,
                covered=0,
                required=required,
                license_ids=["CC-BY-4.0-claimed", "special-upstream"],
                evidence_hashes=[readme_hash],
                interpretation=(
                    "The authors support research execution, but the annotation "
                    "sheet has no per-task license field and two upstream projects "
                    "are handled through a research-use belief rather than a bound "
                    "license object."
                ),
            ),
            _scope(
                scope=RightsScope.SOFTWARE_REUSE,
                status=RightsStatus.PARTIAL,
                covered=0,
                required=required,
                license_ids=["MIT-harness"],
                evidence_hashes=[license_hash],
                interpretation=(
                    "MIT covers the harness code; it does not replace the terms of "
                    "the adapted source code and task data."
                ),
            ),
            _scope(
                scope=RightsScope.DERIVATIVE_CREATION,
                status=RightsStatus.PARTIAL,
                covered=0,
                required=required,
                license_ids=["CC-BY-4.0-claimed", "special-upstream"],
                evidence_hashes=[readme_hash],
                interpretation=(
                    "Most benchmark tasks are claimed CC-BY-4.0, while six retain "
                    "upstream terms that are not bound into the machine-readable CSV."
                ),
            ),
            _scope(
                scope=RightsScope.CONTENT_REDISTRIBUTION,
                status=RightsStatus.BLOCKED,
                covered=0,
                required=required,
                license_ids=["do-not-redistribute-unzipped-data"],
                evidence_hashes=[readme_hash],
                interpretation=(
                    "The official instructions explicitly ask users not to "
                    "redistribute the unzipped benchmark data."
                ),
            ),
        ],
        gate_passed=False,
        blockers=[
            "full-artifact-redistribution-prohibited",
            "machine-readable-per-task-license-binding-absent",
            "special-upstream-rights-unresolved",
        ],
    )
    endpoint = CandidateEndpointAudit.create(
        candidate_id=ReplacementCandidateId.SCIENCE_AGENT_BENCH,
        construct_kind=CandidateConstruct.SCIENTIFIC_PROGRAM_SYNTHESIS,
        endpoint_kind=EndpointKind.MIXED_EXECUTION_AND_LLM_VISUAL_JUDGE,
        deterministic=False,
        executable=True,
        llm_or_post_result_human_primary=True,
        best_of_attempts_primary=True,
        packaged_executable_scorer=True,
        construct_coherent=True,
        gate_passed=False,
        evidence_artifact_hashes=[readme_hash],
        interpretation=(
            "Task-specific programs execute, but the documented evaluation uses "
            "GPT-4o for visual outputs and reports the best trajectory across three "
            "attempts. Those mechanisms may be secondary, not the frozen primary "
            "endpoint required here."
        ),
    )
    baseline = StrongBaselineAvailabilityAudit.create(
        candidate_id=ReplacementCandidateId.SCIENCE_AGENT_BENCH,
        published_comparison_available=True,
        official_baseline_code_available=True,
        exact_reproduction_command_available=True,
        gate_passed=True,
        interpretation=(
            "The official repository provides direct/self-debug agent commands, "
            "containerized evaluation, metrics, and published baseline comparisons."
        ),
    )
    downloaded = sum(len(value) for value in material.raw_by_role.values())
    compute = CandidateComputeAudit.create(
        candidate_id=ReplacementCandidateId.SCIENCE_AGENT_BENCH,
        audited_download_bytes=downloaded,
        audited_expanded_bytes=downloaded,
        docker_required=True,
        privileged_container_required=False,
        gpu_tasks_present=False,
        mutable_external_service_required=True,
        bounded_local_execution=False,
        interpretation=(
            "The authors report a 102-task evaluator pass in about 30 minutes with "
            "eight threads, but the full mutable SharePoint artifact, dynamic "
            "per-task dependencies, and GPT-4o visual judge prevent a fully bounded "
            "local primary endpoint."
        ),
    )
    replay = CandidateReplayInput(
        candidate_id=ReplacementCandidateId.SCIENCE_AGENT_BENCH.value,
        task_count=inventory.task_count,
        capacity_group_ids=inventory.source_group_ids,
        declared_unlineaged_group_upper_bound=14,
        development_group_capacity=30,
        potential_reserve_group_capacity=14,
        sealed_reserve_group_capacity=0,
        gates=ReplacementGateVector(
            revision=True,
            lineage=False,
            license=False,
            objective_endpoint=False,
            construct_coherence=True,
            strong_baseline=True,
            bounded_local_compute=False,
            reserve_seal=False,
        ),
    )
    return ReplacementCandidateAudit.create(
        candidate_id=ReplacementCandidateId.SCIENCE_AGENT_BENCH,
        resource_snapshot=snapshot,
        lineage=inventory,
        license_audit=license_audit,
        endpoint_audit=endpoint,
        baseline_audit=baseline,
        compute_audit=compute,
        replay_input=replay,
        notes=[
            "The verified split has 102 tasks but only 30 repository groups.",
            "The paper's 44-publication count is an optimistic independent-unit upper bound.",
            "Publication IDs are not present per row in the official annotation sheet.",
        ],
    )


def _build_core_bench_audit(
    material: OfficialCandidateMaterial,
) -> ReplacementCandidateAudit:
    snapshot = material.snapshot()
    parsed = parse_core_bench_lineage(
        material.raw_by_role["train-json"],
        declared_total_papers=90,
        expected_train_papers=45,
    )
    inventory = parsed.inventory
    required = 90
    readme_hash = _artifact_hash(snapshot, "repository-readme")
    license_hash = _artifact_hash(snapshot, "repository-license")
    license_audit = CandidateLicenseAudit.create(
        candidate_id=ReplacementCandidateId.CORE_BENCH,
        required_group_count=required,
        declared_license_group_counts={
            "capsule-license-unbound": 90,
            "MIT-harness-repository": 1,
        },
        exact_source_license_object_group_count=0,
        missing_or_unbound_group_count=90,
        scopes=[
            _scope(
                scope=RightsScope.LOCAL_EXECUTION,
                status=RightsStatus.PARTIAL,
                covered=0,
                required=required,
                license_ids=["Code-Ocean-capsule-unbound"],
                evidence_hashes=[readme_hash],
                interpretation=(
                    "The harness downloads paper capsules, but the task manifest "
                    "does not bind a license object for each capsule."
                ),
            ),
            _scope(
                scope=RightsScope.SOFTWARE_REUSE,
                status=RightsStatus.PARTIAL,
                covered=0,
                required=required,
                license_ids=["MIT-harness"],
                evidence_hashes=[license_hash],
                interpretation=(
                    "MIT covers CORE-Bench harness software, not the 90 paper "
                    "capsules and their data."
                ),
            ),
            _scope(
                scope=RightsScope.DERIVATIVE_CREATION,
                status=RightsStatus.BLOCKED,
                covered=0,
                required=required,
                license_ids=["capsule-license-unbound"],
                evidence_hashes=[readme_hash],
                interpretation="No per-capsule derivative-use evidence is bound.",
            ),
            _scope(
                scope=RightsScope.CONTENT_REDISTRIBUTION,
                status=RightsStatus.BLOCKED,
                covered=0,
                required=required,
                license_ids=["capsule-license-unbound"],
                evidence_hashes=[readme_hash],
                interpretation=(
                    "The benchmark server hosts capsules, but server availability "
                    "does not establish redistribution rights."
                ),
            ),
        ],
        gate_passed=False,
        blockers=[
            "capsule-license-manifest-absent",
            "harness-license-does-not-cover-capsules",
        ],
    )
    endpoint = CandidateEndpointAudit.create(
        candidate_id=ReplacementCandidateId.CORE_BENCH,
        construct_kind=CandidateConstruct.COMPUTATIONAL_REPRODUCIBILITY,
        endpoint_kind=EndpointKind.DETERMINISTIC_REPRODUCTION_QA,
        deterministic=True,
        executable=True,
        llm_or_post_result_human_primary=False,
        best_of_attempts_primary=False,
        packaged_executable_scorer=True,
        construct_coherent=True,
        gate_passed=True,
        evidence_artifact_hashes=[readme_hash],
        interpretation=(
            "An agent executes a paper capsule and submits a structured report "
            "scored against successful reproduction results. Easy/medium/hard "
            "questions are technical variants of one paper, not independent units."
        ),
    )
    baseline = StrongBaselineAvailabilityAudit.create(
        candidate_id=ReplacementCandidateId.CORE_BENCH,
        published_comparison_available=True,
        official_baseline_code_available=True,
        exact_reproduction_command_available=True,
        gate_passed=True,
        interpretation=(
            "The official repository includes CORE-Agent/AutoGPT baselines and a "
            "reproduce_results command path, although the harness is now superseded."
        ),
    )
    downloaded = sum(len(value) for value in material.raw_by_role.values())
    compute = CandidateComputeAudit.create(
        candidate_id=ReplacementCandidateId.CORE_BENCH,
        audited_download_bytes=downloaded,
        audited_expanded_bytes=downloaded,
        docker_required=True,
        privileged_container_required=True,
        gpu_tasks_present=True,
        mutable_external_service_required=True,
        bounded_local_execution=False,
        interpretation=(
            "The local harness uses privileged Docker-in-Docker for medium tasks, "
            "contains GPU tasks, and otherwise recommends Azure VMs; full paper "
            "capsule execution is not a bounded local workload here."
        ),
    )
    replay = CandidateReplayInput(
        candidate_id=ReplacementCandidateId.CORE_BENCH.value,
        task_count=inventory.task_count,
        capacity_group_ids=inventory.source_group_ids,
        declared_unlineaged_group_upper_bound=45,
        development_group_capacity=45,
        potential_reserve_group_capacity=45,
        sealed_reserve_group_capacity=45,
        gates=ReplacementGateVector(
            revision=True,
            lineage=False,
            license=False,
            objective_endpoint=True,
            construct_coherence=True,
            strong_baseline=True,
            bounded_local_compute=False,
            reserve_seal=True,
        ),
    )
    return ReplacementCandidateAudit.create(
        candidate_id=ReplacementCandidateId.CORE_BENCH,
        resource_snapshot=snapshot,
        lineage=inventory,
        license_audit=license_audit,
        endpoint_audit=endpoint,
        baseline_audit=baseline,
        compute_audit=compute,
        replay_input=replay,
        notes=[
            "The 270 advertised tasks are three difficulty variants of 90 papers.",
            "The clear train file contains 45 paper groups; the encrypted test file remains unread.",
            "A maximum 45-paper reserve is below the frozen requirement of 84.",
        ],
    )


def _build_qrdata_audit(
    material: OfficialCandidateMaterial,
) -> ReplacementCandidateAudit:
    snapshot = material.snapshot()
    parsed = parse_qrdata_lineage(
        material.raw_by_role["questions-json"],
        material.raw_by_role["data-zip"],
        expected_task_count=411,
    )
    inventory = parsed.inventory
    required = len(inventory.source_group_ids)
    if required != 190 or parsed.auxiliary_counts["archive_file_count"] != 195:
        raise ValueError("QRData shared-sheet grouping changed")
    license_hash = _artifact_hash(snapshot, "repository-license")
    evaluator_hash = _artifact_hash(snapshot, "evaluator")
    license_audit = CandidateLicenseAudit.create(
        candidate_id=ReplacementCandidateId.QRDATA,
        required_group_count=required,
        declared_license_group_counts={
            "CC-BY-NC-4.0-global-benchmark": 190,
            "upstream-data-sheet-license-unbound": 190,
        },
        exact_source_license_object_group_count=0,
        missing_or_unbound_group_count=190,
        scopes=[
            _scope(
                scope=RightsScope.LOCAL_EXECUTION,
                status=RightsStatus.VERIFIED,
                covered=required,
                required=required,
                license_ids=["CC-BY-NC-4.0"],
                evidence_hashes=[license_hash],
                interpretation=(
                    "The frozen repository applies CC-BY-NC-4.0 to the benchmark "
                    "package, permitting non-commercial local research use subject "
                    "to its terms."
                ),
            ),
            _scope(
                scope=RightsScope.SOFTWARE_REUSE,
                status=RightsStatus.PARTIAL,
                covered=0,
                required=required,
                license_ids=["CC-BY-NC-4.0-global"],
                evidence_hashes=[license_hash],
                interpretation=(
                    "The global license covers the packaged evaluator, but no "
                    "software-specific or per-source sheet manifest is provided."
                ),
            ),
            _scope(
                scope=RightsScope.DERIVATIVE_CREATION,
                status=RightsStatus.PARTIAL,
                covered=0,
                required=required,
                license_ids=["CC-BY-NC-4.0-global"],
                evidence_hashes=[license_hash],
                interpretation=(
                    "Non-commercial adaptation is stated globally, while upstream "
                    "rights for the 195 data sheets are not listed per source."
                ),
            ),
            _scope(
                scope=RightsScope.CONTENT_REDISTRIBUTION,
                status=RightsStatus.PARTIAL,
                covered=0,
                required=required,
                license_ids=["CC-BY-NC-4.0-global"],
                evidence_hashes=[license_hash],
                interpretation=(
                    "The repository license permits non-commercial sharing with "
                    "attribution, but the licensor's authority over every upstream "
                    "textbook, course, and paper data sheet is not evidenced."
                ),
            ),
        ],
        gate_passed=False,
        blockers=[
            "per-source-upstream-license-manifest-absent",
            "redistribution-authority-not-evidenced-per-sheet",
        ],
    )
    endpoint = CandidateEndpointAudit.create(
        candidate_id=ReplacementCandidateId.QRDATA,
        construct_kind=CandidateConstruct.STATISTICAL_CAUSAL_REASONING,
        endpoint_kind=EndpointKind.DETERMINISTIC_NUMERIC_AND_MULTIPLE_CHOICE,
        deterministic=True,
        executable=True,
        llm_or_post_result_human_primary=False,
        best_of_attempts_primary=False,
        packaged_executable_scorer=True,
        construct_coherent=True,
        gate_passed=True,
        evidence_artifact_hashes=[evaluator_hash],
        interpretation=(
            "The official evaluator deterministically scores numerical answers "
            "within a 3% relative band and multiple-choice prefixes. Questions that "
            "share a data-file set are one independent source group."
        ),
    )
    baseline = StrongBaselineAvailabilityAudit.create(
        candidate_id=ReplacementCandidateId.QRDATA,
        published_comparison_available=True,
        official_baseline_code_available=False,
        exact_reproduction_command_available=False,
        gate_passed=False,
        interpretation=(
            "The paper reports CoT, program-of-thought, ReAct, and code-interpreter "
            "comparisons, but the official repository contains only benchmark data "
            "and the scorer, not an exact baseline inference implementation."
        ),
    )
    downloaded = sum(len(value) for value in material.raw_by_role.values())
    expanded = int(parsed.auxiliary_counts["archive_expanded_bytes"])
    compute = CandidateComputeAudit.create(
        candidate_id=ReplacementCandidateId.QRDATA,
        audited_download_bytes=downloaded,
        audited_expanded_bytes=expanded,
        docker_required=False,
        privileged_container_required=False,
        gpu_tasks_present=False,
        mutable_external_service_required=False,
        bounded_local_execution=True,
        interpretation=(
            "The frozen package is about 20.6 MB compressed and 312.6 MB expanded; "
            "lineage and deterministic scoring are bounded local CPU work."
        ),
    )
    replay = CandidateReplayInput(
        candidate_id=ReplacementCandidateId.QRDATA.value,
        task_count=inventory.task_count,
        capacity_group_ids=inventory.source_group_ids,
        declared_unlineaged_group_upper_bound=0,
        development_group_capacity=30,
        potential_reserve_group_capacity=required - 30,
        sealed_reserve_group_capacity=0,
        gates=ReplacementGateVector(
            revision=True,
            lineage=True,
            license=False,
            objective_endpoint=True,
            construct_coherence=True,
            strong_baseline=False,
            bounded_local_compute=True,
            reserve_seal=False,
        ),
    )
    return ReplacementCandidateAudit.create(
        candidate_id=ReplacementCandidateId.QRDATA,
        resource_snapshot=snapshot,
        lineage=inventory,
        license_audit=license_audit,
        endpoint_audit=endpoint,
        baseline_audit=baseline,
        compute_audit=compute,
        replay_input=replay,
        notes=[
            "411 questions collapse to 190 unique shared data-file-set groups.",
            "The archive contains exactly 195 referenced files and no extras.",
            "Answers are co-located with lineage metadata, so the current release is not a sealed reserve.",
        ],
    )


def build_official_candidate_audits(
    materials: Mapping[ReplacementCandidateId, OfficialCandidateMaterial],
) -> list[ReplacementCandidateAudit]:
    """Build all four mandatory audits without a model or result-dependent choice."""

    if set(materials) != set(ReplacementCandidateId):
        raise ValueError("all four mandatory candidate materials are required")
    audits = [
        _build_autosdt_audit(materials[ReplacementCandidateId.AUTOSDT_5K]),
        _build_scienceagentbench_audit(
            materials[ReplacementCandidateId.SCIENCE_AGENT_BENCH]
        ),
        _build_core_bench_audit(materials[ReplacementCandidateId.CORE_BENCH]),
        _build_qrdata_audit(materials[ReplacementCandidateId.QRDATA]),
    ]
    return sorted(audits, key=lambda item: item.candidate_id.value)


_GATE_BLOCKERS = {
    "revision": "official-revisions-not-fully-frozen",
    "lineage": "independent-source-lineage-incomplete",
    "license": "per-source-license-gate-failed",
    "objective_endpoint": "deterministic-primary-endpoint-gate-failed",
    "construct_coherence": "construct-coherence-gate-failed",
    "strong_baseline": "strong-baseline-unavailable",
    "bounded_local_compute": "bounded-local-compute-gate-failed",
    "reserve_seal": "reserve-seal-gate-failed",
}


def _candidate_projection(
    candidate: CandidateReplayInput,
) -> ReplacementCandidateProjection:
    gate_values = candidate.gates.model_dump(mode="python")
    blockers = [
        _GATE_BLOCKERS[name]
        for name, passed in gate_values.items()
        if not passed
    ]
    if candidate.development_group_capacity < REQUIRED_DEVELOPMENT_GROUPS:
        blockers.append("development-source-groups-below-required")
    if candidate.potential_reserve_group_capacity < REQUIRED_RESERVE_GROUPS:
        blockers.append("potential-reserve-source-groups-below-required")
    if candidate.sealed_reserve_group_capacity < REQUIRED_RESERVE_GROUPS:
        blockers.append("sealed-reserve-source-groups-below-required")
    blockers = sorted(set(blockers))
    payload = {
        "schema_version": "replacement-candidate-projection-v1",
        "candidate_id": candidate.candidate_id,
        "task_count": candidate.task_count,
        "lineaged_capacity_group_count": len(candidate.capacity_group_ids),
        "declared_unlineaged_group_upper_bound": (
            candidate.declared_unlineaged_group_upper_bound
        ),
        "independent_group_upper_bound": (
            len(candidate.capacity_group_ids)
            + candidate.declared_unlineaged_group_upper_bound
        ),
        "development_group_capacity": candidate.development_group_capacity,
        "potential_reserve_group_capacity": (
            candidate.potential_reserve_group_capacity
        ),
        "sealed_reserve_group_capacity": candidate.sealed_reserve_group_capacity,
        "required_development_groups": REQUIRED_DEVELOPMENT_GROUPS,
        "required_reserve_groups": REQUIRED_RESERVE_GROUPS,
        "passed_gate_count": sum(bool(value) for value in gate_values.values()),
        "gates": candidate.gates.model_dump(mode="json"),
        "blockers": blockers,
        "eligible": not blockers,
    }
    payload["projection_sha256"] = canonical_sha256(payload)
    return ReplacementCandidateProjection.model_validate(payload)


def project_replacement_tournament(
    replay_payload: Mapping[str, Any],
) -> ReplacementTournamentProjection:
    """Apply the non-hardcoded conjunctive policy locally."""

    if replay_payload.get("schema_version") != (
        "replacement-objective-data-replay-input-v1"
    ):
        raise ValueError("unsupported replacement replay schema")
    if replay_payload.get("outcome_values_included") is not False:
        raise ValueError("outcome values must be excluded")
    if replay_payload.get("candidate_model_calls_run") is not False:
        raise ValueError("candidate model calls must remain false")
    if (
        replay_payload.get("heterogeneous_post_result_combination_allowed")
        is not False
    ):
        raise ValueError("post-result benchmark combination must remain false")
    if replay_payload.get("required_development_groups") != (
        REQUIRED_DEVELOPMENT_GROUPS
    ) or replay_payload.get("required_reserve_groups") != REQUIRED_RESERVE_GROUPS:
        raise ValueError("replacement capacity thresholds changed")
    raw_candidates = replay_payload.get("candidates")
    if not isinstance(raw_candidates, list) or len(raw_candidates) < 4:
        raise ValueError("at least four candidate panels are required")
    candidates = [
        CandidateReplayInput.model_validate(item) for item in raw_candidates
    ]
    if len({item.candidate_id for item in candidates}) != len(candidates):
        raise ValueError("candidate identifiers must be unique")
    projections = [_candidate_projection(item) for item in candidates]
    ranked = sorted(
        projections,
        key=lambda item: (
            -int(item.eligible),
            -item.passed_gate_count,
            -item.sealed_reserve_group_capacity,
            -item.development_group_capacity,
            item.candidate_id,
        ),
    )
    eligible = [item.candidate_id for item in ranked if item.eligible]
    selected = eligible[0] if eligible else None
    decision_payload = {
        "schema_version": "replacement-tournament-decision-v1",
        "status": (
            ReplacementTournamentStatus.CANDIDATE_QUALIFIED_FOR_BASELINE_REPRODUCTION.value
            if selected is not None
            else ReplacementTournamentStatus.ALL_CANDIDATES_REJECTED.value
        ),
        "selected_candidate_id": selected,
        "eligible_candidate_ids": eligible,
        "ranked_candidate_ids": [item.candidate_id for item in ranked],
        "candidate_projection_hashes": {
            item.candidate_id: item.projection_sha256
            for item in sorted(projections, key=lambda value: value.candidate_id)
        },
        "baseline_reproduction_authorized": selected is not None,
        "evaluator_or_critic_construction_authorized": False,
        "provider_credentials_collected": False,
        "research_question_issued": False,
        "confirmation_panel_created_or_read": False,
        "heterogeneous_post_result_combination_authorized": False,
        "publication_claim_authorized": False,
        "public_release_authorized": False,
        "submission_authorized": False,
        "next_action": (
            "reproduce-qualified-strong-baseline-before-rq"
            if selected is not None
            else "repair-or-broaden-objective-data-before-model-calls"
        ),
    }
    decision_payload["decision_sha256"] = canonical_sha256(decision_payload)
    decision = ReplacementTournamentDecision.model_validate(decision_payload)
    projection_payload = {
        "schema_version": "replacement-tournament-projection-v1",
        "candidate_projections": [
            item.model_dump(mode="json")
            for item in sorted(projections, key=lambda value: value.candidate_id)
        ],
        "decision": decision.model_dump(mode="json"),
    }
    projection_payload["projection_sha256"] = canonical_sha256(projection_payload)
    return ReplacementTournamentProjection.model_validate(projection_payload)


def build_replacement_replay_payload(
    audits: Sequence[ReplacementCandidateAudit],
) -> dict[str, Any]:
    """Build the only scientific input visible to the frozen runner."""

    if len(audits) < 4:
        raise ValueError("at least four candidate audits are required")
    if len({item.candidate_id for item in audits}) != len(audits):
        raise ValueError("candidate audits must be unique")
    return {
        "schema_version": "replacement-objective-data-replay-input-v1",
        "required_development_groups": REQUIRED_DEVELOPMENT_GROUPS,
        "required_reserve_groups": REQUIRED_RESERVE_GROUPS,
        "candidate_model_calls_run": False,
        "outcome_values_included": False,
        "heterogeneous_post_result_combination_allowed": False,
        "candidates": [
            item.replay_input.model_dump(mode="json")
            for item in sorted(audits, key=lambda value: value.candidate_id.value)
        ],
    }


def run_replacement_tournament_replay(
    *,
    replay_payload: Mapping[str, Any],
    input_path: Path,
    runner_path: Path,
    interpreters: Mapping[str, Path],
    expected_projection: ReplacementTournamentProjection,
    observed_at: datetime,
) -> ReplacementReplayCertificate:
    """Execute the result-blind projection in two independent installations."""

    if len(interpreters) < 2:
        raise ValueError("two independent interpreter installations are required")
    input_text = _canonical_json_text(replay_payload)
    _write_text_atomic(input_path, input_text)
    input_sha256 = hashlib.sha256(input_text.encode("utf-8")).hexdigest()
    runner_sha256 = _file_sha256(runner_path)
    runtimes = [
        probe_interpreter_runtime(role_id=role_id, executable=path)
        for role_id, path in sorted(interpreters.items())
    ]
    observations: list[ReplacementReplayObservation] = []
    for runtime in runtimes:
        command = [
            str(interpreters[runtime.role_id]),
            str(runner_path),
            str(input_path),
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            timeout=60,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"replacement replay failed for {runtime.role_id}: "
                f"{completed.stderr.decode('utf-8', errors='replace')[:1000]}"
            )
        try:
            output = json.loads(completed.stdout.decode("utf-8"))
            observed_projection = ReplacementTournamentProjection.model_validate(
                output
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError(
                f"replacement replay output invalid for {runtime.role_id}"
            ) from exc
        if observed_projection.projection_sha256 != (
            expected_projection.projection_sha256
        ):
            raise RuntimeError(
                f"replacement replay projection mismatch for {runtime.role_id}"
            )
        observations.append(
            ReplacementReplayObservation.create(
                role_id=runtime.role_id,
                interpreter_environment_hash=runtime.environment_hash,
                command_hash=canonical_sha256(command),
                input_sha256=input_sha256,
                runner_sha256=runner_sha256,
                stdout_sha256=hashlib.sha256(completed.stdout).hexdigest(),
                stderr_sha256=hashlib.sha256(completed.stderr).hexdigest(),
                projection_sha256=observed_projection.projection_sha256,
                observed_at=observed_at,
            )
        )
    return ReplacementReplayCertificate.create(
        runner_sha256=runner_sha256,
        input_sha256=input_sha256,
        interpreter_runtimes=runtimes,
        observations=observations,
        expected_projection_sha256=expected_projection.projection_sha256,
        exact=True,
    )


def build_replacement_tournament_report(
    *,
    study_id: str,
    created_at: datetime,
    literature_cutoff: date,
    research_questions: list[str],
    intended_reader: str,
    review_angle: str,
    sources: list[ResearchSource],
    nearest_work: list[NearestWorkDelta],
    source_probes: list[LiveResourceProbe],
    candidate_audits: list[ReplacementCandidateAudit],
    replay_certificate: ReplacementReplayCertificate,
) -> ReplacementObjectiveDataTournamentReport:
    replay_payload = build_replacement_replay_payload(candidate_audits)
    projection = project_replacement_tournament(replay_payload)
    if (
        replay_certificate.expected_projection_sha256
        != projection.projection_sha256
    ):
        raise ValueError("frozen replay differs from local tournament projection")
    return ReplacementObjectiveDataTournamentReport.create(
        study_id=study_id,
        created_at=created_at,
        literature_cutoff=literature_cutoff,
        research_questions=research_questions,
        intended_reader=intended_reader,
        review_angle=review_angle,
        sources=sources,
        nearest_work=nearest_work,
        source_probes=source_probes,
        candidate_audits=candidate_audits,
        projection=projection,
        replay_certificate=replay_certificate,
    )


def replacement_tournament_json_schemas() -> dict[str, Any]:
    models: tuple[type[BaseModel], ...] = (
        FrozenResourceArtifact,
        CandidateResourceSnapshot,
        TaskLineageRecord,
        CandidateLineageInventory,
        RightsScopeDecision,
        CandidateLicenseAudit,
        CandidateEndpointAudit,
        StrongBaselineAvailabilityAudit,
        CandidateComputeAudit,
        ReplacementGateVector,
        CandidateReplayInput,
        ReplacementCandidateAudit,
        ReplacementCandidateProjection,
        ReplacementTournamentDecision,
        ReplacementTournamentProjection,
        ReplacementReplayObservation,
        ReplacementReplayCertificate,
        ReplacementObjectiveDataTournamentReport,
        ReplacementTournamentArtifactManifest,
    )
    return {
        model.__name__: model.model_json_schema()
        for model in sorted(models, key=lambda item: item.__name__)
    }


def render_replacement_tournament_markdown(
    report: ReplacementObjectiveDataTournamentReport,
) -> str:
    decision = report.projection.decision
    projection_by_id = {
        item.candidate_id: item for item in report.projection.candidate_projections
    }
    lines = [
        "# Task 263.6.6 replacement objective-data opportunity tournament",
        "",
        f"- Status: `{decision.status.value}`",
        f"- Report hash: `{report.report_hash}`",
        f"- Exact replay: `{report.projection.projection_sha256}`",
        "- Candidate model calls: `false`",
        "- Outcome/reference values projected: `false`",
        "- Provider credentials collected: `false`",
        "- Research Question Certificate issued: `false`",
        "- Confirmation panel created or read: `false`",
        "",
        "## Frozen research questions",
        "",
    ]
    lines.extend(
        f"{index}. {question}"
        for index, question in enumerate(report.research_questions, start=1)
    )
    lines.extend(
        [
            "",
            "## Candidate decision matrix",
            "",
            (
                "| Candidate | Tasks | Independent upper bound | Dev | Potential "
                "reserve | Sealed reserve | Revision | Lineage | License | "
                "Objective | Baseline | Compute | Eligible |"
            ),
            (
                "|---|---:|---:|---:|---:|---:|---|---|---|---|---|---|---|"
            ),
        ]
    )
    for audit in report.candidate_audits:
        projection = projection_by_id[audit.candidate_id.value]
        gates = projection.gates
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{audit.candidate_id.value}`",
                    str(projection.task_count),
                    str(projection.independent_group_upper_bound),
                    str(projection.development_group_capacity),
                    str(projection.potential_reserve_group_capacity),
                    str(projection.sealed_reserve_group_capacity),
                    str(gates.revision).lower(),
                    str(gates.lineage).lower(),
                    str(gates.license).lower(),
                    str(gates.objective_endpoint).lower(),
                    str(gates.strong_baseline).lower(),
                    str(gates.bounded_local_compute).lower(),
                    str(projection.eligible).lower(),
                ]
            )
            + " |"
        )
    lines.extend(["", "## Candidate findings", ""])
    for audit in report.candidate_audits:
        projection = projection_by_id[audit.candidate_id.value]
        lines.extend(
            [
                f"### {audit.candidate_id.value}",
                "",
                (
                    f"- Lineage: {audit.lineage.task_count} technical tasks, "
                    f"{len(audit.lineage.source_group_ids)} directly lineaged "
                    "source groups."
                ),
                (
                    f"- Endpoint: `{audit.endpoint_audit.endpoint_kind.value}`; "
                    f"deterministic gate "
                    f"`{str(audit.endpoint_audit.gate_passed).lower()}`."
                ),
                (
                    f"- License: exact source objects "
                    f"{audit.license_audit.exact_source_license_object_group_count}/"
                    f"{audit.license_audit.required_group_count}; gate "
                    f"`{str(audit.license_audit.gate_passed).lower()}`."
                ),
                (
                    "- Blockers: "
                    + ", ".join(f"`{item}`" for item in projection.blockers)
                ),
            ]
        )
        lines.extend(f"- {note}" for note in audit.notes)
        lines.append("")
    lines.extend(
        [
            "## Synthesis",
            "",
            (
                "None of the four candidates satisfies the conjunction. "
                "AutoSDT has repository scale but is a public reference-program "
                "training corpus without frozen task evaluators or a sealed reserve. "
                "ScienceAgentBench has a real harness and baselines but only 44 "
                "publication groups at most, mixed LLM evaluation, and redistribution "
                "constraints. CORE-Bench has a strong objective reproducibility "
                "construct, but only 90 paper groups, at most 45 sealed reserve papers, "
                "unbound capsule rights, and an unbounded privileged/GPU workload. "
                "QRData has 190 shared-sheet groups and a bounded deterministic scorer, "
                "but its answers are co-located, per-sheet upstream rights are absent, "
                "and the official baseline implementation is missing."
            ),
            "",
            "## Enforced stop",
            "",
            "- Baseline reproduction authorized: `false`",
            "- Evaluator or critic construction authorized: `false`",
            "- Heterogeneous post-result combination authorized: `false`",
            "- Publication claim or release authorized: `false`",
            "- External submission authorized: `false`",
            f"- Next action: `{decision.next_action}`",
            "",
            "## Verified primary sources",
            "",
        ]
    )
    lines.extend(f"- [{item.title}]({item.source_url})" for item in report.sources)
    return "\n".join(lines) + "\n"


def write_replacement_tournament(
    report: ReplacementObjectiveDataTournamentReport,
    output_root: Path,
    *,
    runner_path: Path,
) -> ReplacementTournamentArtifactManifest:
    output_root.mkdir(parents=True, exist_ok=True)
    report_path = output_root / REPLACEMENT_REPORT_FILENAME
    markdown_path = output_root / REPLACEMENT_MARKDOWN_FILENAME
    schema_path = output_root / REPLACEMENT_SCHEMA_FILENAME
    replay_input_path = output_root / REPLACEMENT_REPLAY_INPUT_FILENAME
    if not replay_input_path.is_file():
        raise FileNotFoundError("result-blind replay input must exist first")
    replay_input_sha256 = _file_sha256(replay_input_path)
    if replay_input_sha256 != report.replay_certificate.input_sha256:
        raise PortfolioIntegrityError("replacement replay input hash mismatch")
    report_text = _canonical_json_text(report.model_dump(mode="json"))
    markdown_text = render_replacement_tournament_markdown(report)
    schema_text = _canonical_json_text(replacement_tournament_json_schemas())
    _write_text_atomic(report_path, report_text)
    _write_text_atomic(markdown_path, markdown_text)
    _write_text_atomic(schema_path, schema_text)
    manifest = ReplacementTournamentArtifactManifest.create(
        report_sha256=hashlib.sha256(report_text.encode("utf-8")).hexdigest(),
        markdown_sha256=hashlib.sha256(markdown_text.encode("utf-8")).hexdigest(),
        schema_sha256=hashlib.sha256(schema_text.encode("utf-8")).hexdigest(),
        replay_input_sha256=replay_input_sha256,
        runner_sha256=_file_sha256(runner_path),
        candidate_revisions={
            audit.candidate_id.value: audit.resource_snapshot.dataset_revision
            for audit in report.candidate_audits
        },
    )
    _write_text_atomic(
        output_root / REPLACEMENT_MANIFEST_FILENAME,
        _canonical_json_text(manifest.model_dump(mode="json")),
    )
    return manifest


def load_replacement_tournament(
    output_root: Path,
) -> tuple[
    ReplacementObjectiveDataTournamentReport,
    ReplacementTournamentArtifactManifest,
]:
    report_path = output_root / REPLACEMENT_REPORT_FILENAME
    markdown_path = output_root / REPLACEMENT_MARKDOWN_FILENAME
    schema_path = output_root / REPLACEMENT_SCHEMA_FILENAME
    replay_input_path = output_root / REPLACEMENT_REPLAY_INPUT_FILENAME
    manifest_path = output_root / REPLACEMENT_MANIFEST_FILENAME
    manifest = ReplacementTournamentArtifactManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    observed = {
        "report": _file_sha256(report_path),
        "markdown": _file_sha256(markdown_path),
        "schema": _file_sha256(schema_path),
        "replay": _file_sha256(replay_input_path),
    }
    expected = {
        "report": manifest.report_sha256,
        "markdown": manifest.markdown_sha256,
        "schema": manifest.schema_sha256,
        "replay": manifest.replay_input_sha256,
    }
    if observed != expected:
        raise PortfolioIntegrityError("replacement tournament artifact tamper")
    report = ReplacementObjectiveDataTournamentReport.model_validate_json(
        report_path.read_text(encoding="utf-8")
    )
    revisions = {
        audit.candidate_id.value: audit.resource_snapshot.dataset_revision
        for audit in report.candidate_audits
    }
    if revisions != manifest.candidate_revisions:
        raise PortfolioIntegrityError("replacement manifest revision mismatch")
    if report.replay_certificate.input_sha256 != manifest.replay_input_sha256:
        raise PortfolioIntegrityError("report replay input mismatch")
    return report, manifest


__all__ = [
    "AUTOSDT_DATASET_REVISION",
    "AUTOSDT_REPOSITORY_REVISION",
    "CORE_BENCH_DATASET_REVISION",
    "CORE_BENCH_REPOSITORY_REVISION",
    "CandidateComputeAudit",
    "CandidateConstruct",
    "CandidateEndpointAudit",
    "CandidateLicenseAudit",
    "CandidateLineageInventory",
    "CandidateReplayInput",
    "CandidateResourceSnapshot",
    "EndpointKind",
    "FrozenResourceArtifact",
    "OfficialCandidateMaterial",
    "ParsedCandidateLineage",
    "QRDATA_REPOSITORY_REVISION",
    "REPLACEMENT_MANIFEST_FILENAME",
    "REPLACEMENT_MARKDOWN_FILENAME",
    "REPLACEMENT_REPLAY_INPUT_FILENAME",
    "REPLACEMENT_REPORT_FILENAME",
    "REPLACEMENT_RUNNER_SOURCE_PATH",
    "REPLACEMENT_SCHEMA_FILENAME",
    "REQUIRED_DEVELOPMENT_GROUPS",
    "REQUIRED_RESERVE_GROUPS",
    "REQUIRED_TOTAL_GROUPS",
    "ReplacementCandidateAudit",
    "ReplacementCandidateId",
    "ReplacementCandidateProjection",
    "ReplacementGateVector",
    "ReplacementObjectiveDataTournamentReport",
    "ReplacementReplayCertificate",
    "ReplacementReplayObservation",
    "ReplacementTournamentArtifactManifest",
    "ReplacementTournamentDecision",
    "ReplacementTournamentProjection",
    "ReplacementTournamentStatus",
    "RightsScope",
    "RightsScopeDecision",
    "RightsStatus",
    "SCIENCE_AGENT_BENCH_DATASET_REVISION",
    "SCIENCE_AGENT_BENCH_REPOSITORY_REVISION",
    "StrongBaselineAvailabilityAudit",
    "TaskLineageRecord",
    "build_official_candidate_audits",
    "build_replacement_replay_payload",
    "build_replacement_tournament_report",
    "fetch_replacement_candidate_materials",
    "load_replacement_tournament",
    "normalize_repository_url",
    "parse_autosdt_lineage",
    "parse_core_bench_lineage",
    "parse_qrdata_lineage",
    "parse_scienceagentbench_lineage",
    "project_replacement_tournament",
    "render_replacement_tournament_markdown",
    "replacement_tournament_json_schemas",
    "run_replacement_tournament_replay",
    "write_replacement_tournament",
]
