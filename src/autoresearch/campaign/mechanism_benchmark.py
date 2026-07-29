"""Frozen development and confirmatory fixtures for task 261.2.

The fixtures exercise a generated selective claim gate without reusing the ten
revealed parent Sprint tasks.  Development labels are intentionally available
to the deterministic evaluator.  Confirmatory payloads are committed here but
must not be passed to the generator or executed before task 261.2.3 admits a
verified code freeze.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from autoresearch.campaign.mechanism_round import (
    MechanismPanelSpec,
    MechanismTaskReference,
    ParentSprintEvidence,
)
from autoresearch.kernel.contracts import (
    KernelContract,
    NonEmptyText,
    Sha256,
    StableId,
    canonical_sha256,
)


class ClaimDecision(str, Enum):
    """Admissible generated-mechanism decisions."""

    ACCEPT = "accept"
    ABSTAIN = "abstain"


class DevelopmentScreenDecision(str, Enum):
    """Truthful terminal states before confirmatory preregistration."""

    ADVANCE_TO_PREREGISTRATION = "advance_to_preregistration"
    NEGATIVE_DEVELOPMENT = "negative_development"
    BLOCKED = "blocked"


class MechanismClaimFixture(KernelContract):
    """One claim with public signals and an evaluator-only support label."""

    claim_id: StableId
    support_score: float = Field(ge=0.0, le=1.0)
    contradiction_score: float = Field(ge=0.0, le=1.0)
    uncertainty: float = Field(ge=0.0, le=1.0)
    independent_source_count: int = Field(ge=0, le=20)
    source_quality: float = Field(ge=0.0, le=1.0)
    supported: bool

    def public_payload(self) -> dict[str, str | float | int]:
        """Return the model-visible input without the evaluator label."""

        return {
            "claim_id": self.claim_id,
            "support_score": self.support_score,
            "contradiction_score": self.contradiction_score,
            "uncertainty": self.uncertainty,
            "independent_source_count": self.independent_source_count,
            "source_quality": self.source_quality,
        }


class MechanismEvaluationTask(KernelContract):
    """A content-addressed task whose label never enters generated code input."""

    schema_version: Literal["mechanism-evaluation-task-v1"] = (
        "mechanism-evaluation-task-v1"
    )
    task_id: StableId
    task_family: StableId
    description: NonEmptyText
    claims: list[MechanismClaimFixture] = Field(min_length=6)
    task_hash: Sha256

    @field_validator("claims")
    @classmethod
    def _normalize_claims(
        cls,
        value: list[MechanismClaimFixture],
    ) -> list[MechanismClaimFixture]:
        claim_ids = [claim.claim_id for claim in value]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("mechanism task claim IDs must be unique")
        return sorted(value, key=lambda claim: claim.claim_id)

    @model_validator(mode="after")
    def _validate_hash(self) -> MechanismEvaluationTask:
        if self.task_hash != self.calculated_hash():
            raise ValueError("mechanism evaluation task_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> MechanismEvaluationTask:
        """Normalize a task and attach its canonical digest."""

        payload = dict(values)
        payload["schema_version"] = "mechanism-evaluation-task-v1"
        claims = [
            claim
            if isinstance(claim, MechanismClaimFixture)
            else MechanismClaimFixture.model_validate(claim)
            for claim in payload["claims"]
        ]
        payload["claims"] = [
            claim.model_dump(mode="json")
            for claim in sorted(claims, key=lambda item: item.claim_id)
        ]
        payload["task_hash"] = canonical_sha256(payload)
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the task digest."""

        return canonical_sha256(
            self.model_dump(mode="json", exclude={"task_hash"})
        )

    def reference(self) -> MechanismTaskReference:
        """Project the task into the result-blind panel contract."""

        public_contract = {
            "schema_version": "mechanism-claim-input-v1",
            "required_fields": [
                "claim_id",
                "contradiction_score",
                "independent_source_count",
                "source_quality",
                "support_score",
                "uncertainty",
            ],
            "generated_output": [
                "claim_id",
                "decision",
                "reason_code",
                "risk_score",
            ],
        }
        source_payload = {
            "task_id": self.task_id,
            "task_family": self.task_family,
            "claims": [
                claim.model_dump(mode="json") for claim in self.claims
            ],
        }
        return MechanismTaskReference(
            task_id=self.task_id,
            task_family=self.task_family,
            source_fingerprint=canonical_sha256(source_payload),
            task_contract_hash=canonical_sha256(public_contract),
        )


