"""Tests for the topic-neutral planning-literature gap-repair contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from autoresearch.competition.contest_planning_literature_coverage import (
    PlanningLiteratureCandidate,
    PlanningLiteratureCoverageReceiptV4,
    PlanningLiteratureRole,
    role_query_from_boolean,
    select_planning_literature,
)
from autoresearch.competition.contest_planning_literature_gap_repair import (
    PlanningLiteratureGapRepairError,
    PlanningLiteratureGapRepairEvidenceInput,
    PlanningLiteratureRepairTermProvenance,
    PlanningLiteratureRoleQueryRepair,
    diagnose_planning_literature_gap,
    load_planning_literature_gap_diagnosis,
    load_planning_literature_gap_repair_projection,
    project_planning_literature_query_repair,
    write_planning_literature_gap_diagnosis,
    write_planning_literature_gap_repair_projection,
)
from autoresearch.competition.manifest import canonical_model_hash


def _queries():  # type: ignore[no-untyped-def]
    object_group = '("aurelia systems" OR "borealis systems")'
    return (
        role_query_from_boolean(
            PlanningLiteratureRole.DIRECT_CORE,
            "query-direct",
            f'{object_group} AND ("primary effects" OR "direct outcomes")',
        ),
        role_query_from_boolean(
            PlanningLiteratureRole.METHOD_FOUNDATION,
            "query-method",
            '("estimation methods" OR "inference methods") AND '
            '("validation protocols" OR "calibration procedures")',
        ),
        role_query_from_boolean(
            PlanningLiteratureRole.MECHANISM_OR_NULL,
            "query-mechanism",
            f'{object_group} AND ("mechanism pathways" OR "null explanations")',
        ),
        role_query_from_boolean(
            PlanningLiteratureRole.COUNTEREVIDENCE,
            "query-counter",
            f'{object_group} AND ("negative results" OR bias)',
        ),
    )


def _candidate(
    record_id: str,
    title: str,
    abstract: str,
    role: PlanningLiteratureRole,
    *,
    anchor_id: str | None = None,
) -> PlanningLiteratureCandidate:
    query = next(item for item in _queries() if item.role is role)
    return PlanningLiteratureCandidate(
        record_id=record_id,
        title=title,
        abstract=abstract,
        anchor_id=anchor_id,
        retrieval_queries=(query.raw_query,),
        source_stages=("targeted_direction",),
        quality_score=0.8,
    )


def _complete_candidates() -> tuple[PlanningLiteratureCandidate, ...]:
    return (
        _candidate(
            "direct-1",
            "Aurelia systems show primary effects",
            "The direct outcomes are measured under a fixed protocol.",
            PlanningLiteratureRole.DIRECT_CORE,
        ),
        _candidate(
            "direct-2",
            "Borealis systems and direct outcomes",
            "A replication measures primary effects.",
            PlanningLiteratureRole.DIRECT_CORE,
        ),
        _candidate(
            "method-1",
            "Estimation methods for aurelia systems with validation protocols",
            "Inference methods are compared with calibration procedures.",
            PlanningLiteratureRole.METHOD_FOUNDATION,
        ),
        _candidate(
            "mechanism-1",
            "Mechanism pathways in aurelia systems",
            "Null explanations are evaluated in borealis systems.",
            PlanningLiteratureRole.MECHANISM_OR_NULL,
        ),
        _candidate(
            "counter-1",
            "Negative results for aurelia systems",
            "Bias can account for the response in borealis systems.",
            PlanningLiteratureRole.COUNTEREVIDENCE,
        ),
    )


def _semantic_counter_gap():  # type: ignore[no-untyped-def]
    candidates = tuple(item for item in _complete_candidates() if item.record_id != "counter-1")
    return select_planning_literature(candidates, _queries(), maximum_records=8)


def _authority_counter_gap():  # type: ignore[no-untyped-def]
    candidates = _complete_candidates()
    eligible = tuple(item.record_id for item in candidates if item.record_id != "counter-1")
    return select_planning_literature(
        candidates,
        _queries(),
        maximum_records=8,
        required_anchor_eligible_record_ids=eligible,
    )


def _freeze_as_v4(receipt):  # type: ignore[no-untyped-def]
    payload = receipt.model_dump(mode="json")
    for field in (
        "method_focus_basis_queries",
        "method_bridge_contract",
        "method_bridge_assessments",
        "eligible_role_family_counts",
        "warnings",
    ):
        payload.pop(field)
    payload["schema_version"] = "contest-planning-literature-coverage-v4"
    payload["selection_semantics"] = (
        "targeted_lineage_distinct_anchor_semantic_first_dp_then_quality_limited_supplements"
    )
    payload["receipt_hash"] = canonical_model_hash(
        {key: value for key, value in payload.items() if key != "receipt_hash"}
    )
    return PlanningLiteratureCoverageReceiptV4.model_validate(payload)


def _evidence_inputs() -> tuple[PlanningLiteratureGapRepairEvidenceInput, ...]:
    return (
        PlanningLiteratureGapRepairEvidenceInput.create(
            source_scope="focus",
            source_artifact_hash="a" * 64,
            record_id="focus-record-1",
            title="Observed limitations in replicated studies",
            abstract="The focused evidence identifies bounded scope.",
        ),
        PlanningLiteratureGapRepairEvidenceInput.create(
            source_scope="broad",
            source_artifact_hash="b" * 64,
            record_id="broad-record-1",
            title="Robustness audit",
            abstract="Several failure modes arise from measurement drift.",
        ),
        PlanningLiteratureGapRepairEvidenceInput.create(
            source_scope="focus",
            source_artifact_hash="a" * 64,
            record_id="focus-record-2",
            title="Independent replications and sensitivity analyses",
            abstract="The evidence reports uncertainty estimates.",
        ),
    )


def _counter_repair(
    evidence: tuple[PlanningLiteratureGapRepairEvidenceInput, ...],
) -> PlanningLiteratureRoleQueryRepair:
    return PlanningLiteratureRoleQueryRepair(
        role=PlanningLiteratureRole.COUNTEREVIDENCE,
        replacement_terms=(
            PlanningLiteratureRepairTermProvenance(
                term="limitations",
                evidence_hash=evidence[0].evidence_hash,
                matched_field="title",
            ),
            PlanningLiteratureRepairTermProvenance(
                term="failure modes",
                evidence_hash=evidence[1].evidence_hash,
                matched_field="abstract",
            ),
        ),
    )


def test_diagnosis_separates_semantic_and_authority_role_shortfalls() -> None:
    semantic = diagnose_planning_literature_gap(_semantic_counter_gap())
    authority = diagnose_planning_literature_gap(_authority_counter_gap())

    semantic_by_role = {item.role: item for item in semantic.role_diagnostics}
    authority_by_role = {item.role: item for item in authority.role_diagnostics}
    assert semantic_by_role[PlanningLiteratureRole.COUNTEREVIDENCE].gap_kind == (
        "semantic_shortfall"
    )
    assert semantic_by_role[PlanningLiteratureRole.COUNTEREVIDENCE].semantic_anchor_count == 0
    assert authority_by_role[PlanningLiteratureRole.COUNTEREVIDENCE].gap_kind == (
        "authority_shortfall"
    )
    assert authority_by_role[PlanningLiteratureRole.COUNTEREVIDENCE].semantic_anchor_count == 1
    assert (
        authority_by_role[PlanningLiteratureRole.COUNTEREVIDENCE].authority_eligible_anchor_count
        == 0
    )
    assert authority_by_role[
        PlanningLiteratureRole.COUNTEREVIDENCE
    ].authority_ineligible_anchor_ids == ("counter-1",)
    assert (
        semantic.repairable_roles
        == authority.repairable_roles
        == (PlanningLiteratureRole.COUNTEREVIDENCE,)
    )
    assert semantic.supplemental_retrieval_allowed is True
    assert authority.supplemental_retrieval_allowed is True


def test_frozen_v4_failure_remains_diagnosable_after_v5_becomes_current() -> None:
    current = _authority_counter_gap()
    frozen_v4 = _freeze_as_v4(current)

    diagnosis = diagnose_planning_literature_gap(frozen_v4)

    assert current.schema_version == "contest-planning-literature-coverage-v5"
    assert diagnosis.coverage_receipt.schema_version == ("contest-planning-literature-coverage-v4")
    assert diagnosis.coverage_receipt_hash == frozen_v4.receipt_hash
    assert diagnosis.repairable_roles == (PlanningLiteratureRole.COUNTEREVIDENCE,)


def test_v5_method_focus_bridge_shortfall_relaxes_to_warning() -> None:
    candidates = tuple(item for item in _complete_candidates() if item.record_id != "method-1") + (
        _candidate(
            "method-unbridged",
            "Estimation methods with validation protocols",
            "Inference methods are compared with calibration procedures.",
            PlanningLiteratureRole.METHOD_FOUNDATION,
        ),
    )
    relaxed = select_planning_literature(candidates, _queries(), maximum_records=8)

    assert relaxed.passed is True
    assert relaxed.failure_reasons == ()
    assert "method_focus_bridge_relaxed" in relaxed.warnings
    assert "method-unbridged" in relaxed.selected_record_ids
    method_anchor = next(
        item
        for item in relaxed.anchor_assignments
        if item.role is PlanningLiteratureRole.METHOD_FOUNDATION
    )
    assert method_anchor.record_id == "method-unbridged"


def test_diagnosis_rejects_passing_or_historical_coverage() -> None:
    passing = select_planning_literature(
        _complete_candidates(),
        _queries(),
        maximum_records=8,
    )
    with pytest.raises(PlanningLiteratureGapRepairError, match="failed v4"):
        diagnose_planning_literature_gap(passing)

    historical = passing.model_copy(
        update={"schema_version": "contest-planning-literature-coverage-v3"}
    )
    with pytest.raises(PlanningLiteratureGapRepairError, match="failed v4"):
        diagnose_planning_literature_gap(historical)  # type: ignore[arg-type]


def test_budget_failure_is_not_mislabelled_as_query_retrieval_gap() -> None:
    structural_failure = select_planning_literature(
        _complete_candidates(),
        _queries(),
        maximum_records=4,
    )

    diagnosis = diagnose_planning_literature_gap(structural_failure)

    assert diagnosis.repairable_roles == ()
    assert diagnosis.supplemental_retrieval_allowed is False
    assert diagnosis.non_retrieval_blockers == ("maximum_records_prevents_required_coverage",)
    assert {item.gap_kind for item in diagnosis.role_diagnostics} == {"none"}


def test_r2_is_complete_and_changes_only_the_gap_role_second_group() -> None:
    diagnosis = diagnose_planning_literature_gap(_authority_counter_gap())
    evidence = _evidence_inputs()

    projection = project_planning_literature_query_repair(
        diagnosis,
        evidence_inputs=evidence,
        repairs=(_counter_repair(evidence),),
    )

    r1 = diagnosis.coverage_receipt.role_queries
    r2 = projection.r2_role_queries
    assert len(r2) == 4
    assert tuple(item.raw_query for item in r2[:3]) == tuple(item.raw_query for item in r1[:3])
    assert r2[3].raw_query == (
        r1[3].raw_query.split(" AND ", maxsplit=1)[0] + ' AND (limitations OR "failure modes")'
    )
    assert tuple(item.query_id for item in r2[:3]) == tuple(item.query_id for item in r1[:3])
    assert r2[3].query_id == f"{r1[3].query_id}-r2"
    assert r2[3].query_id != r1[3].query_id
    assert r2[0].must_groups[0] == r2[2].must_groups[0] == r2[3].must_groups[0]
    assert all(len(item.must_groups) == 2 for item in r2)
    assert {item.role for item in projection.repairs} == set(diagnosis.repairable_roles)


def test_repair_terms_must_come_from_bound_focus_or_broad_evidence() -> None:
    diagnosis = diagnose_planning_literature_gap(_authority_counter_gap())
    evidence = _evidence_inputs()
    invented = PlanningLiteratureRoleQueryRepair(
        role=PlanningLiteratureRole.COUNTEREVIDENCE,
        replacement_terms=(
            PlanningLiteratureRepairTermProvenance(
                term="invented failure construct",
                evidence_hash=evidence[0].evidence_hash,
                matched_field="title",
            ),
            PlanningLiteratureRepairTermProvenance(
                term="failure modes",
                evidence_hash=evidence[1].evidence_hash,
                matched_field="abstract",
            ),
        ),
    )

    with pytest.raises(PlanningLiteratureGapRepairError, match="does not occur"):
        project_planning_literature_query_repair(
            diagnosis,
            evidence_inputs=evidence,
            repairs=(invented,),
        )

    missing_evidence = _counter_repair(evidence).model_copy(
        update={
            "replacement_terms": (
                PlanningLiteratureRepairTermProvenance(
                    term="limitations",
                    evidence_hash="f" * 64,
                    matched_field="title",
                ),
                _counter_repair(evidence).replacement_terms[1],
            )
        }
    )
    with pytest.raises(PlanningLiteratureGapRepairError, match="unknown evidence"):
        project_planning_literature_query_repair(
            diagnosis,
            evidence_inputs=evidence,
            repairs=(missing_evidence,),
        )


@pytest.mark.parametrize("count", (1, 5))
def test_each_gap_replacement_requires_two_to_four_terms(count: int) -> None:
    evidence_hash = "a" * 64
    with pytest.raises(ValidationError):
        PlanningLiteratureRoleQueryRepair(
            role=PlanningLiteratureRole.COUNTEREVIDENCE,
            replacement_terms=tuple(
                PlanningLiteratureRepairTermProvenance(
                    term=f"term {index}",
                    evidence_hash=evidence_hash,
                    matched_field="title",
                )
                for index in range(count)
            ),
        )


def test_counter_repair_rejects_evidenced_but_weak_only_terms() -> None:
    diagnosis = diagnose_planning_literature_gap(_authority_counter_gap())
    weak_evidence = (
        PlanningLiteratureGapRepairEvidenceInput.create(
            source_scope="focus",
            source_artifact_hash="c" * 64,
            record_id="focus-weak",
            title="Counterexamples and anomalies",
            abstract="Weak descriptive deviations only.",
        ),
    )
    weak = PlanningLiteratureRoleQueryRepair(
        role=PlanningLiteratureRole.COUNTEREVIDENCE,
        replacement_terms=(
            PlanningLiteratureRepairTermProvenance(
                term="counterexamples",
                evidence_hash=weak_evidence[0].evidence_hash,
                matched_field="title",
            ),
            PlanningLiteratureRepairTermProvenance(
                term="anomalies",
                evidence_hash=weak_evidence[0].evidence_hash,
                matched_field="title",
            ),
        ),
    )

    with pytest.raises(PlanningLiteratureGapRepairError, match="weak-only"):
        project_planning_literature_query_repair(
            diagnosis,
            evidence_inputs=weak_evidence,
            repairs=(weak,),
        )


def test_only_roles_diagnosed_as_gaps_can_be_repaired() -> None:
    diagnosis = diagnose_planning_literature_gap(_authority_counter_gap())
    evidence = _evidence_inputs()
    non_gap = PlanningLiteratureRoleQueryRepair(
        role=PlanningLiteratureRole.METHOD_FOUNDATION,
        replacement_terms=(
            PlanningLiteratureRepairTermProvenance(
                term="sensitivity analyses",
                evidence_hash=evidence[2].evidence_hash,
                matched_field="title",
            ),
            PlanningLiteratureRepairTermProvenance(
                term="uncertainty estimates",
                evidence_hash=evidence[2].evidence_hash,
                matched_field="abstract",
            ),
        ),
    )

    with pytest.raises(PlanningLiteratureGapRepairError, match="exactly the diagnosed"):
        project_planning_literature_query_repair(
            diagnosis,
            evidence_inputs=evidence,
            repairs=(non_gap,),
        )


def test_diagnosis_and_projection_persist_and_replay(tmp_path: Path) -> None:
    diagnosis = diagnose_planning_literature_gap(_authority_counter_gap())
    evidence = _evidence_inputs()
    projection = project_planning_literature_query_repair(
        diagnosis,
        evidence_inputs=evidence,
        repairs=(_counter_repair(evidence),),
    )
    diagnosis_path = write_planning_literature_gap_diagnosis(
        tmp_path / "gap-diagnosis.json",
        diagnosis,
    )
    projection_path = write_planning_literature_gap_repair_projection(
        tmp_path / "gap-repair.json",
        projection,
    )

    assert load_planning_literature_gap_diagnosis(diagnosis_path) == diagnosis
    assert load_planning_literature_gap_repair_projection(projection_path) == projection


def test_tampered_diagnosis_projection_and_evidence_fail_replay(tmp_path: Path) -> None:
    diagnosis = diagnose_planning_literature_gap(_authority_counter_gap())
    evidence = _evidence_inputs()
    projection = project_planning_literature_query_repair(
        diagnosis,
        evidence_inputs=evidence,
        repairs=(_counter_repair(evidence),),
    )
    diagnosis_path = write_planning_literature_gap_diagnosis(
        tmp_path / "gap-diagnosis.json",
        diagnosis,
    )
    projection_path = write_planning_literature_gap_repair_projection(
        tmp_path / "gap-repair.json",
        projection,
    )

    diagnosis_payload = json.loads(diagnosis_path.read_text(encoding="utf-8"))
    diagnosis_payload["role_diagnostics"][3]["authority_eligible_anchor_count"] = 1
    diagnosis_path.write_text(json.dumps(diagnosis_payload), encoding="utf-8")
    with pytest.raises((ValidationError, ValueError), match="diagnosis|count|hash"):
        load_planning_literature_gap_diagnosis(diagnosis_path)

    projection_payload = json.loads(projection_path.read_text(encoding="utf-8"))
    projection_payload["r2_role_queries"][0]["raw_query"] = (
        '("changed object" OR "other object") AND ' '("primary effects" OR "direct outcomes")'
    )
    projection_path.write_text(json.dumps(projection_payload), encoding="utf-8")
    with pytest.raises((ValidationError, ValueError), match="projection|query|bytes|object"):
        load_planning_literature_gap_repair_projection(projection_path)

    projection_path = write_planning_literature_gap_repair_projection(
        tmp_path / "gap-repair.json",
        projection,
    )
    evidence_payload = json.loads(projection_path.read_text(encoding="utf-8"))
    evidence_payload["evidence_inputs"][0]["title"] = "Rewritten source title"
    projection_path.write_text(json.dumps(evidence_payload), encoding="utf-8")
    with pytest.raises((ValidationError, ValueError), match="evidence|hash"):
        load_planning_literature_gap_repair_projection(projection_path)
