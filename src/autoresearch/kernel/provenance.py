"""W3C PROV-aligned, content-addressed provenance contracts.

The contracts keep the project domain model independent from a particular
graph database or JSON-LD serializer.  They cover the PROV starting points
(Entity, Activity, Agent), qualified relations, and the research-specific
claim/evidence/validation/decision chain used by AutoResearch.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import Field, JsonValue, field_validator, model_validator

from autoresearch.schemas import ValidationStatus

from .contracts import KernelContract, NonEmptyText, Sha256, StableId, canonical_sha256


class ProvenanceError(RuntimeError):
    """Base error for invalid provenance operations."""


class ProvenanceIntegrityError(ProvenanceError):
    """Raised when a content-addressed bundle no longer matches its digest."""


class ClaimTraceError(ProvenanceError):
    """Raised when a claim lacks a complete validated causal chain."""


class EntityKind(str, Enum):
    """Research object kinds represented as PROV entities."""

    SOURCE_SNAPSHOT = "source_snapshot"
    INPUT = "input"
    ARTIFACT = "artifact"
    CODE = "code"
    MODEL_CONFIG = "model_config"
    HYPOTHESIS = "hypothesis"
    LITERATURE = "literature"
    FAILURE = "failure"
    SKILL = "skill"
    STRATEGY = "strategy"
    EXPERIMENT_RECORD = "experiment_record"
    DECISION = "decision"


class ActivityKind(str, Enum):
    """Research activities that use and generate entities."""

    RETRIEVAL = "retrieval"
    PROPOSAL = "proposal"
    EXECUTION = "execution"
    VALIDATION = "validation"
    DECISION = "decision"
    PROJECTION = "projection"
    TOOL_INVOCATION = "tool_invocation"


class ProvenanceAgentKind(str, Enum):
    """Responsible agents without assuming one model or workflow vendor."""

    PERSON = "person"
    ORGANIZATION = "organization"
    SOFTWARE = "software"
    MODEL = "model"
    TOOL = "tool"
    DETERMINISTIC_POLICY = "deterministic_policy"


class EvidenceDirection(str, Enum):
    """Directional relationship between evidence and a claim."""

    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    LIMITS = "limits"


class InvocationStatus(str, Enum):
    """Terminal status retained for tool and model interaction digests."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


class VersionedRecord(KernelContract):
    """Shared version and valid-time envelope for provenance records."""

    version: int = Field(default=1, ge=1)
    valid_from: datetime
    valid_to: datetime | None = None
    invalidated_at: datetime | None = None
    supersedes_id: StableId | None = None
    event_ids: list[StableId] = Field(default_factory=list)

    @field_validator("valid_from", "valid_to", "invalidated_at")
    @classmethod
    def _require_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("provenance timestamps must be timezone-aware UTC")
        return value.astimezone(timezone.utc)

    @field_validator("event_ids")
    @classmethod
    def _sort_unique_event_ids(cls, value: list[str]) -> list[str]:
        _require_unique(value, "event")
        return sorted(value)

    @model_validator(mode="after")
    def _validate_valid_time(self) -> VersionedRecord:
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("valid_to cannot precede valid_from")
        if self.invalidated_at is not None and self.invalidated_at < self.valid_from:
            raise ValueError("invalidated_at cannot precede valid_from")
        if (
            self.valid_to is not None
            and self.invalidated_at is not None
            and self.invalidated_at > self.valid_to
        ):
            raise ValueError("invalidated_at cannot follow valid_to")
        if self.version > 1 and self.supersedes_id is None:
            raise ValueError("versions after one must identify the superseded record")
        if self.version == 1 and self.supersedes_id is not None:
            raise ValueError("version one cannot supersede another record")
        return self


class Entity(VersionedRecord):
    """A physical, digital, conceptual, or other research thing."""

    entity_id: StableId
    kind: EntityKind
    label: NonEmptyText
    content_digest: Sha256 | None = None
    source_uri: NonEmptyText | None = None
    media_type: NonEmptyText | None = None
    attributes: dict[str, JsonValue] = Field(default_factory=dict)