class GeneratedClaimDecision(KernelContract):
    """One schema-checked decision emitted by generated code."""

    claim_id: StableId
    decision: ClaimDecision
    risk_score: float = Field(ge=0.0, le=1.0)
    reason_code: StableId


class MechanismDevelopmentTaskResult(KernelContract):
    """One development task evaluated through a sealed Harness episode."""

    schema_version: Literal["mechanism-development-task-result-v1"] = (
        "mechanism-development-task-result-v1"
    )
    task_id: StableId
    task_hash: Sha256
    generated_source_sha256: Sha256
    harness_spec_hash: Sha256
    harness_episode_hash: Sha256
    output_artifact_sha256: Sha256
    decisions: list[GeneratedClaimDecision]
    claim_count: int = Field(ge=1)
    accepted_count: int = Field(ge=0)
    accepted_unsupported_count: int = Field(ge=0)
    coverage: float = Field(ge=0.0, le=1.0)
    unsupported_claim_rate: float = Field(ge=0.0, le=1.0)
    execution_succeeded: bool
    confirmatory_result: Literal[False] = False
    result_hash: Sha256

    @model_validator(mode="after")
    def _validate_result(self) -> MechanismDevelopmentTaskResult:
        if self.claim_count != len(self.decisions):
            raise ValueError("development claim count contradicts decisions")
        accepted = [
            decision
            for decision in self.decisions
            if decision.decision is ClaimDecision.ACCEPT
        ]
        if self.accepted_count != len(accepted):
            raise ValueError("development accepted count contradicts decisions")
        expected_coverage = len(accepted) / self.claim_count
        if abs(self.coverage - expected_coverage) > 1e-12:
            raise ValueError("development coverage contradicts decisions")
        expected_risk = (
            self.accepted_unsupported_count / len(accepted)
            if accepted
            else 0.0
        )
        if abs(self.unsupported_claim_rate - expected_risk) > 1e-12:
            raise ValueError("development unsupported rate contradicts decisions")
        if self.accepted_unsupported_count > self.accepted_count:
            raise ValueError("unsupported accepted count exceeds accepted count")
        if self.result_hash != self.calculated_hash():
            raise ValueError("development task result_hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        task: MechanismEvaluationTask,
        generated_source_sha256: str,
        harness_spec_hash: str,
        harness_episode_hash: str,
        output_artifact_sha256: str,
        decisions: list[GeneratedClaimDecision],
        execution_succeeded: bool,
    ) -> MechanismDevelopmentTaskResult:
        """Compute task metrics from evaluator labels, never self-reported metrics."""

        decision_by_id = {decision.claim_id: decision for decision in decisions}
        expected_ids = {claim.claim_id for claim in task.claims}
        if set(decision_by_id) != expected_ids:
            raise ValueError("generated decisions do not cover the exact task claims")
        ordered = [decision_by_id[claim.claim_id] for claim in task.claims]
        labels = {claim.claim_id: claim.supported for claim in task.claims}
        accepted = [
            decision
            for decision in ordered
            if decision.decision is ClaimDecision.ACCEPT
        ]
        unsupported = sum(not labels[decision.claim_id] for decision in accepted)
        claim_count = len(ordered)
        coverage = len(accepted) / claim_count
        risk = unsupported / len(accepted) if accepted else 0.0
        payload: dict[str, Any] = {
            "schema_version": "mechanism-development-task-result-v1",
            "task_id": task.task_id,
            "task_hash": task.task_hash,
            "generated_source_sha256": generated_source_sha256,
            "harness_spec_hash": harness_spec_hash,
            "harness_episode_hash": harness_episode_hash,
            "output_artifact_sha256": output_artifact_sha256,
            "decisions": [
                decision.model_dump(mode="json") for decision in ordered
            ],
            "claim_count": claim_count,
            "accepted_count": len(accepted),
            "accepted_unsupported_count": unsupported,
            "coverage": coverage,
            "unsupported_claim_rate": risk,
            "execution_succeeded": execution_succeeded,
            "confirmatory_result": False,
        }
        payload["result_hash"] = canonical_sha256(payload)
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the task result digest."""

        return canonical_sha256(
            self.model_dump(mode="json", exclude={"result_hash"})
        )


class MechanismDevelopmentScreen(KernelContract):
    """Deterministic development decision with confirmatory evidence still sealed."""

    schema_version: Literal["mechanism-development-screen-v1"] = (
        "mechanism-development-screen-v1"
    )
    round_freeze_hash: Sha256
    panel_hash: Sha256
    generated_source_sha256: Sha256
    development_result_hashes: list[Sha256] = Field(min_length=3)
    claim_count: int = Field(ge=1)
    accepted_count: int = Field(ge=0)
    accepted_unsupported_count: int = Field(ge=0)
    coverage: float = Field(ge=0.0, le=1.0)
    unsupported_claim_rate: float = Field(ge=0.0, le=1.0)
    minimum_coverage: float = Field(gt=0.0, le=1.0)
    maximum_unsupported_claim_rate: float = Field(ge=0.0, lt=1.0)
    all_harness_episodes_succeeded: bool
    decision: DevelopmentScreenDecision
    failure_codes: list[StableId]
    confirmatory_results_revealed: Literal[False] = False
    confirmatory_result_artifact_count: Literal[0] = 0
    scientific_result_created: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    screen_hash: Sha256

    @field_validator("development_result_hashes", "failure_codes")
    @classmethod
    def _normalize_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("development screen identifiers must be unique")
        return sorted(value)

    @model_validator(mode="after")
    def _validate_screen(self) -> MechanismDevelopmentScreen:
        expected_decision, expected_failures = _screen_verdict(
            all_succeeded=self.all_harness_episodes_succeeded,
            coverage=self.coverage,
            unsupported_rate=self.unsupported_claim_rate,
            minimum_coverage=self.minimum_coverage,
            maximum_unsupported_rate=self.maximum_unsupported_claim_rate,
        )
        if self.decision is not expected_decision:
            raise ValueError("development decision contradicts deterministic metrics")
        if self.failure_codes != expected_failures:
            raise ValueError("development failure codes contradict deterministic metrics")
        if self.accepted_unsupported_count > self.accepted_count:
            raise ValueError("screen unsupported accepted count exceeds accepted count")
        if self.claim_count <= 0:
            raise ValueError("development screen requires claims")
        if abs(self.coverage - self.accepted_count / self.claim_count) > 1e-12:
            raise ValueError("development screen coverage is inconsistent")
        expected_risk = (
            self.accepted_unsupported_count / self.accepted_count
            if self.accepted_count
            else 0.0
        )
        if abs(self.unsupported_claim_rate - expected_risk) > 1e-12:
            raise ValueError("development screen unsupported rate is inconsistent")
        if self.screen_hash != self.calculated_hash():
            raise ValueError("development screen_hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        round_freeze_hash: str,
        panel: MechanismPanelSpec,
        generated_source_sha256: str,
        results: list[MechanismDevelopmentTaskResult],
    ) -> MechanismDevelopmentScreen:
        """Aggregate development tasks under the preregistered risk/coverage rule."""

        if len(results) != len(panel.development_tasks):
            raise ValueError("development result count does not match frozen panel")
        expected_task_ids = [task.task_id for task in panel.development_tasks]
        observed_task_ids = sorted(result.task_id for result in results)
        if observed_task_ids != expected_task_ids:
            raise ValueError("development results do not match frozen panel tasks")
        if any(
            result.generated_source_sha256 != generated_source_sha256
            for result in results
        ):
            raise ValueError("development task executed a different generated source")
        claim_count = sum(result.claim_count for result in results)
        accepted_count = sum(result.accepted_count for result in results)
        unsupported = sum(
            result.accepted_unsupported_count for result in results
        )
        coverage = accepted_count / claim_count
        risk = unsupported / accepted_count if accepted_count else 0.0
        all_succeeded = all(result.execution_succeeded for result in results)
        decision, failures = _screen_verdict(
            all_succeeded=all_succeeded,
            coverage=coverage,
            unsupported_rate=risk,
            minimum_coverage=panel.minimum_coverage,
            maximum_unsupported_rate=panel.maximum_unsupported_claim_rate,
        )
        payload: dict[str, Any] = {
            "schema_version": "mechanism-development-screen-v1",
            "round_freeze_hash": round_freeze_hash,
            "panel_hash": panel.panel_hash,
            "generated_source_sha256": generated_source_sha256,
            "development_result_hashes": sorted(
                result.result_hash for result in results
            ),
            "claim_count": claim_count,
            "accepted_count": accepted_count,
            "accepted_unsupported_count": unsupported,
            "coverage": coverage,
            "unsupported_claim_rate": risk,
            "minimum_coverage": panel.minimum_coverage,
            "maximum_unsupported_claim_rate": panel.maximum_unsupported_claim_rate,
            "all_harness_episodes_succeeded": all_succeeded,
            "decision": decision.value,
            "failure_codes": failures,
            "confirmatory_results_revealed": False,
            "confirmatory_result_artifact_count": 0,
            "scientific_result_created": False,
            "external_submission_authorized": False,
        }
        payload["screen_hash"] = canonical_sha256(payload)
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the development-screen digest."""

        return canonical_sha256(
            self.model_dump(mode="json", exclude={"screen_hash"})
        )


