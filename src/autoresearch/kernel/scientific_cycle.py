"""Provider- and topic-neutral contracts for a mechanism research cycle.

The models in this module describe scientific-stage semantics only. They do
not execute experiments, validate external hashes, judge novelty, or authorize
promotion or publication. Those responsibilities remain with the existing
Harness, Loop, provenance, and evaluation layers.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import Field, JsonValue, field_validator, model_validator

from .contracts import (
    ContractIntegrityError,
    GraphEdge,
    GraphNode,
    GraphPlane,
    GraphSnapshot,
    KernelContract,
    NonEmptyText,
    Sha256,
    StableId,
    canonical_sha256,
)


class HypothesisAssessment(str, Enum):
    """Scientific interpretation of one tested hypothesis."""

    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    INCONCLUSIVE = "inconclusive"


class ContentAddressedRef(KernelContract):
    """A declared reference to an external content-addressed contract.

    This reference does not prove that the external object exists or is valid.
    A separate read-only bridge must resolve and verify it before promotion.
    """

    ref_id: StableId
    ref_hash: Sha256


class ScientificCycleParentRef(KernelContract):
    """Declared identity of the immediate previous snapshot in one cycle."""

    cycle_id: StableId
    version: int = Field(ge=1)
    snapshot_hash: Sha256


class ProvenanceBinding(KernelContract):
    """IDs that a cycle record declares within one provenance bundle."""

    bundle_ref: ContentAddressedRef
    agent_ids: list[StableId] = Field(min_length=1)
    activity_ids: list[StableId] = Field(min_length=1)
    entity_ids: list[StableId] = Field(min_length=1)
    record_entity_id: StableId
    authoring_activity_id: StableId
    author_agent_ids: list[StableId] = Field(min_length=1)
    plan_ids: list[StableId] = Field(min_length=1)
    claim_ids: list[StableId] = Field(default_factory=list)
    evidence_ids: list[StableId] = Field(default_factory=list)
    validation_ids: list[StableId] = Field(default_factory=list)
    decision_ids: list[StableId] = Field(default_factory=list)

    @field_validator(
        "agent_ids",
        "activity_ids",
        "entity_ids",
        "author_agent_ids",
        "plan_ids",
        "claim_ids",
        "evidence_ids",
        "validation_ids",
        "decision_ids",
    )
    @classmethod
    def _normalize_ids(cls, value: list[str]) -> list[str]:
        return _sorted_unique(value, label="provenance")

    @model_validator(mode="after")
    def _validate_authoring_roles(self) -> ProvenanceBinding:
        _require_bound_ids(
            [self.record_entity_id],
            self.entity_ids,
            role="record entity",
        )
        _require_bound_ids(
            [self.authoring_activity_id],
            self.activity_ids,
            role="authoring activity",
        )
        _require_bound_ids(
            self.author_agent_ids,
            self.agent_ids,
            role="author agent",
        )
        return self


class ResearchObservation(KernelContract):
    """A measured result with an explicit procedure and uncertainty boundary."""

    observation_id: StableId
    statement: NonEmptyText
    measurement_spec_ref: ContentAddressedRef
    result_entity_ids: list[StableId] = Field(min_length=1)
    uncertainty_entity_ids: list[StableId] = Field(default_factory=list)
    limitation_entity_ids: list[StableId] = Field(default_factory=list)
    provenance: ProvenanceBinding

    @field_validator(
        "result_entity_ids",
        "uncertainty_entity_ids",
        "limitation_entity_ids",
    )
    @classmethod
    def _normalize_ids(cls, value: list[str]) -> list[str]:
        return _sorted_unique(value, label="observation entity")

    @model_validator(mode="after")
    def _validate_observation(self) -> ResearchObservation:
        if not self.uncertainty_entity_ids and not self.limitation_entity_ids:
            raise ValueError("observation requires uncertainty or limitation evidence")
        _require_bound_ids(
            (
                *self.result_entity_ids,
                *self.uncertainty_entity_ids,
                *self.limitation_entity_ids,
            ),
            self.provenance.entity_ids,
            role="observation entity",
        )
        return self


class ResearchProblem(KernelContract):
    """A bounded problem grounded in observations, without a causal verdict."""

    problem_id: StableId
    observation_ids: list[StableId] = Field(min_length=1)
    statement: NonEmptyText
    scope: NonEmptyText
    provenance: ProvenanceBinding

    @field_validator("observation_ids")
    @classmethod
    def _normalize_ids(cls, value: list[str]) -> list[str]:
        return _sorted_unique(value, label="problem observation")


class ResearchHypothesis(KernelContract):
    """A falsifiable mechanism claim and its discriminating alternatives."""

    hypothesis_id: StableId
    problem_ids: list[StableId] = Field(min_length=1)
    mechanism_claim_id: StableId
    prediction_claim_ids: list[StableId] = Field(min_length=1)
    falsifier_claim_ids: list[StableId] = Field(min_length=1)
    competing_explanation_claim_ids: list[StableId] = Field(min_length=1)
    scope: NonEmptyText
    provenance: ProvenanceBinding

    @field_validator(
        "problem_ids",
        "prediction_claim_ids",
        "falsifier_claim_ids",
        "competing_explanation_claim_ids",
    )
    @classmethod
    def _normalize_ids(cls, value: list[str]) -> list[str]:
        return _sorted_unique(value, label="hypothesis reference")

    @model_validator(mode="after")
    def _validate_hypothesis(self) -> ResearchHypothesis:
        role_ids = [
            self.mechanism_claim_id,
            *self.prediction_claim_ids,
            *self.falsifier_claim_ids,
            *self.competing_explanation_claim_ids,
        ]
        if len(role_ids) != len(set(role_ids)):
            raise ValueError("hypothesis claim roles overlap")
        _require_bound_ids(
            role_ids,
            self.provenance.claim_ids,
            role="hypothesis claim",
        )
        return self


class ScientificIntervention(KernelContract):
    """A preregistered test derived from hypotheses, without observed results."""

    intervention_id: StableId
    hypothesis_ids: list[StableId] = Field(min_length=1)
    protocol_ref: ContentAddressedRef
    comparator_entity_ids: list[StableId] = Field(min_length=1)
    changed_factor_entity_ids: list[StableId] = Field(min_length=1)
    frozen_factor_entity_ids: list[StableId] = Field(min_length=1)
    estimand_claim_ids: list[StableId] = Field(min_length=1)
    metric_spec_entity_ids: list[StableId] = Field(min_length=1)
    decision_rule_entity_ids: list[StableId] = Field(min_length=1)
    harness_spec_ref: ContentAddressedRef
    loop_spec_ref: ContentAddressedRef
    provenance: ProvenanceBinding

    @field_validator(
        "hypothesis_ids",
        "comparator_entity_ids",
        "changed_factor_entity_ids",
        "frozen_factor_entity_ids",
        "estimand_claim_ids",
        "metric_spec_entity_ids",
        "decision_rule_entity_ids",
    )
    @classmethod
    def _normalize_ids(cls, value: list[str]) -> list[str]:
        return _sorted_unique(value, label="intervention reference")

    @model_validator(mode="after")
    def _validate_intervention(self) -> ScientificIntervention:
        overlap = set(self.changed_factor_entity_ids) & set(self.frozen_factor_entity_ids)
        if overlap:
            raise ValueError("changed and frozen factors overlap")
        _require_bound_ids(
            (
                *self.comparator_entity_ids,
                *self.changed_factor_entity_ids,
                *self.frozen_factor_entity_ids,
                *self.metric_spec_entity_ids,
                *self.decision_rule_entity_ids,
            ),
            self.provenance.entity_ids,
            role="intervention entity",
        )
        _require_bound_ids(
            self.estimand_claim_ids,
            self.provenance.claim_ids,
            role="intervention estimand claim",
        )
        return self


class HypothesisAssessmentRecord(KernelContract):
    """Evidence-aware interpretation of one hypothesis after an intervention."""

    hypothesis_id: StableId
    assessment: HypothesisAssessment
    supporting_evidence_ids: list[StableId] = Field(default_factory=list)
    counterevidence_ids: list[StableId] = Field(default_factory=list)
    limiting_evidence_ids: list[StableId] = Field(default_factory=list)
    failure_entity_ids: list[StableId] = Field(default_factory=list)
    objective_result_entity_ids: list[StableId] = Field(default_factory=list)
    uncertainty_entity_ids: list[StableId] = Field(default_factory=list)
    rationale: NonEmptyText

    @field_validator(
        "supporting_evidence_ids",
        "counterevidence_ids",
        "limiting_evidence_ids",
        "failure_entity_ids",
        "objective_result_entity_ids",
        "uncertainty_entity_ids",
    )
    @classmethod
    def _normalize_ids(cls, value: list[str]) -> list[str]:
        return _sorted_unique(value, label="assessment reference")

    @model_validator(mode="after")
    def _validate_assessment(self) -> HypothesisAssessmentRecord:
        evidence_roles = (
            self.supporting_evidence_ids,
            self.counterevidence_ids,
            self.limiting_evidence_ids,
        )
        flattened = [item for role in evidence_roles for item in role]
        if len(flattened) != len(set(flattened)):
            raise ValueError("assessment evidence roles overlap")

        if self.assessment == HypothesisAssessment.SUPPORTED:
            if not self.supporting_evidence_ids:
                raise ValueError("supported assessment requires supporting evidence")
            self._require_result_and_uncertainty()
        elif self.assessment == HypothesisAssessment.CONTRADICTED:
            if not self.counterevidence_ids:
                raise ValueError("contradicted assessment requires counterevidence")
            self._require_result_and_uncertainty()
        else:
            if not self.uncertainty_entity_ids:
                raise ValueError("inconclusive assessment requires uncertainty")
            if not self.limiting_evidence_ids and not self.failure_entity_ids:
                raise ValueError(
                    "inconclusive assessment requires limiting evidence or a failure entity"
                )
        return self

    def _require_result_and_uncertainty(self) -> None:
        if not self.objective_result_entity_ids or not self.uncertainty_entity_ids:
            raise ValueError("assessment requires an objective result and uncertainty")


class ResearchEvaluation(KernelContract):
    """An external evaluation report and its per-hypothesis interpretations."""

    evaluation_id: StableId
    intervention_ids: list[StableId] = Field(min_length=1)
    evaluation_report_ref: ContentAddressedRef
    evaluation_subject_hash: Sha256
    assessments: list[HypothesisAssessmentRecord] = Field(min_length=1)
    provenance: ProvenanceBinding

    @field_validator("intervention_ids")
    @classmethod
    def _normalize_ids(cls, value: list[str]) -> list[str]:
        return _sorted_unique(value, label="evaluation intervention")

    @model_validator(mode="after")
    def _validate_evaluation(self) -> ResearchEvaluation:
        assessment_ids = [item.hypothesis_id for item in self.assessments]
        if len(assessment_ids) != len(set(assessment_ids)):
            raise ValueError("duplicate hypothesis assessments")
        self.assessments = sorted(self.assessments, key=lambda item: item.hypothesis_id)

        evidence_ids = [
            evidence_id
            for assessment in self.assessments
            for evidence_id in (
                *assessment.supporting_evidence_ids,
                *assessment.counterevidence_ids,
                *assessment.limiting_evidence_ids,
            )
        ]
        entity_ids = [
            entity_id
            for assessment in self.assessments
            for entity_id in (
                *assessment.failure_entity_ids,
                *assessment.objective_result_entity_ids,
                *assessment.uncertainty_entity_ids,
            )
        ]
        _require_bound_ids(
            evidence_ids,
            self.provenance.evidence_ids,
            role="evaluation evidence",
        )
        _require_bound_ids(
            entity_ids,
            self.provenance.entity_ids,
            role="evaluation entity",
        )
        return self


ScientificRecord = (
    ResearchObservation
    | ResearchProblem
    | ResearchHypothesis
    | ScientificIntervention
    | ResearchEvaluation
)


def scientific_record_semantic_hash(record: ScientificRecord) -> str:
    """Hash one versioned lifecycle record without its provenance container.

    Evaluation report identity is excluded to avoid a report-to-provenance hash
    cycle. The separately required evaluation subject hash remains in scope.
    """

    supported_types = {
        ResearchObservation,
        ResearchProblem,
        ResearchHypothesis,
        ScientificIntervention,
        ResearchEvaluation,
    }
    if type(record) not in supported_types:
        raise TypeError(f"unsupported scientific record type: {type(record).__name__}")

    excluded_fields = {"provenance"}
    if isinstance(record, ResearchEvaluation):
        excluded_fields.add("evaluation_report_ref")
    return canonical_sha256(
        {
            "schema_version": 1,
            "record_type": type(record).__name__,
            "record": record.model_dump(mode="json", exclude=excluded_fields),
        }
    )


class _ScientificCycleSnapshotContent(KernelContract):
    """Validated cycle content before its canonical hash is attached."""

    schema_version: Literal[1] = 1
    cycle_id: StableId
    version: int = Field(ge=1)
    parent_snapshot_ref: ScientificCycleParentRef | None = None
    observations: list[ResearchObservation] = Field(min_length=1)
    problems: list[ResearchProblem] = Field(default_factory=list)
    hypotheses: list[ResearchHypothesis] = Field(default_factory=list)
    interventions: list[ScientificIntervention] = Field(default_factory=list)
    evaluations: list[ResearchEvaluation] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_cycle(self) -> _ScientificCycleSnapshotContent:
        if self.version == 1:
            if self.parent_snapshot_ref is not None:
                raise ValueError("scientific cycle version 1 cannot declare a parent")
        else:
            if self.parent_snapshot_ref is None:
                raise ValueError("scientific cycle version greater than 1 requires a parent")
            if self.parent_snapshot_ref.cycle_id != self.cycle_id:
                raise ValueError("scientific cycle parent must belong to the same cycle")
            if self.parent_snapshot_ref.version != self.version - 1:
                raise ValueError("scientific cycle parent must be the immediate previous version")

        self.observations = sorted(self.observations, key=lambda item: item.observation_id)
        self.problems = sorted(self.problems, key=lambda item: item.problem_id)
        self.hypotheses = sorted(self.hypotheses, key=lambda item: item.hypothesis_id)
        self.interventions = sorted(
            self.interventions,
            key=lambda item: item.intervention_id,
        )
        self.evaluations = sorted(self.evaluations, key=lambda item: item.evaluation_id)

        record_ids = [
            *(item.observation_id for item in self.observations),
            *(item.problem_id for item in self.problems),
            *(item.hypothesis_id for item in self.hypotheses),
            *(item.intervention_id for item in self.interventions),
            *(item.evaluation_id for item in self.evaluations),
        ]
        duplicates = _duplicates(record_ids)
        if duplicates:
            raise ValueError("duplicate scientific record IDs: " + ", ".join(sorted(duplicates)))

        observation_ids = {item.observation_id for item in self.observations}
        for problem in self.problems:
            _require_existing_ids(
                problem.observation_ids,
                observation_ids,
                role="observation",
                owner=problem.problem_id,
            )

        problem_ids = {item.problem_id for item in self.problems}
        for hypothesis in self.hypotheses:
            _require_existing_ids(
                hypothesis.problem_ids,
                problem_ids,
                role="problem",
                owner=hypothesis.hypothesis_id,
            )

        hypothesis_ids = {item.hypothesis_id for item in self.hypotheses}
        interventions_by_id = {item.intervention_id: item for item in self.interventions}
        for intervention in self.interventions:
            _require_existing_ids(
                intervention.hypothesis_ids,
                hypothesis_ids,
                role="hypothesis",
                owner=intervention.intervention_id,
            )

        intervention_ids = set(interventions_by_id)
        for evaluation in self.evaluations:
            _require_existing_ids(
                evaluation.intervention_ids,
                intervention_ids,
                role="intervention",
                owner=evaluation.evaluation_id,
            )
            tested_hypotheses = {
                hypothesis_id
                for intervention_id in evaluation.intervention_ids
                for hypothesis_id in interventions_by_id[intervention_id].hypothesis_ids
            }
            assessed_hypotheses = {
                assessment.hypothesis_id for assessment in evaluation.assessments
            }
            if assessed_hypotheses != tested_hypotheses:
                raise ValueError(
                    f"evaluation {evaluation.evaluation_id} must assess exactly the "
                    "hypotheses tested by its interventions"
                )
        return self


class ScientificCycleSnapshot(_ScientificCycleSnapshotContent):
    """A content-addressed, incomplete-or-complete mechanism research cycle."""

    snapshot_hash: Sha256

    @model_validator(mode="after")
    def _verify_snapshot_hash(self) -> ScientificCycleSnapshot:
        expected = self.calculated_hash()
        if self.snapshot_hash != expected:
            raise ValueError(
                f"scientific cycle snapshot hash mismatch: expected {expected}, "
                f"got {self.snapshot_hash}"
            )
        return self

    @classmethod
    def create(
        cls,
        *,
        cycle_id: str,
        version: int,
        observations: list[ResearchObservation],
        schema_version: Literal[1] = 1,
        parent_snapshot_ref: ScientificCycleParentRef | None = None,
        problems: list[ResearchProblem] | None = None,
        hypotheses: list[ResearchHypothesis] | None = None,
        interventions: list[ScientificIntervention] | None = None,
        evaluations: list[ResearchEvaluation] | None = None,
    ) -> ScientificCycleSnapshot:
        """Normalize and validate cycle content before attaching its digest."""

        content = _ScientificCycleSnapshotContent.model_validate(
            {
                "schema_version": schema_version,
                "cycle_id": cycle_id,
                "version": version,
                "parent_snapshot_ref": parent_snapshot_ref,
                "observations": observations,
                "problems": problems or [],
                "hypotheses": hypotheses or [],
                "interventions": interventions or [],
                "evaluations": evaluations or [],
            }
        )
        payload = content.model_dump(mode="json")
        payload["snapshot_hash"] = canonical_sha256(content)
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Calculate the digest over normalized fields except ``snapshot_hash``."""

        return canonical_sha256(self.model_dump(mode="json", exclude={"snapshot_hash"}))

    def verify_integrity(self) -> None:
        """Fail closed if nested content was mutated after validation."""

        expected = self.calculated_hash()
        if self.snapshot_hash != expected:
            raise ContractIntegrityError(
                "scientific cycle snapshot failed integrity verification: "
                f"expected {expected}, got {self.snapshot_hash}"
            )

    def knowledge_snapshot(self, *, graph_id: str | None = None) -> GraphSnapshot:
        """Project only lifecycle semantics into the existing knowledge plane."""

        self.verify_integrity()
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []

        for observation in self.observations:
            nodes.append(
                GraphNode(
                    node_id=observation.observation_id,
                    plane=GraphPlane.KNOWLEDGE,
                    node_type="research.observation",
                    label=observation.statement,
                    attributes={"external_validation": "unverified"},
                )
            )
        for problem in self.problems:
            nodes.append(
                GraphNode(
                    node_id=problem.problem_id,
                    plane=GraphPlane.KNOWLEDGE,
                    node_type="research.problem",
                    label=problem.statement,
                    attributes={
                        "scope": problem.scope,
                        "external_validation": "unverified",
                    },
                )
            )
            for observation_id in problem.observation_ids:
                edges.append(_knowledge_edge("grounds", observation_id, problem.problem_id))
        for hypothesis in self.hypotheses:
            nodes.append(
                GraphNode(
                    node_id=hypothesis.hypothesis_id,
                    plane=GraphPlane.KNOWLEDGE,
                    node_type="research.hypothesis",
                    label=hypothesis.scope,
                    attributes={
                        "mechanism_claim_id": hypothesis.mechanism_claim_id,
                        "external_validation": "unverified",
                    },
                )
            )
            for problem_id in hypothesis.problem_ids:
                edges.append(_knowledge_edge("motivates", problem_id, hypothesis.hypothesis_id))
        for intervention in self.interventions:
            nodes.append(
                GraphNode(
                    node_id=intervention.intervention_id,
                    plane=GraphPlane.KNOWLEDGE,
                    node_type="research.intervention",
                    label="Declared scientific intervention",
                    attributes={"external_validation": "unverified"},
                )
            )
            for hypothesis_id in intervention.hypothesis_ids:
                edges.append(_knowledge_edge("tests", intervention.intervention_id, hypothesis_id))
        for evaluation in self.evaluations:
            nodes.append(
                GraphNode(
                    node_id=evaluation.evaluation_id,
                    plane=GraphPlane.KNOWLEDGE,
                    node_type="research.evaluation",
                    label="Declared research evaluation",
                    attributes={"external_validation": "unverified"},
                )
            )
            for assessment in evaluation.assessments:
                edges.append(
                    _knowledge_edge(
                        "assesses",
                        evaluation.evaluation_id,
                        assessment.hypothesis_id,
                        attributes={"declared_assessment": assessment.assessment.value},
                    )
                )

        effective_graph_id = graph_id or f"knowledge_{self.snapshot_hash}"
        return GraphSnapshot(
            graph_id=effective_graph_id,
            version=self.version,
            plane=GraphPlane.KNOWLEDGE,
            nodes=nodes,
            edges=edges,
            metadata={
                "cycle_id": self.cycle_id,
                "scientific_cycle_snapshot_hash": self.snapshot_hash,
                "external_validation": "unverified",
            },
        )