class Activity(VersionedRecord):
    """An interval during which entities are used or generated."""

    activity_id: StableId
    kind: ActivityKind
    label: NonEmptyText
    started_at: datetime
    ended_at: datetime
    attributes: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("started_at", "ended_at")
    @classmethod
    def _require_activity_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("activity timestamps must be timezone-aware UTC")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _validate_activity_interval(self) -> Activity:
        if self.ended_at < self.started_at:
            raise ValueError("activity ended_at cannot precede started_at")
        if self.valid_from > self.started_at:
            raise ValueError("activity valid_from cannot follow started_at")
        if self.valid_to is not None and self.ended_at > self.valid_to:
            raise ValueError("activity ended_at cannot follow valid_to")
        return self


class Agent(VersionedRecord):
    """A person, organization, model, tool, or software bearer of responsibility."""

    agent_id: StableId
    kind: ProvenanceAgentKind
    label: NonEmptyText
    implementation_hash: Sha256 | None = None
    attributes: dict[str, JsonValue] = Field(default_factory=dict)


class Plan(VersionedRecord):
    """A PROV plan that constrains an associated activity."""

    plan_id: StableId
    title: NonEmptyText
    description: NonEmptyText
    content_digest: Sha256


class Usage(VersionedRecord):
    """Qualified PROV usage: an activity used an entity."""

    usage_id: StableId
    activity_id: StableId
    entity_id: StableId
    role: NonEmptyText
    at_time: datetime

    @field_validator("at_time")
    @classmethod
    def _require_usage_utc(cls, value: datetime) -> datetime:
        return _utc(value, "usage at_time")


class Generation(VersionedRecord):
    """Qualified PROV generation: an activity generated an entity."""

    generation_id: StableId
    entity_id: StableId
    activity_id: StableId
    at_time: datetime

    @field_validator("at_time")
    @classmethod
    def _require_generation_utc(cls, value: datetime) -> datetime:
        return _utc(value, "generation at_time")


class Derivation(VersionedRecord):
    """Qualified derivation between a generated and a used entity."""

    derivation_id: StableId
    generated_entity_id: StableId
    used_entity_id: StableId
    activity_id: StableId | None = None
    kind: Literal["derivation", "revision"] = "derivation"


class Association(VersionedRecord):
    """Qualified association between an activity, agent, and optional plan."""

    association_id: StableId
    activity_id: StableId
    agent_id: StableId
    role: NonEmptyText
    plan_id: StableId | None = None
    at_time: datetime

    @field_validator("at_time")
    @classmethod
    def _require_association_utc(cls, value: datetime) -> datetime:
        return _utc(value, "association at_time")


class SourceSnapshot(VersionedRecord):
    """Immutable source capture anchoring evidence to retrievable content."""

    snapshot_id: StableId
    entity_id: StableId
    source_uri: NonEmptyText
    retrieved_at: datetime
    content_digest: Sha256
    media_type: NonEmptyText = "application/json"

    @field_validator("retrieved_at")
    @classmethod
    def _require_retrieved_utc(cls, value: datetime) -> datetime:
        return _utc(value, "source snapshot retrieved_at")


class Claim(VersionedRecord):
    """A scoped scientific or operational assertion."""

    claim_id: StableId
    statement: NonEmptyText
    project_id: StableId | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    core: bool = False


class _EvidenceRecord(VersionedRecord):
    """Shared fields for directional evidence and counterevidence."""

    evidence_id: StableId
    claim_id: StableId
    artifact_entity_id: StableId
    source_entity_id: StableId
    source_snapshot_id: StableId
    generating_activity_id: StableId
    responsible_agent_ids: list[StableId] = Field(min_length=1)
    validation_ids: list[StableId] = Field(min_length=1)
    summary: NonEmptyText
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("responsible_agent_ids", "validation_ids")
    @classmethod
    def _sort_unique_references(cls, value: list[str]) -> list[str]:
        _require_unique(value, "evidence reference")
        return sorted(value)


class Evidence(_EvidenceRecord):
    """Evidence supporting or limiting a claim."""

    direction: Literal[EvidenceDirection.SUPPORTS, EvidenceDirection.LIMITS]


class Counterevidence(_EvidenceRecord):
    """Evidence that contradicts a claim."""

    direction: Literal[EvidenceDirection.CONTRADICTS] = EvidenceDirection.CONTRADICTS