def build_task2612_panel(parent: ParentSprintEvidence) -> MechanismPanelSpec:
    """Freeze the independent partitions before generated code sees development data."""

    development = [task.reference() for task in task2612_development_tasks()]
    confirmatory = [task.reference() for task in task2612_confirmatory_tasks()]
    return MechanismPanelSpec.create(
        parent=parent,
        panel_id="task2612-independent-claim-panel-v1",
        development_tasks=development,
        confirmatory_tasks=confirmatory,
        minimum_coverage=0.60,
        maximum_unsupported_claim_rate=0.10,
        bootstrap_resamples=20_000,
        bootstrap_seed=261203,
    )


def task2612_development_tasks() -> list[MechanismEvaluationTask]:
    """Return three revealed development tasks outside the parent Sprint families."""

    return [
        _task(
            "task2612-dev-literature",
            "literature_claims",
            "Mixed literature-attribution claims with strong, weak, and conflicting evidence.",
            _claim_rows("dl", _DEVELOPMENT_ROWS[0]),
        ),
        _task(
            "task2612-dev-execution",
            "execution_claims",
            "Execution and provenance claims with independent source-count variation.",
            _claim_rows("de", _DEVELOPMENT_ROWS[1]),
        ),
        _task(
            "task2612-dev-figure",
            "figure_claims",
            "Figure-description claims under uncertainty and source-quality variation.",
            _claim_rows("df", _DEVELOPMENT_ROWS[2]),
        ),
    ]