SCIENTIFIC_CYCLE_MODELS = (
    ContentAddressedRef,
    ScientificCycleParentRef,
    ProvenanceBinding,
    ResearchObservation,
    ResearchProblem,
    ResearchHypothesis,
    ScientificIntervention,
    HypothesisAssessmentRecord,
    ResearchEvaluation,
    ScientificCycleSnapshot,
)


def scientific_cycle_json_schemas() -> dict[str, dict[str, Any]]:
    """Export deterministic JSON Schemas for the public lifecycle contracts."""

    return {model.__name__: model.model_json_schema() for model in SCIENTIFIC_CYCLE_MODELS}


def _sorted_unique(values: list[str], *, label: str) -> list[str]:
    duplicates = _duplicates(values)
    if duplicates:
        raise ValueError(f"duplicate {label} IDs: {', '.join(sorted(duplicates))}")
    return sorted(values)


def _duplicates(values: list[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def _require_bound_ids(
    referenced_ids: tuple[str, ...] | list[str],
    bound_ids: list[str],
    *,
    role: str,
) -> None:
    missing = set(referenced_ids) - set(bound_ids)
    if missing:
        raise ValueError(f"{role} IDs are not present in provenance: {', '.join(sorted(missing))}")


def _require_existing_ids(
    referenced_ids: list[str],
    available_ids: set[str],
    *,
    role: str,
    owner: str,
) -> None:
    missing = set(referenced_ids) - available_ids
    if missing:
        raise ValueError(f"{owner} references missing {role}: {', '.join(sorted(missing))}")


def _knowledge_edge(
    edge_type: Literal["grounds", "motivates", "tests", "assesses"],
    source_id: str,
    target_id: str,
    *,
    attributes: dict[str, JsonValue] | None = None,
) -> GraphEdge:
    edge_hash = canonical_sha256(
        {
            "edge_type": edge_type,
            "source_id": source_id,
            "target_id": target_id,
        }
    )
    return GraphEdge(
        edge_id=f"edge_{edge_hash}",
        plane=GraphPlane.KNOWLEDGE,
        edge_type=edge_type,
        source_id=source_id,
        target_id=target_id,
        attributes=attributes or {},
    )