class Validation(VersionedRecord):
    """A timestamped validation result in a subject's validation history."""

    validation_id: StableId
    subject_id: StableId
    activity_id: StableId
    agent_id: StableId
    status: ValidationStatus
    summary: NonEmptyText
    checked_at: datetime
    artifact_entity_id: StableId | None = None

    @field_validator("checked_at")
    @classmethod
    def _require_checked_utc(cls, value: datetime) -> datetime:
        return _utc(value, "validation checked_at")


class Decision(VersionedRecord):
    """A policy decision grounded in claims and validation records."""

    decision_id: StableId
    claim_ids: list[StableId] = Field(min_length=1)
    activity_id: StableId
    responsible_agent_id: StableId
    validation_ids: list[StableId] = Field(min_length=1)
    artifact_entity_id: StableId
    outcome: NonEmptyText
    rationale: NonEmptyText
    decided_at: datetime

    @field_validator("claim_ids", "validation_ids")
    @classmethod
    def _sort_unique_decision_refs(cls, value: list[str]) -> list[str]:
        _require_unique(value, "decision reference")
        return sorted(value)

    @field_validator("decided_at")
    @classmethod
    def _require_decided_utc(cls, value: datetime) -> datetime:
        return _utc(value, "decision decided_at")


class ToolInvocation(VersionedRecord):
    """Digest-only record of a tool call; raw payloads are intentionally absent."""

    invocation_id: StableId
    activity_id: StableId
    agent_id: StableId
    tool_name: NonEmptyText
    request_digest: Sha256
    response_digest: Sha256
    input_entity_ids: list[StableId] = Field(default_factory=list)
    output_entity_ids: list[StableId] = Field(default_factory=list)
    status: InvocationStatus
    started_at: datetime
    completed_at: datetime

    @field_validator("input_entity_ids", "output_entity_ids")
    @classmethod
    def _sort_unique_invocation_refs(cls, value: list[str]) -> list[str]:
        _require_unique(value, "tool entity")
        return sorted(value)

    @field_validator("started_at", "completed_at")
    @classmethod
    def _require_invocation_utc(cls, value: datetime) -> datetime:
        return _utc(value, "tool invocation timestamp")

    @model_validator(mode="after")
    def _validate_invocation_interval(self) -> ToolInvocation:
        if self.completed_at < self.started_at:
            raise ValueError("tool invocation completed_at cannot precede started_at")
        return self


class ModelInteractionDigest(VersionedRecord):
    """Provider-neutral model interaction metadata without raw prompt or response."""

    interaction_id: StableId
    activity_id: StableId
    agent_id: StableId
    model_name: NonEmptyText
    provider: NonEmptyText
    prompt_digest: Sha256
    response_digest: Sha256
    tool_invocation_ids: list[StableId] = Field(default_factory=list)
    status: InvocationStatus
    started_at: datetime
    completed_at: datetime

    @field_validator("tool_invocation_ids")
    @classmethod
    def _sort_unique_tool_refs(cls, value: list[str]) -> list[str]:
        _require_unique(value, "model tool invocation")
        return sorted(value)

    @field_validator("started_at", "completed_at")
    @classmethod
    def _require_interaction_utc(cls, value: datetime) -> datetime:
        return _utc(value, "model interaction timestamp")

    @model_validator(mode="after")
    def _validate_interaction_interval(self) -> ModelInteractionDigest:
        if self.completed_at < self.started_at:
            raise ValueError("model interaction completed_at cannot precede started_at")
        return self


class ClaimTrace(KernelContract):
    """Resolved, validated causal path for one claim."""

    claim_id: StableId
    evidence_ids: list[StableId]
    counterevidence_ids: list[StableId]
    limiting_evidence_ids: list[StableId]
    source_entity_ids: list[StableId]
    input_entity_ids: list[StableId]
    activity_ids: list[StableId]
    agent_ids: list[StableId]
    artifact_entity_ids: list[StableId]
    validation_ids: list[StableId]
    decision_ids: list[StableId]