def task2612_confirmatory_tasks() -> list[MechanismEvaluationTask]:
    """Return six sealed task payloads reserved for task 261.2.3."""

    families = (
        "cross_domain_claims",
        "distribution_shift_claims",
        "conflict_heavy_claims",
        "sparse_evidence_claims",
        "high_uncertainty_claims",
        "mixed_provenance_claims",
    )
    descriptions = (
        "Cross-domain claim evidence held out from mechanism generation.",
        "Shifted signal combinations held out from development.",
        "Contradictory-source cases held out from development.",
        "Sparse-source cases held out from development.",
        "High-uncertainty cases held out from development.",
        "Mixed literature and execution provenance held out from development.",
    )
    return [
        _task(
            f"task2612-confirm-{index + 1:02d}",
            family,
            description,
            _claim_rows(f"c{index + 1}", rows),
        )
        for index, (family, description, rows) in enumerate(
            zip(
                families,
                descriptions,
                _CONFIRMATORY_ROWS,
                strict=True,
            )
        )
    ]


def _task(
    task_id: str,
    task_family: str,
    description: str,
    claims: list[MechanismClaimFixture],
) -> MechanismEvaluationTask:
    return MechanismEvaluationTask.create(
        task_id=task_id,
        task_family=task_family,
        description=description,
        claims=claims,
    )


