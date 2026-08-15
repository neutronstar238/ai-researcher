from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from autoresearch.kernel import (
    Activity,
    ActivityKind,
    Agent,
    Association,
    ContentAddressedRef,
    Entity,
    EntityKind,
    Generation,
    GraderIndependence,
    LoopRunSnapshot,
    Plan,
    ProvenanceAgentKind,
    ProvenanceBinding,
    ProvenanceBundle,
    ResearchObservation,
    ScientificCycleParentRef,
    ScientificCycleSnapshot,
    ScientificCycleValidationError,
    ScientificCycleValidationReceipt,
    canonical_sha256,
    scientific_cycle_validation_json_schemas,
    scientific_record_semantic_hash,
    validate_scientific_cycle,
)
from tests.unit.kernel._scientific_cycle_validation_fixtures import (
    build_scientific_cycle_validation_fixture,
)

T0 = datetime(2026, 8, 14, 1, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(minutes=1)
T2 = T1 + timedelta(minutes=1)


def _hash(value: object) -> str:
    return canonical_sha256(value)


def _ref(ref_id: str, ref_hash: str) -> ContentAddressedRef:
    return ContentAddressedRef(ref_id=ref_id, ref_hash=ref_hash)


def _observation_binding(bundle_hash: str) -> ProvenanceBinding:
    return ProvenanceBinding(
        bundle_ref=_ref("bundle.cycle", bundle_hash),
        record_entity_id="entity.record.observation",
        authoring_activity_id="activity.author.observation",
        author_agent_ids=["agent.author"],
        agent_ids=["agent.author", "agent.executor"],
        activity_ids=["activity.author.observation", "activity.measure"],
        entity_ids=[
            "entity.record.observation",
            "entity.result",
            "entity.uncertainty",
        ],
        plan_ids=["plan.author", "plan.measurement"],
        validation_ids=[],
        decision_ids=[],
    )


def _observation(bundle_hash: str) -> ResearchObservation:
    return ResearchObservation(
        observation_id="observation.generic",
        statement="A frozen measurement produced a bounded result.",
        measurement_spec_ref=_ref("plan.measurement", _hash("measurement-plan")),
        result_entity_ids=["entity.result"],
        uncertainty_entity_ids=["entity.uncertainty"],
        limitation_entity_ids=[],
        provenance=_observation_binding(bundle_hash),
    )


def _bundle() -> tuple[ProvenanceBundle, ResearchObservation]:
    provisional = _observation("0" * 64)
    record_digest = scientific_record_semantic_hash(provisional)
    bundle = ProvenanceBundle.create(
        bundle_id="bundle.cycle",
        project_id="project.generic",
        run_id="run.generic",
        created_at=T2,
        entities=[
            Entity(
                entity_id="entity.record.observation",
                kind=EntityKind.EXPERIMENT_RECORD,
                label="Authored observation record",
                content_digest=record_digest,
                valid_from=T1,
            ),
            Entity(
                entity_id="entity.result",
                kind=EntityKind.EXPERIMENT_RECORD,
                label="Measured result",
                content_digest=_hash("result"),
                valid_from=T1,
            ),
            Entity(
                entity_id="entity.uncertainty",
                kind=EntityKind.ARTIFACT,
                label="Uncertainty record",
                content_digest=_hash("uncertainty"),
                valid_from=T1,
            ),
        ],
        activities=[
            Activity(
                activity_id="activity.author.observation",
                kind=ActivityKind.PROJECTION,
                label="Author observation",
                started_at=T0,
                ended_at=T1,
                valid_from=T0,
            ),
            Activity(
                activity_id="activity.measure",
                kind=ActivityKind.EXECUTION,
                label="Frozen measurement",
                started_at=T0,
                ended_at=T1,
                valid_from=T0,
            ),
        ],
        agents=[
            Agent(
                agent_id="agent.author",
                kind=ProvenanceAgentKind.SOFTWARE,
                label="Lifecycle author",
                implementation_hash=_hash("author-implementation"),
                valid_from=T0,
            ),
            Agent(
                agent_id="agent.executor",
                kind=ProvenanceAgentKind.SOFTWARE,
                label="Measurement executor",
                implementation_hash=_hash("executor-implementation"),
                valid_from=T0,
            ),
        ],
        plans=[
            Plan(
                plan_id="plan.author",
                title="Authorship plan",
                description="Create one immutable lifecycle record.",
                content_digest=_hash("author-plan"),
                valid_from=T0,
            ),
            Plan(
                plan_id="plan.measurement",
                title="Measurement plan",
                description="Produce a result and an uncertainty record.",
                content_digest=_hash("measurement-plan"),
                valid_from=T0,
            ),
        ],
        generations=[
            Generation(
                generation_id="generation.record.observation",
                entity_id="entity.record.observation",
                activity_id="activity.author.observation",
                at_time=T1,
                valid_from=T1,
            ),
            Generation(
                generation_id="generation.result",
                entity_id="entity.result",
                activity_id="activity.measure",
                at_time=T1,
                valid_from=T1,
            ),
            Generation(
                generation_id="generation.uncertainty",
                entity_id="entity.uncertainty",
                activity_id="activity.measure",
                at_time=T1,
                valid_from=T1,
            ),
        ],
        associations=[
            Association(
                association_id="association.author.observation",
                activity_id="activity.author.observation",
                agent_id="agent.author",
                role="author",
                plan_id="plan.author",
                at_time=T0,
                valid_from=T0,
            ),
            Association(
                association_id="association.measure.executor",
                activity_id="activity.measure",
                agent_id="agent.executor",
                role="executor",
                plan_id="plan.measurement",
                at_time=T0,
                valid_from=T0,
            ),
        ],
    )
    return bundle, _observation(bundle.bundle_hash)


def _snapshot() -> tuple[ScientificCycleSnapshot, ProvenanceBundle]:
    bundle, observation = _bundle()
    snapshot = ScientificCycleSnapshot.create(
        cycle_id="cycle.generic",
        version=1,
        observations=[observation],
    )
    return snapshot, bundle


def test_read_only_bridge_validates_structural_authorship_for_a_prefix() -> None:
    snapshot, bundle = _snapshot()
    before_snapshot = snapshot.model_dump_json()
    before_bundle = bundle.model_dump_json()

    receipt = validate_scientific_cycle(
        snapshot,
        provenance_bundles=[bundle],
    )

    assert receipt.cycle_snapshot_hash == snapshot.snapshot_hash
    assert receipt.structurally_authored_record_ids == ["observation.generic"]
    assert receipt.validated_assessments == []
    assert receipt.system_generation_verified is False
    assert receipt.real_world_identity_attested is False
    receipt.verify_integrity()
    assert snapshot.model_dump_json() == before_snapshot
    assert bundle.model_dump_json() == before_bundle


def test_bridge_rejects_a_declared_bundle_hash_that_was_not_supplied() -> None:
    snapshot, bundle = _snapshot()
    payload = snapshot.model_dump(mode="json", exclude={"snapshot_hash"})
    payload["observations"][0]["provenance"]["bundle_ref"]["ref_hash"] = "f" * 64
    forged = ScientificCycleSnapshot.create(**payload)

    with pytest.raises(ScientificCycleValidationError, match="provenance bundle"):
        validate_scientific_cycle(forged, provenance_bundles=[bundle])


def test_bridge_rejects_missing_exact_author_association() -> None:
    snapshot, bundle = _snapshot()
    payload = bundle.model_dump(mode="json", exclude={"bundle_hash"})
    payload["associations"][0]["role"] = "participant"
    altered = ProvenanceBundle.create(**payload)
    cycle_payload = snapshot.model_dump(mode="json", exclude={"snapshot_hash"})
    cycle_payload["observations"][0]["provenance"]["bundle_ref"][
        "ref_hash"
    ] = altered.bundle_hash
    altered_snapshot = ScientificCycleSnapshot.create(**cycle_payload)

    with pytest.raises(ScientificCycleValidationError, match="author association"):
        validate_scientific_cycle(altered_snapshot, provenance_bundles=[altered])


def test_bridge_rejects_record_content_not_generated_by_the_declared_author() -> None:
    snapshot, bundle = _snapshot()
    payload = bundle.model_dump(mode="json", exclude={"bundle_hash"})
    record = next(
        entity
        for entity in payload["entities"]
        if entity["entity_id"] == "entity.record.observation"
    )
    record["content_digest"] = _hash("different-record")
    altered = ProvenanceBundle.create(**payload)
    cycle_payload = snapshot.model_dump(mode="json", exclude={"snapshot_hash"})
    cycle_payload["observations"][0]["provenance"]["bundle_ref"][
        "ref_hash"
    ] = altered.bundle_hash
    altered_snapshot = ScientificCycleSnapshot.create(**cycle_payload)

    with pytest.raises(ScientificCycleValidationError, match="semantic digest"):
        validate_scientific_cycle(altered_snapshot, provenance_bundles=[altered])


def test_bridge_requires_exact_append_only_parent_history() -> None:
    first, bundle = _snapshot()
    changed = _observation(bundle.bundle_hash).model_copy(
        update={"statement": "A later snapshot silently rewrote the prior record."}
    )
    second = ScientificCycleSnapshot.create(
        cycle_id=first.cycle_id,
        version=2,
        parent_snapshot_ref=ScientificCycleParentRef(
            cycle_id=first.cycle_id,
            version=first.version,
            snapshot_hash=first.snapshot_hash,
        ),
        observations=[changed],
    )

    with pytest.raises(ScientificCycleValidationError, match="history modified"):
        validate_scientific_cycle(
            second,
            parent_snapshot=first,
            provenance_bundles=[bundle],
        )


def test_validation_receipt_is_strict_deterministic_and_tamper_evident() -> None:
    snapshot, bundle = _snapshot()
    first = validate_scientific_cycle(snapshot, provenance_bundles=[bundle])
    second = validate_scientific_cycle(snapshot, provenance_bundles=[bundle])

    assert first.receipt_hash == second.receipt_hash
    schemas = scientific_cycle_validation_json_schemas()
    assert schemas == scientific_cycle_validation_json_schemas()
    assert schemas["ScientificCycleValidationReceipt"]["additionalProperties"] is False

    payload = first.model_dump(mode="json")
    payload["structurally_authored_record_ids"] = ["record.changed"]
    with pytest.raises(ValueError, match="receipt hash mismatch"):
        ScientificCycleValidationReceipt.model_validate(payload)


def test_bridge_does_not_upgrade_the_declared_knowledge_projection() -> None:
    snapshot, bundle = _snapshot()
    before = snapshot.knowledge_snapshot()

    validate_scientific_cycle(snapshot, provenance_bundles=[bundle])
    after = snapshot.knowledge_snapshot()

    assert after == before
    assert after.metadata["external_validation"] == "unverified"
    assert all(
        node.attributes["external_validation"] == "unverified"
        for node in after.nodes
    )


def test_bridge_verifies_a_complete_external_chain_without_copying_raw_content() -> None:
    fixture = build_scientific_cycle_validation_fixture()
    inputs_before = {
        "cycle": fixture.cycle.model_dump_json(),
        "bundle": fixture.provenance_bundle.model_dump_json(),
        "harness": fixture.harness_spec.model_dump_json(),
        "loop": fixture.loop_spec.model_dump_json(),
        "report": fixture.evaluation_report.model_dump_json(),
        "episodes": [item.model_dump_json() for item in fixture.episodes],
        "snapshots": [item.model_dump_json() for item in fixture.loop_snapshots],
    }

    receipt = validate_scientific_cycle(
        fixture.cycle,
        provenance_bundles=[fixture.provenance_bundle],
        harness_specs=[fixture.harness_spec],
        loop_specs=[fixture.loop_spec],
        evaluation_reports=[fixture.evaluation_report],
        episodes=fixture.episodes,
        loop_snapshots=fixture.loop_snapshots,
    )

    assessment = receipt.validated_assessments[0]
    assert assessment.verification_status.value == "verified"
    assert assessment.declared_assessment.value == "supported"
    assert assessment.reason_codes == []
    assert len(assessment.episode_refs) == 3
    assert len(assessment.loop_snapshot_hashes) == 3
    assert len(receipt.structurally_authored_record_ids) == 5
    receipt_payload = receipt.model_dump_json()
    assert "statement" not in receipt_payload
    assert "structured_output" not in receipt_payload
    assert fixture.cycle.model_dump_json() == inputs_before["cycle"]
    assert fixture.provenance_bundle.model_dump_json() == inputs_before["bundle"]
    assert fixture.harness_spec.model_dump_json() == inputs_before["harness"]
    assert fixture.loop_spec.model_dump_json() == inputs_before["loop"]
    assert fixture.evaluation_report.model_dump_json() == inputs_before["report"]
    assert [item.model_dump_json() for item in fixture.episodes] == inputs_before[
        "episodes"
    ]
    assert [item.model_dump_json() for item in fixture.loop_snapshots] == inputs_before[
        "snapshots"
    ]


def test_unknown_grader_independence_cannot_verify_a_decisive_assessment() -> None:
    fixture = build_scientific_cycle_validation_fixture(
        grader_independence=GraderIndependence.UNKNOWN
    )

    receipt = validate_scientific_cycle(
        fixture.cycle,
        provenance_bundles=[fixture.provenance_bundle],
        harness_specs=[fixture.harness_spec],
        loop_specs=[fixture.loop_spec],
        evaluation_reports=[fixture.evaluation_report],
        episodes=fixture.episodes,
        loop_snapshots=fixture.loop_snapshots,
    )

    assessment = receipt.validated_assessments[0]
    assert assessment.declared_assessment.value == "supported"
    assert assessment.verification_status.value == "inconclusive"
    assert "independent_grader_not_verified" in assessment.reason_codes


def test_loop_snapshot_must_resolve_by_its_exact_declared_hash() -> None:
    fixture = build_scientific_cycle_validation_fixture()
    payload = fixture.loop_snapshots[0].model_dump(
        mode="json",
        exclude={"snapshot_hash"},
    )
    del payload["state"]["variables"]["harness_journal_seal_hash"]
    payload["snapshot_hash"] = canonical_sha256(payload)
    altered = LoopRunSnapshot.model_validate(payload)

    with pytest.raises(ScientificCycleValidationError, match="snapshot is unresolved"):
        validate_scientific_cycle(
            fixture.cycle,
            provenance_bundles=[fixture.provenance_bundle],
            harness_specs=[fixture.harness_spec],
            loop_specs=[fixture.loop_spec],
            evaluation_reports=[fixture.evaluation_report],
            episodes=fixture.episodes,
            loop_snapshots=(altered, *fixture.loop_snapshots[1:]),
        )


def test_terminal_loop_snapshot_must_bind_every_episode_identity_field() -> None:
    fixture = build_scientific_cycle_validation_fixture(
        omit_loop_binding_key="harness_journal_seal_hash"
    )

    with pytest.raises(ScientificCycleValidationError, match="does not bind the episode"):
        validate_scientific_cycle(
            fixture.cycle,
            provenance_bundles=[fixture.provenance_bundle],
            harness_specs=[fixture.harness_spec],
            loop_specs=[fixture.loop_spec],
            evaluation_reports=[fixture.evaluation_report],
            episodes=fixture.episodes,
            loop_snapshots=fixture.loop_snapshots,
        )


def test_nested_external_report_tampering_fails_before_scientific_interpretation() -> None:
    fixture = build_scientific_cycle_validation_fixture()
    fixture.evaluation_report.outcomes[0].summary_hash = "f" * 64

    with pytest.raises(ScientificCycleValidationError, match="EvaluationReport"):
        validate_scientific_cycle(
            fixture.cycle,
            provenance_bundles=[fixture.provenance_bundle],
            harness_specs=[fixture.harness_spec],
            loop_specs=[fixture.loop_spec],
            evaluation_reports=[fixture.evaluation_report],
            episodes=fixture.episodes,
            loop_snapshots=fixture.loop_snapshots,
        )
