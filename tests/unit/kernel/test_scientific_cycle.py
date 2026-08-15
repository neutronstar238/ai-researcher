from __future__ import annotations

import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from autoresearch.kernel import (
    ContentAddressedRef,
    ContractIntegrityError,
    GraphPlane,
    HypothesisAssessment,
    HypothesisAssessmentRecord,
    ProvenanceBinding,
    ResearchEvaluation,
    ResearchHypothesis,
    ResearchObservation,
    ResearchProblem,
    ScientificCycleParentRef,
    ScientificCycleSnapshot,
    ScientificIntervention,
    canonical_sha256,
    scientific_cycle_json_schemas,
    scientific_record_semantic_hash,
)


def _ref(name: str) -> ContentAddressedRef:
    digit = str((sum(ord(character) for character in name) % 9) + 1)
    return ContentAddressedRef(ref_id=name, ref_hash=digit * 64)


def _binding(
    *,
    suffix: str,
    entities: tuple[str, ...] = (),
    claims: tuple[str, ...] = (),
    evidence: tuple[str, ...] = (),
) -> ProvenanceBinding:
    return ProvenanceBinding(
        bundle_ref=_ref(f"bundle_{suffix}"),
        agent_ids=[f"agent_{suffix}"],
        activity_ids=[f"activity_{suffix}"],
        entity_ids=[f"entity_record_{suffix}", *entities],
        record_entity_id=f"entity_record_{suffix}",
        authoring_activity_id=f"activity_{suffix}",
        author_agent_ids=[f"agent_{suffix}"],
        plan_ids=[f"plan_{suffix}"],
        claim_ids=list(claims),
        evidence_ids=list(evidence),
        validation_ids=[f"validation_{suffix}"],
        decision_ids=[],
    )


def _observation(
    observation_id: str = "observation_a",
    *,
    result_id: str = "entity_result_a",
) -> ResearchObservation:
    uncertainty_id = f"entity_uncertainty_{observation_id}"
    return ResearchObservation(
        observation_id=observation_id,
        statement="A measured signal changed under the frozen observation procedure.",
        measurement_spec_ref=_ref(f"measurement_{observation_id}"),
        result_entity_ids=[result_id],
        uncertainty_entity_ids=[uncertainty_id],
        limitation_entity_ids=[],
        provenance=_binding(
            suffix=observation_id,
            entities=(result_id, uncertainty_id),
        ),
    )


def _problem(
    problem_id: str = "problem_a",
    *,
    observation_ids: tuple[str, ...] = ("observation_a",),
) -> ResearchProblem:
    return ResearchProblem(
        problem_id=problem_id,
        observation_ids=list(observation_ids),
        statement="The observed change requires an explanation that distinguishes alternatives.",
        scope="The frozen measurement scope only.",
        provenance=_binding(suffix=problem_id),
    )


def _hypothesis(
    hypothesis_id: str = "hypothesis_a",
    *,
    problem_ids: tuple[str, ...] = ("problem_a",),
) -> ResearchHypothesis:
    claims = (
        f"claim_mechanism_{hypothesis_id}",
        f"claim_prediction_{hypothesis_id}",
        f"claim_falsifier_{hypothesis_id}",
        f"claim_competing_{hypothesis_id}",
    )
    return ResearchHypothesis(
        hypothesis_id=hypothesis_id,
        problem_ids=list(problem_ids),
        mechanism_claim_id=claims[0],
        prediction_claim_ids=[claims[1]],
        falsifier_claim_ids=[claims[2]],
        competing_explanation_claim_ids=[claims[3]],
        scope="The registered observation and intervention scope.",
        provenance=_binding(suffix=hypothesis_id, claims=claims),
    )


def _intervention(
    intervention_id: str = "intervention_a",
    *,
    hypothesis_ids: tuple[str, ...] = ("hypothesis_a",),
) -> ScientificIntervention:
    entities = (
        f"entity_comparator_{intervention_id}",
        f"entity_changed_{intervention_id}",
        f"entity_frozen_{intervention_id}",
        f"entity_metric_{intervention_id}",
        f"entity_rule_{intervention_id}",
    )
    estimand = f"claim_estimand_{intervention_id}"
    return ScientificIntervention(
        intervention_id=intervention_id,
        hypothesis_ids=list(hypothesis_ids),
        protocol_ref=_ref(f"protocol_{intervention_id}"),
        comparator_entity_ids=[entities[0]],
        changed_factor_entity_ids=[entities[1]],
        frozen_factor_entity_ids=[entities[2]],
        estimand_claim_ids=[estimand],
        metric_spec_entity_ids=[entities[3]],
        decision_rule_entity_ids=[entities[4]],
        harness_spec_ref=_ref(f"harness_{intervention_id}"),
        loop_spec_ref=_ref(f"loop_{intervention_id}"),
        provenance=_binding(
            suffix=intervention_id,
            entities=entities,
            claims=(estimand,),
        ),
    )