def _claim_rows(
    prefix: str,
    rows: tuple[tuple[float, float, float, int, float, bool], ...],
) -> list[MechanismClaimFixture]:
    return [
        MechanismClaimFixture(
            claim_id=f"{prefix}-{index:02d}",
            support_score=support,
            contradiction_score=contradiction,
            uncertainty=uncertainty,
            independent_source_count=count,
            source_quality=quality,
            supported=label,
        )
        for index, (support, contradiction, uncertainty, count, quality, label) in enumerate(
            rows,
            start=1,
        )
    ]


def _screen_verdict(
    *,
    all_succeeded: bool,
    coverage: float,
    unsupported_rate: float,
    minimum_coverage: float,
    maximum_unsupported_rate: float,
) -> tuple[DevelopmentScreenDecision, list[str]]:
    failures: list[str] = []
    if not all_succeeded:
        failures.append("development_harness_execution")
    if coverage < minimum_coverage:
        failures.append("minimum_coverage")
    if unsupported_rate > maximum_unsupported_rate:
        failures.append("maximum_unsupported_claim_rate")
    if "development_harness_execution" in failures:
        return DevelopmentScreenDecision.BLOCKED, sorted(failures)
    if failures:
        return DevelopmentScreenDecision.NEGATIVE_DEVELOPMENT, sorted(failures)
    return DevelopmentScreenDecision.ADVANCE_TO_PREREGISTRATION, []


# Six supported and two unsupported cases per development task.  The labels are
# evaluator-only and are never included in the generated source input.
_DEVELOPMENT_ROWS = (
    (
        (0.93, 0.03, 0.08, 4, 0.94, True),
        (0.88, 0.05, 0.12, 3, 0.90, True),
        (0.82, 0.08, 0.18, 3, 0.86, True),
        (0.79, 0.12, 0.20, 2, 0.82, True),
        (0.76, 0.10, 0.24, 2, 0.80, True),
        (0.72, 0.14, 0.27, 3, 0.78, True),
        (0.42, 0.58, 0.64, 1, 0.62, False),
        (0.31, 0.72, 0.73, 0, 0.48, False),
    ),
    (
        (0.91, 0.04, 0.10, 5, 0.91, True),
        (0.86, 0.06, 0.15, 4, 0.88, True),
        (0.83, 0.11, 0.17, 3, 0.84, True),
        (0.80, 0.09, 0.22, 2, 0.83, True),
        (0.75, 0.13, 0.25, 3, 0.79, True),
        (0.71, 0.15, 0.29, 2, 0.77, True),
        (0.47, 0.52, 0.61, 1, 0.59, False),
        (0.28, 0.76, 0.79, 0, 0.43, False),
    ),
    (
        (0.92, 0.02, 0.09, 4, 0.93, True),
        (0.87, 0.07, 0.13, 3, 0.89, True),
        (0.84, 0.09, 0.16, 3, 0.87, True),
        (0.78, 0.11, 0.21, 2, 0.81, True),
        (0.74, 0.12, 0.26, 2, 0.78, True),
        (0.70, 0.16, 0.28, 3, 0.76, True),
        (0.44, 0.57, 0.67, 1, 0.57, False),
        (0.25, 0.80, 0.82, 0, 0.40, False),
    ),
)


