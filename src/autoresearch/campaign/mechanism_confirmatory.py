"""One-shot confirmatory adjudication for the task 261.2 mechanism round."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import random
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from autoresearch.campaign.mechanism_benchmark import (
    ClaimDecision,
    GeneratedClaimDecision,
    MechanismEvaluationTask,
)
from autoresearch.campaign.mechanism_development import (
    MechanismDevelopmentManifest,
    MechanismDevelopmentStatus,
    MechanismProgram,
    load_mechanism_development,
)
from autoresearch.campaign.mechanism_round import (
    GeneratedCodeEvidence,
    MechanismPanelSpec,
    MechanismRoundFreeze,
)
from autoresearch.campaign.mechanism_sandbox import (
    run_generated_code_harness,
)
from autoresearch.competition.manifest import write_json_model
from autoresearch.kernel import (
    Activity,
    ActivityKind,
    Agent,
    Association,
    Claim,
    ControlGraphRuntime,
    Decision,
    Derivation,
    Entity,
    EntityKind,
    EpisodeOutcomeStatus,
    EventJournal,
    Evidence,
    EvidenceDirection,
    Generation,
    HoldoutState,
    InvocationStatus,
    LoopBudgetPolicy,
    LoopEdgeKind,
    LoopEdgeSpec,
    LoopGuardKind,
    LoopGuardSpec,
    LoopHoldoutPolicy,
    LoopNodeExecutionRequest,
    LoopNodeKind,
    LoopNodeOutcome,
    LoopNodeResult,
    LoopNodeSpec,
    LoopPermissionPolicy,
    LoopRetryPolicy,
    LoopRunSnapshot,
    LoopRunStatus,
    LoopSpec,
    LoopStartRequest,
    LoopUsage,
    Plan,
    ProvenanceAgentKind,
    ProvenanceBundle,
    SourceSnapshot,
    ToolInvocation,
    Usage,
    Validation,
    always_guard,
)
from autoresearch.kernel.contracts import (
    ActorKind,
    KernelContract,
    NonEmptyText,
    Sha256,
    StableId,
    canonical_sha256,
)
from autoresearch.schemas import ValidationStatus, file_hash

_SCHEMA_VERSION = "mechanism-confirmatory-v1"
_TASK_ID = "task2612-confirmatory"
_PROJECT_ID = "autoresearch-ccfb"
_PRIMARY_METRIC = "unsupported_claim_rate_at_minimum_coverage"
_UNCERTAINTY_RULE = "independent-task percentile bootstrap of aggregate ratios"
_STOP_RULE = (
    "Execute each of the six frozen confirmatory tasks once in task-id order, "
    "retain failures and abstentions, continue to deterministic adjudication, "
    "and prohibit retries, adaptation, threshold changes, or endpoint rewrites."
)
_EXPECTED_CONFIRMATORY_TASK_COUNT = 6
_FROZEN_SOURCE_NAMES = {
    "development-manifest.json": "development-manifest.json",
    "freeze/round-freeze.json": "round-freeze.json",
    "panel/panel-spec.json": "panel-spec.json",
    "panel/sealed-confirmatory-tasks.json": "confirmatory-tasks.json",
    "generated/run.py": "run.py",
    "model/mechanism-program.json": "mechanism-program.json",
    "model/proposal.json": "proposal.json",
    "model/diagnosis.json": "diagnosis.json",
    "model/source-serialization.json": "source-serialization.json",
    "review/generated-code-evidence.json": "generated-code-evidence.json",
    "development/screen.json": "development-screen.json",
}


class MechanismConfirmatoryIntegrityError(ValueError):
    """Raised when a confirmatory freeze, execution, or report is inconsistent."""


class MechanismScientificOutcome(str, Enum):
    """Scientific endpoint produced only after the frozen panel is terminal."""

    POSITIVE_RESULT = "positive_result"
    NEGATIVE_RESULT = "negative_result"


class MechanismConfirmatoryStatus(str, Enum):
    """Terminal task 261.2.3 status."""

    POSITIVE_RESULT = "positive_result"
    NEGATIVE_RESULT = "negative_result"
    VERIFICATION_FAILED = "verification_failed"


class MechanismTaskExecutionRole(str, Enum):
    """Separate the authoritative panel from post-endpoint reproduction."""

    PRIMARY_CONFIRMATORY = "primary_confirmatory"
    INDEPENDENT_REPRODUCTION = "independent_reproduction"


class MechanismExecutionEnvironment(KernelContract):
    """Exact code/runtime policy frozen before confirmatory reveal."""

    schema_version: Literal["mechanism-execution-environment-v1"] = (
        "mechanism-execution-environment-v1"
    )
    python_version: NonEmptyText
    python_implementation: NonEmptyText
    python_executable_sha256: Sha256
    operating_system: NonEmptyText
    machine: NonEmptyText
    isolation_arguments: list[Literal["-I"]]
    explicit_environment_keys: list[StableId]
    inherited_environment_value_sha256s: dict[StableId, Sha256]
    dependency_lock_sha256: Sha256
    implementation_file_sha256s: dict[str, Sha256]
    repository_commit_sha: NonEmptyText | None = None
    repository_was_clean: bool
    network_allowed: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    environment_hash: Sha256

    @field_validator("explicit_environment_keys")
    @classmethod
    def _normalize_keys(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("execution environment keys must be unique")
        return sorted(value)

    @field_validator("repository_commit_sha")
    @classmethod
    def _validate_git_object_id(cls, value: str | None) -> str | None:
        if value is not None and (
            len(value) not in {40, 64}
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ValueError("repository commit must be a 40- or 64-character Git object ID")
        return value

    @model_validator(mode="after")
    def _validate_hash(self) -> MechanismExecutionEnvironment:
        if self.isolation_arguments != ["-I"]:
            raise ValueError("confirmatory Python isolation arguments changed")
        if self.environment_hash != self.calculated_hash():
            raise MechanismConfirmatoryIntegrityError("execution environment_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> MechanismExecutionEnvironment:
        payload = dict(values)
        payload["schema_version"] = "mechanism-execution-environment-v1"
        payload["isolation_arguments"] = ["-I"]
        payload["explicit_environment_keys"] = sorted(payload["explicit_environment_keys"])
        payload["inherited_environment_value_sha256s"] = dict(
            sorted(payload["inherited_environment_value_sha256s"].items())
        )
        payload["implementation_file_sha256s"] = dict(
            sorted(payload["implementation_file_sha256s"].items())
        )
        payload["network_allowed"] = False
        payload["external_submission_authorized"] = False
        payload["environment_hash"] = canonical_sha256(payload)
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"environment_hash"}))


class MechanismConfirmatoryPreregistration(KernelContract):
    """Result-blind freeze that must exist before the Control Graph starts."""

    schema_version: Literal["mechanism-confirmatory-preregistration-v1"] = (
        "mechanism-confirmatory-preregistration-v1"
    )
    run_id: StableId
    frozen_at: datetime
    development_manifest_hash: Sha256
    round_freeze_hash: Sha256
    development_screen_hash: Sha256
    proposal_hash: Sha256
    mechanism_program_hash: Sha256
    compiler_contract_hash: Sha256
    generated_source_sha256: Sha256
    generated_code_evidence_hash: Sha256
    panel_hash: Sha256
    confirmatory_bundle_sha256: Sha256
    confirmatory_bundle_hash: Sha256
    confirmatory_task_hashes: dict[StableId, Sha256]
    control_spec_hash: Sha256
    environment: MechanismExecutionEnvironment
    primary_metric: Literal["unsupported_claim_rate_at_minimum_coverage"] = (
        "unsupported_claim_rate_at_minimum_coverage"
    )
    minimum_coverage: float = Field(gt=0.0, le=1.0)
    maximum_unsupported_claim_rate: float = Field(ge=0.0, lt=1.0)
    uncertainty_rule: Literal["independent-task percentile bootstrap of aggregate ratios"] = (
        "independent-task percentile bootstrap of aggregate ratios"
    )
    bootstrap_resamples: int = Field(ge=1_000)
    bootstrap_seed: int = Field(ge=0)
    confidence_level: float = Field(default=0.95, ge=0.95, le=0.95)
    independent_unit: Literal["confirmatory_task"] = "confirmatory_task"
    stop_rule: NonEmptyText = _STOP_RULE
    maximum_task_attempts: Literal[1] = 1
    continue_after_task_failure: Literal[True] = True
    post_reveal_adaptation_allowed: Literal[False] = False
    post_freeze_threshold_change_allowed: Literal[False] = False
    endpoint_rewrite_allowed: Literal[False] = False
    confirmatory_results_revealed: Literal[False] = False
    confirmatory_result_artifact_count: Literal[0] = 0
    scientific_result_created: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    frozen_artifact_file_sha256s: dict[str, Sha256]
    preregistration_hash: Sha256

    @field_validator("frozen_at")
    @classmethod
    def _require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("confirmatory freeze time must be timezone-aware")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _validate_preregistration(self) -> MechanismConfirmatoryPreregistration:
        if len(self.confirmatory_task_hashes) != _EXPECTED_CONFIRMATORY_TASK_COUNT:
            raise ValueError("confirmatory preregistration must freeze six tasks")
        if self.stop_rule != _STOP_RULE:
            raise ValueError("confirmatory stop rule changed")
        if self.preregistration_hash != self.calculated_hash():
            raise MechanismConfirmatoryIntegrityError("confirmatory preregistration_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> MechanismConfirmatoryPreregistration:
        payload = dict(values)
        payload["schema_version"] = "mechanism-confirmatory-preregistration-v1"
        payload["primary_metric"] = _PRIMARY_METRIC
        payload["uncertainty_rule"] = _UNCERTAINTY_RULE
        payload["confidence_level"] = 0.95
        payload["independent_unit"] = "confirmatory_task"
        payload["stop_rule"] = _STOP_RULE
        payload["maximum_task_attempts"] = 1
        payload["continue_after_task_failure"] = True
        payload["post_reveal_adaptation_allowed"] = False
        payload["post_freeze_threshold_change_allowed"] = False
        payload["endpoint_rewrite_allowed"] = False
        payload["confirmatory_results_revealed"] = False
        payload["confirmatory_result_artifact_count"] = 0
        payload["scientific_result_created"] = False
        payload["external_submission_authorized"] = False
        payload["confirmatory_task_hashes"] = dict(
            sorted(payload["confirmatory_task_hashes"].items())
        )
        payload["frozen_artifact_file_sha256s"] = dict(
            sorted(payload["frozen_artifact_file_sha256s"].items())
        )
        normalized = cls.model_construct(**payload).model_dump(
            mode="json",
            exclude={"preregistration_hash"},
        )
        normalized["preregistration_hash"] = canonical_sha256(normalized)
        return cls.model_validate(normalized)

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"preregistration_hash"}))


class MechanismConfirmatoryTaskResult(KernelContract):
    """One terminal task result, including failures and abstentions."""

    schema_version: Literal["mechanism-confirmatory-task-result-v1"] = (
        "mechanism-confirmatory-task-result-v1"
    )
    execution_role: MechanismTaskExecutionRole
    task_id: StableId
    task_hash: Sha256
    generated_source_sha256: Sha256
    harness_spec_hash: Sha256 | None = None
    harness_episode_hash: Sha256 | None = None
    output_artifact_sha256: Sha256 | None = None
    decisions: list[GeneratedClaimDecision]
    claim_count: int = Field(ge=1)
    accepted_count: int = Field(ge=0)
    accepted_unsupported_count: int = Field(ge=0)
    coverage: float = Field(ge=0.0, le=1.0)
    unsupported_claim_rate: float = Field(ge=0.0, le=1.0)
    execution_succeeded: bool
    failure_codes: list[StableId]
    network_used: Literal[False] = False
    explicit_environment_keys: list[StableId]
    one_shot_attempt_count: Literal[1] = 1
    scientific_projection_hash: Sha256
    result_hash: Sha256

    @field_validator("failure_codes", "explicit_environment_keys")
    @classmethod
    def _normalize_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("confirmatory task identifiers must be unique")
        return sorted(value)

    @model_validator(mode="after")
    def _validate_result(self) -> MechanismConfirmatoryTaskResult:
        decision_ids = [decision.claim_id for decision in self.decisions]
        if len(decision_ids) != len(set(decision_ids)):
            raise ValueError("confirmatory decisions contain duplicate claim IDs")
        if self.execution_succeeded:
            if self.failure_codes:
                raise ValueError("successful confirmatory task cannot have failures")
            if len(self.decisions) != self.claim_count:
                raise ValueError("successful confirmatory task lacks decisions")
            required = (
                self.harness_spec_hash,
                self.harness_episode_hash,
                self.output_artifact_sha256,
            )
            if any(value is None for value in required):
                raise ValueError("successful confirmatory task lacks Harness hashes")
        elif self.decisions:
            raise ValueError("failed confirmatory task cannot retain partial decisions")
        elif not self.failure_codes:
            raise ValueError("failed confirmatory task needs a failure code")
        accepted = [
            decision for decision in self.decisions if decision.decision is ClaimDecision.ACCEPT
        ]
        if self.accepted_count != len(accepted):
            raise ValueError("confirmatory accepted count contradicts decisions")
        if self.accepted_unsupported_count > self.accepted_count:
            raise ValueError("unsupported accepted count exceeds accepted count")
        expected_coverage = self.accepted_count / self.claim_count
        if abs(self.coverage - expected_coverage) > 1e-12:
            raise ValueError("confirmatory coverage contradicts counts")
        expected_risk = (
            self.accepted_unsupported_count / self.accepted_count if self.accepted_count else 0.0
        )
        if abs(self.unsupported_claim_rate - expected_risk) > 1e-12:
            raise ValueError("confirmatory unsupported rate contradicts counts")
        if self.scientific_projection_hash != self.calculated_projection_hash():
            raise MechanismConfirmatoryIntegrityError(
                "confirmatory task scientific projection mismatch"
            )
        if self.result_hash != self.calculated_hash():
            raise MechanismConfirmatoryIntegrityError("confirmatory task result_hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        execution_role: MechanismTaskExecutionRole,
        task: MechanismEvaluationTask,
        generated_source_sha256: str,
        decisions: list[GeneratedClaimDecision],
        execution_succeeded: bool,
        failure_codes: Sequence[str],
        explicit_environment_keys: Sequence[str],
        harness_spec_hash: str | None = None,
        harness_episode_hash: str | None = None,
        output_artifact_sha256: str | None = None,
    ) -> MechanismConfirmatoryTaskResult:
        decision_by_id = {decision.claim_id: decision for decision in decisions}
        expected_ids = {claim.claim_id for claim in task.claims}
        if execution_succeeded and set(decision_by_id) != expected_ids:
            raise ValueError("confirmatory decisions do not cover exact task claims")
        if not execution_succeeded:
            decision_by_id = {}
        ordered = [
            decision_by_id[claim.claim_id]
            for claim in task.claims
            if claim.claim_id in decision_by_id
        ]
        labels = {claim.claim_id: claim.supported for claim in task.claims}
        accepted = [decision for decision in ordered if decision.decision is ClaimDecision.ACCEPT]
        unsupported = sum(not labels[decision.claim_id] for decision in accepted)
        payload: dict[str, Any] = {
            "schema_version": "mechanism-confirmatory-task-result-v1",
            "execution_role": execution_role,
            "task_id": task.task_id,
            "task_hash": task.task_hash,
            "generated_source_sha256": generated_source_sha256,
            "harness_spec_hash": harness_spec_hash,
            "harness_episode_hash": harness_episode_hash,
            "output_artifact_sha256": output_artifact_sha256,
            "decisions": [decision.model_dump(mode="json") for decision in ordered],
            "claim_count": len(task.claims),
            "accepted_count": len(accepted),
            "accepted_unsupported_count": unsupported,
            "coverage": len(accepted) / len(task.claims),
            "unsupported_claim_rate": (unsupported / len(accepted) if accepted else 0.0),
            "execution_succeeded": execution_succeeded,
            "failure_codes": sorted(set(failure_codes)),
            "network_used": False,
            "explicit_environment_keys": sorted(set(explicit_environment_keys)),
            "one_shot_attempt_count": 1,
        }
        projection = _task_scientific_projection(payload)
        payload["scientific_projection_hash"] = canonical_sha256(projection)
        payload["result_hash"] = canonical_sha256(payload)
        return cls.model_validate(payload)

    def calculated_projection_hash(self) -> str:
        return canonical_sha256(_task_scientific_projection(self.model_dump(mode="json")))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"result_hash"}))


class MechanismConfirmatoryEndpoint(KernelContract):
    """Immutable positive or negative endpoint from six independent tasks."""

    schema_version: Literal["mechanism-confirmatory-endpoint-v1"] = (
        "mechanism-confirmatory-endpoint-v1"
    )
    run_id: StableId
    preregistration_hash: Sha256
    panel_hash: Sha256
    generated_source_sha256: Sha256
    started_at: datetime
    completed_at: datetime
    task_result_hashes: list[Sha256] = Field(min_length=6, max_length=6)
    task_projection_hashes: list[Sha256] = Field(min_length=6, max_length=6)
    task_count: Literal[6] = 6
    successful_task_count: int = Field(ge=0, le=6)
    failed_task_count: int = Field(ge=0, le=6)
    claim_count: int = Field(ge=1)
    accepted_count: int = Field(ge=0)
    accepted_unsupported_count: int = Field(ge=0)
    coverage: float = Field(ge=0.0, le=1.0)
    coverage_ci95_lower: float = Field(ge=0.0, le=1.0)
    coverage_ci95_upper: float = Field(ge=0.0, le=1.0)
    unsupported_claim_rate: float = Field(ge=0.0, le=1.0)
    unsupported_rate_ci95_lower: float = Field(ge=0.0, le=1.0)
    unsupported_rate_ci95_upper: float = Field(ge=0.0, le=1.0)
    minimum_coverage: float = Field(gt=0.0, le=1.0)
    maximum_unsupported_claim_rate: float = Field(ge=0.0, lt=1.0)
    bootstrap_resamples: int = Field(ge=1_000)
    bootstrap_seed: int = Field(ge=0)
    gates: dict[StableId, bool]
    failure_codes: list[StableId]
    outcome: MechanismScientificOutcome
    confirmatory_results_revealed: Literal[True] = True
    confirmatory_result_artifact_count: Literal[6] = 6
    scientific_result_created: Literal[True] = True
    endpoint_rewrite_allowed: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    scientific_projection_hash: Sha256
    endpoint_hash: Sha256

    @field_validator("started_at", "completed_at")
    @classmethod
    def _require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("confirmatory endpoint time must be timezone-aware")
        return value.astimezone(timezone.utc)

    @field_validator("task_result_hashes", "task_projection_hashes", "failure_codes")
    @classmethod
    def _normalize_lists(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("confirmatory endpoint identifiers must be unique")
        return sorted(value)

    @model_validator(mode="after")
    def _validate_endpoint(self) -> MechanismConfirmatoryEndpoint:
        if self.completed_at < self.started_at:
            raise ValueError("confirmatory endpoint completion precedes start")
        if self.successful_task_count + self.failed_task_count != self.task_count:
            raise ValueError("confirmatory task terminal counts are inconsistent")
        expected_coverage = self.accepted_count / self.claim_count
        if abs(self.coverage - expected_coverage) > 1e-12:
            raise ValueError("endpoint coverage contradicts counts")
        expected_risk = (
            self.accepted_unsupported_count / self.accepted_count if self.accepted_count else 0.0
        )
        if abs(self.unsupported_claim_rate - expected_risk) > 1e-12:
            raise ValueError("endpoint unsupported rate contradicts counts")
        expected_outcome = (
            MechanismScientificOutcome.POSITIVE_RESULT
            if self.gates and all(self.gates.values())
            else MechanismScientificOutcome.NEGATIVE_RESULT
        )
        if self.outcome is not expected_outcome:
            raise ValueError("scientific outcome contradicts frozen gates")
        expected_failures = sorted(gate_id for gate_id, passed in self.gates.items() if not passed)
        if self.failure_codes != expected_failures:
            raise ValueError("endpoint failure codes contradict frozen gates")
        if self.scientific_projection_hash != self.calculated_projection_hash():
            raise MechanismConfirmatoryIntegrityError("endpoint scientific projection mismatch")
        if self.endpoint_hash != self.calculated_hash():
            raise MechanismConfirmatoryIntegrityError("endpoint_hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        preregistration: MechanismConfirmatoryPreregistration,
        results: list[MechanismConfirmatoryTaskResult],
        started_at: datetime,
        completed_at: datetime,
    ) -> MechanismConfirmatoryEndpoint:
        if len(results) != _EXPECTED_CONFIRMATORY_TASK_COUNT:
            raise ValueError("confirmatory endpoint requires six task results")
        if any(
            result.execution_role is not MechanismTaskExecutionRole.PRIMARY_CONFIRMATORY
            for result in results
        ):
            raise ValueError("reproduction results cannot create an endpoint")
        if {result.task_id for result in results} != set(preregistration.confirmatory_task_hashes):
            raise ValueError("endpoint task set differs from preregistration")
        for result in results:
            expected_hash = preregistration.confirmatory_task_hashes[result.task_id]
            if result.task_hash != expected_hash:
                raise ValueError("endpoint task hash differs from preregistration")
            if result.generated_source_sha256 != preregistration.generated_source_sha256:
                raise ValueError("endpoint source differs from preregistration")
        ordered = sorted(results, key=lambda item: item.task_id)
        projection = _build_endpoint_scientific_projection(
            preregistration=preregistration,
            results=ordered,
        )
        payload: dict[str, Any] = {
            "schema_version": "mechanism-confirmatory-endpoint-v1",
            "run_id": preregistration.run_id,
            "started_at": started_at,
            "completed_at": completed_at,
            "task_result_hashes": sorted(result.result_hash for result in ordered),
            **{key: value for key, value in projection.items() if key != "schema_version"},
            "confirmatory_result_artifact_count": (_EXPECTED_CONFIRMATORY_TASK_COUNT),
            "endpoint_rewrite_allowed": False,
            "external_submission_authorized": False,
        }
        normalized = cls.model_construct(**payload).model_dump(
            mode="json",
            exclude={"scientific_projection_hash", "endpoint_hash"},
        )
        normalized["scientific_projection_hash"] = canonical_sha256(
            _endpoint_scientific_projection(normalized)
        )
        normalized["endpoint_hash"] = canonical_sha256(normalized)
        return cls.model_validate(normalized)

    def calculated_projection_hash(self) -> str:
        return canonical_sha256(_endpoint_scientific_projection(self.model_dump(mode="json")))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"endpoint_hash"}))


class MechanismControlNodeReceipt(KernelContract):
    """Durable executor-side idempotency record for one Control Graph node."""

    schema_version: Literal["mechanism-control-node-receipt-v1"] = (
        "mechanism-control-node-receipt-v1"
    )
    node_id: StableId
    idempotency_key: StableId
    request_hash: Sha256
    result: LoopNodeResult
    produced_file_sha256s: dict[str, Sha256]
    receipt_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> MechanismControlNodeReceipt:
        if self.receipt_hash != self.calculated_hash():
            raise MechanismConfirmatoryIntegrityError("control node receipt_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> MechanismControlNodeReceipt:
        payload = dict(values)
        payload["schema_version"] = "mechanism-control-node-receipt-v1"
        payload["produced_file_sha256s"] = dict(sorted(payload["produced_file_sha256s"].items()))
        normalized = cls.model_construct(**payload).model_dump(
            mode="json",
            exclude={"receipt_hash"},
        )
        normalized["receipt_hash"] = canonical_sha256(normalized)
        return cls.model_validate(normalized)

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"receipt_hash"}))


class MechanismReproductionReport(KernelContract):
    """Independent post-endpoint rerun that cannot alter the endpoint."""

    schema_version: Literal["mechanism-confirmatory-reproduction-v1"] = (
        "mechanism-confirmatory-reproduction-v1"
    )
    source_endpoint_hash: Sha256
    source_scientific_projection_hash: Sha256
    reproduced_task_result_hashes: list[Sha256] = Field(min_length=6, max_length=6)
    reproduced_task_projection_hashes: list[Sha256] = Field(
        min_length=6,
        max_length=6,
    )
    task_projection_matches: dict[StableId, bool]
    reproduced_scientific_projection_hash: Sha256
    clean_directory_started_empty: Literal[True] = True
    endpoint_mutation_allowed: Literal[False] = False
    scientific_result_created: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    artifact_file_sha256s: dict[str, Sha256]
    passed: bool
    report_hash: Sha256

    @model_validator(mode="after")
    def _validate_report(self) -> MechanismReproductionReport:
        expected = (
            bool(self.task_projection_matches)
            and all(self.task_projection_matches.values())
            and self.reproduced_scientific_projection_hash == self.source_scientific_projection_hash
        )
        if self.passed != expected:
            raise ValueError("reproduction verdict contradicts projections")
        if self.report_hash != self.calculated_hash():
            raise MechanismConfirmatoryIntegrityError("reproduction report_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> MechanismReproductionReport:
        payload = dict(values)
        payload["schema_version"] = "mechanism-confirmatory-reproduction-v1"
        payload["reproduced_task_result_hashes"] = sorted(payload["reproduced_task_result_hashes"])
        payload["reproduced_task_projection_hashes"] = sorted(
            payload["reproduced_task_projection_hashes"]
        )
        payload["task_projection_matches"] = dict(
            sorted(payload["task_projection_matches"].items())
        )
        payload["artifact_file_sha256s"] = dict(sorted(payload["artifact_file_sha256s"].items()))
        payload["clean_directory_started_empty"] = True
        payload["endpoint_mutation_allowed"] = False
        payload["scientific_result_created"] = False
        payload["external_submission_authorized"] = False
        payload["passed"] = (
            bool(payload["task_projection_matches"])
            and all(payload["task_projection_matches"].values())
            and payload["reproduced_scientific_projection_hash"]
            == payload["source_scientific_projection_hash"]
        )
        normalized = cls.model_construct(**payload).model_dump(
            mode="json",
            exclude={"report_hash"},
        )
        normalized["report_hash"] = canonical_sha256(normalized)
        return cls.model_validate(normalized)

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"report_hash"}))


class MechanismRollbackReport(KernelContract):
    """Non-destructive rehearsal of the exact sealed pre-reveal state."""

    schema_version: Literal["mechanism-confirmatory-rollback-v1"] = (
        "mechanism-confirmatory-rollback-v1"
    )
    source_endpoint_hash: Sha256
    rollback_target_preregistration_hash: Sha256
    rollback_target_holdout_state: Literal["sealed"] = "sealed"
    rollback_artifact_file_sha256s: dict[str, Sha256]
    expected_artifact_file_sha256s: dict[str, Sha256]
    confirmatory_result_artifact_count: Literal[0] = 0
    canonical_endpoint_preserved: Literal[True] = True
    destructive_rollback_performed: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    passed: bool
    report_hash: Sha256

    @model_validator(mode="after")
    def _validate_report(self) -> MechanismRollbackReport:
        expected = self.rollback_artifact_file_sha256s == self.expected_artifact_file_sha256s
        if self.passed != expected:
            raise ValueError("rollback verdict contradicts frozen artifacts")
        if self.report_hash != self.calculated_hash():
            raise MechanismConfirmatoryIntegrityError("rollback report_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> MechanismRollbackReport:
        payload = dict(values)
        payload["schema_version"] = "mechanism-confirmatory-rollback-v1"
        payload["rollback_target_holdout_state"] = "sealed"
        payload["rollback_artifact_file_sha256s"] = dict(
            sorted(payload["rollback_artifact_file_sha256s"].items())
        )
        payload["expected_artifact_file_sha256s"] = dict(
            sorted(payload["expected_artifact_file_sha256s"].items())
        )
        payload["confirmatory_result_artifact_count"] = 0
        payload["canonical_endpoint_preserved"] = True
        payload["destructive_rollback_performed"] = False
        payload["external_submission_authorized"] = False
        payload["passed"] = (
            payload["rollback_artifact_file_sha256s"] == payload["expected_artifact_file_sha256s"]
        )
        normalized = cls.model_construct(**payload).model_dump(
            mode="json",
            exclude={"report_hash"},
        )
        normalized["report_hash"] = canonical_sha256(normalized)
        return cls.model_validate(normalized)

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"report_hash"}))


class MechanismEvaluationSecurityReport(KernelContract):
    """Operational/security verdict kept separate from scientific direction."""

    schema_version: Literal["mechanism-confirmatory-evaluation-security-v1"] = (
        "mechanism-confirmatory-evaluation-security-v1"
    )
    endpoint_hash: Sha256
    scientific_outcome: MechanismScientificOutcome
    control_spec_hash: Sha256
    control_snapshot_hash: Sha256
    journal_lineage_hash: Sha256
    journal_seal_hash: Sha256
    provenance_bundle_hash: Sha256
    reproduction_report_hash: Sha256
    rollback_report_hash: Sha256
    checks: dict[StableId, bool]
    failure_codes: list[StableId]
    passed: bool
    scientific_verdict_unchanged: Literal[True] = True
    external_submission_authorized: Literal[False] = False
    report_hash: Sha256

    @field_validator("failure_codes")
    @classmethod
    def _normalize_failures(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("evaluation failure codes must be unique")
        return sorted(value)

    @model_validator(mode="after")
    def _validate_report(self) -> MechanismEvaluationSecurityReport:
        expected_passed = bool(self.checks) and all(self.checks.values())
        if self.passed != expected_passed:
            raise ValueError("evaluation/security verdict contradicts checks")
        expected_failures = sorted(
            check_id for check_id, passed in self.checks.items() if not passed
        )
        if self.failure_codes != expected_failures:
            raise ValueError("evaluation failure codes contradict checks")
        if self.report_hash != self.calculated_hash():
            raise MechanismConfirmatoryIntegrityError("evaluation/security report_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> MechanismEvaluationSecurityReport:
        payload = dict(values)
        payload["schema_version"] = "mechanism-confirmatory-evaluation-security-v1"
        payload["checks"] = dict(sorted(payload["checks"].items()))
        payload["failure_codes"] = sorted(
            check_id for check_id, passed in payload["checks"].items() if not passed
        )
        payload["passed"] = bool(payload["checks"]) and all(payload["checks"].values())
        payload["scientific_verdict_unchanged"] = True
        payload["external_submission_authorized"] = False
        normalized = cls.model_construct(**payload).model_dump(
            mode="json",
            exclude={"report_hash"},
        )
        normalized["report_hash"] = canonical_sha256(normalized)
        return cls.model_validate(normalized)

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"report_hash"}))


class MechanismConfirmatoryManifest(KernelContract):
    """Terminal task 261.2.3 index with every artifact content-addressed."""

    schema_version: Literal["mechanism-confirmatory-manifest-v1"] = (
        "mechanism-confirmatory-manifest-v1"
    )
    run_id: StableId
    status: MechanismConfirmatoryStatus
    completed_at: datetime
    preregistration_hash: Sha256
    endpoint_hash: Sha256
    scientific_projection_hash: Sha256
    scientific_outcome: MechanismScientificOutcome
    control_snapshot_hash: Sha256
    journal_lineage_hash: Sha256
    journal_seal_hash: Sha256
    provenance_bundle_hash: Sha256
    evaluation_security_report_hash: Sha256
    reproduction_report_hash: Sha256
    rollback_report_hash: Sha256
    task_result_count: Literal[6] = 6
    confirmatory_results_revealed: Literal[True] = True
    scientific_result_created: Literal[True] = True
    endpoint_rewrite_allowed: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    artifact_file_sha256s: dict[str, Sha256]
    manifest_hash: Sha256

    @field_validator("completed_at")
    @classmethod
    def _require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("confirmatory completion time must be timezone-aware")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _validate_manifest(self) -> MechanismConfirmatoryManifest:
        expected_status = (
            MechanismConfirmatoryStatus.POSITIVE_RESULT
            if self.scientific_outcome is MechanismScientificOutcome.POSITIVE_RESULT
            else MechanismConfirmatoryStatus.NEGATIVE_RESULT
        )
        if (
            self.status is not MechanismConfirmatoryStatus.VERIFICATION_FAILED
            and self.status is not expected_status
        ):
            raise ValueError("confirmatory status contradicts scientific outcome")
        if self.manifest_hash != self.calculated_hash():
            raise MechanismConfirmatoryIntegrityError("confirmatory manifest_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> MechanismConfirmatoryManifest:
        payload = dict(values)
        payload["schema_version"] = "mechanism-confirmatory-manifest-v1"
        payload["task_result_count"] = _EXPECTED_CONFIRMATORY_TASK_COUNT
        payload["confirmatory_results_revealed"] = True
        payload["scientific_result_created"] = True
        payload["endpoint_rewrite_allowed"] = False
        payload["external_submission_authorized"] = False
        payload["artifact_file_sha256s"] = dict(sorted(payload["artifact_file_sha256s"].items()))
        normalized = cls.model_construct(**payload).model_dump(
            mode="json",
            exclude={"manifest_hash"},
        )
        normalized["manifest_hash"] = canonical_sha256(normalized)
        return cls.model_validate(normalized)

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"manifest_hash"}))


def freeze_task2612_confirmatory(
    *,
    development_dir: Path | str,
    output_dir: Path | str,
    run_id: str = "task2612-mechanism-confirmatory-v1",
    clock: Callable[[], datetime] | None = None,
) -> MechanismConfirmatoryPreregistration:
    """Freeze exact code, environment, statistics, graph, and untouched tasks."""

    now = clock or (lambda: datetime.now(timezone.utc))
    source_root = Path(development_dir).resolve()
    development = load_mechanism_development(source_root)
    if development.status is not MechanismDevelopmentStatus.READY_FOR_PREREGISTRATION:
        raise MechanismConfirmatoryIntegrityError(
            "confirmatory freeze requires ready development evidence"
        )
    root = Path(output_dir).resolve()
    preregistration_path = root / "preregistration.json"
    if preregistration_path.is_file():
        return load_mechanism_confirmatory_preregistration(root)
    if root.exists() and any(root.iterdir()):
        raise MechanismConfirmatoryIntegrityError(
            "confirmatory freeze output must be empty or already frozen"
        )
    root.mkdir(parents=True, exist_ok=True)
    frozen_root = root / "frozen"
    frozen_root.mkdir()
    for source_name, target_name in _FROZEN_SOURCE_NAMES.items():
        source_path = source_root / source_name
        if not source_path.is_file():
            raise MechanismConfirmatoryIntegrityError(f"development evidence lacks {source_name}")
        shutil.copyfile(source_path, frozen_root / target_name)

    round_freeze = MechanismRoundFreeze.model_validate_json(
        (frozen_root / "round-freeze.json").read_text(encoding="utf-8")
    )
    panel = MechanismPanelSpec.model_validate_json(
        (frozen_root / "panel-spec.json").read_text(encoding="utf-8")
    )
    program = MechanismProgram.model_validate_json(
        (frozen_root / "mechanism-program.json").read_text(encoding="utf-8")
    )
    code_evidence = GeneratedCodeEvidence.model_validate_json(
        (frozen_root / "generated-code-evidence.json").read_text(encoding="utf-8")
    )
    serialization = _read_json(frozen_root / "source-serialization.json")
    task_bundle = _load_confirmatory_task_bundle(frozen_root / "confirmatory-tasks.json")
    tasks = _tasks_from_bundle(task_bundle)
    _validate_development_causal_chain(
        development=development,
        round_freeze=round_freeze,
        panel=panel,
        program=program,
        code_evidence=code_evidence,
        serialization=serialization,
        tasks=tasks,
        source_path=frozen_root / "run.py",
    )
    spec = build_mechanism_confirmatory_control_spec(
        source_sha256=development.generated_source_sha256 or "",
        task_ids=[task.task_id for task in tasks],
    )
    write_json_model(root / "control" / "loop-spec.json", spec)
    environment = _current_execution_environment()
    frozen_hashes = _frozen_artifact_hashes(root)
    preregistration = MechanismConfirmatoryPreregistration.create(
        run_id=run_id,
        frozen_at=now(),
        development_manifest_hash=development.manifest_hash,
        round_freeze_hash=round_freeze.freeze_hash,
        development_screen_hash=development.development_screen_hash,
        proposal_hash=development.proposal_hash,
        mechanism_program_hash=program.program_hash,
        compiler_contract_hash=str(serialization["compiler_contract_hash"]),
        generated_source_sha256=development.generated_source_sha256,
        generated_code_evidence_hash=code_evidence.evidence_hash,
        panel_hash=panel.panel_hash,
        confirmatory_bundle_sha256=file_hash(frozen_root / "confirmatory-tasks.json"),
        confirmatory_bundle_hash=str(task_bundle["bundle_hash"]),
        confirmatory_task_hashes={task.task_id: task.task_hash for task in tasks},
        control_spec_hash=spec.spec_hash,
        environment=environment,
        minimum_coverage=panel.minimum_coverage,
        maximum_unsupported_claim_rate=(panel.maximum_unsupported_claim_rate),
        bootstrap_resamples=panel.bootstrap_resamples,
        bootstrap_seed=panel.bootstrap_seed,
        frozen_artifact_file_sha256s=frozen_hashes,
    )
    write_json_model(preregistration_path, preregistration)
    return load_mechanism_confirmatory_preregistration(root)


def load_mechanism_confirmatory_preregistration(
    output_dir: Path | str,
) -> MechanismConfirmatoryPreregistration:
    """Verify the result-blind freeze without opening result artifacts."""

    root = Path(output_dir).resolve()
    preregistration = MechanismConfirmatoryPreregistration.model_validate_json(
        (root / "preregistration.json").read_text(encoding="utf-8")
    )
    actual = _frozen_artifact_hashes(root)
    if actual != preregistration.frozen_artifact_file_sha256s:
        raise MechanismConfirmatoryIntegrityError("confirmatory frozen artifact index drift")
    spec = LoopSpec.model_validate_json(
        (root / "control" / "loop-spec.json").read_text(encoding="utf-8")
    )
    if spec.spec_hash != preregistration.control_spec_hash:
        raise MechanismConfirmatoryIntegrityError(
            "confirmatory Control Graph differs from preregistration"
        )
    tasks = _tasks_from_bundle(
        _load_confirmatory_task_bundle(root / "frozen" / "confirmatory-tasks.json")
    )
    if {task.task_id: task.task_hash for task in tasks} != preregistration.confirmatory_task_hashes:
        raise MechanismConfirmatoryIntegrityError(
            "confirmatory task hashes differ from preregistration"
        )
    return preregistration


def build_mechanism_confirmatory_control_spec(
    *,
    source_sha256: str,
    task_ids: Sequence[str],
) -> LoopSpec:
    """Build an acyclic one-shot graph with a deterministic scientific gate."""

    ordered_ids = sorted(task_ids)
    if len(ordered_ids) != _EXPECTED_CONFIRMATORY_TASK_COUNT:
        raise ValueError("confirmatory Control Graph requires six tasks")
    nodes = [
        LoopNodeSpec(
            node_id="start",
            version="1",
            kind=LoopNodeKind.START,
        ),
        LoopNodeSpec(
            node_id="reveal-confirmatory",
            version="1",
            kind=LoopNodeKind.ACTION,
            handler_id="handler.reveal-confirmatory",
            required_permission_ids=["holdout.reveal.confirmatory"],
            retry_policy=LoopRetryPolicy(max_attempts=1),
            side_effecting=True,
            may_reveal_holdout=True,
        ),
    ]
    for task_id in ordered_ids:
        nodes.append(
            LoopNodeSpec(
                node_id=f"execute-{task_id}",
                version="1",
                kind=LoopNodeKind.ACTION,
                handler_id=f"handler.execute.{task_id}",
                required_permission_ids=["code.execute.sandbox"],
                retry_policy=LoopRetryPolicy(max_attempts=1),
                minimum_usage=LoopUsage(tool_calls=1),
                side_effecting=True,
                adaptive=False,
                allowed_after_holdout_reveal=True,
            )
        )
    nodes.extend(
        [
            LoopNodeSpec(
                node_id="adjudicate",
                version="1",
                kind=LoopNodeKind.GATE,
                handler_id="handler.adjudicate",
                actor_kind=ActorKind.DETERMINISTIC_POLICY,
                retry_policy=LoopRetryPolicy(max_attempts=1),
                adaptive=False,
                allowed_after_holdout_reveal=True,
                scientific_gate=True,
            ),
            LoopNodeSpec(
                node_id="positive-result",
                version="1",
                kind=LoopNodeKind.TERMINAL,
                terminal_status=LoopRunStatus.SUCCEEDED,
            ),
            LoopNodeSpec(
                node_id="negative-result",
                version="1",
                kind=LoopNodeKind.TERMINAL,
                terminal_status=LoopRunStatus.NEGATIVE_RESULT,
            ),
        ]
    )
    edges: list[LoopEdgeSpec] = [
        LoopEdgeSpec(
            edge_id="edge.start.reveal",
            version="1",
            kind=LoopEdgeKind.NEXT,
            source_node_id="start",
            target_node_id="reveal-confirmatory",
            guards=[always_guard("guard.start.reveal")],
        )
    ]
    execution_nodes = [f"execute-{task_id}" for task_id in ordered_ids]
    edges.append(
        LoopEdgeSpec(
            edge_id="edge.reveal.first-task",
            version="1",
            kind=LoopEdgeKind.NEXT,
            source_node_id="reveal-confirmatory",
            target_node_id=execution_nodes[0],
            guards=[
                _outcome_guard(
                    "guard.reveal.succeeded",
                    [LoopNodeOutcome.SUCCEEDED],
                )
            ],
        )
    )
    for index, source_node_id in enumerate(execution_nodes):
        target_node_id = (
            execution_nodes[index + 1] if index + 1 < len(execution_nodes) else "adjudicate"
        )
        edges.append(
            LoopEdgeSpec(
                edge_id=f"edge.{source_node_id}.{target_node_id}",
                version="1",
                kind=LoopEdgeKind.NEXT,
                source_node_id=source_node_id,
                target_node_id=target_node_id,
                guards=[
                    _outcome_guard(
                        f"guard.{source_node_id}.terminal",
                        [
                            LoopNodeOutcome.SUCCEEDED,
                            LoopNodeOutcome.NEGATIVE_RESULT,
                        ],
                    )
                ],
            )
        )
    edges.extend(
        [
            LoopEdgeSpec(
                edge_id="edge.adjudicate.positive",
                version="1",
                kind=LoopEdgeKind.NEXT,
                source_node_id="adjudicate",
                target_node_id="positive-result",
                priority=10,
                guards=[
                    _outcome_guard(
                        "guard.adjudicate.positive",
                        [LoopNodeOutcome.SUCCEEDED],
                    )
                ],
            ),
            LoopEdgeSpec(
                edge_id="edge.adjudicate.negative",
                version="1",
                kind=LoopEdgeKind.NEXT,
                source_node_id="adjudicate",
                target_node_id="negative-result",
                priority=20,
                guards=[
                    _outcome_guard(
                        "guard.adjudicate.negative",
                        [LoopNodeOutcome.NEGATIVE_RESULT],
                    )
                ],
            ),
        ]
    )
    return LoopSpec.create(
        spec_id=f"mechanism-confirmatory-{source_sha256[:16]}",
        version="1",
        graph_version=1,
        task_id=_TASK_ID,
        entry_node_id="start",
        nodes=nodes,
        edges=edges,
        budget_policy=LoopBudgetPolicy(
            policy_id="budget.mechanism-confirmatory",
            version="1",
            max_steps=10,
            max_tokens=0,
            max_estimated_cost_usd=0.0,
            max_wall_time_seconds=300.0,
            max_tool_calls=_EXPECTED_CONFIRMATORY_TASK_COUNT,
            max_total_retries=0,
            max_failures=_EXPECTED_CONFIRMATORY_TASK_COUNT,
            max_human_interventions=0,
        ),
        permission_policy=LoopPermissionPolicy(
            policy_id="permission.mechanism-confirmatory",
            version="1",
            granted_permission_ids=[
                "code.execute.sandbox",
                "holdout.reveal.confirmatory",
            ],
            approval_required_permission_ids=[],
            forbidden_permission_ids=[
                "code.execute.unrestricted",
                "external.submit",
                "network.access",
                "secret.read",
            ],
            deny_unknown=True,
            permission_expansion_allowed=False,
        ),
        holdout_policy=LoopHoldoutPolicy(
            policy_id="holdout.mechanism-confirmatory",
            version="1",
            initial_state=HoldoutState.SEALED,
            forbid_adaptive_after_reveal=True,
            reveal_permission_id="holdout.reveal.confirmatory",
        ),
        immutable_during_run=True,
        model_graph_proposals_allowed=False,
        scientific_gates_deterministic=True,
        permission_expansion_allowed=False,
        release_authorization_allowed=False,
    )


def run_task2612_confirmatory(
    *,
    output_dir: Path | str,
    clock: Callable[[], datetime] | None = None,
    control_fault_injector: Callable[[str, str], None] | None = None,
) -> MechanismConfirmatoryManifest:
    """Execute the frozen panel once, reproduce it, and seal all evidence."""

    now = clock or (lambda: datetime.now(timezone.utc))
    root = Path(output_dir).resolve()
    manifest_path = root / "confirmatory-manifest.json"
    if manifest_path.is_file():
        return load_mechanism_confirmatory(root)
    preregistration = load_mechanism_confirmatory_preregistration(root)
    current_environment = _current_execution_environment()
    if current_environment.environment_hash != preregistration.environment.environment_hash:
        raise MechanismConfirmatoryIntegrityError(
            "current execution environment differs from preregistration"
        )
    spec = LoopSpec.model_validate_json(
        (root / "control" / "loop-spec.json").read_text(encoding="utf-8")
    )
    tasks = _tasks_from_bundle(
        _load_confirmatory_task_bundle(root / "frozen" / "confirmatory-tasks.json")
    )
    source_text = (root / "frozen" / "run.py").read_text(encoding="utf-8")
    executor = _MechanismConfirmatoryExecutor(
        root=root,
        preregistration=preregistration,
        tasks=tasks,
        source_text=source_text,
        clock=now,
    )
    journal_path = root / "control" / "journal"
    journal = (
        EventJournal.open(journal_path)
        if journal_path.exists()
        else EventJournal.create(
            journal_path,
            run_id=preregistration.run_id,
            created_at=preregistration.frozen_at,
        )
    )
    runtime = ControlGraphRuntime(
        spec=spec,
        journal=journal,
        executor=executor,
        clock=now,
        fault_injector=control_fault_injector,
    )
    start_request = LoopStartRequest(
        run_id=preregistration.run_id,
        task_id=_TASK_ID,
        mechanism_family=("model-authored-multi-signal-degradation-gate"),
        variables={
            "preregistration_hash": preregistration.preregistration_hash,
            "generated_source_sha256": (preregistration.generated_source_sha256),
            "panel_hash": preregistration.panel_hash,
            "maximum_task_attempts": 1,
        },
        approvals=[],
    )
    snapshot = runtime.start(start_request)
    if snapshot.state.status is LoopRunStatus.RUNNING:
        snapshot = runtime.resume()
    if snapshot.state.status not in {
        LoopRunStatus.SUCCEEDED,
        LoopRunStatus.NEGATIVE_RESULT,
    }:
        raise MechanismConfirmatoryIntegrityError(
            f"confirmatory Control Graph ended as {snapshot.state.status.value}"
        )
    write_json_model(root / "control" / "terminal-snapshot.json", snapshot)
    endpoint = MechanismConfirmatoryEndpoint.model_validate_json(
        (root / "endpoint.json").read_text(encoding="utf-8")
    )
    expected_runtime_status = (
        LoopRunStatus.SUCCEEDED
        if endpoint.outcome is MechanismScientificOutcome.POSITIVE_RESULT
        else LoopRunStatus.NEGATIVE_RESULT
    )
    if snapshot.state.status is not expected_runtime_status:
        raise MechanismConfirmatoryIntegrityError(
            "Control Graph terminal status differs from endpoint"
        )
    provenance = _write_confirmatory_provenance(
        root=root,
        preregistration=preregistration,
        endpoint=endpoint,
        snapshot=snapshot,
    )
    reproduction = reproduce_task2612_confirmatory(
        output_dir=root,
        preregistration=preregistration,
        endpoint=endpoint,
        tasks=tasks,
        source_text=source_text,
        clock=now,
    )
    rollback = rehearse_task2612_confirmatory_rollback(
        output_dir=root,
        preregistration=preregistration,
        endpoint=endpoint,
    )
    results = _load_primary_results(root, preregistration)
    trace = provenance.require_claim_trace(f"claim.{preregistration.run_id}.endpoint")
    attempts = snapshot.state.attempts_by_node
    task_node_ids = [f"execute-{task_id}" for task_id in preregistration.confirmatory_task_hashes]
    checks = {
        "all_frozen_artifacts_match": (
            _frozen_artifact_hashes(root) == preregistration.frozen_artifact_file_sha256s
        ),
        "control_graph_immutable_and_terminal": (
            snapshot.spec_hash == preregistration.control_spec_hash
            and snapshot.seal_hash is not None
        ),
        "endpoint_is_hash_valid": (endpoint.endpoint_hash == endpoint.calculated_hash()),
        "environment_matches_preregistration": (
            current_environment.environment_hash == preregistration.environment.environment_hash
        ),
        "exact_task_result_count": (len(results) == _EXPECTED_CONFIRMATORY_TASK_COUNT),
        "no_network_used": all(not result.network_used for result in results),
        "no_secret_environment_keys": all(
            not _secret_environment_keys(result.explicit_environment_keys) for result in results
        ),
        "one_control_attempt_per_task": all(
            attempts.get(node_id) == 1 for node_id in task_node_ids
        ),
        "provenance_claim_trace_complete": bool(trace.evidence_ids),
        "reproduction_passed": reproduction.passed,
        "rollback_rehearsal_passed": rollback.passed,
        "scientific_endpoint_not_rewritten": (
            MechanismConfirmatoryEndpoint.model_validate_json(
                (root / "endpoint.json").read_text(encoding="utf-8")
            ).endpoint_hash
            == endpoint.endpoint_hash
        ),
    }
    if snapshot.seal_hash is None:
        raise MechanismConfirmatoryIntegrityError("terminal Control Graph lacks a journal seal")
    evaluation = MechanismEvaluationSecurityReport.create(
        endpoint_hash=endpoint.endpoint_hash,
        scientific_outcome=endpoint.outcome,
        control_spec_hash=spec.spec_hash,
        control_snapshot_hash=snapshot.snapshot_hash,
        journal_lineage_hash=snapshot.lineage_hash,
        journal_seal_hash=snapshot.seal_hash,
        provenance_bundle_hash=provenance.bundle_hash,
        reproduction_report_hash=reproduction.report_hash,
        rollback_report_hash=rollback.report_hash,
        checks=checks,
    )
    write_json_model(
        root / "evaluation" / "security-report.json",
        evaluation,
    )
    status = (
        MechanismConfirmatoryStatus.VERIFICATION_FAILED
        if not evaluation.passed
        else (
            MechanismConfirmatoryStatus.POSITIVE_RESULT
            if endpoint.outcome is MechanismScientificOutcome.POSITIVE_RESULT
            else MechanismConfirmatoryStatus.NEGATIVE_RESULT
        )
    )
    manifest = MechanismConfirmatoryManifest.create(
        run_id=preregistration.run_id,
        status=status,
        completed_at=now(),
        preregistration_hash=preregistration.preregistration_hash,
        endpoint_hash=endpoint.endpoint_hash,
        scientific_projection_hash=endpoint.scientific_projection_hash,
        scientific_outcome=endpoint.outcome,
        control_snapshot_hash=snapshot.snapshot_hash,
        journal_lineage_hash=snapshot.lineage_hash,
        journal_seal_hash=snapshot.seal_hash,
        provenance_bundle_hash=provenance.bundle_hash,
        evaluation_security_report_hash=evaluation.report_hash,
        reproduction_report_hash=reproduction.report_hash,
        rollback_report_hash=rollback.report_hash,
        artifact_file_sha256s=_artifact_file_hashes(root),
    )
    write_json_model(manifest_path, manifest)
    return load_mechanism_confirmatory(root)


def load_mechanism_confirmatory(
    output_dir: Path | str,
) -> MechanismConfirmatoryManifest:
    """Verify the terminal manifest and every indexed confirmatory artifact."""

    root = Path(output_dir).resolve()
    manifest = MechanismConfirmatoryManifest.model_validate_json(
        (root / "confirmatory-manifest.json").read_text(encoding="utf-8")
    )
    if _artifact_file_hashes(root) != manifest.artifact_file_sha256s:
        raise MechanismConfirmatoryIntegrityError("confirmatory terminal artifact index drift")
    endpoint = MechanismConfirmatoryEndpoint.model_validate_json(
        (root / "endpoint.json").read_text(encoding="utf-8")
    )
    if (
        endpoint.endpoint_hash != manifest.endpoint_hash
        or endpoint.scientific_projection_hash != manifest.scientific_projection_hash
        or endpoint.outcome is not manifest.scientific_outcome
    ):
        raise MechanismConfirmatoryIntegrityError(
            "terminal manifest differs from scientific endpoint"
        )
    ProvenanceBundle.load_json(root / "provenance" / "provenance-v2.json")
    return manifest


def reproduce_task2612_confirmatory(
    *,
    output_dir: Path | str,
    preregistration: MechanismConfirmatoryPreregistration,
    endpoint: MechanismConfirmatoryEndpoint,
    tasks: Sequence[MechanismEvaluationTask],
    source_text: str,
    clock: Callable[[], datetime],
) -> MechanismReproductionReport:
    """Rerun exact frozen code in a clean directory after endpoint sealing."""

    root = Path(output_dir).resolve() / "reproduction"
    report_path = root / "report.json"
    if report_path.is_file():
        report = MechanismReproductionReport.model_validate_json(
            report_path.read_text(encoding="utf-8")
        )
        actual = _relative_file_hashes(root / "execution")
        if actual != report.artifact_file_sha256s:
            raise MechanismConfirmatoryIntegrityError("reproduction artifact index drift")
        return report
    if root.exists() and any(root.iterdir()):
        raise MechanismConfirmatoryIntegrityError("reproduction directory is partial, not clean")
    root.mkdir(parents=True, exist_ok=True)
    primary_results = {
        result.task_id: result
        for result in _load_primary_results(
            Path(output_dir).resolve(),
            preregistration,
        )
    }
    reproduced: list[MechanismConfirmatoryTaskResult] = []
    for task in sorted(tasks, key=lambda item: item.task_id):
        result = _execute_task_once(
            output_dir=root / "execution" / task.task_id,
            run_id=f"{preregistration.run_id}-reproduction-{task.task_id}",
            task=task,
            source_text=source_text,
            source_sha256=preregistration.generated_source_sha256,
            execution_role=(MechanismTaskExecutionRole.INDEPENDENT_REPRODUCTION),
            clock=clock,
        )
        write_json_model(
            root / "execution" / task.task_id / "task-result.json",
            result,
        )
        reproduced.append(result)
    matches = {
        result.task_id: (
            result.scientific_projection_hash
            == primary_results[result.task_id].scientific_projection_hash
        )
        for result in reproduced
    }
    reproduced_projection_hash = _reproduced_endpoint_projection_hash(
        preregistration=preregistration,
        results=reproduced,
    )
    report = MechanismReproductionReport.create(
        source_endpoint_hash=endpoint.endpoint_hash,
        source_scientific_projection_hash=endpoint.scientific_projection_hash,
        reproduced_task_result_hashes=[result.result_hash for result in reproduced],
        reproduced_task_projection_hashes=[
            result.scientific_projection_hash for result in reproduced
        ],
        task_projection_matches=matches,
        reproduced_scientific_projection_hash=reproduced_projection_hash,
        artifact_file_sha256s=_relative_file_hashes(root / "execution"),
    )
    write_json_model(report_path, report)
    return report


def rehearse_task2612_confirmatory_rollback(
    *,
    output_dir: Path | str,
    preregistration: MechanismConfirmatoryPreregistration,
    endpoint: MechanismConfirmatoryEndpoint,
) -> MechanismRollbackReport:
    """Copy the pre-reveal state without deleting or rewriting the endpoint."""

    root = Path(output_dir).resolve()
    rollback_root = root / "rollback" / "pre-reveal"
    report_path = root / "rollback" / "report.json"
    if report_path.is_file():
        report = MechanismRollbackReport.model_validate_json(
            report_path.read_text(encoding="utf-8")
        )
        actual = _rollback_artifact_hashes(rollback_root)
        if actual != report.rollback_artifact_file_sha256s:
            raise MechanismConfirmatoryIntegrityError("rollback rehearsal artifact drift")
        return report
    if rollback_root.exists():
        raise MechanismConfirmatoryIntegrityError(
            "rollback rehearsal target already exists without a report"
        )
    rollback_root.mkdir(parents=True)
    shutil.copyfile(
        root / "preregistration.json",
        rollback_root / "preregistration.json",
    )
    shutil.copytree(root / "frozen", rollback_root / "frozen")
    (rollback_root / "control").mkdir()
    shutil.copyfile(
        root / "control" / "loop-spec.json",
        rollback_root / "control" / "loop-spec.json",
    )
    actual = _rollback_artifact_hashes(rollback_root)
    expected = {
        "control/loop-spec.json": file_hash(root / "control" / "loop-spec.json"),
        "preregistration.json": file_hash(root / "preregistration.json"),
        **{
            f"frozen/{path}": digest
            for path, digest in preregistration.frozen_artifact_file_sha256s.items()
            if path.startswith("frozen/")
            for path in [path.removeprefix("frozen/")]
        },
    }
    if (
        endpoint.endpoint_hash
        != MechanismConfirmatoryEndpoint.model_validate_json(
            (root / "endpoint.json").read_text(encoding="utf-8")
        ).endpoint_hash
    ):
        raise MechanismConfirmatoryIntegrityError(
            "canonical endpoint changed during rollback rehearsal"
        )
    report = MechanismRollbackReport.create(
        source_endpoint_hash=endpoint.endpoint_hash,
        rollback_target_preregistration_hash=(preregistration.preregistration_hash),
        rollback_artifact_file_sha256s=actual,
        expected_artifact_file_sha256s=expected,
    )
    write_json_model(report_path, report)
    return report


class _MechanismConfirmatoryExecutor:
    executor_id = "mechanism.confirmatory.executor"
    executor_version = "1"

    def __init__(
        self,
        *,
        root: Path,
        preregistration: MechanismConfirmatoryPreregistration,
        tasks: Sequence[MechanismEvaluationTask],
        source_text: str,
        clock: Callable[[], datetime],
    ) -> None:
        self.root = root
        self.preregistration = preregistration
        self.tasks = {task.task_id: task for task in tasks}
        self.source_text = source_text
        self.clock = clock

    def execute(self, request: LoopNodeExecutionRequest) -> LoopNodeResult:
        receipt_path = self.root / "control" / "receipts" / f"{request.node.node_id}.json"
        request_hash = canonical_sha256(request)
        if receipt_path.is_file():
            receipt = MechanismControlNodeReceipt.model_validate_json(
                receipt_path.read_text(encoding="utf-8")
            )
            if (
                receipt.request_hash != request_hash
                or receipt.idempotency_key != request.idempotency_key
            ):
                raise MechanismConfirmatoryIntegrityError(
                    "control node idempotency receipt conflicts with request"
                )
            _verify_produced_files(self.root, receipt.produced_file_sha256s)
            return receipt.result
        handler_id = request.node.handler_id or ""
        if handler_id == "handler.reveal-confirmatory":
            result, produced = self._reveal(request)
        elif handler_id.startswith("handler.execute."):
            task_id = handler_id.removeprefix("handler.execute.")
            result, produced = self._execute_task(request, task_id)
        elif handler_id == "handler.adjudicate":
            result, produced = self._adjudicate(request)
        else:
            raise MechanismConfirmatoryIntegrityError(f"unknown confirmatory handler {handler_id}")
        receipt = MechanismControlNodeReceipt.create(
            node_id=request.node.node_id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            result=result,
            produced_file_sha256s=produced,
        )
        write_json_model(receipt_path, receipt)
        return result

    def _reveal(
        self,
        request: LoopNodeExecutionRequest,
    ) -> tuple[LoopNodeResult, dict[str, str]]:
        if request.holdout_state is not HoldoutState.SEALED:
            raise MechanismConfirmatoryIntegrityError(
                "confirmatory reveal node did not start sealed"
            )
        path = self.root / "control" / "reveal-receipt.json"
        if path.is_file():
            payload = _read_json(path)
            if payload.get("preregistration_hash") != (self.preregistration.preregistration_hash):
                raise MechanismConfirmatoryIntegrityError("confirmatory reveal receipt drift")
        else:
            write_json_model(
                path,
                {
                    "schema_version": "mechanism-confirmatory-reveal-v1",
                    "run_id": self.preregistration.run_id,
                    "preregistration_hash": (self.preregistration.preregistration_hash),
                    "panel_hash": self.preregistration.panel_hash,
                    "task_hashes": (self.preregistration.confirmatory_task_hashes),
                    "revealed_at": self.clock()
                    .astimezone(timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "adaptive_change_allowed": False,
                    "external_submission_authorized": False,
                },
            )
        relative = path.relative_to(self.root).as_posix()
        result = LoopNodeResult(
            outcome=LoopNodeOutcome.SUCCEEDED,
            summary=(
                "The exact preregistered confirmatory task bundle was revealed "
                "without changing source, graph, metric, uncertainty, or gates."
            ),
            output_artifact_ids=[f"artifact.reveal.{file_hash(path)[:16]}"],
            reveal_holdout=True,
            side_effect_committed=True,
        )
        return result, {relative: file_hash(path)}

    def _execute_task(
        self,
        request: LoopNodeExecutionRequest,
        task_id: str,
    ) -> tuple[LoopNodeResult, dict[str, str]]:
        if request.holdout_state is not HoldoutState.REVEALED:
            raise MechanismConfirmatoryIntegrityError("confirmatory task executed before reveal")
        task = self.tasks.get(task_id)
        if task is None:
            raise MechanismConfirmatoryIntegrityError(f"confirmatory task {task_id} is not frozen")
        task_root = self.root / "confirmatory" / task.task_id
        result_path = task_root / "task-result.json"
        if result_path.is_file():
            task_result = MechanismConfirmatoryTaskResult.model_validate_json(
                result_path.read_text(encoding="utf-8")
            )
        else:
            task_result = _execute_task_once(
                output_dir=task_root,
                run_id=f"{self.preregistration.run_id}-{task.task_id}",
                task=task,
                source_text=self.source_text,
                source_sha256=(self.preregistration.generated_source_sha256),
                execution_role=(MechanismTaskExecutionRole.PRIMARY_CONFIRMATORY),
                clock=self.clock,
            )
            write_json_model(result_path, task_result)
        _validate_task_result_against_preregistration(
            task_result,
            self.preregistration,
        )
        relative = result_path.relative_to(self.root).as_posix()
        outcome = (
            LoopNodeOutcome.SUCCEEDED
            if task_result.execution_succeeded
            else LoopNodeOutcome.NEGATIVE_RESULT
        )
        loop_result = LoopNodeResult(
            outcome=outcome,
            summary=(
                f"Confirmatory task {task.task_id} reached a terminal "
                f"{'successful' if task_result.execution_succeeded else 'failed'} "
                "Harness result and will not be retried."
            ),
            usage=LoopUsage(tool_calls=1),
            output_artifact_ids=[f"artifact.task.{task.task_id}.{task_result.result_hash[:12]}"],
            variable_updates={
                f"result_hash.{task.task_id}": task_result.result_hash,
                f"execution_succeeded.{task.task_id}": (task_result.execution_succeeded),
            },
            side_effect_committed=True,
        )
        return loop_result, {relative: file_hash(result_path)}

    def _adjudicate(
        self,
        request: LoopNodeExecutionRequest,
    ) -> tuple[LoopNodeResult, dict[str, str]]:
        if request.holdout_state is not HoldoutState.REVEALED:
            raise MechanismConfirmatoryIntegrityError(
                "adjudication requires a revealed terminal panel"
            )
        endpoint_path = self.root / "endpoint.json"
        if endpoint_path.is_file():
            endpoint = MechanismConfirmatoryEndpoint.model_validate_json(
                endpoint_path.read_text(encoding="utf-8")
            )
        else:
            results = _load_primary_results(
                self.root,
                self.preregistration,
            )
            endpoint = MechanismConfirmatoryEndpoint.create(
                preregistration=self.preregistration,
                results=results,
                started_at=self.preregistration.frozen_at,
                completed_at=self.clock(),
            )
            write_json_model(endpoint_path, endpoint)
        relative = endpoint_path.relative_to(self.root).as_posix()
        outcome = (
            LoopNodeOutcome.SUCCEEDED
            if endpoint.outcome is MechanismScientificOutcome.POSITIVE_RESULT
            else LoopNodeOutcome.NEGATIVE_RESULT
        )
        result = LoopNodeResult(
            outcome=outcome,
            summary=(
                "The deterministic task-level bootstrap adjudicator sealed "
                f"{endpoint.outcome.value}; this result cannot be rewritten."
            ),
            output_artifact_ids=[f"artifact.endpoint.{endpoint.endpoint_hash[:16]}"],
            variable_updates={
                "endpoint_hash": endpoint.endpoint_hash,
                "scientific_outcome": endpoint.outcome.value,
            },
            side_effect_committed=True,
        )
        return result, {relative: file_hash(endpoint_path)}


def _execute_task_once(
    *,
    output_dir: Path,
    run_id: str,
    task: MechanismEvaluationTask,
    source_text: str,
    source_sha256: str,
    execution_role: MechanismTaskExecutionRole,
    clock: Callable[[], datetime],
) -> MechanismConfirmatoryTaskResult:
    try:
        spec, episode, observation, decisions = run_generated_code_harness(
            run_id=run_id,
            episode_id=f"{run_id}-episode",
            output_dir=output_dir,
            source_text=source_text,
            claims=[claim.public_payload() for claim in task.claims],
            preflight_approved=True,
            clock=clock(),
        )
        succeeded = (
            episode.final_outcome.status is EpisodeOutcomeStatus.SUCCEEDED
            and observation is not None
            and observation.output_sha256 is not None
            and len(decisions) == len(task.claims)
        )
        failure_codes = (
            []
            if succeeded
            else (
                [failure.code for failure in episode.failures] or ["confirmatory_harness_execution"]
            )
        )
        return MechanismConfirmatoryTaskResult.create(
            execution_role=execution_role,
            task=task,
            generated_source_sha256=source_sha256,
            decisions=decisions if succeeded else [],
            execution_succeeded=succeeded,
            failure_codes=failure_codes,
            explicit_environment_keys=(
                observation.explicit_environment_keys if observation is not None else []
            ),
            harness_spec_hash=spec.spec_hash,
            harness_episode_hash=episode.episode_hash,
            output_artifact_sha256=(observation.output_sha256 if observation is not None else None),
        )
    except (
        OSError,
        RuntimeError,
        ValidationError,
        ValueError,
    ) as exc:
        summary = _safe_exception_digest(exc)
        return MechanismConfirmatoryTaskResult.create(
            execution_role=execution_role,
            task=task,
            generated_source_sha256=source_sha256,
            decisions=[],
            execution_succeeded=False,
            failure_codes=[f"confirmatory_execution_{summary[:16]}"],
            explicit_environment_keys=[],
        )


def _write_confirmatory_provenance(
    *,
    root: Path,
    preregistration: MechanismConfirmatoryPreregistration,
    endpoint: MechanismConfirmatoryEndpoint,
    snapshot: LoopRunSnapshot,
) -> ProvenanceBundle:
    path = root / "provenance" / "provenance-v2.json"
    if path.is_file():
        bundle = ProvenanceBundle.load_json(path)
        bundle.require_claim_trace(f"claim.{preregistration.run_id}.endpoint")
        return bundle
    started_at = preregistration.frozen_at
    completed_at = endpoint.completed_at
    claim_id = f"claim.{preregistration.run_id}.endpoint"
    evidence_id = f"evidence.{preregistration.run_id}.endpoint"
    validation_id = f"validation.{preregistration.run_id}.endpoint"
    decision_id = f"decision.{preregistration.run_id}.endpoint"
    source_entity_id = f"entity.{preregistration.run_id}.preregistration"
    code_entity_id = f"entity.{preregistration.run_id}.source"
    endpoint_entity_id = f"entity.{preregistration.run_id}.endpoint"
    decision_entity_id = f"entity.{preregistration.run_id}.decision"
    execution_activity_id = f"activity.{preregistration.run_id}.execution"
    validation_activity_id = f"activity.{preregistration.run_id}.validation"
    decision_activity_id = f"activity.{preregistration.run_id}.decision"
    executor_agent_id = "agent.mechanism-confirmatory.harness"
    policy_agent_id = "agent.mechanism-confirmatory.adjudicator"
    plan_id = f"plan.{preregistration.run_id}"
    bundle = ProvenanceBundle.create(
        bundle_id=f"provenance.{preregistration.run_id}",
        project_id=_PROJECT_ID,
        run_id=preregistration.run_id,
        created_at=completed_at,
        entities=[
            Entity(
                entity_id=source_entity_id,
                kind=EntityKind.SOURCE_SNAPSHOT,
                label="Frozen mechanism confirmatory preregistration",
                content_digest=preregistration.preregistration_hash,
                source_uri=f"urn:autoresearch:{preregistration.run_id}:preregistration",
                media_type="application/json",
                valid_from=started_at,
            ),
            Entity(
                entity_id=code_entity_id,
                kind=EntityKind.CODE,
                label="Exact model-authored mechanism source",
                content_digest=preregistration.generated_source_sha256,
                media_type="text/x-python",
                valid_from=started_at,
            ),
            Entity(
                entity_id=endpoint_entity_id,
                kind=EntityKind.EXPERIMENT_RECORD,
                label="Immutable confirmatory scientific endpoint",
                content_digest=endpoint.endpoint_hash,
                media_type="application/json",
                attributes={
                    "scientific_outcome": endpoint.outcome.value,
                    "scientific_projection_hash": (endpoint.scientific_projection_hash),
                },
                valid_from=completed_at,
            ),
            Entity(
                entity_id=decision_entity_id,
                kind=EntityKind.DECISION,
                label="Deterministic confirmatory gate decision",
                content_digest=canonical_sha256(
                    {
                        "endpoint_hash": endpoint.endpoint_hash,
                        "outcome": endpoint.outcome.value,
                    }
                ),
                media_type="application/json",
                valid_from=completed_at,
            ),
        ],
        activities=[
            Activity(
                activity_id=execution_activity_id,
                kind=ActivityKind.EXECUTION,
                label="One-shot confirmatory Harness and Control Graph execution",
                started_at=started_at,
                ended_at=completed_at,
                valid_from=started_at,
                valid_to=completed_at,
                attributes={
                    "control_spec_hash": preregistration.control_spec_hash,
                    "journal_lineage_hash": snapshot.lineage_hash,
                },
            ),
            Activity(
                activity_id=validation_activity_id,
                kind=ActivityKind.VALIDATION,
                label="Validate confirmatory endpoint and registered gates",
                started_at=completed_at,
                ended_at=completed_at,
                valid_from=completed_at,
                valid_to=completed_at,
            ),
            Activity(
                activity_id=decision_activity_id,
                kind=ActivityKind.DECISION,
                label="Adjudicate frozen confirmatory scientific endpoint",
                started_at=completed_at,
                ended_at=completed_at,
                valid_from=completed_at,
                valid_to=completed_at,
            ),
        ],
        agents=[
            Agent(
                agent_id=executor_agent_id,
                kind=ProvenanceAgentKind.SOFTWARE,
                label="Bounded Harness and generated-code sandbox",
                implementation_hash=preregistration.environment.environment_hash,
                valid_from=started_at,
            ),
            Agent(
                agent_id=policy_agent_id,
                kind=ProvenanceAgentKind.DETERMINISTIC_POLICY,
                label="Frozen confirmatory bootstrap adjudicator",
                implementation_hash=preregistration.control_spec_hash,
                valid_from=started_at,
            ),
        ],
        plans=[
            Plan(
                plan_id=plan_id,
                title="Task 261.2.3 confirmatory preregistration",
                description=(
                    "Freeze exact v12 source, environment, panel, uncertainty, "
                    "gates, and one-shot stop policy before reveal."
                ),
                content_digest=preregistration.preregistration_hash,
                valid_from=started_at,
            )
        ],
        usages=[
            Usage(
                usage_id=f"usage.{preregistration.run_id}.preregistration",
                activity_id=execution_activity_id,
                entity_id=source_entity_id,
                role="frozen preregistration",
                at_time=started_at,
                valid_from=started_at,
            ),
            Usage(
                usage_id=f"usage.{preregistration.run_id}.source",
                activity_id=execution_activity_id,
                entity_id=code_entity_id,
                role="exact generated mechanism source",
                at_time=started_at,
                valid_from=started_at,
            ),
        ],
        generations=[
            Generation(
                generation_id=f"generation.{preregistration.run_id}.endpoint",
                entity_id=endpoint_entity_id,
                activity_id=execution_activity_id,
                at_time=completed_at,
                valid_from=completed_at,
            ),
            Generation(
                generation_id=f"generation.{preregistration.run_id}.decision",
                entity_id=decision_entity_id,
                activity_id=decision_activity_id,
                at_time=completed_at,
                valid_from=completed_at,
            ),
        ],
        derivations=[
            Derivation(
                derivation_id=f"derivation.{preregistration.run_id}.endpoint-source",
                generated_entity_id=endpoint_entity_id,
                used_entity_id=code_entity_id,
                activity_id=execution_activity_id,
                valid_from=completed_at,
            ),
            Derivation(
                derivation_id=f"derivation.{preregistration.run_id}.decision-endpoint",
                generated_entity_id=decision_entity_id,
                used_entity_id=endpoint_entity_id,
                activity_id=decision_activity_id,
                valid_from=completed_at,
            ),
        ],
        associations=[
            Association(
                association_id=f"association.{preregistration.run_id}.execution",
                activity_id=execution_activity_id,
                agent_id=executor_agent_id,
                role="bounded executor",
                plan_id=plan_id,
                at_time=started_at,
                valid_from=started_at,
            ),
            Association(
                association_id=f"association.{preregistration.run_id}.validation",
                activity_id=validation_activity_id,
                agent_id=policy_agent_id,
                role="deterministic validator",
                plan_id=plan_id,
                at_time=completed_at,
                valid_from=completed_at,
            ),
            Association(
                association_id=f"association.{preregistration.run_id}.decision",
                activity_id=decision_activity_id,
                agent_id=policy_agent_id,
                role="deterministic adjudicator",
                plan_id=plan_id,
                at_time=completed_at,
                valid_from=completed_at,
            ),
        ],
        source_snapshots=[
            SourceSnapshot(
                snapshot_id=f"snapshot.{preregistration.run_id}.preregistration",
                entity_id=source_entity_id,
                source_uri=f"urn:autoresearch:{preregistration.run_id}:preregistration",
                retrieved_at=started_at,
                content_digest=preregistration.preregistration_hash,
                media_type="application/json",
                valid_from=started_at,
            )
        ],
        claims=[
            Claim(
                claim_id=claim_id,
                statement=(
                    "The exact frozen v12 mechanism produced the recorded "
                    f"{endpoint.outcome.value} under the preregistered six-task "
                    "confirmatory gate."
                ),
                project_id=_PROJECT_ID,
                confidence=1.0,
                core=True,
                valid_from=completed_at,
            )
        ],
        evidence=[
            Evidence(
                evidence_id=evidence_id,
                claim_id=claim_id,
                artifact_entity_id=endpoint_entity_id,
                source_entity_id=source_entity_id,
                source_snapshot_id=(f"snapshot.{preregistration.run_id}.preregistration"),
                generating_activity_id=execution_activity_id,
                responsible_agent_ids=[executor_agent_id],
                validation_ids=[validation_id],
                summary=(
                    "Six independent tasks were executed once and aggregated by "
                    "the frozen task-level percentile bootstrap policy."
                ),
                confidence=1.0,
                direction=EvidenceDirection.SUPPORTS,
                valid_from=completed_at,
            )
        ],
        counterevidence=[],
        validations=[
            Validation(
                validation_id=validation_id,
                subject_id=evidence_id,
                activity_id=validation_activity_id,
                agent_id=policy_agent_id,
                status=ValidationStatus.PASSED,
                summary=(
                    "Endpoint counts, confidence bounds, task hashes, source hash, "
                    "and deterministic gate decision are internally consistent."
                ),
                checked_at=completed_at,
                artifact_entity_id=endpoint_entity_id,
                valid_from=completed_at,
            )
        ],
        decisions=[
            Decision(
                decision_id=decision_id,
                claim_ids=[claim_id],
                activity_id=decision_activity_id,
                responsible_agent_id=policy_agent_id,
                validation_ids=[validation_id],
                artifact_entity_id=decision_entity_id,
                outcome=endpoint.outcome.value,
                rationale=(
                    "The endpoint direction is the conjunction of all frozen "
                    "coverage, unsupported-risk, execution, network, and one-shot gates."
                ),
                decided_at=completed_at,
                valid_from=completed_at,
            )
        ],
        tool_invocations=[
            ToolInvocation(
                invocation_id=f"invocation.{preregistration.run_id}.harness",
                activity_id=execution_activity_id,
                agent_id=executor_agent_id,
                tool_name="generated-code-harness",
                request_digest=preregistration.preregistration_hash,
                response_digest=endpoint.endpoint_hash,
                input_entity_ids=[source_entity_id, code_entity_id],
                output_entity_ids=[endpoint_entity_id],
                status=InvocationStatus.SUCCEEDED,
                started_at=started_at,
                completed_at=completed_at,
                valid_from=started_at,
            )
        ],
        model_interactions=[],
        metadata={
            "schema_family": _SCHEMA_VERSION,
            "development_manifest_hash": (preregistration.development_manifest_hash),
            "mechanism_program_hash": (preregistration.mechanism_program_hash),
            "confirmatory_task_count": _EXPECTED_CONFIRMATORY_TASK_COUNT,
            "confirmatory_results_revealed": True,
            "external_submission_authorized": False,
        },
    )
    bundle.require_claim_trace(claim_id)
    bundle.save_json(path)
    return ProvenanceBundle.load_json(path)


def _current_execution_environment() -> MechanismExecutionEnvironment:
    project_root = Path(__file__).resolve().parents[3]
    implementation_paths = [
        Path(__file__).resolve(),
        project_root / "src" / "autoresearch" / "campaign" / "mechanism_benchmark.py",
        project_root / "src" / "autoresearch" / "campaign" / "mechanism_development.py",
        project_root / "src" / "autoresearch" / "campaign" / "mechanism_sandbox.py",
        project_root / "src" / "autoresearch" / "experiments" / "executor.py",
        project_root / "src" / "autoresearch" / "kernel" / "loop.py",
        project_root / "src" / "autoresearch" / "kernel" / "journal.py",
        project_root / "src" / "autoresearch" / "kernel" / "provenance.py",
    ]
    inherited_hashes = {
        key: hashlib.sha256(value.encode("utf-8")).hexdigest()
        for key in ("SYSTEMROOT", "WINDIR")
        if (value := os.environ.get(key))
    }
    commit_sha, clean = _repository_state(project_root)
    return MechanismExecutionEnvironment.create(
        python_version=platform.python_version(),
        python_implementation=platform.python_implementation(),
        python_executable_sha256=file_hash(Path(sys.executable)),
        operating_system=f"{platform.system()} {platform.release()}",
        machine=platform.machine() or "unknown",
        explicit_environment_keys=[
            "PYTHONHASHSEED",
            "PYTHONIOENCODING",
            "PYTHONUTF8",
            "TEMP",
            "TMP",
            *inherited_hashes,
        ],
        inherited_environment_value_sha256s=inherited_hashes,
        dependency_lock_sha256=file_hash(project_root / "poetry.lock"),
        implementation_file_sha256s={
            path.relative_to(project_root).as_posix(): file_hash(path)
            for path in implementation_paths
        },
        repository_commit_sha=commit_sha,
        repository_was_clean=clean,
    )


def _repository_state(project_root: Path) -> tuple[str | None, bool]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None, False
    return (commit if len(commit) == 40 else None), not bool(status.strip())


def _load_confirmatory_task_bundle(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    if payload.get("schema_version") != "mechanism-confirmatory-task-bundle-v1":
        raise MechanismConfirmatoryIntegrityError("confirmatory task bundle schema mismatch")
    if payload.get("executed") is not False:
        raise MechanismConfirmatoryIntegrityError("confirmatory bundle was already marked executed")
    if payload.get("result_artifact_count") != 0:
        raise MechanismConfirmatoryIntegrityError("confirmatory bundle already contains results")
    expected_hash = canonical_sha256(
        {key: value for key, value in payload.items() if key != "bundle_hash"}
    )
    if payload.get("bundle_hash") != expected_hash:
        raise MechanismConfirmatoryIntegrityError("confirmatory task bundle_hash mismatch")
    return payload


def _tasks_from_bundle(
    payload: Mapping[str, Any],
) -> list[MechanismEvaluationTask]:
    tasks_value = payload.get("tasks")
    if not isinstance(tasks_value, list):
        raise MechanismConfirmatoryIntegrityError("confirmatory task bundle lacks tasks")
    tasks = [MechanismEvaluationTask.model_validate(value) for value in tasks_value]
    if len(tasks) != _EXPECTED_CONFIRMATORY_TASK_COUNT:
        raise MechanismConfirmatoryIntegrityError("confirmatory task bundle must contain six tasks")
    if tasks != sorted(tasks, key=lambda item: item.task_id):
        raise MechanismConfirmatoryIntegrityError("confirmatory task bundle is not task-id sorted")
    return tasks


def _validate_development_causal_chain(
    *,
    development: MechanismDevelopmentManifest,
    round_freeze: MechanismRoundFreeze,
    panel: MechanismPanelSpec,
    program: MechanismProgram,
    code_evidence: GeneratedCodeEvidence,
    serialization: Mapping[str, Any],
    tasks: Sequence[MechanismEvaluationTask],
    source_path: Path,
) -> None:
    expected = (
        development.round_freeze_hash == round_freeze.freeze_hash
        and development.panel_hash == panel.panel_hash
        and development.proposal_hash == round_freeze.proposal_hash
        and development.generated_source_sha256 == round_freeze.generated_source_sha256
        and development.generated_code_evidence_hash == code_evidence.evidence_hash
        and program.program_hash == serialization.get("mechanism_program_hash")
        and source_path.is_file()
        and file_hash(source_path) == development.generated_source_sha256
        and code_evidence.source_sha256 == development.generated_source_sha256
    )
    if not expected:
        raise MechanismConfirmatoryIntegrityError("development causal chain is inconsistent")
    references = {reference.task_id: reference for reference in panel.confirmatory_tasks}
    if {task.task_id for task in tasks} != set(references):
        raise MechanismConfirmatoryIntegrityError(
            "frozen confirmatory tasks differ from panel references"
        )
    development_fingerprints = [
        reference.source_fingerprint for reference in panel.development_tasks
    ]
    confirmatory_fingerprints = [
        reference.source_fingerprint for reference in panel.confirmatory_tasks
    ]
    if (
        len(development_fingerprints) != len(set(development_fingerprints))
        or len(confirmatory_fingerprints) != len(set(confirmatory_fingerprints))
        or set(development_fingerprints) & set(confirmatory_fingerprints)
    ):
        raise MechanismConfirmatoryIntegrityError(
            "development and confirmatory source fingerprints are not disjoint"
        )
    for task in tasks:
        reference = references[task.task_id]
        if task.reference() != reference:
            raise MechanismConfirmatoryIntegrityError(
                f"confirmatory task {task.task_id} differs from panel reference"
            )


def _bootstrap_task_ratios(
    results: Sequence[MechanismConfirmatoryTaskResult],
    *,
    resamples: int,
    seed: int,
) -> tuple[tuple[float, float], tuple[float, float]]:
    rng = random.Random(seed)
    coverages: list[float] = []
    risks: list[float] = []
    result_count = len(results)
    for _ in range(resamples):
        sampled = [results[rng.randrange(result_count)] for _ in range(result_count)]
        claim_count = sum(result.claim_count for result in sampled)
        accepted_count = sum(result.accepted_count for result in sampled)
        unsupported_count = sum(result.accepted_unsupported_count for result in sampled)
        coverages.append(accepted_count / claim_count)
        risks.append(unsupported_count / accepted_count if accepted_count else 1.0)
    coverages.sort()
    risks.sort()
    return _percentile_interval(coverages), _percentile_interval(risks)


def _percentile_interval(values: Sequence[float]) -> tuple[float, float]:
    count = len(values)
    lower = max(0, int(0.025 * count) - 1)
    upper = min(count - 1, int(0.975 * count))
    return float(values[lower]), float(values[upper])


def _load_primary_results(
    root: Path,
    preregistration: MechanismConfirmatoryPreregistration,
) -> list[MechanismConfirmatoryTaskResult]:
    results: list[MechanismConfirmatoryTaskResult] = []
    for task_id in sorted(preregistration.confirmatory_task_hashes):
        path = root / "confirmatory" / task_id / "task-result.json"
        if not path.is_file():
            raise MechanismConfirmatoryIntegrityError(
                f"confirmatory task result missing for {task_id}"
            )
        result = MechanismConfirmatoryTaskResult.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        _validate_task_result_against_preregistration(result, preregistration)
        results.append(result)
    return results


def _validate_task_result_against_preregistration(
    result: MechanismConfirmatoryTaskResult,
    preregistration: MechanismConfirmatoryPreregistration,
) -> None:
    if (
        result.execution_role is not MechanismTaskExecutionRole.PRIMARY_CONFIRMATORY
        or result.task_hash != preregistration.confirmatory_task_hashes.get(result.task_id)
        or result.generated_source_sha256 != preregistration.generated_source_sha256
    ):
        raise MechanismConfirmatoryIntegrityError(
            f"confirmatory task result {result.task_id} violates preregistration"
        )


def _reproduced_endpoint_projection_hash(
    *,
    preregistration: MechanismConfirmatoryPreregistration,
    results: Sequence[MechanismConfirmatoryTaskResult],
) -> str:
    return canonical_sha256(
        _build_endpoint_scientific_projection(
            preregistration=preregistration,
            results=results,
        )
    )


def _build_endpoint_scientific_projection(
    *,
    preregistration: MechanismConfirmatoryPreregistration,
    results: Sequence[MechanismConfirmatoryTaskResult],
) -> dict[str, Any]:
    """Independently derive every scientific field from frozen inputs and results."""

    claim_count = sum(result.claim_count for result in results)
    accepted_count = sum(result.accepted_count for result in results)
    unsupported_count = sum(result.accepted_unsupported_count for result in results)
    coverage = accepted_count / claim_count
    unsupported_rate = unsupported_count / accepted_count if accepted_count else 0.0
    coverage_ci, unsupported_ci = _bootstrap_task_ratios(
        results,
        resamples=preregistration.bootstrap_resamples,
        seed=preregistration.bootstrap_seed,
    )
    gates = {
        "all_task_executions_succeeded": all(result.execution_succeeded for result in results),
        "exact_confirmatory_task_count": (len(results) == _EXPECTED_CONFIRMATORY_TASK_COUNT),
        "minimum_coverage_met": (coverage >= preregistration.minimum_coverage),
        "no_network_used": all(not result.network_used for result in results),
        "one_shot_attempts_only": all(result.one_shot_attempt_count == 1 for result in results),
        "unsupported_rate_ci_upper_met": (
            unsupported_ci[1] <= preregistration.maximum_unsupported_claim_rate
        ),
        "unsupported_rate_point_met": (
            unsupported_rate <= preregistration.maximum_unsupported_claim_rate
        ),
    }
    outcome = (
        MechanismScientificOutcome.POSITIVE_RESULT
        if all(gates.values())
        else MechanismScientificOutcome.NEGATIVE_RESULT
    )
    return {
        "schema_version": "mechanism-confirmatory-scientific-projection-v1",
        "preregistration_hash": preregistration.preregistration_hash,
        "panel_hash": preregistration.panel_hash,
        "generated_source_sha256": preregistration.generated_source_sha256,
        "task_projection_hashes": sorted(result.scientific_projection_hash for result in results),
        "task_count": len(results),
        "successful_task_count": sum(result.execution_succeeded for result in results),
        "failed_task_count": sum(not result.execution_succeeded for result in results),
        "claim_count": claim_count,
        "accepted_count": accepted_count,
        "accepted_unsupported_count": unsupported_count,
        "coverage": coverage,
        "coverage_ci95_lower": coverage_ci[0],
        "coverage_ci95_upper": coverage_ci[1],
        "unsupported_claim_rate": unsupported_rate,
        "unsupported_rate_ci95_lower": unsupported_ci[0],
        "unsupported_rate_ci95_upper": unsupported_ci[1],
        "minimum_coverage": preregistration.minimum_coverage,
        "maximum_unsupported_claim_rate": (preregistration.maximum_unsupported_claim_rate),
        "bootstrap_resamples": preregistration.bootstrap_resamples,
        "bootstrap_seed": preregistration.bootstrap_seed,
        "gates": dict(sorted(gates.items())),
        "failure_codes": sorted(gate_id for gate_id, passed in gates.items() if not passed),
        "outcome": outcome,
        "confirmatory_results_revealed": True,
        "scientific_result_created": True,
    }


def _task_scientific_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "mechanism-confirmatory-task-projection-v1",
        "task_id": payload["task_id"],
        "task_hash": payload["task_hash"],
        "generated_source_sha256": payload["generated_source_sha256"],
        "decisions": payload["decisions"],
        "claim_count": payload["claim_count"],
        "accepted_count": payload["accepted_count"],
        "accepted_unsupported_count": payload["accepted_unsupported_count"],
        "coverage": payload["coverage"],
        "unsupported_claim_rate": payload["unsupported_claim_rate"],
        "execution_succeeded": payload["execution_succeeded"],
        "failure_codes": payload["failure_codes"],
        "network_used": payload["network_used"],
        "one_shot_attempt_count": payload["one_shot_attempt_count"],
    }


def _endpoint_scientific_projection(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    fields = (
        "preregistration_hash",
        "panel_hash",
        "generated_source_sha256",
        "task_projection_hashes",
        "task_count",
        "successful_task_count",
        "failed_task_count",
        "claim_count",
        "accepted_count",
        "accepted_unsupported_count",
        "coverage",
        "coverage_ci95_lower",
        "coverage_ci95_upper",
        "unsupported_claim_rate",
        "unsupported_rate_ci95_lower",
        "unsupported_rate_ci95_upper",
        "minimum_coverage",
        "maximum_unsupported_claim_rate",
        "bootstrap_resamples",
        "bootstrap_seed",
        "gates",
        "failure_codes",
        "outcome",
        "confirmatory_results_revealed",
        "scientific_result_created",
    )
    return {
        "schema_version": "mechanism-confirmatory-scientific-projection-v1",
        **{field: payload[field] for field in fields},
    }


def _outcome_guard(
    guard_id: str,
    outcomes: Sequence[LoopNodeOutcome],
) -> LoopGuardSpec:
    return LoopGuardSpec(
        guard_id=guard_id,
        version="1",
        kind=LoopGuardKind.OUTCOME,
        outcomes=list(outcomes),
    )


def _frozen_artifact_hashes(root: Path) -> dict[str, str]:
    paths = [
        *sorted((root / "frozen").rglob("*")),
        root / "control" / "loop-spec.json",
    ]
    return {path.relative_to(root).as_posix(): file_hash(path) for path in paths if path.is_file()}


def _artifact_file_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): file_hash(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and path.name != "confirmatory-manifest.json"
        and not path.name.endswith(".tmp")
    }


def _relative_file_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): file_hash(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.name.endswith(".tmp")
    }


def _rollback_artifact_hashes(root: Path) -> dict[str, str]:
    return _relative_file_hashes(root)


def _verify_produced_files(root: Path, expected: Mapping[str, str]) -> None:
    actual = {
        relative: file_hash(root / relative) for relative in expected if (root / relative).is_file()
    }
    if actual != dict(expected):
        raise MechanismConfirmatoryIntegrityError("control node produced-file hash drift")


def _secret_environment_keys(keys: Sequence[str]) -> list[str]:
    markers = ("api", "auth", "credential", "key", "password", "secret", "token")
    return sorted(key for key in keys if any(marker in key.casefold() for marker in markers))


def _safe_exception_digest(error: BaseException) -> str:
    return hashlib.sha256(
        f"{type(error).__name__}:{' '.join(str(error).split())[:400]}".encode()
    ).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise MechanismConfirmatoryIntegrityError(f"expected JSON object at {path}")
    return payload


__all__ = [
    "MechanismConfirmatoryEndpoint",
    "MechanismConfirmatoryIntegrityError",
    "MechanismConfirmatoryManifest",
    "MechanismConfirmatoryPreregistration",
    "MechanismConfirmatoryStatus",
    "MechanismConfirmatoryTaskResult",
    "MechanismEvaluationSecurityReport",
    "MechanismExecutionEnvironment",
    "MechanismReproductionReport",
    "MechanismRollbackReport",
    "MechanismScientificOutcome",
    "MechanismTaskExecutionRole",
    "build_mechanism_confirmatory_control_spec",
    "freeze_task2612_confirmatory",
    "load_mechanism_confirmatory",
    "load_mechanism_confirmatory_preregistration",
    "rehearse_task2612_confirmatory_rollback",
    "reproduce_task2612_confirmatory",
    "run_task2612_confirmatory",
]