def _assessment(
    hypothesis_id: str,
    assessment: HypothesisAssessment,
    *,
    suffix: str,
) -> HypothesisAssessmentRecord:
    common = {
        "hypothesis_id": hypothesis_id,
        "assessment": assessment,
        "supporting_evidence_ids": [],
        "counterevidence_ids": [],
        "limiting_evidence_ids": [],
        "failure_entity_ids": [],
        "objective_result_entity_ids": [f"entity_objective_result_{suffix}"],
        "uncertainty_entity_ids": [f"entity_assessment_uncertainty_{suffix}"],
        "rationale": "The registered decision rule was applied to bound evidence.",
    }
    if assessment == HypothesisAssessment.SUPPORTED:
        common["supporting_evidence_ids"] = [f"evidence_support_{suffix}"]
    elif assessment == HypothesisAssessment.CONTRADICTED:
        common["counterevidence_ids"] = [f"evidence_counter_{suffix}"]
    else:
        common["limiting_evidence_ids"] = [f"evidence_limit_{suffix}"]
    return HypothesisAssessmentRecord.model_validate(common)


def _evaluation(
    *,
    intervention_ids: tuple[str, ...] = ("intervention_a",),
    assessments: tuple[HypothesisAssessmentRecord, ...] | None = None,
) -> ResearchEvaluation:
    selected = assessments or (
        _assessment(
            "hypothesis_a",
            HypothesisAssessment.SUPPORTED,
            suffix="a",
        ),
    )
    evidence_ids = tuple(
        evidence_id
        for assessment in selected
        for evidence_id in (
            *assessment.supporting_evidence_ids,
            *assessment.counterevidence_ids,
            *assessment.limiting_evidence_ids,
        )
    )
    entity_ids = tuple(
        entity_id
        for assessment in selected
        for entity_id in (
            *assessment.failure_entity_ids,
            *assessment.objective_result_entity_ids,
            *assessment.uncertainty_entity_ids,
        )
    )
    return ResearchEvaluation(
        evaluation_id="evaluation_a",
        intervention_ids=list(intervention_ids),
        evaluation_report_ref=_ref("evaluation_report_a"),
        evaluation_subject_hash=_ref("evaluation_subject_a").ref_hash,
        assessments=list(selected),
        provenance=_binding(
            suffix="evaluation_a",
            entities=entity_ids,
            evidence=evidence_ids,
        ),
    )


def _full_snapshot() -> ScientificCycleSnapshot:
    observation_a = _observation()
    observation_b = _observation("observation_b", result_id="entity_result_b")
    problem = _problem(observation_ids=(observation_b.observation_id, observation_a.observation_id))
    hypothesis_a = _hypothesis()
    hypothesis_b = _hypothesis("hypothesis_b")
    intervention = _intervention(
        hypothesis_ids=(hypothesis_b.hypothesis_id, hypothesis_a.hypothesis_id)
    )
    evaluation = _evaluation(
        assessments=(
            _assessment(
                hypothesis_b.hypothesis_id,
                HypothesisAssessment.CONTRADICTED,
                suffix="b",
            ),
            _assessment(
                hypothesis_a.hypothesis_id,
                HypothesisAssessment.SUPPORTED,
                suffix="a",
            ),
        )
    )
    return ScientificCycleSnapshot.create(
        cycle_id="cycle_alpha",
        version=1,
        observations=[observation_b, observation_a],
        problems=[problem],
        hypotheses=[hypothesis_b, hypothesis_a],
        interventions=[intervention],
        evaluations=[evaluation],
    )