_CONFIRMATORY_ROWS = (
    (
        (0.89, 0.05, 0.14, 4, 0.91, True),
        (0.81, 0.10, 0.19, 3, 0.85, True),
        (0.77, 0.13, 0.23, 2, 0.82, True),
        (0.73, 0.16, 0.27, 2, 0.79, True),
        (0.69, 0.18, 0.31, 3, 0.77, True),
        (0.66, 0.20, 0.34, 2, 0.74, True),
        (0.49, 0.49, 0.58, 1, 0.61, False),
        (0.36, 0.65, 0.71, 1, 0.52, False),
    ),
    (
        (0.86, 0.08, 0.18, 3, 0.88, True),
        (0.80, 0.12, 0.23, 2, 0.84, True),
        (0.74, 0.17, 0.29, 3, 0.79, True),
        (0.71, 0.18, 0.32, 2, 0.76, True),
        (0.67, 0.22, 0.35, 2, 0.73, True),
        (0.64, 0.24, 0.38, 3, 0.72, True),
        (0.52, 0.45, 0.55, 1, 0.63, False),
        (0.40, 0.61, 0.68, 1, 0.55, False),
    ),
    (
        (0.90, 0.04, 0.12, 4, 0.92, True),
        (0.85, 0.08, 0.16, 3, 0.87, True),
        (0.79, 0.14, 0.22, 3, 0.83, True),
        (0.75, 0.18, 0.26, 2, 0.80, True),
        (0.72, 0.19, 0.29, 3, 0.78, True),
        (0.68, 0.23, 0.33, 2, 0.75, True),
        (0.59, 0.62, 0.48, 3, 0.70, False),
        (0.46, 0.74, 0.60, 2, 0.64, False),
    ),
    (
        (0.88, 0.06, 0.15, 2, 0.89, True),
        (0.82, 0.09, 0.20, 2, 0.84, True),
        (0.77, 0.12, 0.24, 2, 0.81, True),
        (0.73, 0.15, 0.28, 1, 0.78, True),
        (0.69, 0.18, 0.32, 1, 0.75, True),
        (0.65, 0.22, 0.36, 1, 0.72, True),
        (0.51, 0.48, 0.59, 0, 0.60, False),
        (0.38, 0.67, 0.72, 0, 0.50, False),
    ),
    (
        (0.91, 0.05, 0.20, 4, 0.92, True),
        (0.84, 0.09, 0.25, 3, 0.86, True),
        (0.79, 0.12, 0.29, 3, 0.82, True),
        (0.75, 0.15, 0.33, 2, 0.79, True),
        (0.72, 0.17, 0.36, 3, 0.77, True),
        (0.68, 0.20, 0.39, 2, 0.74, True),
        (0.53, 0.43, 0.69, 1, 0.62, False),
        (0.41, 0.59, 0.81, 1, 0.54, False),
    ),
    (
        (0.90, 0.03, 0.11, 5, 0.93, True),
        (0.85, 0.07, 0.17, 4, 0.88, True),
        (0.80, 0.10, 0.21, 3, 0.84, True),
        (0.76, 0.13, 0.25, 3, 0.81, True),
        (0.71, 0.17, 0.30, 2, 0.77, True),
        (0.67, 0.21, 0.34, 2, 0.74, True),
        (0.48, 0.55, 0.63, 1, 0.58, False),
        (0.34, 0.70, 0.76, 0, 0.46, False),
    ),
)