class _ProvenanceBundleContent(KernelContract):
    """Validated bundle content before its canonical digest is attached."""

    schema_version: Literal[2] = 2
    bundle_id: StableId
    project_id: StableId
    run_id: StableId
    created_at: datetime
    entities: list[Entity] = Field(default_factory=list)
    activities: list[Activity] = Field(default_factory=list)
    agents: list[Agent] = Field(default_factory=list)
    plans: list[Plan] = Field(default_factory=list)
    usages: list[Usage] = Field(default_factory=list)
    generations: list[Generation] = Field(default_factory=list)
    derivations: list[Derivation] = Field(default_factory=list)
    associations: list[Association] = Field(default_factory=list)
    source_snapshots: list[SourceSnapshot] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    counterevidence: list[Counterevidence] = Field(default_factory=list)
    validations: list[Validation] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    tool_invocations: list[ToolInvocation] = Field(default_factory=list)
    model_interactions: list[ModelInteractionDigest] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("created_at")
    @classmethod
    def _require_created_utc(cls, value: datetime) -> datetime:
        return _utc(value, "bundle created_at")

    @model_validator(mode="after")
    def _validate_bundle(self) -> _ProvenanceBundleContent:
        self._sort_records()
        self._validate_unique_ids()
        self._validate_references()
        self._validate_revisions()
        return self

    def _sort_records(self) -> None:
        for field_name, id_field in _COLLECTION_ID_FIELDS:
            records = cast(list[KernelContract], getattr(self, field_name))
            records.sort(key=lambda record: str(getattr(record, id_field)))

    def _validate_unique_ids(self) -> None:
        all_ids: list[str] = []
        for field_name, id_field in _COLLECTION_ID_FIELDS:
            records = cast(list[KernelContract], getattr(self, field_name))
            all_ids.extend(str(getattr(record, id_field)) for record in records)
        _require_unique(all_ids, "provenance record")

    def _validate_references(self) -> None:
        entities = _index(self.entities, "entity_id")
        activities = _index(self.activities, "activity_id")
        agents = _index(self.agents, "agent_id")
        plans = _index(self.plans, "plan_id")
        claims = _index(self.claims, "claim_id")
        evidence_records = {
            **_index(self.evidence, "evidence_id"),
            **_index(self.counterevidence, "evidence_id"),
        }
        validations = _index(self.validations, "validation_id")
        decisions = _index(self.decisions, "decision_id")
        invocations = _index(self.tool_invocations, "invocation_id")
        snapshots = _index(self.source_snapshots, "snapshot_id")

        for usage in self.usages:
            activity = _require_ref(activities, usage.activity_id, usage.usage_id, "activity")
            _require_ref(entities, usage.entity_id, usage.usage_id, "entity")
            _require_within_activity(usage.at_time, activity, usage.usage_id)
        for generation in self.generations:
            activity = _require_ref(
                activities, generation.activity_id, generation.generation_id, "activity"
            )
            _require_ref(entities, generation.entity_id, generation.generation_id, "entity")
            _require_within_activity(generation.at_time, activity, generation.generation_id)
        for derivation in self.derivations:
            _require_ref(
                entities,
                derivation.generated_entity_id,
                derivation.derivation_id,
                "generated entity",
            )
            _require_ref(
                entities, derivation.used_entity_id, derivation.derivation_id, "used entity"
            )
            if derivation.activity_id is not None:
                _require_ref(
                    activities, derivation.activity_id, derivation.derivation_id, "activity"
                )
        for association in self.associations:
            activity = _require_ref(
                activities, association.activity_id, association.association_id, "activity"
            )
            _require_ref(agents, association.agent_id, association.association_id, "agent")
            if association.plan_id is not None:
                _require_ref(plans, association.plan_id, association.association_id, "plan")
            _require_within_activity(association.at_time, activity, association.association_id)
        for snapshot in self.source_snapshots:
            entity = _require_ref(entities, snapshot.entity_id, snapshot.snapshot_id, "entity")
            if entity.kind is not EntityKind.SOURCE_SNAPSHOT:
                raise ValueError(
                    f"source snapshot {snapshot.snapshot_id} references non-source entity "
                    f"{entity.entity_id}"
                )
            if entity.content_digest != snapshot.content_digest:
                raise ValueError(
                    f"source snapshot {snapshot.snapshot_id} content hash differs from entity"
                )
        for item in [*self.evidence, *self.counterevidence]:
            _require_ref(claims, item.claim_id, item.evidence_id, "claim")
            _require_ref(entities, item.artifact_entity_id, item.evidence_id, "artifact entity")
            _require_ref(entities, item.source_entity_id, item.evidence_id, "source entity")
            snapshot = _require_ref(
                snapshots, item.source_snapshot_id, item.evidence_id, "source snapshot"
            )
            if snapshot.entity_id != item.source_entity_id:
                raise ValueError(
                    f"evidence {item.evidence_id} source and snapshot entity differ"
                )
            _require_ref(
                activities,
                item.generating_activity_id,
                item.evidence_id,
                "generating activity",
            )
            for agent_id in item.responsible_agent_ids:
                _require_ref(agents, agent_id, item.evidence_id, "responsible agent")
            for validation_id in item.validation_ids:
                validation = _require_ref(
                    validations, validation_id, item.evidence_id, "validation"
                )
                if validation.subject_id != item.evidence_id:
                    raise ValueError(
                        f"validation {validation_id} does not validate evidence "
                        f"{item.evidence_id}"
                    )
        valid_subject_ids = set(entities) | set(claims) | set(evidence_records) | set(decisions)
        for validation in self.validations:
            if validation.subject_id not in valid_subject_ids:
                raise ValueError(
                    f"validation {validation.validation_id} references missing subject "
                    f"{validation.subject_id}"
                )
            _require_ref(
                activities, validation.activity_id, validation.validation_id, "activity"
            )
            _require_ref(agents, validation.agent_id, validation.validation_id, "agent")
            if validation.artifact_entity_id is not None:
                _require_ref(
                    entities,
                    validation.artifact_entity_id,
                    validation.validation_id,
                    "artifact entity",
                )
        for decision in self.decisions:
            for claim_id in decision.claim_ids:
                _require_ref(claims, claim_id, decision.decision_id, "claim")
            _require_ref(activities, decision.activity_id, decision.decision_id, "activity")
            _require_ref(agents, decision.responsible_agent_id, decision.decision_id, "agent")
            _require_ref(
                entities,
                decision.artifact_entity_id,
                decision.decision_id,
                "artifact entity",
            )
            for validation_id in decision.validation_ids:
                _require_ref(validations, validation_id, decision.decision_id, "validation")
        for invocation in self.tool_invocations:
            _require_ref(activities, invocation.activity_id, invocation.invocation_id, "activity")
            _require_ref(agents, invocation.agent_id, invocation.invocation_id, "agent")
            for entity_id in [*invocation.input_entity_ids, *invocation.output_entity_ids]:
                _require_ref(entities, entity_id, invocation.invocation_id, "entity")
        for interaction in self.model_interactions:
            _require_ref(
                activities, interaction.activity_id, interaction.interaction_id, "activity"
            )
            agent = _require_ref(agents, interaction.agent_id, interaction.interaction_id, "agent")
            if agent.kind is not ProvenanceAgentKind.MODEL:
                raise ValueError(
                    f"model interaction {interaction.interaction_id} requires a model agent"
                )
            for invocation_id in interaction.tool_invocation_ids:
                _require_ref(
                    invocations, invocation_id, interaction.interaction_id, "tool invocation"
                )

    def _validate_revisions(self) -> None:
        for field_name, id_field in _VERSIONED_COLLECTION_ID_FIELDS:
            records = cast(list[VersionedRecord], getattr(self, field_name))
            by_id = {str(getattr(record, id_field)): record for record in records}
            for record_id, record in by_id.items():
                if record.supersedes_id is None:
                    continue
                previous = by_id.get(record.supersedes_id)
                if previous is None:
                    raise ValueError(
                        f"{field_name} record {record_id} supersedes missing "
                        f"{record.supersedes_id}"
                    )
                if record.version <= previous.version:
                    raise ValueError(
                        f"{field_name} record {record_id} must increase predecessor version"
                    )
                if previous.invalidated_at is None:
                    raise ValueError(
                        f"superseded {field_name} record {record.supersedes_id} "
                        "must be invalidated"
                    )
                if record.valid_from < previous.invalidated_at:
                    raise ValueError(
                        f"{field_name} record {record_id} starts before predecessor invalidation"
                    )


