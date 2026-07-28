from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from autoresearch.evidence import project_evidence_v1
from autoresearch.kernel import (
    Activity,
    ActivityKind,
    Agent,
    Association,
    Claim,
    ClaimTraceError,
    Counterevidence,
    Decision,
    Derivation,
    Entity,
    EntityKind,
    Evidence,
    EvidenceDirection,
    Generation,
    InvocationStatus,
    ModelInteractionDigest,
    Plan,
    ProvenanceAgentKind,
    ProvenanceBundle,
    ProvenanceIntegrityError,
    SourceSnapshot,
    ToolInvocation,
    Usage,
    Validation,
    canonical_sha256,
    provenance_json_schemas,
    stable_record_id,
)
from autoresearch.knowledge import (
    KnowledgeEntry,
    KnowledgeEntryType,
    VaultProjectionError,
    project_provenance_to_vault,
)
from autoresearch.schemas import ValidationStatus

T0 = datetime(2026, 7, 28, 8, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(minutes=5)
T2 = T1 + timedelta(minutes=1)
TP = T0 - timedelta(minutes=1)


def _digest(value: object) -> str:
    return canonical_sha256(value)


def _bundle() -> ProvenanceBundle:
    source = Entity(
        entity_id="entity.source",
        kind=EntityKind.SOURCE_SNAPSHOT,
        label="Frozen input snapshot",
        content_digest=_digest("source"),
        source_uri="dataset://benchmark/frozen",
        media_type="application/json",
        valid_from=T0,
        event_ids=["event.input"],
    )
    artifact = Entity(
        entity_id="entity.artifact",
        kind=EntityKind.ARTIFACT,
        label="Evaluation result",
        content_digest=_digest("artifact"),
        source_uri="run://fixture/result.json",
        media_type="application/json",
        valid_from=T1,
        event_ids=["event.evaluated"],
    )
    decision_artifact = Entity(
        entity_id="entity.decision",
        kind=EntityKind.DECISION,
        label="Next-round decision artifact",
        content_digest=_digest("decision"),
        source_uri="run://fixture/decision.json",
        media_type="application/json",
        valid_from=T2,
        event_ids=["event.decided"],
    )
    evaluate = Activity(
        activity_id="activity.evaluate",
        kind=ActivityKind.EXECUTION,
        label="Frozen evaluation",
        started_at=T0,
        ended_at=T1,
        valid_from=T0,
        event_ids=["event.evaluated"],
    )
    decide = Activity(
        activity_id="activity.decide",
        kind=ActivityKind.DECISION,
        label="Deterministic decision",
        started_at=T1,
        ended_at=T2,
        valid_from=T1,
        event_ids=["event.decided"],
    )
    propose = Activity(
        activity_id="activity.propose",
        kind=ActivityKind.PROPOSAL,
        label="Bounded model proposal",
        started_at=TP,
        ended_at=T0,
        valid_from=TP,
    )
    software = Agent(
        agent_id="agent.software",
        kind=ProvenanceAgentKind.SOFTWARE,
        label="Frozen evaluator",
        implementation_hash=_digest("evaluator"),
        valid_from=TP,
    )
    policy = Agent(
        agent_id="agent.policy",
        kind=ProvenanceAgentKind.DETERMINISTIC_POLICY,
        label="Deterministic gate",
        implementation_hash=_digest("gate"),
        valid_from=TP,
    )
    model = Agent(
        agent_id="agent.model",
        kind=ProvenanceAgentKind.MODEL,
        label="Local proposal model",
        implementation_hash=_digest("model-config"),
        valid_from=TP,
        attributes={"role_boundary": "proposal_only"},
    )
    plan = Plan(
        plan_id="plan.frozen",
        title="Frozen protocol",
        description="Use the fixed input, code, and decision rule.",
        content_digest=_digest("plan"),
        valid_from=TP,
    )
    validations = [
        Validation(
            validation_id="validation.support",
            subject_id="evidence.support",
            activity_id="activity.evaluate",
            agent_id="agent.policy",
            status=ValidationStatus.PASSED,
            summary="The artifact and rule support the operational claim.",
            checked_at=T1,
            artifact_entity_id="entity.artifact",
            valid_from=T1,
            event_ids=["event.validated"],
        ),
        Validation(
            validation_id="validation.limit",
            subject_id="evidence.limit",
            activity_id="activity.evaluate",
            agent_id="agent.policy",
            status=ValidationStatus.WARNING,
            summary="The confidence interval limits generalization.",
            checked_at=T1,
            artifact_entity_id="entity.artifact",
            valid_from=T1,
            event_ids=["event.validated"],
        ),
        Validation(
            validation_id="validation.counter",
            subject_id="evidence.counter",
            activity_id="activity.evaluate",
            agent_id="agent.policy",
            status=ValidationStatus.PASSED,
            summary="The frozen threshold contradicts the broad improvement claim.",
            checked_at=T1,
            artifact_entity_id="entity.artifact",
            valid_from=T1,
            event_ids=["event.validated"],
        ),
    ]
    return ProvenanceBundle.create(
        bundle_id="bundle.fixture",
        project_id="project-fixture",
        run_id="run.fixture",
        created_at=T2,
        entities=[source, artifact, decision_artifact],
        activities=[evaluate, decide, propose],
        agents=[software, policy, model],
        plans=[plan],
        usages=[
            Usage(
                usage_id="usage.evaluate-source",
                activity_id="activity.evaluate",
                entity_id="entity.source",
                role="frozen input",
                at_time=T0,
                valid_from=T0,
            ),
            Usage(
                usage_id="usage.decide-artifact",
                activity_id="activity.decide",
                entity_id="entity.artifact",
                role="validated result",
                at_time=T1,
                valid_from=T1,
            ),
        ],
        generations=[
            Generation(
                generation_id="generation.artifact",
                entity_id="entity.artifact",
                activity_id="activity.evaluate",
                at_time=T1,
                valid_from=T1,
            ),
            Generation(
                generation_id="generation.decision",
                entity_id="entity.decision",
                activity_id="activity.decide",
                at_time=T2,
                valid_from=T2,
            ),
        ],
        derivations=[
            Derivation(
                derivation_id="derivation.artifact",
                generated_entity_id="entity.artifact",
                used_entity_id="entity.source",
                activity_id="activity.evaluate",
                valid_from=T1,
            )
        ],
        associations=[
            Association(
                association_id="association.evaluate-software",
                activity_id="activity.evaluate",
                agent_id="agent.software",
                role="executor",
                plan_id="plan.frozen",
                at_time=T0,
                valid_from=T0,
            ),
            Association(
                association_id="association.evaluate-policy",
                activity_id="activity.evaluate",
                agent_id="agent.policy",
                role="validator",
                plan_id="plan.frozen",
                at_time=T1,
                valid_from=T1,
            ),
            Association(
                association_id="association.decide-policy",
                activity_id="activity.decide",
                agent_id="agent.policy",
                role="decision policy",
                plan_id="plan.frozen",
                at_time=T1,
                valid_from=T1,
            ),
            Association(
                association_id="association.propose-model",
                activity_id="activity.propose",
                agent_id="agent.model",
                role="proposal only",
                plan_id="plan.frozen",
                at_time=TP,
                valid_from=TP,
            ),
        ],
        source_snapshots=[
            SourceSnapshot(
                snapshot_id="snapshot.source",
                entity_id="entity.source",
                source_uri="dataset://benchmark/frozen",
                retrieved_at=T0,
                content_digest=_digest("source"),
                valid_from=T0,
            )
        ],
        claims=[
            Claim(
                claim_id="claim.core",
                statement="The frozen evaluation triggered the next-round rule.",
                project_id="project-fixture",
                confidence=1.0,
                core=True,
                valid_from=T1,
                event_ids=["event.validated"],
            )
        ],
        evidence=[
            Evidence(
                evidence_id="evidence.support",
                claim_id="claim.core",
                artifact_entity_id="entity.artifact",
                source_entity_id="entity.source",
                source_snapshot_id="snapshot.source",
                generating_activity_id="activity.evaluate",
                responsible_agent_ids=["agent.software"],
                validation_ids=["validation.support"],
                summary="The validated result satisfies the deterministic transition rule.",
                confidence=1.0,
                direction=EvidenceDirection.SUPPORTS,
                valid_from=T1,
                event_ids=["event.validated"],
            ),
            Evidence(
                evidence_id="evidence.limit",
                claim_id="claim.core",
                artifact_entity_id="entity.artifact",
                source_entity_id="entity.source",
                source_snapshot_id="snapshot.source",
                generating_activity_id="activity.evaluate",
                responsible_agent_ids=["agent.software"],
                validation_ids=["validation.limit"],
                summary="The result is valid only for the frozen benchmark scope.",
                confidence=0.8,
                direction=EvidenceDirection.LIMITS,
                valid_from=T1,
                event_ids=["event.validated"],
            ),
        ],
        counterevidence=[
            Counterevidence(
                evidence_id="evidence.counter",
                claim_id="claim.core",
                artifact_entity_id="entity.artifact",
                source_entity_id="entity.source",
                source_snapshot_id="snapshot.source",
                generating_activity_id="activity.evaluate",
                responsible_agent_ids=["agent.software"],
                validation_ids=["validation.counter"],
                summary="The result contradicts a broader, out-of-scope improvement claim.",
                confidence=0.9,
                valid_from=T1,
                event_ids=["event.validated"],
            )
        ],
        validations=validations,
        decisions=[
            Decision(
                decision_id="decision.next",
                claim_ids=["claim.core"],
                activity_id="activity.decide",
                responsible_agent_id="agent.policy",
                validation_ids=["validation.support"],
                artifact_entity_id="entity.decision",
                outcome="next_round",
                rationale="The deterministic threshold selected the next-round transition.",
                decided_at=T2,
                valid_from=T2,
                event_ids=["event.decided"],
            )
        ],
        tool_invocations=[
            ToolInvocation(
                invocation_id="invocation.evaluate",
                activity_id="activity.evaluate",
                agent_id="agent.software",
                tool_name="fixture_evaluator",
                request_digest=_digest("request"),
                response_digest=_digest("response"),
                input_entity_ids=["entity.source"],
                output_entity_ids=["entity.artifact"],
                status=InvocationStatus.SUCCEEDED,
                started_at=T0,
                completed_at=T1,
                valid_from=T0,
            )
        ],
        model_interactions=[
            ModelInteractionDigest(
                interaction_id="interaction.propose",
                activity_id="activity.propose",
                agent_id="agent.model",
                model_name="local-model",
                provider="provider-neutral-test",
                prompt_digest=_digest("prompt"),
                response_digest=_digest("response"),
                status=InvocationStatus.SUCCEEDED,
                started_at=TP,
                completed_at=T0,
                valid_from=TP,
            )
        ],
        metadata={"fixture": True},
    )


def _payload(bundle: ProvenanceBundle) -> dict[str, Any]:
    return bundle.model_dump(mode="python", exclude={"bundle_hash"})


def test_bundle_round_trips_and_resolves_complete_claim_trace(tmp_path: Path) -> None:
    bundle = _bundle()
    reordered_payload = _payload(bundle)
    reordered_payload["entities"].reverse()
    reordered_payload["validations"].reverse()
    reordered = ProvenanceBundle.create(**reordered_payload)

    loaded = ProvenanceBundle.load_json(bundle.save_json(tmp_path / "provenance.json"))
    trace = loaded.require_claim_trace("claim.core")

    assert loaded.bundle_hash == bundle.bundle_hash
    assert reordered.bundle_hash == bundle.bundle_hash
    assert trace.evidence_ids == ["evidence.support"]
    assert trace.counterevidence_ids == ["evidence.counter"]
    assert trace.limiting_evidence_ids == ["evidence.limit"]
    assert trace.source_entity_ids == ["entity.source"]
    assert trace.input_entity_ids == ["entity.source"]
    assert trace.activity_ids == ["activity.decide", "activity.evaluate"]
    assert trace.agent_ids == ["agent.policy", "agent.software"]
    assert trace.artifact_entity_ids == ["entity.artifact", "entity.decision"]
    assert trace.validation_ids == ["validation.support"]
    assert trace.decision_ids == ["decision.next"]


def test_tampering_and_missing_required_generation_block_claim(tmp_path: Path) -> None:
    mutated = _bundle()
    mutated.entities[0].label = "Changed after validation"

    with pytest.raises(ProvenanceIntegrityError, match="failed integrity"):
        mutated.require_claim_trace("claim.core")

    original = _bundle()
    path = original.save_json(tmp_path / "bundle.json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["entities"][0]["label"] = "Tampered persisted content"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValidationError, match="bundle_hash mismatch"):
        ProvenanceBundle.load_json(path)

    payload = _payload(original)
    payload["generations"] = [
        generation
        for generation in payload["generations"]
        if generation["entity_id"] != "entity.artifact"
    ]
    missing_generation = ProvenanceBundle.create(**payload)
    with pytest.raises(ClaimTraceError, match="artifact generation"):
        missing_generation.require_claim_trace("claim.core")


def test_bundle_rejects_orphan_references_and_out_of_interval_relations() -> None:
    payload = _payload(_bundle())
    payload["entities"] = [
        entity for entity in payload["entities"] if entity["entity_id"] != "entity.source"
    ]
    with pytest.raises(ValidationError, match="missing entity entity.source"):
        ProvenanceBundle.create(**payload)

    payload = _payload(_bundle())
    payload["usages"][0]["at_time"] = TP - timedelta(minutes=1)
    with pytest.raises(ValidationError, match="outside activity"):
        ProvenanceBundle.create(**payload)


def test_validation_history_uses_latest_valid_revision() -> None:
    bundle = _bundle()
    payload = _payload(bundle)
    previous = next(
        validation
        for validation in payload["validations"]
        if validation["validation_id"] == "validation.support"
    )
    previous["valid_to"] = T1
    previous["invalidated_at"] = T1
    current = {
        **previous,
        "validation_id": "validation.support.v2",
        "version": 2,
        "valid_to": None,
        "invalidated_at": None,
        "supersedes_id": "validation.support",
        "status": ValidationStatus.WARNING,
        "summary": "Independent replay retained support with a warning.",
    }
    payload["validations"].append(current)
    support = next(
        item for item in payload["evidence"] if item["evidence_id"] == "evidence.support"
    )
    support["validation_ids"] = ["validation.support", "validation.support.v2"]
    payload["decisions"][0]["validation_ids"] = ["validation.support.v2"]

    revised = ProvenanceBundle.create(**payload)

    assert revised.latest_validation("evidence.support").validation_id == (
        "validation.support.v2"
    )
    assert revised.latest_validation("evidence.support").status is ValidationStatus.WARNING
    assert revised.require_claim_trace("claim.core").validation_ids == [
        "validation.support.v2"
    ]


def test_revision_requires_invalidated_predecessor() -> None:
    payload = _payload(_bundle())
    previous = next(
        validation
        for validation in payload["validations"]
        if validation["validation_id"] == "validation.support"
    )
    payload["validations"].append(
        {
            **previous,
            "validation_id": "validation.support.v2",
            "version": 2,
            "supersedes_id": "validation.support",
        }
    )
    with pytest.raises(ValidationError, match="must be invalidated"):
        ProvenanceBundle.create(**payload)


def test_model_interactions_are_digest_only_and_require_model_agent() -> None:
    interaction = _bundle().model_interactions[0]
    payload = interaction.model_dump(mode="python")
    payload["prompt"] = "raw content must not enter the contract"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ModelInteractionDigest.model_validate(payload)

    bundle_payload = _payload(_bundle())
    bundle_payload["model_interactions"][0]["agent_id"] = "agent.software"
    with pytest.raises(ValidationError, match="requires a model agent"):
        ProvenanceBundle.create(**bundle_payload)


def test_evidence_v1_projection_preserves_reader_and_direction_compatibility() -> None:
    graph = project_evidence_v1(_bundle())

    assert graph.schema_version == 1
    assert set(graph.evidence) == {
        "evidence.support",
        "evidence.limit",
        "evidence.counter",
    }
    assert graph.evidence["evidence.support"].supports_claim is True
    assert graph.evidence["evidence.limit"].supports_claim is False
    assert graph.evidence["evidence.counter"].supports_claim is False

    graph.require_core_claim_coverage(["claim.core"])
    assert graph.claims["claim.core"].status.value == "supported"


def test_vault_projection_requires_approval_and_maps_research_record_types(
    tmp_path: Path,
) -> None:
    bundle = _bundle()
    payload = _payload(bundle)
    taxonomy = [
        ("entity.literature", EntityKind.LITERATURE, "Paper"),
        ("entity.hypothesis", EntityKind.HYPOTHESIS, "Hypothesis"),
        ("entity.failure", EntityKind.FAILURE, "Failure"),
        ("entity.skill", EntityKind.SKILL, "Skill"),
        ("entity.strategy", EntityKind.STRATEGY, "Strategy"),
        ("entity.experiment", EntityKind.EXPERIMENT_RECORD, "Experiment"),
    ]
    for entity_id, kind, label in taxonomy:
        payload["entities"].append(
            Entity(
                entity_id=entity_id,
                kind=kind,
                label=label,
                content_digest=_digest(entity_id),
                source_uri=f"source://{entity_id}",
                valid_from=T0,
                event_ids=[f"event.{entity_id}"],
                attributes={"confidence": 0.75},
            )
        )
    expanded = ProvenanceBundle.create(**payload)

    with pytest.raises(VaultProjectionError, match="explicit approval"):
        project_provenance_to_vault(expanded, tmp_path, approved_record_ids=[])
    with pytest.raises(VaultProjectionError, match="unknown"):
        project_provenance_to_vault(
            expanded,
            tmp_path,
            approved_record_ids=["entity.unknown"],
        )

    approved = [
        *(entity_id for entity_id, _, _ in taxonomy),
        "entity.source",
        "entity.artifact",
        "entity.decision",
        "claim.core",
        "evidence.support",
        "evidence.limit",
        "evidence.counter",
        "decision.next",
    ]
    result = project_provenance_to_vault(
        expanded,
        tmp_path,
        approved_record_ids=approved,
    )
    entries = [
        KnowledgeEntry.from_markdown((tmp_path / path).read_text(encoding="utf-8"))
        for path in result.written_paths
    ]

    assert len(result.written_paths) == len(approved)
    assert {entry.entry_type for entry in entries}.issuperset(
        {
            KnowledgeEntryType.PAPER_NOTE,
            KnowledgeEntryType.RESEARCH_CANDIDATE,
            KnowledgeEntryType.FAILURE_CASE,
            KnowledgeEntryType.SKILL_CARD,
            KnowledgeEntryType.STRATEGY_CARD,
            KnowledgeEntryType.EXPERIMENT_RECORD,
            KnowledgeEntryType.EVIDENCE_NOTE,
            KnowledgeEntryType.REVIEW_NOTE,
        }
    )
    evidence_entry = next(
        entry for entry in entries if entry.entry_id == "evidence.support"
    )
    assert "[[claim.core]]" in evidence_entry.body
    assert "[[entity.source]]" in evidence_entry.body
    assert "Artifact hash:" in evidence_entry.body
    assert "Confidence:" in evidence_entry.body
    assert "Valid from:" in evidence_entry.body
    assert "Supersedes:" in evidence_entry.body
    assert "Event IDs:" in evidence_entry.body
    assert evidence_entry.source_refs == ["dataset://benchmark/frozen"]
    assert not any("entity.unknown" in path for path in result.written_paths)


def test_stable_record_ids_are_deterministic_and_content_sensitive() -> None:
    assert stable_record_id("entity", {"b": 2, "a": 1}) == stable_record_id(
        "entity", {"a": 1, "b": 2}
    )
    assert stable_record_id("entity", {"a": 1}) != stable_record_id(
        "entity", {"a": 2}
    )
    schemas = provenance_json_schemas()
    assert {
        "Entity",
        "Activity",
        "Agent",
        "Usage",
        "Generation",
        "Derivation",
        "Association",
        "Plan",
        "Claim",
        "Evidence",
        "Counterevidence",
        "Decision",
        "Validation",
        "ToolInvocation",
        "ModelInteractionDigest",
        "ProvenanceBundle",
    }.issubset(schemas)