def test_observation_only_prefix_is_valid_and_content_addressed() -> None:
    snapshot = ScientificCycleSnapshot.create(
        cycle_id="cycle_prefix",
        version=1,
        observations=[_observation()],
    )

    assert snapshot.problems == []
    assert len(snapshot.snapshot_hash) == 64
    snapshot.verify_integrity()
    assert ScientificCycleSnapshot.model_validate(snapshot.model_dump(mode="json")) == snapshot


def test_provenance_binding_requires_explicit_authoring_roles() -> None:
    binding = _binding(suffix="binding")

    assert binding.record_entity_id in binding.entity_ids
    assert binding.authoring_activity_id in binding.activity_ids
    assert set(binding.author_agent_ids).issubset(binding.agent_ids)
    assert binding.plan_ids == ["plan_binding"]

    for field in (
        "record_entity_id",
        "authoring_activity_id",
        "author_agent_ids",
        "plan_ids",
    ):
        payload = binding.model_dump(mode="json")
        del payload[field]
        with pytest.raises(ValidationError):
            ProvenanceBinding.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    (
        ("record_entity_id", "entity_missing", "record entity"),
        ("authoring_activity_id", "activity_missing", "authoring activity"),
        ("author_agent_ids", ["agent_missing"], "author agent"),
    ),
)
def test_provenance_binding_authoring_roles_must_be_bound(
    field: str,
    replacement: str | list[str],
    message: str,
) -> None:
    payload = _binding(suffix="binding").model_dump(mode="json")
    payload[field] = replacement

    with pytest.raises(ValidationError, match=message):
        ProvenanceBinding.model_validate(payload)


def test_provenance_binding_author_and_plan_ids_are_sorted_and_unique() -> None:
    payload = _binding(suffix="binding").model_dump(mode="json")
    payload["agent_ids"] = ["agent_z", "agent_a"]
    payload["author_agent_ids"] = ["agent_z", "agent_a"]
    payload["plan_ids"] = ["plan_z", "plan_a"]

    binding = ProvenanceBinding.model_validate(payload)

    assert binding.author_agent_ids == ["agent_a", "agent_z"]
    assert binding.plan_ids == ["plan_a", "plan_z"]

    for field in ("author_agent_ids", "plan_ids"):
        duplicate_payload = payload | {field: [payload[field][0], payload[field][0]]}
        with pytest.raises(ValidationError, match="duplicate provenance IDs"):
            ProvenanceBinding.model_validate(duplicate_payload)


def test_scientific_record_semantic_hash_is_versioned_and_provenance_neutral() -> None:
    records: list[
        ResearchObservation
        | ResearchProblem
        | ResearchHypothesis
        | ScientificIntervention
        | ResearchEvaluation
    ] = [
        _observation(),
        _problem(),
        _hypothesis(),
        _intervention(),
        _evaluation(),
    ]

    for record in records:
        excluded_fields = {"provenance"}
        if isinstance(record, ResearchEvaluation):
            excluded_fields.add("evaluation_report_ref")
        expected = canonical_sha256(
            {
                "schema_version": 1,
                "record_type": type(record).__name__,
                "record": record.model_dump(mode="json", exclude=excluded_fields),
            }
        )
        assert scientific_record_semantic_hash(record) == expected

        payload = record.model_dump(mode="json")
        payload["provenance"]["bundle_ref"] = _ref("bundle_rebound").model_dump(mode="json")
        rebound = type(record).model_validate(payload)
        assert scientific_record_semantic_hash(rebound) == expected


def test_scientific_record_semantic_hash_excludes_only_evaluation_report_identity() -> None:
    evaluation = _evaluation()
    payload = evaluation.model_dump(mode="json")
    payload["evaluation_report_ref"] = _ref("evaluation_report_rebound").model_dump(mode="json")
    rebound = ResearchEvaluation.model_validate(payload)

    expected_payload = evaluation.model_dump(
        mode="json",
        exclude={"provenance", "evaluation_report_ref"},
    )
    assert scientific_record_semantic_hash(evaluation) == canonical_sha256(
        {
            "schema_version": 1,
            "record_type": "ResearchEvaluation",
            "record": expected_payload,
        }
    )
    assert scientific_record_semantic_hash(rebound) == scientific_record_semantic_hash(evaluation)

    changed_subject = evaluation.model_copy(
        update={"evaluation_subject_hash": _ref("evaluation_subject_changed").ref_hash}
    )
    assert scientific_record_semantic_hash(changed_subject) != scientific_record_semantic_hash(
        evaluation
    )