class ProvenanceBundle(_ProvenanceBundleContent):
    """Content-addressed provenance bundle with fail-closed claim tracing."""

    bundle_hash: Sha256

    @model_validator(mode="after")
    def _validate_bundle_hash(self) -> ProvenanceBundle:
        expected = self.calculated_hash()
        if self.bundle_hash != expected:
            raise ValueError(
                f"bundle_hash mismatch for {self.bundle_id}: "
                f"expected {expected}, got {self.bundle_hash}"
            )
        return self

    @classmethod
    def create(cls, **values: Any) -> ProvenanceBundle:
        """Validate, canonicalize, and attach a content digest."""

        content = _ProvenanceBundleContent.model_validate(values)
        payload = content.model_dump(mode="json")
        payload["bundle_hash"] = canonical_sha256(payload)
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Calculate the digest over all canonical fields except ``bundle_hash``."""

        return canonical_sha256(self.model_dump(mode="json", exclude={"bundle_hash"}))

    def verify_integrity(self) -> None:
        """Fail closed if the in-memory bundle was changed after validation."""

        expected = self.calculated_hash()
        if self.bundle_hash != expected:
            raise ProvenanceIntegrityError(
                f"provenance bundle {self.bundle_id} failed integrity verification: "
                f"expected {expected}, got {self.bundle_hash}"
            )

    def save_json(self, path: Path | str) -> Path:
        """Persist canonical bundle content as readable deterministic JSON."""

        self.verify_integrity()
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(
                self.model_dump(mode="json"),
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        return output_path

    @classmethod
    def load_json(cls, path: Path | str) -> ProvenanceBundle:
        """Load and verify a persisted bundle."""

        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))

    def latest_validation(self, evidence_id: str) -> Validation:
        """Return the current validation in an evidence record's history."""

        records = [
            item
            for item in [*self.evidence, *self.counterevidence]
            if item.evidence_id == evidence_id
        ]
        if not records:
            raise ClaimTraceError(f"missing evidence {evidence_id}")
        record = _current_record(records, "evidence")
        linked = [
            validation
            for validation in self.validations
            if validation.validation_id in record.validation_ids
        ]
        return cast(Validation, _current_record(linked, "validation"))

    def require_claim_trace(self, claim_id: str) -> ClaimTrace:
        """Resolve a complete validated source-to-decision causal chain."""

        self.verify_integrity()
        claim_records = [claim for claim in self.claims if claim.claim_id == claim_id]
        claim = _current_record(claim_records, "claim")
        if claim.invalidated_at is not None:
            raise ClaimTraceError(f"claim {claim_id} is invalidated")

        current_evidence = self._current_evidence_for_claim(claim_id)
        supporting = [
            item
            for item in current_evidence
            if item.direction is EvidenceDirection.SUPPORTS
            and item.invalidated_at is None
            and self.latest_validation(item.evidence_id).status
            in {ValidationStatus.PASSED, ValidationStatus.WARNING}
        ]
        if not supporting:
            raise ClaimTraceError(
                f"claim {claim_id} lacks current supporting evidence with a passing validation"
            )

        entities = _index(self.entities, "entity_id")
        activities = _index(self.activities, "activity_id")
        associations_by_activity: dict[str, list[Association]] = {}
        for association in self.associations:
            if association.invalidated_at is None:
                associations_by_activity.setdefault(association.activity_id, []).append(association)
        usages_by_activity: dict[str, list[Usage]] = {}
        for usage in self.usages:
            if usage.invalidated_at is None:
                usages_by_activity.setdefault(usage.activity_id, []).append(usage)
        generated_by_activity: dict[str, list[Generation]] = {}
        generations_by_entity: dict[str, list[Generation]] = {}
        for generation in self.generations:
            if generation.invalidated_at is None:
                generated_by_activity.setdefault(generation.activity_id, []).append(generation)
                generations_by_entity.setdefault(generation.entity_id, []).append(generation)

        valid_evidence: list[_EvidenceRecord] = []
        input_ids: set[str] = set()
        activity_ids: set[str] = set()
        agent_ids: set[str] = set()
        artifact_ids: set[str] = set()
        validation_ids: set[str] = set()
        source_ids: set[str] = set()
        failures: list[str] = []
        for item in supporting:
            activity = activities[item.generating_activity_id]
            usage_ids = {
                usage.entity_id
                for usage in usages_by_activity.get(activity.activity_id, [])
            }
            generation_ids = {
                generation.entity_id
                for generation in generated_by_activity.get(activity.activity_id, [])
            }
            activity_agent_ids = {
                association.agent_id
                for association in associations_by_activity.get(activity.activity_id, [])
            }
            missing: list[str] = []
            if item.source_entity_id not in usage_ids:
                missing.append("source usage")
            if item.artifact_entity_id not in generation_ids:
                missing.append("artifact generation")
            if not set(item.responsible_agent_ids).issubset(activity_agent_ids):
                missing.append("responsible association")
            if entities[item.artifact_entity_id].content_digest is None:
                missing.append("artifact hash")
            if missing:
                failures.append(f"{item.evidence_id}: {', '.join(missing)}")
                continue
            validation = self.latest_validation(item.evidence_id)
            valid_evidence.append(item)
            input_ids.update(usage_ids)
            activity_ids.update({activity.activity_id, validation.activity_id})
            agent_ids.update(activity_agent_ids)
            agent_ids.add(validation.agent_id)
            artifact_ids.add(item.artifact_entity_id)
            validation_ids.add(validation.validation_id)
            source_ids.add(item.source_entity_id)
            for source_generation in generations_by_entity.get(
                item.source_entity_id, []
            ):
                upstream_activity = activities[source_generation.activity_id]
                upstream_associations = associations_by_activity.get(
                    upstream_activity.activity_id, []
                )
                if not upstream_associations:
                    raise ClaimTraceError(
                        f"source entity {item.source_entity_id} lacks a responsible "
                        "generating activity association"
                    )
                upstream_usages = usages_by_activity.get(upstream_activity.activity_id, [])
                if not upstream_usages:
                    raise ClaimTraceError(
                        f"source entity {item.source_entity_id} lacks generating inputs"
                    )
                activity_ids.add(upstream_activity.activity_id)
                agent_ids.update(
                    association.agent_id for association in upstream_associations
                )
                input_ids.update(usage.entity_id for usage in upstream_usages)
                artifact_ids.add(item.source_entity_id)

        if not valid_evidence:
            details = "; ".join(failures) or "no valid evidence chain"
            raise ClaimTraceError(f"claim {claim_id} causal chain is incomplete: {details}")

        current_decisions = [
            decision
            for decision in _current_records(self.decisions)
            if claim_id in decision.claim_ids and decision.invalidated_at is None
        ]
        linked_decisions = [
            decision
            for decision in current_decisions
            if validation_ids.intersection(decision.validation_ids)
        ]
        if not linked_decisions:
            raise ClaimTraceError(
                f"claim {claim_id} lacks a current decision grounded in its validation"
            )
        for decision in linked_decisions:
            if decision.activity_id not in associations_by_activity:
                raise ClaimTraceError(
                    f"decision {decision.decision_id} lacks a responsible activity association"
                )
            decision_generations = {
                generation.entity_id
                for generation in generated_by_activity.get(decision.activity_id, [])
            }
            if decision.artifact_entity_id not in decision_generations:
                raise ClaimTraceError(
                    f"decision {decision.decision_id} lacks artifact generation provenance"
                )
            activity_ids.add(decision.activity_id)
            artifact_ids.add(decision.artifact_entity_id)
            agent_ids.add(decision.responsible_agent_id)

        return ClaimTrace(
            claim_id=claim_id,
            evidence_ids=sorted(item.evidence_id for item in valid_evidence),
            counterevidence_ids=sorted(
                item.evidence_id
                for item in current_evidence
                if item.direction is EvidenceDirection.CONTRADICTS
            ),
            limiting_evidence_ids=sorted(
                item.evidence_id
                for item in current_evidence
                if item.direction is EvidenceDirection.LIMITS
            ),
            source_entity_ids=sorted(source_ids),
            input_entity_ids=sorted(input_ids),
            activity_ids=sorted(activity_ids),
            agent_ids=sorted(agent_ids),
            artifact_entity_ids=sorted(artifact_ids),
            validation_ids=sorted(validation_ids),
            decision_ids=sorted(decision.decision_id for decision in linked_decisions),
        )

    def _current_evidence_for_claim(
        self, claim_id: str
    ) -> list[Evidence | Counterevidence]:
        records = [
            item
            for item in [*self.evidence, *self.counterevidence]
            if item.claim_id == claim_id
        ]
        return cast(list[Evidence | Counterevidence], _current_records(records))


