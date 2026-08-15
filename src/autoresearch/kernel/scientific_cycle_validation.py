"""Read-only validation bridge for scientific-cycle declarations.

The bridge resolves content-addressed lifecycle bindings against the existing
provenance, Harness, Loop, and evaluation contracts.  It never executes,
repairs, promotes, publishes, or mutates any resolved object.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import Enum
from typing import Any, Literal, Protocol, TypeVar, cast

from pydantic import Field, model_validator

from autoresearch.schemas import ValidationStatus

from .contracts import KernelContract, Sha256, StableId, canonical_sha256
from .evaluation import (
    EvaluationGate,
    EvaluationReport,
    EvaluationVerdict,
    GraderIndependence,
    RegressionDimension,
)
from .harness import EpisodeOutcomeStatus, EpisodePackage, HarnessSpec
from .loop import TERMINAL_LOOP_STATUSES, LoopRunSnapshot, LoopSpec
from .provenance import (
    Activity,
    Counterevidence,
    Entity,
    EntityKind,
    Evidence,
    EvidenceDirection,
    Plan,
    ProvenanceBundle,
)
from .scientific_cycle import (
    ContentAddressedRef,
    HypothesisAssessment,
    HypothesisAssessmentRecord,
    ProvenanceBinding,
    ResearchEvaluation,
    ResearchHypothesis,
    ResearchObservation,
    ResearchProblem,
    ScientificCycleSnapshot,
    ScientificIntervention,
    scientific_record_semantic_hash,
)


class ScientificCycleValidationError(ValueError):
    """Raised when a declared identity or resolved object fails closed."""


class ScientificCycleExternalResolver(Protocol):
    """Read-only exact lookup boundary used by the validation bridge."""

    def get_provenance_bundle(
        self, ref: ContentAddressedRef
    ) -> ProvenanceBundle | None: ...

    def get_harness_spec(self, ref: ContentAddressedRef) -> HarnessSpec | None: ...

    def get_loop_spec(self, ref: ContentAddressedRef) -> LoopSpec | None: ...

    def get_evaluation_report(
        self, ref: ContentAddressedRef
    ) -> EvaluationReport | None: ...

    def get_episode(self, episode_id: str, episode_hash: str) -> EpisodePackage | None: ...

    def get_loop_snapshot(self, snapshot_hash: str) -> LoopRunSnapshot | None: ...


class AssessmentVerificationStatus(str, Enum):
    """Bridge result without rewriting the declared scientific assessment."""

    VERIFIED = "verified"
    INCONCLUSIVE = "inconclusive"


class ResolvedScientificContractRef(KernelContract):
    """Digest-only receipt for one exact external object consumed by the bridge."""

    contract_type: StableId
    ref_id: StableId
    ref_hash: Sha256


class ValidatedAssessment(KernelContract):
    """Per-hypothesis verification result with no copied scientific prose."""

    evaluation_id: StableId
    hypothesis_id: StableId
    declared_assessment: HypothesisAssessment
    verification_status: AssessmentVerificationStatus
    reason_codes: list[StableId] = Field(default_factory=list)
    episode_refs: list[ContentAddressedRef] = Field(default_factory=list)
    loop_snapshot_hashes: list[Sha256] = Field(default_factory=list)

    @model_validator(mode="after")
    def _normalize(self) -> ValidatedAssessment:
        self.reason_codes = _sorted_unique(self.reason_codes, "reason code")
        self.episode_refs = sorted(
            self.episode_refs,
            key=lambda item: (item.ref_id, item.ref_hash),
        )
        self.loop_snapshot_hashes = _sorted_unique(
            self.loop_snapshot_hashes,
            "loop snapshot hash",
        )
        if (
            self.declared_assessment == HypothesisAssessment.INCONCLUSIVE
            and self.verification_status != AssessmentVerificationStatus.INCONCLUSIVE
        ):
            raise ValueError("a declared inconclusive assessment cannot become verified")
        if (
            self.verification_status == AssessmentVerificationStatus.INCONCLUSIVE
            and not self.reason_codes
        ):
            raise ValueError("inconclusive verification requires reason codes")
        return self


class _ScientificCycleValidationReceiptContent(KernelContract):
    schema_version: Literal[1] = 1
    cycle_id: StableId
    cycle_version: int = Field(ge=1)
    cycle_snapshot_hash: Sha256
    structurally_authored_record_ids: list[StableId]
    validated_assessments: list[ValidatedAssessment]
    resolved_contracts: list[ResolvedScientificContractRef]
    system_generation_verified: Literal[False] = False
    real_world_identity_attested: Literal[False] = False

    @model_validator(mode="after")
    def _normalize(self) -> _ScientificCycleValidationReceiptContent:
        self.structurally_authored_record_ids = _sorted_unique(
            self.structurally_authored_record_ids,
            "structurally authored record",
        )
        assessment_keys = [
            (item.evaluation_id, item.hypothesis_id)
            for item in self.validated_assessments
        ]
        if len(assessment_keys) != len(set(assessment_keys)):
            raise ValueError("validated assessment identities must be unique")
        self.validated_assessments = sorted(
            self.validated_assessments,
            key=lambda item: (item.evaluation_id, item.hypothesis_id),
        )
        ref_keys = [
            (item.contract_type, item.ref_id, item.ref_hash)
            for item in self.resolved_contracts
        ]
        if len(ref_keys) != len(set(ref_keys)):
            raise ValueError("resolved contract receipts must be unique")
        self.resolved_contracts = sorted(
            self.resolved_contracts,
            key=lambda item: (item.contract_type, item.ref_id, item.ref_hash),
        )
        return self


class ScientificCycleValidationReceipt(_ScientificCycleValidationReceiptContent):
    """Content-addressed result of one read-only bridge validation."""

    receipt_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> ScientificCycleValidationReceipt:
        if self.receipt_hash != self.calculated_hash():
            raise ValueError("scientific-cycle validation receipt hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ScientificCycleValidationReceipt:
        content = _ScientificCycleValidationReceiptContent.model_validate(values)
        payload = content.model_dump(mode="json")
        payload["receipt_hash"] = canonical_sha256(content)
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"receipt_hash"}))

    def verify_integrity(self) -> None:
        if self.receipt_hash != self.calculated_hash():
            raise ScientificCycleValidationError(
                "scientific-cycle validation receipt failed integrity verification"
            )


_T = TypeVar("_T", bound=KernelContract)


class InMemoryScientificCycleResolver:
    """Deterministic exact resolver for tests and local content-addressed stores."""

    def __init__(
        self,
        *,
        provenance_bundles: Sequence[ProvenanceBundle] = (),
        harness_specs: Sequence[HarnessSpec] = (),
        loop_specs: Sequence[LoopSpec] = (),
        evaluation_reports: Sequence[EvaluationReport] = (),
        episodes: Sequence[EpisodePackage] = (),
        loop_snapshots: Sequence[LoopRunSnapshot] = (),
    ) -> None:
        self._provenance = _exact_index(
            provenance_bundles,
            ProvenanceBundle,
            "bundle_id",
            "bundle_hash",
        )
        self._harness = _exact_index(
            harness_specs,
            HarnessSpec,
            "spec_id",
            "spec_hash",
        )
        self._loop = _exact_index(loop_specs, LoopSpec, "spec_id", "spec_hash")
        self._reports = _exact_index(
            evaluation_reports,
            EvaluationReport,
            "report_id",
            "report_hash",
        )
        self._episodes = _exact_index(
            episodes,
            EpisodePackage,
            "episode_id",
            "episode_hash",
        )
        self._loop_snapshots = _hash_index(
            loop_snapshots,
            LoopRunSnapshot,
            "snapshot_hash",
        )

    def get_provenance_bundle(
        self, ref: ContentAddressedRef
    ) -> ProvenanceBundle | None:
        return _clone_optional(self._provenance.get((ref.ref_id, ref.ref_hash)))

    def get_harness_spec(self, ref: ContentAddressedRef) -> HarnessSpec | None:
        return _clone_optional(self._harness.get((ref.ref_id, ref.ref_hash)))

    def get_loop_spec(self, ref: ContentAddressedRef) -> LoopSpec | None:
        return _clone_optional(self._loop.get((ref.ref_id, ref.ref_hash)))

    def get_evaluation_report(
        self, ref: ContentAddressedRef
    ) -> EvaluationReport | None:
        return _clone_optional(self._reports.get((ref.ref_id, ref.ref_hash)))

    def get_episode(self, episode_id: str, episode_hash: str) -> EpisodePackage | None:
        return _clone_optional(self._episodes.get((episode_id, episode_hash)))

    def get_loop_snapshot(self, snapshot_hash: str) -> LoopRunSnapshot | None:
        return _clone_optional(self._loop_snapshots.get(snapshot_hash))


def validate_scientific_cycle(
    snapshot: ScientificCycleSnapshot,
    *,
    resolver: ScientificCycleExternalResolver | None = None,
    parent_snapshot: ScientificCycleSnapshot | None = None,
    provenance_bundles: Sequence[ProvenanceBundle] = (),
    harness_specs: Sequence[HarnessSpec] = (),
    loop_specs: Sequence[LoopSpec] = (),
    evaluation_reports: Sequence[EvaluationReport] = (),
    episodes: Sequence[EpisodePackage] = (),
    loop_snapshots: Sequence[LoopRunSnapshot] = (),
) -> ScientificCycleValidationReceipt:
    """Verify a lifecycle snapshot without executing or mutating dependencies.

    Supplying a resolver is the production boundary.  Explicit sequences are a
    deterministic local convenience and cannot be combined with a resolver.
    """

    if resolver is not None and any(
        (
            provenance_bundles,
            harness_specs,
            loop_specs,
            evaluation_reports,
            episodes,
            loop_snapshots,
        )
    ):
        raise ScientificCycleValidationError(
            "an external resolver cannot be combined with local resolver inputs"
        )
    active_resolver = resolver or InMemoryScientificCycleResolver(
        provenance_bundles=provenance_bundles,
        harness_specs=harness_specs,
        loop_specs=loop_specs,
        evaluation_reports=evaluation_reports,
        episodes=episodes,
        loop_snapshots=loop_snapshots,
    )
    original_snapshot = _canonical_dump(snapshot)
    cycle = _clone_required(snapshot, ScientificCycleSnapshot, "scientific cycle")
    cycle.verify_integrity()
    _verify_parent(cycle, parent_snapshot)

    resolved: dict[tuple[str, str, str], ResolvedScientificContractRef] = {}
    records = _cycle_records(cycle)
    bundles: dict[str, ProvenanceBundle] = {}
    for record in records:
        bundle = _resolve_bundle(record.provenance, active_resolver, resolved)
        bundles[record.provenance.bundle_ref.ref_hash] = bundle
        _verify_binding(record, bundle)
        if isinstance(record, ResearchObservation):
            _verify_observation(record, bundle)
        elif isinstance(record, ResearchHypothesis):
            _verify_hypothesis(record, bundle)
        elif isinstance(record, ScientificIntervention):
            _verify_intervention_declaration(record, bundle)
        elif isinstance(record, ResearchEvaluation):
            _verify_evaluation_declaration(record, bundle)

    assessments: list[ValidatedAssessment] = []
    hypotheses = {item.hypothesis_id: item for item in cycle.hypotheses}
    interventions = {item.intervention_id: item for item in cycle.interventions}
    for evaluation in cycle.evaluations:
        assessments.extend(
            _verify_external_evaluation(
                evaluation,
                hypotheses=hypotheses,
                interventions=interventions,
                resolver=active_resolver,
                resolved=resolved,
            )
        )

    if _canonical_dump(snapshot) != original_snapshot:
        raise ScientificCycleValidationError("validation mutated the scientific cycle")
    return ScientificCycleValidationReceipt.create(
        cycle_id=cycle.cycle_id,
        cycle_version=cycle.version,
        cycle_snapshot_hash=cycle.snapshot_hash,
        structurally_authored_record_ids=[_record_id(record) for record in records],
        validated_assessments=assessments,
        resolved_contracts=list(resolved.values()),
    )


def evaluation_subject_hash(report: EvaluationReport) -> str:
    """Hash the science-relevant report subject without bundle/policy hash cycles."""

    checked = _clone_required(report, EvaluationReport, "evaluation report")
    checked.verify_integrity()
    outcomes = []
    for outcome in checked.outcomes:
        payload = outcome.model_dump(mode="json", exclude={"evidence_bundle_hash"})
        outcomes.append(payload)
    return canonical_sha256(
        {
            "schema_version": 1,
            "task": checked.task.model_dump(mode="json"),
            "rubric": checked.rubric.model_dump(mode="json"),
            "trials": [item.model_dump(mode="json") for item in checked.trials],
            "trajectories": [item.model_dump(mode="json") for item in checked.trajectories],
            "outcomes": outcomes,
            "graders": [item.model_dump(mode="json") for item in checked.graders],
            "failure_slices": [
                item.model_dump(mode="json") for item in checked.failure_slices
            ],
            "uncertainty": checked.uncertainty.model_dump(mode="json"),
            "regression": checked.regression.model_dump(mode="json"),
            "security": checked.security.model_dump(mode="json"),
            "scientific_validity_verdict": checked.scientific_validity_verdict.value,
        }
    )


def scientific_cycle_validation_json_schemas() -> dict[str, dict[str, Any]]:
    """Export strict schemas for bridge receipts, not external input payloads."""

    models = (
        ResolvedScientificContractRef,
        ValidatedAssessment,
        ScientificCycleValidationReceipt,
    )
    return {model.__name__: model.model_json_schema() for model in models}


def _verify_parent(
    cycle: ScientificCycleSnapshot,
    parent_snapshot: ScientificCycleSnapshot | None,
) -> None:
    if cycle.version == 1:
        if parent_snapshot is not None:
            raise ScientificCycleValidationError("version one cannot resolve a parent")
        return
    if parent_snapshot is None:
        raise ScientificCycleValidationError("scientific cycle parent is missing")
    parent = _clone_required(
        parent_snapshot,
        ScientificCycleSnapshot,
        "scientific cycle parent",
    )
    parent.verify_integrity()
    declared = cycle.parent_snapshot_ref
    if declared is None or (
        declared.cycle_id,
        declared.version,
        declared.snapshot_hash,
    ) != (parent.cycle_id, parent.version, parent.snapshot_hash):
        raise ScientificCycleValidationError("scientific cycle parent identity mismatch")
    current = {_record_id(item): item for item in _cycle_records(cycle)}
    for previous in _cycle_records(parent):
        candidate = current.get(_record_id(previous))
        if candidate is None:
            raise ScientificCycleValidationError("scientific cycle history removed a record")
        if _canonical_dump(candidate) != _canonical_dump(previous):
            raise ScientificCycleValidationError("scientific cycle history modified a record")


def _resolve_bundle(
    binding: ProvenanceBinding,
    resolver: ScientificCycleExternalResolver,
    resolved: dict[tuple[str, str, str], ResolvedScientificContractRef],
) -> ProvenanceBundle:
    bundle = resolver.get_provenance_bundle(binding.bundle_ref)
    if bundle is None:
        raise ScientificCycleValidationError(
            "declared provenance bundle was not resolved by exact ID and hash"
        )
    checked = _clone_required(bundle, ProvenanceBundle, "provenance bundle")
    checked.verify_integrity()
    if (checked.bundle_id, checked.bundle_hash) != (
        binding.bundle_ref.ref_id,
        binding.bundle_ref.ref_hash,
    ):
        raise ScientificCycleValidationError("provenance bundle identity mismatch")
    _record_resolved(
        resolved,
        "provenance_bundle",
        checked.bundle_id,
        checked.bundle_hash,
    )
    return checked


def _verify_binding(
    record: ResearchObservation
    | ResearchProblem
    | ResearchHypothesis
    | ScientificIntervention
    | ResearchEvaluation,
    bundle: ProvenanceBundle,
) -> None:
    binding = record.provenance
    collections: tuple[tuple[Sequence[Any], str, Sequence[str], str], ...] = (
        (bundle.agents, "agent_id", binding.agent_ids, "agent"),
        (bundle.activities, "activity_id", binding.activity_ids, "activity"),
        (bundle.entities, "entity_id", binding.entity_ids, "entity"),
        (bundle.plans, "plan_id", binding.plan_ids, "plan"),
        (bundle.claims, "claim_id", binding.claim_ids, "claim"),
        (
            [*bundle.evidence, *bundle.counterevidence],
            "evidence_id",
            binding.evidence_ids,
            "evidence",
        ),
        (
            bundle.validations,
            "validation_id",
            binding.validation_ids,
            "validation",
        ),
        (bundle.decisions, "decision_id", binding.decision_ids, "decision"),
    )
    indexed: dict[str, dict[str, Any]] = {}
    for values, id_field, declared_ids, label in collections:
        by_id = {str(getattr(item, id_field)): item for item in values}
        indexed[label] = by_id
        for declared_id in declared_ids:
            item = by_id.get(declared_id)
            if item is None:
                raise ScientificCycleValidationError(
                    f"provenance {label} {declared_id} is missing or has the wrong type"
                )
            _require_current(item, f"provenance {label} {declared_id}")

    entity = cast(Entity, indexed["entity"][binding.record_entity_id])
    expected_kind = {
        ResearchObservation: EntityKind.EXPERIMENT_RECORD,
        ResearchProblem: EntityKind.ARTIFACT,
        ResearchHypothesis: EntityKind.HYPOTHESIS,
        ScientificIntervention: EntityKind.ARTIFACT,
        ResearchEvaluation: EntityKind.DECISION,
    }[type(record)]
    if entity.kind != expected_kind:
        raise ScientificCycleValidationError("record entity has the wrong entity kind")
    if entity.content_digest != scientific_record_semantic_hash(record):
        raise ScientificCycleValidationError("record entity semantic digest mismatch")

    generations = [
        item
        for item in bundle.generations
        if item.entity_id == binding.record_entity_id
        and item.invalidated_at is None
        and item.valid_to is None
    ]
    if len(generations) != 1 or (
        generations[0].activity_id != binding.authoring_activity_id
    ):
        raise ScientificCycleValidationError(
            "record entity lacks one exact authoring generation"
        )
    for author_id in binding.author_agent_ids:
        matches = [
            item
            for item in bundle.associations
            if item.activity_id == binding.authoring_activity_id
            and item.agent_id == author_id
            and item.role == "author"
            and item.plan_id in binding.plan_ids
            and item.invalidated_at is None
            and item.valid_to is None
        ]
        if len(matches) != 1:
            raise ScientificCycleValidationError(
                f"record author association is missing or ambiguous for {author_id}"
            )
        activity = cast(Activity, indexed["activity"][binding.authoring_activity_id])
        plan_id = matches[0].plan_id
        if plan_id is None:
            raise ScientificCycleValidationError(
                "record author association lacks a frozen plan"
            )
        plan = cast(Plan, indexed["plan"][plan_id])
        if plan.valid_from > activity.started_at:
            raise ScientificCycleValidationError(
                "record authoring plan was not frozen before authoring"
            )


def _verify_observation(
    observation: ResearchObservation,
    bundle: ProvenanceBundle,
) -> None:
    plan = _resolve_plan(observation.measurement_spec_ref, observation.provenance, bundle)
    entities = {item.entity_id: item for item in bundle.entities}
    for entity_id in (
        *observation.result_entity_ids,
        *observation.uncertainty_entity_ids,
        *observation.limitation_entity_ids,
    ):
        entity = entities[entity_id]
        if entity.content_digest is None:
            raise ScientificCycleValidationError(
                f"observation entity {entity_id} lacks a content digest"
            )
        if entity.kind not in {EntityKind.EXPERIMENT_RECORD, EntityKind.ARTIFACT}:
            raise ScientificCycleValidationError(
                f"observation entity {entity_id} has the wrong entity kind"
            )
        if not _entity_generated_under_plan(
            entity_id,
            plan.plan_id,
            observation.provenance,
            bundle,
        ):
            raise ScientificCycleValidationError(
                f"observation entity {entity_id} lacks a frozen measurement lineage"
            )


def _verify_hypothesis(
    hypothesis: ResearchHypothesis,
    bundle: ProvenanceBundle,
) -> None:
    claims = {item.claim_id: item for item in bundle.claims}
    for claim_id in (
        hypothesis.mechanism_claim_id,
        *hypothesis.prediction_claim_ids,
        *hypothesis.falsifier_claim_ids,
        *hypothesis.competing_explanation_claim_ids,
    ):
        claim = claims[claim_id]
        _require_current(claim, f"hypothesis claim {claim_id}")
        if claim.project_id not in {None, bundle.project_id}:
            raise ScientificCycleValidationError(
                f"hypothesis claim {claim_id} belongs to another project"
            )


def _verify_intervention_declaration(
    intervention: ScientificIntervention,
    bundle: ProvenanceBundle,
) -> None:
    _resolve_plan(intervention.protocol_ref, intervention.provenance, bundle)
    entities = {item.entity_id: item for item in bundle.entities}
    for entity_id in (
        *intervention.comparator_entity_ids,
        *intervention.changed_factor_entity_ids,
        *intervention.frozen_factor_entity_ids,
        *intervention.metric_spec_entity_ids,
        *intervention.decision_rule_entity_ids,
    ):
        entity = entities[entity_id]
        if entity.content_digest is None:
            raise ScientificCycleValidationError(
                f"intervention entity {entity_id} lacks a content digest"
            )


def _verify_evaluation_declaration(
    evaluation: ResearchEvaluation,
    bundle: ProvenanceBundle,
) -> None:
    entities = {item.entity_id: item for item in bundle.entities}
    for assessment in evaluation.assessments:
        for entity_id in assessment.objective_result_entity_ids:
            _require_entity_kind(
                entities[entity_id],
                {EntityKind.ARTIFACT, EntityKind.EXPERIMENT_RECORD},
                "objective result",
            )
        for entity_id in assessment.uncertainty_entity_ids:
            _require_entity_kind(
                entities[entity_id],
                {EntityKind.ARTIFACT, EntityKind.EXPERIMENT_RECORD},
                "uncertainty",
            )
        for entity_id in assessment.failure_entity_ids:
            _require_entity_kind(entities[entity_id], {EntityKind.FAILURE}, "failure")


def _verify_external_evaluation(
    evaluation: ResearchEvaluation,
    *,
    hypotheses: dict[str, ResearchHypothesis],
    interventions: dict[str, ScientificIntervention],
    resolver: ScientificCycleExternalResolver,
    resolved: dict[tuple[str, str, str], ResolvedScientificContractRef],
) -> list[ValidatedAssessment]:
    report = resolver.get_evaluation_report(evaluation.evaluation_report_ref)
    if report is None:
        raise ScientificCycleValidationError("evaluation report was not resolved exactly")
    report = _clone_required(report, EvaluationReport, "evaluation report")
    report.verify_integrity()
    if (report.report_id, report.report_hash) != (
        evaluation.evaluation_report_ref.ref_id,
        evaluation.evaluation_report_ref.ref_hash,
    ):
        raise ScientificCycleValidationError("evaluation report identity mismatch")
    if evaluation.evaluation_subject_hash != evaluation_subject_hash(report):
        raise ScientificCycleValidationError("evaluation subject hash mismatch")
    _record_resolved(
        resolved,
        "evaluation_report",
        report.report_id,
        report.report_hash,
    )

    selected = [interventions[item] for item in evaluation.intervention_ids]
    harness_refs = {(item.harness_spec_ref.ref_id, item.harness_spec_ref.ref_hash) for item in selected}
    loop_refs = {(item.loop_spec_ref.ref_id, item.loop_spec_ref.ref_hash) for item in selected}
    protocol_hashes = {item.protocol_ref.ref_hash for item in selected}
    if len(harness_refs) != 1 or len(loop_refs) != 1 or len(protocol_hashes) != 1:
        raise ScientificCycleValidationError(
            "one evaluation must resolve one unambiguous execution identity"
        )
    harness_ref = selected[0].harness_spec_ref
    loop_ref = selected[0].loop_spec_ref
    harness = resolver.get_harness_spec(harness_ref)
    loop_spec = resolver.get_loop_spec(loop_ref)
    if harness is None or loop_spec is None:
        raise ScientificCycleValidationError("evaluation execution spec is missing")
    harness = _clone_required(harness, HarnessSpec, "harness spec")
    loop_spec = _clone_required(loop_spec, LoopSpec, "loop spec")
    harness.verify_integrity()
    loop_spec.verify_integrity()
    if (harness.spec_id, harness.spec_hash) != (
        harness_ref.ref_id,
        harness_ref.ref_hash,
    ) or (loop_spec.spec_id, loop_spec.spec_hash) != (
        loop_ref.ref_id,
        loop_ref.ref_hash,
    ):
        raise ScientificCycleValidationError("evaluation execution spec identity mismatch")
    _record_resolved(resolved, "harness_spec", harness.spec_id, harness.spec_hash)
    _record_resolved(resolved, "loop_spec", loop_spec.spec_id, loop_spec.spec_hash)
    if report.task.protocol_hash not in protocol_hashes:
        raise ScientificCycleValidationError("evaluation protocol identity mismatch")
    earliest_trial_start = min(item.started_at for item in report.trials)
    for intervention in selected:
        intervention_bundle = _resolve_bundle(
            intervention.provenance,
            resolver,
            resolved,
        )
        protocol_plan = _resolve_plan(
            intervention.protocol_ref,
            intervention.provenance,
            intervention_bundle,
        )
        if protocol_plan.valid_from > earliest_trial_start:
            raise ScientificCycleValidationError(
                "evaluation protocol was not frozen before execution"
            )
    task_hash = canonical_sha256(harness.task_contract)
    if (
        report.task.task_id != harness.task_contract.task_id
        or report.task.task_contract_hash != task_hash
        or loop_spec.task_id != report.task.task_id
    ):
        raise ScientificCycleValidationError("evaluation task identity mismatch")

    episodes_by_id: dict[str, EpisodePackage] = {}
    loop_by_hash: dict[str, LoopRunSnapshot] = {}
    for trial in report.trials:
        episode = resolver.get_episode(trial.episode_id, trial.episode_hash)
        if episode is None:
            raise ScientificCycleValidationError("evaluation episode is missing")
        episode = _clone_required(episode, EpisodePackage, "episode package")
        episode.verify_integrity()
        trajectory = next(
            item for item in report.trajectories if item.trajectory_id == trial.trajectory_id
        )
        if trajectory.loop_snapshot_hash is None:
            raise ScientificCycleValidationError("evaluation loop snapshot is missing")
        loop_snapshot = resolver.get_loop_snapshot(trajectory.loop_snapshot_hash)
        if loop_snapshot is None:
            raise ScientificCycleValidationError("evaluation loop snapshot is unresolved")
        loop_snapshot = _clone_required(
            loop_snapshot,
            LoopRunSnapshot,
            "loop run snapshot",
        )
        loop_snapshot.verify_integrity()
        _verify_trial_identity(
            trial=trial,
            report=report,
            episode=episode,
            trajectory=trajectory,
            loop_snapshot=loop_snapshot,
            harness=harness,
            loop_spec=loop_spec,
        )
        episodes_by_id[episode.episode_id] = episode
        loop_by_hash[loop_snapshot.snapshot_hash] = loop_snapshot
        _record_resolved(
            resolved,
            "episode_package",
            episode.episode_id,
            episode.episode_hash,
        )
        _record_resolved(
            resolved,
            "loop_run_snapshot",
            loop_snapshot.run_id,
            loop_snapshot.snapshot_hash,
        )

    result: list[ValidatedAssessment] = []
    evaluation_bundle = _resolve_bundle(evaluation.provenance, resolver, resolved)
    related_bindings = [
        evaluation.provenance,
        *[hypotheses[item.hypothesis_id].provenance for item in evaluation.assessments],
        *[item.provenance for item in selected],
    ]
    excluded_agent_ids = {
        agent_id for binding in related_bindings for agent_id in binding.author_agent_ids
    }
    excluded_implementation_hashes: set[str] = set()
    for binding in related_bindings:
        related_bundle = _resolve_bundle(binding, resolver, resolved)
        agents = {item.agent_id: item for item in related_bundle.agents}
        for agent_id in binding.author_agent_ids:
            implementation_hash = agents[agent_id].implementation_hash
            if implementation_hash is not None:
                excluded_implementation_hashes.add(implementation_hash)
    for assessment in evaluation.assessments:
        hypothesis = hypotheses[assessment.hypothesis_id]
        hypothesis_bundle = _resolve_bundle(hypothesis.provenance, resolver, resolved)
        _verify_cross_bundle_claim_identity(
            hypothesis,
            hypothesis_bundle=hypothesis_bundle,
            evaluation_bundle=evaluation_bundle,
        )
        result.append(
            _verify_assessment(
                evaluation,
                assessment,
                hypothesis=hypothesis,
                bundle=evaluation_bundle,
                report=report,
                episodes=list(episodes_by_id.values()),
                loop_snapshots=list(loop_by_hash.values()),
                excluded_agent_ids=excluded_agent_ids,
                excluded_implementation_hashes=excluded_implementation_hashes,
            )
        )
    return result


def _verify_trial_identity(
    *,
    trial: Any,
    report: EvaluationReport,
    episode: EpisodePackage,
    trajectory: Any,
    loop_snapshot: LoopRunSnapshot,
    harness: HarnessSpec,
    loop_spec: LoopSpec,
) -> None:
    outcome = next(item for item in report.outcomes if item.outcome_id == trial.outcome_id)
    cost = next(item for item in report.costs if item.cost_id == trial.cost_id)
    episode_cost = episode.costs[0]
    if (
        episode.harness_spec_id != harness.spec_id
        or episode.harness_spec_hash != harness.spec_hash
        or canonical_sha256(episode.task_contract) != report.task.task_contract_hash
        or episode.task_contract.task_id != report.task.task_id
        or trial.source_trial_id != episode.trials[0].trial_id
        or trial.started_at != episode.started_at
        or trial.completed_at != episode.completed_at
        or trajectory.episode_id != episode.episode_id
        or trajectory.episode_hash != episode.episode_hash
        or trajectory.trajectory_hash
        != canonical_sha256([item.model_dump(mode="json") for item in episode.trajectory])
        or trajectory.journal_lineage_hash != episode.journal_lineage_hash
        or trajectory.replay_hash != episode.journal_lineage_hash
        or trajectory.step_count != len(episode.trajectory)
        or episode.journal_terminal_event_id not in trajectory.event_refs
        or outcome.environment_outcome_hash != canonical_sha256(episode.final_outcome)
        or outcome.environment_output_hash != episode.final_outcome.output_hash
        or outcome.environment_status != episode.final_outcome.status
        or outcome.summary_hash != canonical_sha256(episode.final_outcome.summary)
        or cost.input_tokens != episode_cost.prompt_tokens
        or cost.output_tokens != episode_cost.completion_tokens
        or cost.total_tokens != episode_cost.total_tokens
        or cost.estimated_cost_usd != episode_cost.estimated_cost_usd
        or cost.cost_known != episode_cost.cost_known
        or cost.wall_time_seconds != episode_cost.wall_time_seconds
        or cost.tool_calls != episode_cost.tool_calls
    ):
        raise ScientificCycleValidationError("evaluation trial identity mismatch")
    episode_graders = {item.grader_id: item for item in episode.graders}
    report_graders = [
        item
        for item in report.graders
        if item.grader_record_id in trial.grader_record_ids
    ]
    if any(
        grader.grader_id not in episode_graders
        or grader.grader_version != episode_graders[grader.grader_id].grader_version
        or grader.kind != episode_graders[grader.grader_id].kind
        or grader.score != episode_graders[grader.grader_id].score
        or (grader.verdict == EvaluationVerdict.PASS)
        != episode_graders[grader.grader_id].passed
        for grader in report_graders
    ):
        raise ScientificCycleValidationError("evaluation grader identity mismatch")
    if (
        loop_snapshot.spec_id != loop_spec.spec_id
        or loop_snapshot.spec_hash != loop_spec.spec_hash
        or loop_snapshot.task_id != report.task.task_id
        or loop_snapshot.run_id != episode.run_id
        or loop_snapshot.state.status not in TERMINAL_LOOP_STATUSES
        or loop_snapshot.seal_hash is None
    ):
        raise ScientificCycleValidationError("loop execution identity mismatch")
    variables = loop_snapshot.state.variables
    expected_variables = {
        "harness_episode_id": episode.episode_id,
        "harness_episode_hash": episode.episode_hash,
        "harness_episode_status": episode.final_outcome.status.value,
        "harness_journal_lineage_hash": episode.journal_lineage_hash,
        "harness_journal_seal_hash": episode.journal_seal_hash,
        "harness_spec_hash": episode.harness_spec_hash,
    }
    if any(variables.get(key) != value for key, value in expected_variables.items()):
        raise ScientificCycleValidationError("loop snapshot does not bind the episode")


def _verify_assessment(
    evaluation: ResearchEvaluation,
    assessment: HypothesisAssessmentRecord,
    *,
    hypothesis: ResearchHypothesis,
    bundle: ProvenanceBundle,
    report: EvaluationReport,
    episodes: list[EpisodePackage],
    loop_snapshots: list[LoopRunSnapshot],
    excluded_agent_ids: set[str],
    excluded_implementation_hashes: set[str],
) -> ValidatedAssessment:
    allowed_claims = {
        hypothesis.mechanism_claim_id,
        *hypothesis.prediction_claim_ids,
    }
    evidence_by_id: dict[str, Evidence | Counterevidence] = {
        item.evidence_id: cast(Evidence | Counterevidence, item)
        for item in [*bundle.evidence, *bundle.counterevidence]
    }
    decisive_ids = (
        assessment.supporting_evidence_ids
        if assessment.assessment == HypothesisAssessment.SUPPORTED
        else assessment.counterevidence_ids
    )
    decisive_evidence_passed = True
    limiting_evidence_validated = True
    for evidence_id in (
        *assessment.supporting_evidence_ids,
        *assessment.counterevidence_ids,
        *assessment.limiting_evidence_ids,
    ):
        evidence = evidence_by_id.get(evidence_id)
        if evidence is None:
            raise ScientificCycleValidationError("assessment evidence is missing")
        expected_direction = (
            EvidenceDirection.SUPPORTS
            if evidence_id in assessment.supporting_evidence_ids
            else (
                EvidenceDirection.CONTRADICTS
                if evidence_id in assessment.counterevidence_ids
                else EvidenceDirection.LIMITS
            )
        )
        if evidence.direction != expected_direction or evidence.claim_id not in allowed_claims:
            raise ScientificCycleValidationError(
                "assessment evidence direction or hypothesis claim is invalid"
            )
        if evidence.artifact_entity_id not in assessment.objective_result_entity_ids:
            raise ScientificCycleValidationError(
                "assessment evidence artifact is not a bound objective result"
            )
        decisive = evidence_id in decisive_ids
        trace_passed = _verify_exact_evidence_trace(
            evidence,
            bundle=bundle,
            binding=evaluation.provenance,
            require_passed=decisive,
        )
        if decisive and not trace_passed:
            decisive_evidence_passed = False
        if evidence_id in assessment.limiting_evidence_ids and not trace_passed:
            limiting_evidence_validated = False

    reasons: list[str] = []
    decisive = assessment.assessment in {
        HypothesisAssessment.SUPPORTED,
        HypothesisAssessment.CONTRADICTED,
    }
    if assessment.assessment == HypothesisAssessment.INCONCLUSIVE:
        reasons.append("declared_inconclusive")
        if not limiting_evidence_validated:
            reasons.append("limiting_evidence_not_validated")
    if decisive and not decisive_evidence_passed:
        reasons.append("decisive_evidence_not_passed")
    if decisive and report.scientific_validity_verdict != EvaluationVerdict.PASS:
        reasons.append("scientific_validity_not_passed")
    gate_map = {item.gate: item.verdict for item in report.promotion.gates}
    required_science_gates = {
        EvaluationGate.OUTCOME,
        EvaluationGate.PROTOCOL_MATCH,
        EvaluationGate.EVIDENCE_MATCH,
        EvaluationGate.SCIENTIFIC_CORE,
        EvaluationGate.REPLAY_FIDELITY,
        EvaluationGate.HOLDOUT_INTEGRITY,
        EvaluationGate.GRADER_INTEGRITY,
        EvaluationGate.SECURITY,
        EvaluationGate.REPEATED_TRIALS,
    }
    if decisive and any(
        gate_map.get(gate) != EvaluationVerdict.PASS for gate in required_science_gates
    ):
        reasons.append("required_science_gate_not_passed")
    if decisive and any(
        episode.final_outcome.status
        not in {EpisodeOutcomeStatus.SUCCEEDED, EpisodeOutcomeStatus.NEGATIVE_RESULT}
        for episode in episodes
    ):
        reasons.append("non_scientific_episode_terminal")
    if decisive and not _independent_graders_pass(
        report,
        bundle,
        evaluation.provenance,
        excluded_agent_ids=excluded_agent_ids,
        excluded_implementation_hashes=excluded_implementation_hashes,
    ):
        reasons.append("independent_grader_not_verified")
    if decisive and not _report_science_core_passes(
        report,
        expected_bundle_hash=evaluation.provenance.bundle_ref.ref_hash,
    ):
        reasons.append("recomputed_science_core_not_passed")
    if decisive and not _results_match_evidence(
        assessment,
        bundle=bundle,
        report=report,
        episodes=episodes,
    ):
        reasons.append("result_or_uncertainty_not_bound")

    status = (
        AssessmentVerificationStatus.VERIFIED
        if decisive and not reasons
        else AssessmentVerificationStatus.INCONCLUSIVE
    )
    return ValidatedAssessment(
        evaluation_id=evaluation.evaluation_id,
        hypothesis_id=assessment.hypothesis_id,
        declared_assessment=assessment.assessment,
        verification_status=status,
        reason_codes=reasons,
        episode_refs=[
            ContentAddressedRef(
                ref_id=episode.episode_id,
                ref_hash=episode.episode_hash,
            )
            for episode in episodes
        ],
        loop_snapshot_hashes=[item.snapshot_hash for item in loop_snapshots],
    )


def _verify_exact_evidence_trace(
    evidence: Evidence | Counterevidence,
    *,
    bundle: ProvenanceBundle,
    binding: ProvenanceBinding,
    require_passed: bool,
) -> bool:
    _require_current(evidence, f"evidence {evidence.evidence_id}")
    if evidence.evidence_id not in binding.evidence_ids:
        raise ScientificCycleValidationError("assessment evidence is outside its binding")
    required_bound_agents = set(evidence.responsible_agent_ids)
    required_bound_activities = {evidence.generating_activity_id}
    required_bound_entities = {
        evidence.artifact_entity_id,
        evidence.source_entity_id,
    }
    if (
        not required_bound_agents.issubset(binding.agent_ids)
        or not required_bound_activities.issubset(binding.activity_ids)
        or not required_bound_entities.issubset(binding.entity_ids)
    ):
        raise ScientificCycleValidationError(
            "evidence causal records are outside the evaluation binding"
        )
    entities = {item.entity_id: item for item in bundle.entities}
    artifact = entities[evidence.artifact_entity_id]
    if artifact.content_digest is None:
        raise ScientificCycleValidationError("evidence artifact lacks a content digest")
    usages = [
        item
        for item in bundle.usages
        if item.activity_id == evidence.generating_activity_id
        and item.entity_id == evidence.source_entity_id
        and item.invalidated_at is None
        and item.valid_to is None
    ]
    generations = [
        item
        for item in bundle.generations
        if item.activity_id == evidence.generating_activity_id
        and item.entity_id == evidence.artifact_entity_id
        and item.invalidated_at is None
        and item.valid_to is None
    ]
    associations = [
        item
        for item in bundle.associations
        if item.activity_id == evidence.generating_activity_id
        and item.agent_id in evidence.responsible_agent_ids
        and item.invalidated_at is None
        and item.valid_to is None
    ]
    if not usages or not generations or {
        item.agent_id for item in associations
    } != set(evidence.responsible_agent_ids):
        raise ScientificCycleValidationError("evidence causal trace is incomplete")
    validations = {item.validation_id: item for item in bundle.validations}
    validation_statuses: list[ValidationStatus] = []
    for validation_id in evidence.validation_ids:
        validation = validations[validation_id]
        _require_current(validation, f"validation {validation_id}")
        if validation_id not in binding.validation_ids:
            raise ScientificCycleValidationError("evidence validation is outside its binding")
        if (
            validation.agent_id not in binding.agent_ids
            or validation.activity_id not in binding.activity_ids
        ):
            raise ScientificCycleValidationError(
                "validation agent or activity is outside its binding"
            )
        validation_statuses.append(validation.status)
        validator_association = [
            item
            for item in bundle.associations
            if item.activity_id == validation.activity_id
            and item.agent_id == validation.agent_id
            and item.role == "validator"
            and item.invalidated_at is None
            and item.valid_to is None
        ]
        if len(validator_association) != 1:
            raise ScientificCycleValidationError(
                "validation lacks one exact validator association"
            )
    linked_decisions = [
        item
        for item in bundle.decisions
        if item.decision_id in binding.decision_ids
        and evidence.claim_id in item.claim_ids
        and set(item.validation_ids).intersection(evidence.validation_ids)
        and item.invalidated_at is None
        and item.valid_to is None
    ]
    if require_passed and not linked_decisions:
        raise ScientificCycleValidationError("decisive evidence lacks a bound decision")
    for decision in linked_decisions:
        if (
            decision.responsible_agent_id not in binding.agent_ids
            or decision.activity_id not in binding.activity_ids
            or decision.artifact_entity_id not in binding.entity_ids
        ):
            raise ScientificCycleValidationError(
                "decision causal records are outside the evaluation binding"
            )
        decision_association = [
            item
            for item in bundle.associations
            if item.activity_id == decision.activity_id
            and item.agent_id == decision.responsible_agent_id
            and item.role == "decision_maker"
            and item.invalidated_at is None
            and item.valid_to is None
        ]
        decision_generation = [
            item
            for item in bundle.generations
            if item.activity_id == decision.activity_id
            and item.entity_id == decision.artifact_entity_id
            and item.invalidated_at is None
            and item.valid_to is None
        ]
        if len(decision_association) != 1 or len(decision_generation) != 1:
            raise ScientificCycleValidationError("decision provenance is incomplete")
    if require_passed:
        return all(status == ValidationStatus.PASSED for status in validation_statuses)
    return all(
        status in {ValidationStatus.PASSED, ValidationStatus.WARNING}
        for status in validation_statuses
    )


def _independent_graders_pass(
    report: EvaluationReport,
    bundle: ProvenanceBundle,
    binding: ProvenanceBinding,
    *,
    excluded_agent_ids: set[str],
    excluded_implementation_hashes: set[str],
) -> bool:
    agents = {item.agent_id: item for item in bundle.agents}
    authors = [agents[item] for item in binding.author_agent_ids]
    responsible_ids = {
        agent_id
        for item in [*bundle.evidence, *bundle.counterevidence]
        if item.evidence_id in binding.evidence_ids
        for agent_id in item.responsible_agent_ids
    }
    excluded_ids = set(binding.author_agent_ids) | responsible_ids | excluded_agent_ids
    excluded_hashes = {
        item.implementation_hash
        for item in authors
        if item.implementation_hash is not None
    } | {
        agents[item].implementation_hash
        for item in responsible_ids
        if item in agents and agents[item].implementation_hash is not None
    } | excluded_implementation_hashes
    required_criteria = {item.criterion_id for item in report.rubric.criteria if item.required}
    for grader in report.graders:
        if grader.criterion_id not in required_criteria:
            continue
        agent = agents.get(grader.grader_id)
        if (
            grader.independence != GraderIndependence.INDEPENDENT
            or grader.verdict != EvaluationVerdict.PASS
            or agent is None
            or agent.invalidated_at is not None
            or agent.valid_to is not None
            or agent.implementation_hash is None
            or agent.agent_id in excluded_ids
            or agent.implementation_hash in excluded_hashes
        ):
            return False
        validations = [
            item
            for item in bundle.validations
            if item.validation_id in binding.validation_ids
            and item.agent_id == grader.grader_id
            and item.status == ValidationStatus.PASSED
            and item.invalidated_at is None
            and item.valid_to is None
        ]
        if not validations:
            return False
        if any(
            not any(
                association.activity_id == validation.activity_id
                and association.agent_id == grader.grader_id
                and association.role == "validator"
                and association.invalidated_at is None
                and association.valid_to is None
                for association in bundle.associations
            )
            for validation in validations
        ):
            return False
    return True


def _report_science_core_passes(
    report: EvaluationReport,
    *,
    expected_bundle_hash: str,
) -> bool:
    if report.scientific_validity_verdict != EvaluationVerdict.PASS:
        return False
    if len(report.trials) < report.task.minimum_independent_trials:
        return False
    if report.uncertainty.success_count != report.uncertainty.trial_count:
        return False
    if any(
        outcome.environment_status
        not in {EpisodeOutcomeStatus.SUCCEEDED, EpisodeOutcomeStatus.NEGATIVE_RESULT}
        or outcome.evidence_verdict != EvaluationVerdict.PASS
        or outcome.evidence_bundle_hash != expected_bundle_hash
        for outcome in report.outcomes
    ):
        return False
    required_dimensions = {
        RegressionDimension.EVIDENCE_MATCH,
        RegressionDimension.SCIENTIFIC_CORE,
        RegressionDimension.PROTOCOL_MATCH,
        RegressionDimension.REPLAY_FIDELITY,
        RegressionDimension.HOLDOUT_INTEGRITY,
    }
    regression_verdicts = {
        item.dimension: item.verdict for item in report.regression.results
    }
    if any(
        regression_verdicts.get(dimension) != EvaluationVerdict.PASS
        for dimension in required_dimensions
    ):
        return False
    return report.security.overall_verdict == EvaluationVerdict.PASS


def _verify_cross_bundle_claim_identity(
    hypothesis: ResearchHypothesis,
    *,
    hypothesis_bundle: ProvenanceBundle,
    evaluation_bundle: ProvenanceBundle,
) -> None:
    hypothesis_claims = {item.claim_id: item for item in hypothesis_bundle.claims}
    evaluation_claims = {item.claim_id: item for item in evaluation_bundle.claims}
    for claim_id in {
        hypothesis.mechanism_claim_id,
        *hypothesis.prediction_claim_ids,
    }:
        left = hypothesis_claims.get(claim_id)
        right = evaluation_claims.get(claim_id)
        if left is None or right is None:
            raise ScientificCycleValidationError(
                "assessment claim is missing from one provenance bundle"
            )
        _require_current(left, f"hypothesis claim {claim_id}")
        _require_current(right, f"evaluation claim {claim_id}")
        if canonical_sha256(left) != canonical_sha256(right):
            raise ScientificCycleValidationError(
                "cross-bundle assessment claim identity mismatch"
            )


def _results_match_evidence(
    assessment: HypothesisAssessmentRecord,
    *,
    bundle: ProvenanceBundle,
    report: EvaluationReport,
    episodes: list[EpisodePackage],
) -> bool:
    entities = {item.entity_id: item for item in bundle.entities}
    output_hashes = {
        episode.final_outcome.output_hash
        for episode in episodes
        if episode.final_outcome.output_hash is not None
    }
    objective_digests = {
        entities[item].content_digest for item in assessment.objective_result_entity_ids
    }
    aggregate_digest = canonical_sha256(
        {"episode_output_hashes": sorted(output_hashes)}
    )
    if not (
        output_hashes.issubset(objective_digests)
        or aggregate_digest in objective_digests
    ):
        return False
    uncertainty_hash = report.uncertainty.content_hash()
    return all(
        entities[item].content_digest == uncertainty_hash
        for item in assessment.uncertainty_entity_ids
    )


def _resolve_plan(
    ref: ContentAddressedRef,
    binding: ProvenanceBinding,
    bundle: ProvenanceBundle,
) -> Plan:
    if ref.ref_id not in binding.plan_ids:
        raise ScientificCycleValidationError("frozen plan is outside its binding")
    matches = [
        item
        for item in bundle.plans
        if item.plan_id == ref.ref_id and item.content_digest == ref.ref_hash
    ]
    if len(matches) != 1:
        raise ScientificCycleValidationError("frozen plan identity is missing or ambiguous")
    _require_current(matches[0], f"plan {ref.ref_id}")
    return matches[0]


def _entity_generated_under_plan(
    entity_id: str,
    plan_id: str,
    binding: ProvenanceBinding,
    bundle: ProvenanceBundle,
) -> bool:
    generations = [
        item
        for item in bundle.generations
        if item.entity_id == entity_id
        and item.activity_id in binding.activity_ids
        and item.invalidated_at is None
        and item.valid_to is None
    ]
    if len(generations) != 1:
        return False
    activities = {item.activity_id: item for item in bundle.activities}
    plans = {item.plan_id: item for item in bundle.plans}
    activity = activities[generations[0].activity_id]
    plan = plans[plan_id]
    return plan.valid_from <= activity.started_at and any(
        association.activity_id == generations[0].activity_id
        and association.agent_id in binding.agent_ids
        and association.plan_id == plan_id
        and association.invalidated_at is None
        and association.valid_to is None
        for association in bundle.associations
    )


def _require_entity_kind(
    entity: Entity,
    allowed: set[EntityKind],
    label: str,
) -> None:
    _require_current(entity, f"{label} entity {entity.entity_id}")
    if entity.kind not in allowed or entity.content_digest is None:
        raise ScientificCycleValidationError(
            f"{label} entity has the wrong kind or no content digest"
        )


def _cycle_records(
    cycle: ScientificCycleSnapshot,
) -> list[
    ResearchObservation
    | ResearchProblem
    | ResearchHypothesis
    | ScientificIntervention
    | ResearchEvaluation
]:
    return [
        *cycle.observations,
        *cycle.problems,
        *cycle.hypotheses,
        *cycle.interventions,
        *cycle.evaluations,
    ]


def _record_id(
    record: ResearchObservation
    | ResearchProblem
    | ResearchHypothesis
    | ScientificIntervention
    | ResearchEvaluation,
) -> str:
    if isinstance(record, ResearchObservation):
        return record.observation_id
    if isinstance(record, ResearchProblem):
        return record.problem_id
    if isinstance(record, ResearchHypothesis):
        return record.hypothesis_id
    if isinstance(record, ScientificIntervention):
        return record.intervention_id
    return record.evaluation_id


def _require_current(record: Any, label: str) -> None:
    if record.invalidated_at is not None or record.valid_to is not None:
        raise ScientificCycleValidationError(f"{label} is not current")


def _record_resolved(
    resolved: dict[tuple[str, str, str], ResolvedScientificContractRef],
    contract_type: str,
    ref_id: str,
    ref_hash: str,
) -> None:
    key = (contract_type, ref_id, ref_hash)
    resolved[key] = ResolvedScientificContractRef(
        contract_type=contract_type,
        ref_id=ref_id,
        ref_hash=ref_hash,
    )


def _clone_required(value: Any, expected: type[_T], label: str) -> _T:
    if type(value) is not expected:
        raise ScientificCycleValidationError(f"{label} has the wrong concrete type")
    try:
        return expected.model_validate_json(value.model_dump_json())
    except Exception as exc:
        raise ScientificCycleValidationError(f"{label} failed integrity validation") from exc


def _clone_optional(value: _T | None) -> _T | None:
    if value is None:
        return None
    return type(value).model_validate_json(value.model_dump_json())


def _exact_index(
    values: Sequence[_T],
    expected: type[_T],
    id_field: str,
    hash_field: str,
) -> dict[tuple[str, str], _T]:
    result: dict[tuple[str, str], _T] = {}
    for value in values:
        clone = _clone_required(value, expected, expected.__name__)
        key = (str(getattr(clone, id_field)), str(getattr(clone, hash_field)))
        if key in result:
            raise ScientificCycleValidationError(
                f"duplicate exact {expected.__name__} resolver entry"
            )
        result[key] = clone
    return result


def _hash_index(
    values: Sequence[_T],
    expected: type[_T],
    hash_field: str,
) -> dict[str, _T]:
    result: dict[str, _T] = {}
    for value in values:
        clone = _clone_required(value, expected, expected.__name__)
        key = str(getattr(clone, hash_field))
        if key in result:
            raise ScientificCycleValidationError(
                f"duplicate exact {expected.__name__} resolver entry"
            )
        result[key] = clone
    return result


def _canonical_dump(value: KernelContract) -> str:
    return value.model_dump_json()


def _sorted_unique(values: list[str], label: str) -> list[str]:
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {label}")
    return sorted(values)
