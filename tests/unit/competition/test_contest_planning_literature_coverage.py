"""Adversarial tests for topic-neutral planning-literature coverage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import autoresearch.competition.contest_planning_literature_coverage as coverage_module
from autoresearch.competition.contest_planning_literature_coverage import (
    PlanningLiteratureCandidate,
    PlanningLiteratureCoverageError,
    PlanningLiteratureCoverageReceiptV3,
    PlanningLiteratureCoverageReceiptV4,
    PlanningLiteratureRole,
    classify_planning_candidates,
    parse_planning_literature_coverage_receipt,
    role_query_from_boolean,
    select_planning_literature,
)
from autoresearch.competition.manifest import canonical_model_hash


def _queries():  # type: ignore[no-untyped-def]
    return (
        role_query_from_boolean(
            PlanningLiteratureRole.DIRECT_CORE,
            "query-direct",
            '("aurelia cells" OR "aurelia devices") AND '
            '("phase drift" OR "rank-pattern analysis" OR "state drift")',
        ),
        role_query_from_boolean(
            PlanningLiteratureRole.METHOD_FOUNDATION,
            "query-method",
            '("rank-pattern analysis" OR "ordinal analysis") AND ' "(foundation OR definition)",
        ),
        role_query_from_boolean(
            PlanningLiteratureRole.MECHANISM_OR_NULL,
            "query-mechanism",
            '(transport OR diffusion) AND ("null model" OR surrogate)',
        ),
        role_query_from_boolean(
            PlanningLiteratureRole.COUNTEREVIDENCE,
            "query-counter",
            "(failure OR limitation) AND (bias OR artifact)",
        ),
    )


def _method_bridge_queries():  # type: ignore[no-untyped-def]
    return (
        role_query_from_boolean(
            PlanningLiteratureRole.DIRECT_CORE,
            "bridge-direct",
            '("orion samples" OR "orion systems") AND ' '("ordinal signature" OR "response drift")',
        ),
        role_query_from_boolean(
            PlanningLiteratureRole.METHOD_FOUNDATION,
            "bridge-method",
            '("ordinal signature" OR "information theory") AND '
            "(estimation OR foundation OR validation)",
        ),
        role_query_from_boolean(
            PlanningLiteratureRole.MECHANISM_OR_NULL,
            "bridge-mechanism",
            '(transport OR diffusion) AND (surrogate OR "null model")',
        ),
        role_query_from_boolean(
            PlanningLiteratureRole.COUNTEREVIDENCE,
            "bridge-counter",
            "(failure OR limitation) AND (artifact OR bias)",
        ),
    )


def _candidate(
    record_id: str,
    title: str,
    abstract: str,
    *,
    citation_count: int | None = None,
    quality_score: float = 0.0,
    retrieval_queries: tuple[str, ...] = (),
    source_stages: tuple[str, ...] = ("targeted_direction",),
    context_characters: int | None = None,
    anchor_id: str | None = None,
) -> PlanningLiteratureCandidate:
    return PlanningLiteratureCandidate(
        record_id=record_id,
        title=title,
        abstract=abstract,
        citation_count=citation_count,
        quality_score=quality_score,
        retrieval_queries=retrieval_queries,
        source_stages=source_stages,
        context_characters=context_characters,
        anchor_id=anchor_id,
    )


def _complete_candidates() -> tuple[PlanningLiteratureCandidate, ...]:
    query_by_role = {item.role: item.raw_query for item in _queries()}
    return (
        _candidate(
            "direct-low-citation",
            "Aurelia cells under phase drift",
            "A direct study of aurelia devices and state drift.",
            citation_count=2,
            quality_score=0.7,
            retrieval_queries=(query_by_role[PlanningLiteratureRole.DIRECT_CORE],),
            source_stages=("targeted_direction",),
        ),
        _candidate(
            "direct-second",
            "State drift in aurelia devices",
            "Aurelia cells exhibit phase drift under repeated operation.",
            citation_count=1,
            quality_score=0.6,
            retrieval_queries=(query_by_role[PlanningLiteratureRole.DIRECT_CORE],),
            source_stages=("targeted_direction",),
        ),
        _candidate(
            "method-foundation",
            "Foundation of rank-pattern analysis",
            "A definition of ordinal analysis for sequential observations.",
            citation_count=40,
            quality_score=0.8,
            retrieval_queries=(query_by_role[PlanningLiteratureRole.METHOD_FOUNDATION],),
            source_stages=("targeted_direction",),
        ),
        _candidate(
            "mechanism-null",
            "Diffusion transport under a null model",
            "A transport surrogate separates diffusion from persistent structure.",
            citation_count=20,
            quality_score=0.8,
            retrieval_queries=(query_by_role[PlanningLiteratureRole.MECHANISM_OR_NULL],),
            source_stages=("targeted_direction",),
        ),
        _candidate(
            "counter-bias",
            "Failure and measurement bias",
            "This limitation is caused by a sampling artifact.",
            citation_count=15,
            quality_score=0.8,
            retrieval_queries=(query_by_role[PlanningLiteratureRole.COUNTEREVIDENCE],),
            source_stages=("targeted_direction",),
        ),
        _candidate(
            "direct-third",
            "Phase drift in aurelia cells",
            "Aurelia devices show state drift in an independent setting.",
            citation_count=0,
            quality_score=0.5,
            retrieval_queries=(query_by_role[PlanningLiteratureRole.DIRECT_CORE],),
            source_stages=("targeted_direction",),
        ),
        _candidate(
            "method-second",
            "Ordinal analysis: definition and foundation",
            "Rank-pattern analysis is developed from first principles.",
            citation_count=4,
            quality_score=0.5,
            retrieval_queries=(query_by_role[PlanningLiteratureRole.METHOD_FOUNDATION],),
            source_stages=("targeted_direction",),
        ),
        _candidate(
            "counter-second",
            "Artifact-driven failure",
            "A bias limitation invalidates the apparent response.",
            citation_count=3,
            quality_score=0.5,
            retrieval_queries=(query_by_role[PlanningLiteratureRole.COUNTEREVIDENCE],),
            source_stages=("targeted_direction",),
        ),
    )


def _method_bridge_candidates(
    queries=None,  # type: ignore[no-untyped-def]
) -> tuple[PlanningLiteratureCandidate, ...]:
    active = tuple(queries or _method_bridge_queries())
    by_role = {item.role: item.raw_query for item in active}
    return (
        _candidate(
            "bridge-direct-one",
            "Orion samples under response drift",
            "Orion systems exhibit a repeatable response.",
            retrieval_queries=(by_role[PlanningLiteratureRole.DIRECT_CORE],),
            quality_score=0.7,
        ),
        _candidate(
            "bridge-direct-two",
            "Response drift in orion systems",
            "A second study of orion samples.",
            retrieval_queries=(by_role[PlanningLiteratureRole.DIRECT_CORE],),
            quality_score=0.7,
        ),
        _candidate(
            "bridged-method",
            "Foundation and estimation of ordinal signatures",
            "Ordinal signature validation is developed from first principles.",
            retrieval_queries=(by_role[PlanningLiteratureRole.METHOD_FOUNDATION],),
            quality_score=0.6,
        ),
        _candidate(
            "unbridged-method",
            "Information theory estimation and validation for radio channels",
            "A foundation for an unrelated communication system.",
            retrieval_queries=(by_role[PlanningLiteratureRole.METHOD_FOUNDATION],),
            quality_score=1.0,
            citation_count=1_000_000,
        ),
        _candidate(
            "bridge-mechanism-anchor",
            "Diffusion transport under a null model",
            "A surrogate distinguishes diffusion from transport.",
            retrieval_queries=(by_role[PlanningLiteratureRole.MECHANISM_OR_NULL],),
            quality_score=0.7,
        ),
        _candidate(
            "bridge-counter-anchor",
            "Failure and measurement bias",
            "A limitation caused by an artifact.",
            retrieval_queries=(by_role[PlanningLiteratureRole.COUNTEREVIDENCE],),
            quality_score=0.7,
        ),
    )


def _select_v4_receipt(
    candidates: tuple[PlanningLiteratureCandidate, ...],
    queries,  # type: ignore[no-untyped-def]
    *,
    maximum_records: int,
) -> PlanningLiteratureCoverageReceiptV4:
    classifications = coverage_module._classify_planning_candidates_for_policy(
        candidates,
        queries,
        policy_version="v4",
    )
    eligible_ids = tuple(item.record_id for item in candidates)
    selected, assignments, failures, _warnings = coverage_module._select_classified_planning_literature(
        classifications,
        maximum_records=maximum_records,
        maximum_total_context_characters=None,
        policy_version="v4",
        required_anchor_eligible_record_ids=eligible_ids,
    )
    return coverage_module._build_v4_receipt(
        role_queries=tuple(queries),
        classifications=classifications,
        maximum_records=maximum_records,
        maximum_total_context_characters=None,
        selected_indices=selected,
        anchor_assignments=assignments,
        failure_reasons=failures,
        required_anchor_eligible_record_ids=eligible_ids,
    )


def test_boolean_parser_builds_and_of_or_groups_and_cleans_syntax() -> None:
    query = role_query_from_boolean(
        PlanningLiteratureRole.DIRECT_CORE,
        "query-unicode",
        '("rényi geometry" OR "naïve topology") AND ' '(façade* OR "boundary response")',
    )

    assert query.must_groups == (
        ("naïve topology", "rényi geometry"),
        ("boundary response", "façade"),
    )
    assert query.prefix_terms == ("façade",)


def test_boolean_parser_preserves_boolean_words_inside_a_quoted_term() -> None:
    query = role_query_from_boolean(
        PlanningLiteratureRole.DIRECT_CORE,
        "query-quoted-operator",
        '"law and order" AND (stability OR robustness)',
    )

    assert query.must_groups == (("law and order",), ("robustness", "stability"))


def test_boolean_parser_accepts_apostrophe_inside_a_quoted_term() -> None:
    query = role_query_from_boolean(
        PlanningLiteratureRole.DIRECT_CORE,
        "query-apostrophe",
        '("Amdahl\'s law" OR "Moore\'s law") AND ("memory wall" OR "scaling limit")',
    )

    assert query.must_groups == (
        ("amdahl's law", "moore's law"),
        ("memory wall", "scaling limit"),
    )


@pytest.mark.parametrize(
    "query",
    (
        "alpha OR beta AND gamma",
        "(alpha OR beta",
        "alpha AND NOT beta",
        "alpha AND pred*icate",
        '"unterminated AND beta',
        "title:alpha AND beta",
    ),
)
def test_boolean_parser_fails_closed_when_structure_is_unreliable(query: str) -> None:
    with pytest.raises(PlanningLiteratureCoverageError):
        role_query_from_boolean(
            PlanningLiteratureRole.DIRECT_CORE,
            "query-invalid",
            query,
        )


def test_highly_cited_cross_domain_method_cannot_be_promoted_to_direct_core() -> None:
    method_query = _queries()[1].raw_query
    high_citation_transfer = _candidate(
        "cross-domain-method",
        "Foundation of rank-pattern analysis in ocean colour",
        "This definition of ordinal analysis concerns remote-sensing images.",
        citation_count=100_000,
        quality_score=1.0,
        retrieval_queries=(method_query,),
    )
    candidates = (*_complete_candidates(), high_citation_transfer)

    classifications = classify_planning_candidates(candidates, _queries())
    transfer = next(
        item for item in classifications if item.candidate.record_id == "cross-domain-method"
    )

    assert PlanningLiteratureRole.DIRECT_CORE not in transfer.matched_roles
    assert transfer.semantic_layer is PlanningLiteratureRole.METHOD_FOUNDATION
    receipt = select_planning_literature(candidates, _queries(), maximum_records=8)
    assert receipt.passed is True
    assert receipt.selected_role_counts.direct_core >= 2
    assert {"direct-low-citation", "direct-second"}.issubset(receipt.selected_record_ids)


def test_twenty_method_records_cannot_backfill_core_null_or_counterevidence() -> None:
    method_query = _queries()[1].raw_query
    candidates = tuple(
        _candidate(
            f"method-{index:02d}",
            f"Foundation of rank-pattern analysis, study {index}",
            "A definition of ordinal analysis for an unrelated application.",
            citation_count=1_000 - index,
            retrieval_queries=(method_query,),
        )
        for index in range(20)
    )

    receipt = select_planning_literature(candidates, _queries(), maximum_records=10)

    assert receipt.passed is False
    assert receipt.selected_record_ids == ()
    assert receipt.available_role_counts.method_foundation == 20
    assert receipt.available_role_counts.direct_core == 0
    assert receipt.available_role_counts.mechanism_or_null == 0
    assert receipt.available_role_counts.counterevidence == 0
    assert "insufficient_direct_core" in receipt.failure_reasons
    assert "insufficient_mechanism_or_null" in receipt.failure_reasons
    assert "insufficient_counterevidence" in receipt.failure_reasons


def test_negated_counterevidence_terms_do_not_create_a_counter_anchor() -> None:
    counter_query = _queries()[3].raw_query
    candidates = tuple(
        item
        for item in _complete_candidates()
        if item.record_id not in {"counter-bias", "counter-second"}
    ) + (
        _candidate(
            "negated-counter",
            "No failure and zero measurement bias",
            "The study reports no limitation, without artifact, and not a bias.",
            quality_score=0.95,
            retrieval_queries=(counter_query,),
        ),
    )

    receipt = select_planning_literature(candidates, _queries(), maximum_records=8)

    assert receipt.passed is False
    assert "insufficient_counterevidence" in receipt.failure_reasons


def test_v4_required_anchors_exclude_repository_only_but_allow_preprints() -> None:
    candidates = _complete_candidates()
    eligible = tuple(
        item.record_id for item in candidates if item.record_id != "direct-low-citation"
    )

    receipt = select_planning_literature(
        candidates,
        _queries(),
        maximum_records=5,
        required_anchor_eligible_record_ids=eligible,
    )

    anchor_ids = {item.record_id for item in receipt.anchor_assignments}
    assert receipt.schema_version == "contest-planning-literature-coverage-v5"
    assert receipt.passed is True
    assert "direct-low-citation" not in anchor_ids
    assert "direct-second" in anchor_ids
    assert "direct-third" in anchor_ids


def test_v5_method_focus_bridge_blocks_unrelated_or_dense_anchor_and_supplement() -> None:
    queries = _method_bridge_queries()
    candidates = _method_bridge_candidates(queries)

    receipt = select_planning_literature(candidates, queries, maximum_records=6)

    assert receipt.passed is True
    assert receipt.schema_version == "contest-planning-literature-coverage-v5"
    assert receipt.method_bridge_contract.shared_focus_terms == ("ordinal signature",)
    assert receipt.eligible_role_family_counts.method_foundation == 1
    method_anchor = next(
        item
        for item in receipt.anchor_assignments
        if item.role is PlanningLiteratureRole.METHOD_FOUNDATION
    )
    assert method_anchor.record_id == "bridged-method"
    assert "unbridged-method" not in receipt.selected_record_ids

    assessments = {item.record_id: item for item in receipt.method_bridge_assessments}
    bridged = assessments["bridged-method"]
    assert bridged.bridge_kind == "shared_focus"
    assert bridged.bridge_eligible is True
    assert bridged.shared_focus_matches[0].term == "ordinal signature"
    assert bridged.shared_focus_matches[0].matched_fields == ("title", "abstract")
    assert assessments["unbridged-method"].bridge_kind == "unbridged_method"
    assert assessments["unbridged-method"].bridge_eligible is False
    assert assessments["bridge-direct-one"].bridge_kind == "not_method_candidate"


def test_v5_explicit_method_focus_basis_does_not_drift_with_a_repaired_direct_query() -> None:
    basis_queries = _method_bridge_queries()
    repaired_queries = (
        role_query_from_boolean(
            PlanningLiteratureRole.DIRECT_CORE,
            "repaired-direct",
            '("orion samples" OR "orion systems") AND ' '("response anomaly" OR "response drift")',
        ),
        *basis_queries[1:],
    )
    candidates = _method_bridge_candidates(repaired_queries)

    default_receipt = select_planning_literature(
        candidates,
        repaired_queries,
        maximum_records=6,
    )
    bound_receipt = select_planning_literature(
        candidates,
        repaired_queries,
        maximum_records=6,
        method_focus_basis_queries=basis_queries,
    )

    assert default_receipt.passed is True
    assert "method_focus_bridge_relaxed" in default_receipt.warnings
    assert "unbridged-method" in default_receipt.selected_record_ids
    assert bound_receipt.passed is True
    assert "method_focus_bridge_relaxed" not in bound_receipt.warnings
    assert bound_receipt.method_focus_basis_queries == basis_queries
    assert bound_receipt.method_bridge_contract.shared_focus_terms == ("ordinal signature",)
    assert "bridged-method" in bound_receipt.selected_record_ids


def test_v5_receipt_rejects_rehashed_method_bridge_trace_tamper() -> None:
    receipt = select_planning_literature(
        _method_bridge_candidates(),
        _method_bridge_queries(),
        maximum_records=6,
    )
    payload = receipt.model_dump(mode="json")
    bridged = next(item for item in payload["method_bridge_assessments"] if item["bridge_eligible"])
    bridged["shared_focus_matches"][0]["matched_fields"] = ["abstract"]
    payload["receipt_hash"] = canonical_model_hash(
        {key: value for key, value in payload.items() if key != "receipt_hash"}
    )

    with pytest.raises(ValidationError, match="method bridge assessments do not replay"):
        type(receipt).model_validate(payload)


def test_v5_bridge_assessment_rejects_eligible_kind_without_term_trace() -> None:
    with pytest.raises(ValidationError, match="bridged method assessment requires term traces"):
        coverage_module.PlanningLiteratureMethodBridgeAssessment.model_validate(
            {
                "candidate_index": 0,
                "record_id": "method-without-trace",
                "bridge_kind": "shared_focus",
                "shared_focus_matches": [],
                "direct_object_matches": [],
                "bridge_eligible": True,
            }
        )


def test_v4_receipt_replays_without_method_focus_bridge_reinterpretation() -> None:
    queries = _method_bridge_queries()
    candidates = _method_bridge_candidates(queries)
    classifications = coverage_module._classify_planning_candidates_for_policy(
        candidates,
        queries,
        policy_version="v4",
    )
    eligible_ids = tuple(item.record_id for item in candidates)
    selected, assignments, failures, _warnings = coverage_module._select_classified_planning_literature(
        classifications,
        maximum_records=6,
        maximum_total_context_characters=None,
        policy_version="v4",
        required_anchor_eligible_record_ids=eligible_ids,
    )
    legacy = coverage_module._build_v4_receipt(
        role_queries=queries,
        classifications=classifications,
        maximum_records=6,
        maximum_total_context_characters=None,
        selected_indices=selected,
        anchor_assignments=assignments,
        failure_reasons=failures,
        required_anchor_eligible_record_ids=eligible_ids,
    )

    replayed = parse_planning_literature_coverage_receipt(legacy.model_dump(mode="json"))

    assert isinstance(replayed, PlanningLiteratureCoverageReceiptV4)
    assert replayed.schema_version == "contest-planning-literature-coverage-v4"
    assert "unbridged-method" in replayed.selected_record_ids


def test_v4_anchor_rank_prefers_full_role_specificity_before_authority() -> None:
    direct_query = _queries()[0].raw_query
    candidates = (*_complete_candidates(),)
    candidates = tuple(item for item in candidates if item.record_id != "direct-low-citation") + (
        _candidate(
            "direct-authority",
            "Aurelia cells under phase drift",
            "A focused observation.",
            citation_count=1_000,
            quality_score=0.96,
            retrieval_queries=(direct_query,),
        ),
        _candidate(
            "direct-specific",
            "Aurelia cells and aurelia devices under phase drift and state drift",
            "Both object and phenomenon alternatives are evaluated.",
            citation_count=0,
            quality_score=0.70,
            retrieval_queries=(direct_query,),
        ),
    )

    receipt = _select_v4_receipt(candidates, _queries(), maximum_records=5)

    direct_anchors = {
        item.record_id
        for item in receipt.anchor_assignments
        if item.role is PlanningLiteratureRole.DIRECT_CORE
    }
    assert "direct-specific" in direct_anchors
    assert "direct-authority" not in direct_anchors


def test_v3_receipt_replays_frozen_quality_first_selection() -> None:
    candidates = _complete_candidates()
    queries = _queries()
    classifications = coverage_module._classify_planning_candidates_for_policy(
        candidates,
        queries,
        policy_version="v3",
    )
    candidate_ids = tuple(item.record_id for item in candidates)
    selected, assignments, failures, _warnings = coverage_module._select_classified_planning_literature(
        classifications,
        maximum_records=5,
        maximum_total_context_characters=None,
        policy_version="v3",
        required_anchor_eligible_record_ids=candidate_ids,
    )
    selected_classifications = tuple(classifications[index] for index in selected)
    selected_records = tuple(item.candidate for item in selected_classifications)
    payload = {
        "schema_version": "contest-planning-literature-coverage-v3",
        "role_queries": [item.model_dump(mode="json") for item in queries],
        "classifications": [item.model_dump(mode="json") for item in classifications],
        "thresholds": coverage_module.PlanningLiteratureCoverageThresholdsV3().model_dump(
            mode="json"
        ),
        "candidate_count": len(classifications),
        "maximum_records": 5,
        "maximum_total_context_characters": None,
        "available_role_counts": coverage_module._role_counts(classifications).model_dump(
            mode="json"
        ),
        "selected_role_counts": coverage_module._role_counts(selected_classifications).model_dump(
            mode="json"
        ),
        "selected_record_ids": [item.record_id for item in selected_records],
        "selected_candidate_indices": list(selected),
        "selected_records": [item.model_dump(mode="json") for item in selected_records],
        "anchor_assignments": [item.model_dump(mode="json") for item in assignments],
        "selected_total_context_characters": sum(
            item.effective_context_characters for item in selected_records
        ),
        "failure_reasons": list(failures),
        "passed": not failures,
        "selection_semantics": (
            "targeted_lineage_distinct_anchor_dp_then_quality_limited_supplements"
        ),
    }
    payload["receipt_hash"] = canonical_model_hash(payload)

    replayed = parse_planning_literature_coverage_receipt(payload)

    assert isinstance(replayed, PlanningLiteratureCoverageReceiptV3)
    assert replayed.schema_version == "contest-planning-literature-coverage-v3"


def test_unicode_and_diacritic_terms_are_matched_without_dropping_non_ascii_text() -> None:
    direct = role_query_from_boolean(
        PlanningLiteratureRole.DIRECT_CORE,
        "query-unicode-direct",
        '("rényi geometry" OR "几何结构") AND (naïve OR façade*)',
    )
    other_queries = _queries()[1:]
    candidate = _candidate(
        "unicode-record",
        "Renyi geometry and a naive estimator",
        "The façade-aware analysis also preserves 几何结构 evidence.",
        retrieval_queries=(direct.raw_query,),
        source_stages=("targeted_direction",),
    )

    classification = classify_planning_candidates((candidate,), (direct, *other_queries))[0]

    assert classification.semantic_layer is PlanningLiteratureRole.DIRECT_CORE
    match = classification.role_matches[0]
    assert match.query_id == "query-unicode-direct"
    assert match.role is PlanningLiteratureRole.DIRECT_CORE
    assert len(match.matched_groups) == 2
    assert match.matched_retrieval_queries == (direct.raw_query,)
    assert match.source_stages == ("targeted_direction",)


@pytest.mark.parametrize(
    ("query_term", "candidate_phrase"),
    (
        ("aurelia cells", "Aurelia cell"),
        ("drift study", "Drift studies"),
        ("sensor class", "Sensor classes"),
        ("aurelia cells", "Aurelia monitored cell"),
    ),
)
def test_concept_phrase_matching_accepts_regular_number_and_one_internal_token(
    query_term: str,
    candidate_phrase: str,
) -> None:
    direct = role_query_from_boolean(
        PlanningLiteratureRole.DIRECT_CORE,
        "query-conservative-concept-match",
        f'"{query_term}" AND "phase drift"',
    )
    candidate = _candidate(
        "conservative-concept-match",
        f"{candidate_phrase} under phase drift",
        "The study reports a direct observation.",
        retrieval_queries=(direct.raw_query,),
        source_stages=("targeted_direction",),
    )

    classification = classify_planning_candidates(
        (candidate,),
        (direct, *_queries()[1:]),
    )[0]

    assert classification.semantic_layer is PlanningLiteratureRole.DIRECT_CORE
    assert classification.matched_roles == (PlanningLiteratureRole.DIRECT_CORE,)
    assert len(classification.role_matches[0].matched_groups) == 2


@pytest.mark.parametrize(
    "candidate_phrase",
    (
        "Aurelia adaptive monitored cell",
        "Cells aurelia",
        "Aurelia units",
        "Aurelia cellular response",
    ),
)
def test_concept_phrase_matching_rejects_two_insertions_reordering_and_guesses(
    candidate_phrase: str,
) -> None:
    direct = role_query_from_boolean(
        PlanningLiteratureRole.DIRECT_CORE,
        "query-conservative-concept-rejection",
        '"aurelia cells" AND "phase drift"',
    )
    candidate = _candidate(
        "conservative-concept-rejection",
        f"{candidate_phrase} under phase drift",
        "The study reports a direct observation.",
        retrieval_queries=(direct.raw_query,),
        source_stages=("targeted_direction",),
    )

    classification = classify_planning_candidates(
        (candidate,),
        (direct, *_queries()[1:]),
    )[0]

    assert PlanningLiteratureRole.DIRECT_CORE not in classification.matched_roles


def test_one_record_can_hold_multiple_roles_with_full_query_trace() -> None:
    candidate = _candidate(
        "multi-role",
        "Aurelia cells, phase drift, and diffusion transport",
        "A state-drift study compares transport against a null model surrogate.",
        retrieval_queries=(_queries()[0].raw_query, _queries()[2].raw_query),
        source_stages=("broad_discovery", "targeted_direction"),
    )

    classification = classify_planning_candidates((candidate,), _queries())[0]

    assert classification.matched_roles == (
        PlanningLiteratureRole.DIRECT_CORE,
        PlanningLiteratureRole.MECHANISM_OR_NULL,
    )
    assert {item.query_id for item in classification.role_matches} == {
        "query-direct",
        "query-mechanism",
    }
    assert all(len(item.matched_groups) == 2 for item in classification.role_matches)
    assert all(
        item.source_stages == candidate.source_stages for item in classification.role_matches
    )


@pytest.mark.parametrize(
    "retrieval_queries",
    (
        (),
        ('("Aurelia cells" OR "aurelia devices") AND ' '("phase drift" OR "state drift")',),
        ('("aurelia cells" OR "aurelia devices")  AND ' '("phase drift" OR "state drift")',),
    ),
)
def test_complete_text_match_requires_exact_raw_query_lineage(
    retrieval_queries: tuple[str, ...],
) -> None:
    candidate = _candidate(
        "text-only-direct",
        "Aurelia cells under phase drift",
        "Aurelia devices exhibit state drift.",
        retrieval_queries=retrieval_queries,
        source_stages=("targeted_direction",),
    )

    classification = classify_planning_candidates((candidate,), _queries())[0]

    assert PlanningLiteratureRole.DIRECT_CORE not in classification.matched_roles
    assert all(not match.complete for match in classification.role_matches)


def test_exact_query_lineage_from_broad_discovery_cannot_count_as_targeted_coverage() -> None:
    direct_query = _queries()[0].raw_query
    candidate = _candidate(
        "broad-only-direct",
        "Aurelia cells under phase drift",
        "Aurelia devices exhibit state drift.",
        retrieval_queries=(direct_query,),
        source_stages=("broad_discovery",),
    )

    classification = classify_planning_candidates((candidate,), _queries())[0]

    assert PlanningLiteratureRole.DIRECT_CORE not in classification.matched_roles


def test_selector_limits_unverified_supplements_after_required_roles_pass() -> None:
    candidates = _complete_candidates()

    receipt = select_planning_literature(candidates, _queries(), maximum_records=8)

    assert receipt.passed is True
    assert len(receipt.selected_record_ids) == 7
    assert receipt.selected_records == tuple(
        candidates[index] for index in receipt.selected_candidate_indices
    )
    assert tuple(item.record_id for item in receipt.selected_records) == (
        receipt.selected_record_ids
    )
    assert receipt.selected_role_counts.direct_core >= 2
    assert receipt.selected_role_counts.method_foundation >= 1
    assert receipt.selected_role_counts.mechanism_or_null >= 1
    assert receipt.selected_role_counts.counterevidence >= 1
    assert len(receipt.anchor_assignments) == 5
    assert len({item.record_id for item in receipt.anchor_assignments}) == 5
    assert len({item.anchor_id for item in receipt.anchor_assignments}) == 5
    assert [item.role for item in receipt.anchor_assignments].count(
        PlanningLiteratureRole.DIRECT_CORE
    ) == 2


def test_extreme_citation_magnitude_is_capped_inside_one_quality_tier() -> None:
    direct_query = _queries()[0].raw_query
    moderate = _candidate(
        "moderate-citations",
        "Aurelia cells under phase drift",
        "Aurelia devices exhibit state drift.",
        retrieval_queries=(direct_query,),
        quality_score=0.6,
        citation_count=1_000,
    )
    extreme = moderate.model_copy(
        update={"record_id": "extreme-citations", "citation_count": 100_000_000}
    )
    moderate_classification, extreme_classification = classify_planning_candidates(
        (moderate, extreme), _queries()
    )

    assert (
        coverage_module._quality_key(
            moderate_classification,
            policy_version="v4",
            required_anchor=False,
        )[:4]
        == (
            coverage_module._quality_key(
                extreme_classification,
                policy_version="v4",
                required_anchor=False,
            )[:4]
        )
    )


def test_v5_or_alternative_count_does_not_outrank_equal_title_coverage() -> None:
    mechanism_query = _queries()[2].raw_query
    sparse = _candidate(
        "mechanism-sparse",
        "A transport process under a null model",
        "A controlled account of the process.",
        quality_score=0.8,
        citation_count=50,
        retrieval_queries=(mechanism_query,),
    )
    specific = _candidate(
        "mechanism-specific",
        "Zeta diffusion transport process under a null model",
        "A surrogate analysis distinguishes diffusion from transport.",
        quality_score=0.8,
        citation_count=0,
        retrieval_queries=(mechanism_query,),
    )
    required_without_mechanism = tuple(
        item for item in _complete_candidates()[:5] if item.record_id != "mechanism-null"
    )

    receipt = select_planning_literature(
        (*required_without_mechanism, sparse, specific),
        _queries(),
        maximum_records=5,
    )

    assigned = next(
        item
        for item in receipt.anchor_assignments
        if item.role is PlanningLiteratureRole.MECHANISM_OR_NULL
    )
    assert assigned.record_id == "mechanism-sparse"


def test_citation_bins_are_capped_and_remain_below_authority_quality() -> None:
    assert {
        count: coverage_module._bounded_bibliometric_rank(count)
        for count in (0, 1, 9, 10, 99, 100, 999, 1_000, 100_000_000)
    } == {
        0: 0,
        1: 1,
        9: 1,
        10: 2,
        99: 2,
        100: 3,
        999: 3,
        1_000: 4,
        100_000_000: 4,
    }
    method_query = _queries()[1].raw_query
    ordinary = _candidate(
        "ordinary-high-method",
        "Foundation of rank-pattern analysis",
        "A definition of ordinal analysis.",
        quality_score=0.7,
        citation_count=500,
        retrieval_queries=(method_query,),
    )
    extreme = ordinary.model_copy(update={"record_id": "extreme-method", "citation_count": 500_000})
    higher_authority = ordinary.model_copy(
        update={
            "record_id": "higher-authority-method",
            "quality_score": 0.8,
            "citation_count": 0,
        }
    )
    ordinary_classification, extreme_classification, authority_classification = (
        classify_planning_candidates(
            (ordinary, extreme, higher_authority),
            _queries(),
        )
    )

    assert coverage_module._quality_key(
        extreme_classification,
        role=PlanningLiteratureRole.METHOD_FOUNDATION,
        policy_version="v4",
        required_anchor=False,
    ) < coverage_module._quality_key(
        ordinary_classification,
        role=PlanningLiteratureRole.METHOD_FOUNDATION,
        policy_version="v4",
        required_anchor=False,
    )
    assert coverage_module._quality_key(
        authority_classification,
        role=PlanningLiteratureRole.METHOD_FOUNDATION,
        policy_version="v4",
        required_anchor=False,
    ) < coverage_module._quality_key(
        extreme_classification,
        role=PlanningLiteratureRole.METHOD_FOUNDATION,
        policy_version="v4",
        required_anchor=False,
    )


def test_method_transfer_never_becomes_a_majority_and_off_topic_is_not_selected() -> None:
    required = _complete_candidates()[:5]
    transfers = tuple(
        _candidate(
            f"transfer-{index}",
            f"Rank-pattern analysis application {index}",
            "The application does not define or establish the method.",
            quality_score=1.0 - index / 100,
        )
        for index in range(8)
    )
    off_topic = _candidate(
        "off-topic",
        "Unrelated observational catalogue",
        "A descriptive survey with no matching semantic group.",
        quality_score=1.0,
        citation_count=1_000_000,
    )

    receipt = select_planning_literature(
        (*required, *transfers, off_topic),
        _queries(),
        maximum_records=10,
    )

    assert receipt.passed is True
    assert "off-topic" not in receipt.selected_record_ids
    assert receipt.selected_method_transfer_count * 2 <= len(receipt.selected_record_ids)


def test_multi_role_trace_cannot_supply_more_than_one_required_anchor_slot() -> None:
    query_by_role = {item.role: item.raw_query for item in _queries()}
    multi_role = _candidate(
        "multi-role-core",
        "Aurelia cells phase drift and rank-pattern analysis foundation",
        (
            "A definition using diffusion transport and a null model; a failure limitation "
            "also exposes bias and artifact risks."
        ),
        retrieval_queries=tuple(query_by_role.values()),
    )
    second_direct = _candidate(
        "second-direct-core",
        "Aurelia devices with state drift",
        "A direct study of aurelia cells and phase drift.",
        retrieval_queries=(query_by_role[PlanningLiteratureRole.DIRECT_CORE],),
    )
    transfers = tuple(
        _candidate(
            f"partial-method-{index}",
            "Rank-pattern analysis in an unrelated setting",
            "An application that does not establish first principles.",
        )
        for index in range(3)
    )

    receipt = select_planning_literature(
        (multi_role, second_direct, *transfers),
        _queries(),
        maximum_records=5,
    )

    assert receipt.passed is False
    assert receipt.selected_record_ids == ()
    assert receipt.anchor_assignments == ()
    assert "insufficient_distinct_required_role_anchors" in receipt.failure_reasons


def test_two_records_with_one_work_family_anchor_cannot_fill_two_direct_slots() -> None:
    candidates = list(_complete_candidates()[:5])
    candidates[0] = candidates[0].model_copy(update={"anchor_id": "shared-work-family"})
    candidates[1] = candidates[1].model_copy(update={"anchor_id": "shared-work-family"})

    receipt = select_planning_literature(candidates, _queries(), maximum_records=8)

    assert receipt.passed is False
    assert receipt.available_role_counts.direct_core == 1
    assert "insufficient_direct_core" in receipt.failure_reasons


def test_required_anchor_dp_skips_a_large_high_quality_record_to_preserve_feasibility() -> None:
    query_by_role = {item.role: item.raw_query for item in _queries()}
    candidates = (
        _candidate(
            "direct-large",
            "Aurelia cells under phase drift",
            "Aurelia devices exhibit state drift.",
            retrieval_queries=(query_by_role[PlanningLiteratureRole.DIRECT_CORE],),
            quality_score=1.0,
            citation_count=100,
            context_characters=250,
        ),
        _candidate(
            "direct-small-a",
            "State drift in aurelia devices",
            "Aurelia cells exhibit phase drift.",
            retrieval_queries=(query_by_role[PlanningLiteratureRole.DIRECT_CORE],),
            quality_score=0.8,
            context_characters=100,
        ),
        _candidate(
            "direct-small-b",
            "Phase drift in aurelia cells",
            "Aurelia devices exhibit state drift.",
            retrieval_queries=(query_by_role[PlanningLiteratureRole.DIRECT_CORE],),
            quality_score=0.7,
            context_characters=100,
        ),
        _candidate(
            "method-small",
            "Formal definition of rank-pattern analysis",
            "A foundation for ordinal analysis.",
            retrieval_queries=(query_by_role[PlanningLiteratureRole.METHOD_FOUNDATION],),
            quality_score=0.7,
            context_characters=100,
        ),
        _candidate(
            "mechanism-small",
            "Diffusion transport under a null model",
            "A surrogate null model for transport and diffusion.",
            retrieval_queries=(query_by_role[PlanningLiteratureRole.MECHANISM_OR_NULL],),
            quality_score=0.7,
            context_characters=100,
        ),
        _candidate(
            "counter-small",
            "Failure caused by measurement bias",
            "A limitation and artifact explain the bias.",
            retrieval_queries=(query_by_role[PlanningLiteratureRole.COUNTEREVIDENCE],),
            quality_score=0.7,
            context_characters=100,
        ),
    )

    receipt = select_planning_literature(
        candidates,
        _queries(),
        maximum_records=6,
        maximum_total_context_characters=600,
    )

    assert receipt.passed is True
    assert "direct-large" not in receipt.selected_record_ids
    assert set(receipt.selected_record_ids) == {
        "direct-small-a",
        "direct-small-b",
        "method-small",
        "mechanism-small",
        "counter-small",
    }
    assert receipt.selected_total_context_characters == 500


def test_anchor_dp_preserves_a_feasible_better_role_quality_prefix_at_equal_total_rank() -> None:
    query_by_role = {item.role: item.raw_query for item in _queries()}
    direct_query = query_by_role[PlanningLiteratureRole.DIRECT_CORE]
    candidates = (
        _candidate(
            "direct-best",
            "Aurelia cells under phase drift",
            "Aurelia devices exhibit state drift.",
            retrieval_queries=(direct_query,),
            quality_score=1.0,
            context_characters=300,
            anchor_id="a-direct-family",
        ),
        _candidate(
            "direct-third",
            "Phase drift in aurelia cells",
            "Aurelia devices exhibit state drift.",
            retrieval_queries=(direct_query,),
            quality_score=0.8,
            context_characters=50,
            anchor_id="a-direct-family",
        ),
        _candidate(
            "direct-second",
            "State drift in aurelia devices",
            "Aurelia cells exhibit phase drift.",
            retrieval_queries=(direct_query,),
            quality_score=0.9,
            context_characters=250,
            anchor_id="b-direct-family",
        ),
        _candidate(
            "direct-low",
            "Aurelia devices and phase drift",
            "Aurelia cells exhibit state drift.",
            retrieval_queries=(direct_query,),
            quality_score=0.7,
            context_characters=50,
            anchor_id="b-direct-family",
        ),
        _candidate(
            "method-anchor",
            "Formal definition of rank-pattern analysis",
            "A foundation for ordinal analysis.",
            retrieval_queries=(query_by_role[PlanningLiteratureRole.METHOD_FOUNDATION],),
            context_characters=40,
            anchor_id="c-method-family",
        ),
        _candidate(
            "mechanism-anchor",
            "Diffusion transport under a null model",
            "A surrogate null model for transport and diffusion.",
            retrieval_queries=(query_by_role[PlanningLiteratureRole.MECHANISM_OR_NULL],),
            context_characters=40,
            anchor_id="d-mechanism-family",
        ),
        _candidate(
            "counter-anchor",
            "Failure caused by measurement bias",
            "A limitation and artifact explain the bias.",
            retrieval_queries=(query_by_role[PlanningLiteratureRole.COUNTEREVIDENCE],),
            context_characters=40,
            anchor_id="e-counter-family",
        ),
    )

    receipt = select_planning_literature(
        candidates,
        _queries(),
        maximum_records=5,
        maximum_total_context_characters=500,
    )

    assigned_direct = {
        item.record_id
        for item in receipt.anchor_assignments
        if item.role is PlanningLiteratureRole.DIRECT_CORE
    }
    assert receipt.passed is True
    assert assigned_direct == {"direct-best", "direct-low"}
    assert receipt.selected_total_context_characters == 470


def test_context_budget_is_applied_before_a_candidate_can_fill_a_role() -> None:
    candidates = list(_complete_candidates())
    candidates[0] = candidates[0].model_copy(update={"context_characters": 900})
    candidates[1] = candidates[1].model_copy(update={"context_characters": 900})

    receipt = select_planning_literature(
        tuple(candidates),
        _queries(),
        maximum_records=8,
        maximum_total_context_characters=1_000,
    )

    assert receipt.passed is False
    assert receipt.selected_record_ids == ()
    assert "context_budget_prevents_required_coverage" in receipt.failure_reasons


def test_receipt_is_content_addressed_and_rejects_nested_tamper() -> None:
    receipt = select_planning_literature(
        _complete_candidates(),
        _queries(),
        maximum_records=8,
    )
    payload = receipt.model_dump(mode="json")
    payload["selected_records"][0]["title"] = "tampered title"

    with pytest.raises(ValidationError, match="receipt hash mismatch|selected records"):
        type(receipt).model_validate(payload)


def test_receipt_replay_rejects_rehashed_anchor_assignment_tamper() -> None:
    receipt = select_planning_literature(
        _complete_candidates(),
        _queries(),
        maximum_records=8,
    )
    payload = receipt.model_dump(mode="json")
    payload["anchor_assignments"][0]["record_id"] = payload["anchor_assignments"][1]["record_id"]
    payload["receipt_hash"] = canonical_model_hash(
        {key: value for key, value in payload.items() if key != "receipt_hash"}
    )

    with pytest.raises(ValidationError, match="anchor selection does not replay"):
        type(receipt).model_validate(payload)


def test_legacy_v2_loader_replays_the_frozen_selection_policy(tmp_path: Path) -> None:
    classifications = classify_planning_candidates(_complete_candidates(), _queries())
    selected, assignments, failures, _warnings = coverage_module._select_classified_planning_literature(
        classifications,
        maximum_records=8,
        maximum_total_context_characters=None,
        policy_version="v2",
        required_anchor_eligible_record_ids=tuple(
            item.candidate.record_id for item in classifications
        ),
    )
    selected_classifications = tuple(classifications[index] for index in selected)
    selected_records = tuple(item.candidate for item in selected_classifications)
    payload = {
        "schema_version": "contest-planning-literature-coverage-v2",
        "role_queries": [item.model_dump(mode="json") for item in _queries()],
        "classifications": [item.model_dump(mode="json") for item in classifications],
        "thresholds": {
            "direct_core": 2,
            "method_foundation": 1,
            "mechanism_or_null": 1,
            "counterevidence": 1,
            "method_transfer_must_not_be_majority": True,
        },
        "candidate_count": len(classifications),
        "maximum_records": 8,
        "maximum_total_context_characters": None,
        "available_role_counts": coverage_module._role_counts(classifications).model_dump(
            mode="json"
        ),
        "selected_role_counts": coverage_module._role_counts(selected_classifications).model_dump(
            mode="json"
        ),
        "selected_record_ids": [item.record_id for item in selected_records],
        "selected_candidate_indices": list(selected),
        "selected_records": [item.model_dump(mode="json") for item in selected_records],
        "anchor_assignments": [item.model_dump(mode="json") for item in assignments],
        "selected_total_context_characters": sum(
            item.effective_context_characters for item in selected_records
        ),
        "failure_reasons": list(failures),
        "passed": not failures,
        "selection_semantics": ("targeted_lineage_distinct_anchor_dp_then_within_layer_quality"),
    }
    payload["receipt_hash"] = canonical_model_hash(payload)
    path = tmp_path / "coverage-v2.json"
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    loaded = coverage_module.load_planning_literature_coverage_receipt(path)

    assert loaded.schema_version == "contest-planning-literature-coverage-v2"
    assert len(loaded.selected_records) == 8

    payload["selected_candidate_indices"][0:2] = reversed(
        payload["selected_candidate_indices"][0:2]
    )
    payload["selected_record_ids"][0:2] = reversed(payload["selected_record_ids"][0:2])
    payload["selected_records"][0:2] = reversed(payload["selected_records"][0:2])
    payload["receipt_hash"] = canonical_model_hash(
        {key: value for key, value in payload.items() if key != "receipt_hash"}
    )
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    with pytest.raises(ValidationError, match="selection does not replay"):
        coverage_module.load_planning_literature_coverage_receipt(path)