_COLLECTION_ID_FIELDS = (
    ("entities", "entity_id"),
    ("activities", "activity_id"),
    ("agents", "agent_id"),
    ("plans", "plan_id"),
    ("usages", "usage_id"),
    ("generations", "generation_id"),
    ("derivations", "derivation_id"),
    ("associations", "association_id"),
    ("source_snapshots", "snapshot_id"),
    ("claims", "claim_id"),
    ("evidence", "evidence_id"),
    ("counterevidence", "evidence_id"),
    ("validations", "validation_id"),
    ("decisions", "decision_id"),
    ("tool_invocations", "invocation_id"),
    ("model_interactions", "interaction_id"),
)

_VERSIONED_COLLECTION_ID_FIELDS = _COLLECTION_ID_FIELDS

PROVENANCE_MODELS = (
    Entity,
    Activity,
    Agent,
    Plan,
    Usage,
    Generation,
    Derivation,
    Association,
    SourceSnapshot,
    Claim,
    Evidence,
    Counterevidence,
    Validation,
    Decision,
    ToolInvocation,
    ModelInteractionDigest,
    ClaimTrace,
    ProvenanceBundle,
)


def provenance_json_schemas() -> dict[str, dict[str, Any]]:
    """Export JSON Schema documents for public provenance-v2 contracts."""

    return {model.__name__: model.model_json_schema() for model in PROVENANCE_MODELS}