def test_scientific_record_semantic_hash_tracks_record_semantics() -> None:
    observation = _observation()
    payload = observation.model_dump(mode="json")
    payload["statement"] = "A distinct generic observation statement."
    changed = ResearchObservation.model_validate(payload)

    assert scientific_record_semantic_hash(changed) != scientific_record_semantic_hash(observation)


def test_scientific_record_semantic_hash_rejects_unknown_contract_types() -> None:
    with pytest.raises(TypeError, match="unsupported scientific record type"):
        scientific_record_semantic_hash(_ref("not_a_record"))  # type: ignore[arg-type]


def test_full_branch_merge_cycle_is_order_independent() -> None:
    first = _full_snapshot()
    second = ScientificCycleSnapshot.create(
        cycle_id=first.cycle_id,
        version=first.version,
        observations=list(reversed(first.observations)),
        problems=list(reversed(first.problems)),
        hypotheses=list(reversed(first.hypotheses)),
        interventions=list(reversed(first.interventions)),
        evaluations=list(reversed(first.evaluations)),
    )

    assert first.snapshot_hash == second.snapshot_hash
    assert [item.observation_id for item in first.observations] == [
        "observation_a",
        "observation_b",
    ]
    assert [item.hypothesis_id for item in first.hypotheses] == [
        "hypothesis_a",
        "hypothesis_b",
    ]


def test_nested_snapshot_tampering_fails_closed() -> None:
    payload = _full_snapshot().model_dump(mode="json")
    payload["observations"][0]["statement"] = "Tampered statement."

    with pytest.raises(ValidationError, match="snapshot hash mismatch"):
        ScientificCycleSnapshot.model_validate(payload)


def test_in_memory_tampering_blocks_knowledge_projection() -> None:
    snapshot = _full_snapshot()
    snapshot.observations[0].statement = "Tampered after validation."

    with pytest.raises(ContractIntegrityError, match="failed integrity verification"):
        snapshot.knowledge_snapshot()


def test_snapshot_lineage_requires_the_immediate_parent_in_the_same_cycle() -> None:
    first = _full_snapshot()
    parent = ScientificCycleParentRef(
        cycle_id=first.cycle_id,
        version=first.version,
        snapshot_hash=first.snapshot_hash,
    )
    second = ScientificCycleSnapshot.create(
        cycle_id=first.cycle_id,
        version=2,
        parent_snapshot_ref=parent,
        observations=first.observations,
        problems=first.problems,
        hypotheses=first.hypotheses,
        interventions=first.interventions,
        evaluations=first.evaluations,
    )

    assert second.parent_snapshot_ref == parent
    second.verify_integrity()