def stable_record_id(prefix: str, value: Any, *, length: int = 24) -> str:
    """Create a deterministic identifier from canonical JSON-compatible content."""

    if not prefix or not prefix[0].isalnum():
        raise ValueError("stable ID prefix must begin with an alphanumeric character")
    if not 8 <= length <= 64:
        raise ValueError("stable ID digest length must be between 8 and 64")
    return f"{prefix}_{canonical_sha256(value)[:length]}"


def _utc(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{label} must be timezone-aware UTC")
    return value.astimezone(timezone.utc)


def _index(records: list[Any], id_field: str) -> dict[str, Any]:
    return {str(getattr(record, id_field)): record for record in records}


def _require_ref(
    records: dict[str, Any],
    reference_id: str,
    owner_id: str,
    label: str,
) -> Any:
    try:
        return records[reference_id]
    except KeyError as exc:
        raise ValueError(
            f"provenance record {owner_id} references missing {label} {reference_id}"
        ) from exc


def _require_unique(values: list[str], label: str) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    if duplicates:
        raise ValueError(f"duplicate {label} IDs: {', '.join(sorted(duplicates))}")


def _require_within_activity(at_time: datetime, activity: Activity, owner_id: str) -> None:
    if not activity.started_at <= at_time <= activity.ended_at:
        raise ValueError(
            f"relation {owner_id} time falls outside activity {activity.activity_id}"
        )


def _current_record(records: list[Any], label: str) -> Any:
    current = _current_records(records)
    if not current:
        raise ClaimTraceError(f"missing current {label}")
    if len(current) > 1:
        raise ClaimTraceError(f"ambiguous current {label} records")
    return current[0]


def _current_records(records: list[Any]) -> list[Any]:
    superseded = {
        record.supersedes_id
        for record in records
        if isinstance(record, VersionedRecord) and record.supersedes_id is not None
    }
    return [
        record
        for record in records
        if _record_identifier(record) not in superseded
        and (
            not isinstance(record, VersionedRecord)
            or record.invalidated_at is None
        )
    ]


def _record_identifier(record: Any) -> str:
    for field_name in (
        "entity_id",
        "activity_id",
        "agent_id",
        "plan_id",
        "usage_id",
        "generation_id",
        "derivation_id",
        "association_id",
        "snapshot_id",
        "claim_id",
        "evidence_id",
        "validation_id",
        "decision_id",
        "invocation_id",
        "interaction_id",
    ):
        value = getattr(record, field_name, None)
        if isinstance(value, str):
            return value
    raise ValueError(f"unknown provenance record type {type(record).__name__}")