@pytest.mark.parametrize(
    ("version", "parent", "message"),
    (
        (
            1,
            ScientificCycleParentRef(cycle_id="cycle_alpha", version=1, snapshot_hash="1" * 64),
            "version 1",
        ),
        (2, None, "requires a parent"),
        (
            2,
            ScientificCycleParentRef(cycle_id="cycle_other", version=1, snapshot_hash="1" * 64),
            "same cycle",
        ),
        (
            3,
            ScientificCycleParentRef(cycle_id="cycle_alpha", version=1, snapshot_hash="1" * 64),
            "immediate previous version",
        ),
        (
            2,
            ScientificCycleParentRef(cycle_id="cycle_alpha", version=2, snapshot_hash="1" * 64),
            "immediate previous version",
        ),
    ),
)
def test_impossible_snapshot_lineage_fails_closed(
    version: int,
    parent: ScientificCycleParentRef | None,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        ScientificCycleSnapshot.create(
            cycle_id="cycle_alpha",
            version=version,
            parent_snapshot_ref=parent,
            observations=[_observation()],
        )


@pytest.mark.parametrize(
    ("stage", "field", "replacement", "message"),
    (
        ("problems", "observation_ids", ["hypothesis_a"], "missing observation"),
        ("hypotheses", "problem_ids", ["observation_a"], "missing problem"),
        ("interventions", "hypothesis_ids", ["problem_a"], "missing hypothesis"),
        ("evaluations", "intervention_ids", ["hypothesis_a"], "missing intervention"),
        ("problems", "observation_ids", ["problem_a"], "missing observation"),
        ("hypotheses", "problem_ids", ["hypothesis_a"], "missing problem"),
        ("interventions", "hypothesis_ids", ["intervention_a"], "missing hypothesis"),
        ("evaluations", "intervention_ids", ["evaluation_a"], "missing intervention"),
    ),
)
def test_wrong_stage_and_dangling_references_fail_closed(
    stage: str,
    field: str,
    replacement: list[str],
    message: str,
) -> None:
    snapshot = _full_snapshot()
    payload = snapshot.model_dump(mode="json", exclude={"snapshot_hash"})
    payload[stage][0][field] = replacement

    with pytest.raises(ValidationError, match=message):
        ScientificCycleSnapshot.create(**payload)


def test_stage_ids_must_be_globally_unique() -> None:
    observation = _observation("shared_id")
    problem = _problem("shared_id", observation_ids=("shared_id",))

    with pytest.raises(ValidationError, match="duplicate scientific record IDs"):
        ScientificCycleSnapshot.create(
            cycle_id="cycle_duplicate",
            version=1,
            observations=[observation],
            problems=[problem],
        )


def test_observation_requires_uncertainty_or_limitation_and_bound_entities() -> None:
    payload = _observation().model_dump(mode="json")
    payload["uncertainty_entity_ids"] = []
    with pytest.raises(ValidationError, match="uncertainty or limitation"):
        ResearchObservation.model_validate(payload)

    payload = _observation().model_dump(mode="json")
    payload["result_entity_ids"] = ["entity_unbound"]
    with pytest.raises(ValidationError, match="not present in provenance"):
        ResearchObservation.model_validate(payload)


@pytest.mark.parametrize(
    "missing_field",
    (
        "prediction_claim_ids",
        "falsifier_claim_ids",
        "competing_explanation_claim_ids",
    ),
)
def test_hypothesis_requires_predictions_falsifiers_and_competitors(
    missing_field: str,
) -> None:
    payload = _hypothesis().model_dump(mode="json")
    payload[missing_field] = []

    with pytest.raises(ValidationError):
        ResearchHypothesis.model_validate(payload)


def test_hypothesis_claim_roles_must_be_disjoint() -> None:
    payload = _hypothesis().model_dump(mode="json")
    payload["prediction_claim_ids"] = [payload["mechanism_claim_id"]]

    with pytest.raises(ValidationError, match="claim roles overlap"):
        ResearchHypothesis.model_validate(payload)


@pytest.mark.parametrize(
    "missing_field",
    (
        "comparator_entity_ids",
        "changed_factor_entity_ids",
        "frozen_factor_entity_ids",
        "estimand_claim_ids",
        "metric_spec_entity_ids",
        "decision_rule_entity_ids",
    ),
)
def test_intervention_requires_discriminating_design_fields(missing_field: str) -> None:
    payload = _intervention().model_dump(mode="json")
    payload[missing_field] = []

    with pytest.raises(ValidationError):
        ScientificIntervention.model_validate(payload)


def test_intervention_changed_and_frozen_factors_must_be_disjoint() -> None:
    payload = _intervention().model_dump(mode="json")
    payload["frozen_factor_entity_ids"] = payload["changed_factor_entity_ids"]

    with pytest.raises(ValidationError, match="changed and frozen factors overlap"):
        ScientificIntervention.model_validate(payload)


@pytest.mark.parametrize(
    ("assessment", "field", "message"),
    (
        (HypothesisAssessment.SUPPORTED, "supporting_evidence_ids", "supporting evidence"),
        (HypothesisAssessment.CONTRADICTED, "counterevidence_ids", "counterevidence"),
        (HypothesisAssessment.INCONCLUSIVE, "limiting_evidence_ids", "limiting evidence"),
    ),
)
def test_assessment_requires_status_specific_evidence(
    assessment: HypothesisAssessment,
    field: str,
    message: str,
) -> None:
    payload = _assessment("hypothesis_a", assessment, suffix="status").model_dump(mode="json")
    payload[field] = []

    with pytest.raises(ValidationError, match=message):
        HypothesisAssessmentRecord.model_validate(payload)


def test_supported_and_contradicted_assessments_require_results_and_uncertainty() -> None:
    for field in ("objective_result_entity_ids", "uncertainty_entity_ids"):
        payload = _assessment(
            "hypothesis_a",
            HypothesisAssessment.SUPPORTED,
            suffix=field,
        ).model_dump(mode="json")
        payload[field] = []
        with pytest.raises(ValidationError, match="result and uncertainty"):
            HypothesisAssessmentRecord.model_validate(payload)


def test_evaluation_must_assess_every_tested_hypothesis_exactly_once() -> None:
    snapshot = _full_snapshot()
    payload = snapshot.model_dump(mode="json", exclude={"snapshot_hash"})
    payload["evaluations"][0]["assessments"] = payload["evaluations"][0]["assessments"][:1]

    with pytest.raises(ValidationError, match="must assess exactly the hypotheses"):
        ScientificCycleSnapshot.create(**payload)

    payload = snapshot.model_dump(mode="json", exclude={"snapshot_hash"})
    payload["evaluations"][0]["assessments"].append(
        deepcopy(payload["evaluations"][0]["assessments"][0])
    )
    with pytest.raises(ValidationError, match="duplicate hypothesis assessments"):
        ScientificCycleSnapshot.create(**payload)


def test_evaluation_evidence_and_result_ids_must_be_bound_to_provenance() -> None:
    payload = _evaluation().model_dump(mode="json")
    payload["assessments"][0]["supporting_evidence_ids"] = ["evidence_unbound"]

    with pytest.raises(ValidationError, match="not present in provenance"):
        ResearchEvaluation.model_validate(payload)


def test_knowledge_projection_stays_in_the_knowledge_plane() -> None:
    graph = _full_snapshot().knowledge_snapshot()

    assert graph.plane == GraphPlane.KNOWLEDGE
    assert graph.control_cycle_policy is None
    assert all(node.plane == GraphPlane.KNOWLEDGE for node in graph.nodes)
    assert all(edge.plane == GraphPlane.KNOWLEDGE for edge in graph.edges)
    assert {edge.edge_type for edge in graph.edges} == {
        "assesses",
        "grounds",
        "motivates",
        "tests",
    }
    assert {node.node_type for node in graph.nodes} == {
        "research.evaluation",
        "research.hypothesis",
        "research.intervention",
        "research.observation",
        "research.problem",
    }
    assert graph.metadata["external_validation"] == "unverified"

    nodes_by_type = {node.node_type: node for node in graph.nodes}
    assert nodes_by_type["research.intervention"].label == "Declared scientific intervention"
    assert nodes_by_type["research.evaluation"].label == "Declared research evaluation"
    assert nodes_by_type["research.intervention"].attributes == {
        "external_validation": "unverified"
    }
    assert nodes_by_type["research.evaluation"].attributes == {"external_validation": "unverified"}
    forbidden_attribute_fragments = {
        "bundle",
        "harness",
        "loop",
        "policy",
        "provenance",
        "report",
    }
    for node in graph.nodes:
        assert not any(
            fragment in attribute_name
            for attribute_name in node.attributes
            for fragment in forbidden_attribute_fragments
        )

    assessment_edges = [edge for edge in graph.edges if edge.edge_type == "assesses"]
    assert assessment_edges
    assert all("assessment" not in edge.attributes for edge in assessment_edges)
    assert all("declared_assessment" in edge.attributes for edge in assessment_edges)


def test_scientific_cycle_json_schemas_are_strict_and_stable() -> None:
    first = scientific_cycle_json_schemas()
    second = scientific_cycle_json_schemas()

    assert first == second
    assert first["ScientificCycleSnapshot"]["additionalProperties"] is False
    assert first["ResearchHypothesis"]["additionalProperties"] is False
    assert "ScientificCycleParentRef" in first
    assert "ScientificIntervention" in first

    def assert_strict_objects(value: object) -> None:
        if isinstance(value, dict):
            if value.get("type") == "object":
                assert value.get("additionalProperties") is False
            for nested in value.values():
                assert_strict_objects(nested)
        elif isinstance(value, list):
            for nested in value:
                assert_strict_objects(nested)

    assert_strict_objects(first)

    snapshot = _full_snapshot()
    payload = json.loads(snapshot.model_dump_json())
    snapshot_schema = json.loads(json.dumps(first["ScientificCycleSnapshot"], sort_keys=True))
    assert set(snapshot_schema["required"]).issubset(payload)
    assert set(payload).issubset(snapshot_schema["properties"])
    restored = ScientificCycleSnapshot.model_validate_json(json.dumps(payload, sort_keys=True))
    assert restored == snapshot
