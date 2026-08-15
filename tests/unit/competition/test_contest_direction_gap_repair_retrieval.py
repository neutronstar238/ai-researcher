"""Tests for sparse, role-bound follow-up literature retrieval."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from autoresearch.competition.contest_direction_gap_repair_retrieval import (
    ContestDirectionGapRepairArtifact,
    ContestDirectionGapRepairError,
    ContestDirectionGapRepairRoleQuery,
    build_contest_direction_gap_repair_plan,
    build_contest_direction_gap_repair_plan_from_projection,
    load_contest_direction_gap_repair,
    retrieve_contest_direction_gap_repair,
)
from autoresearch.competition.contest_planning_literature_coverage import (
    PlanningLiteratureRole,
    role_query_from_boolean,
)
from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.literature.models import AcademicPaper

NOW = datetime(2026, 8, 15, 9, 30, tzinfo=timezone.utc)


def _role_query(
    role: PlanningLiteratureRole,
    query_id: str,
    evidence_group: str,
):  # type: ignore[no-untyped-def]
    return role_query_from_boolean(
        role,
        query_id,
        f'("aurelia systems" OR "borealis systems") AND ({evidence_group})',
    )


def _repair_query(
    role: PlanningLiteratureRole,
    *,
    missing_slots: int = 1,
) -> ContestDirectionGapRepairRoleQuery:
    suffix = role.value.replace("_", "-")
    parent_evidence = {
        PlanningLiteratureRole.DIRECT_CORE: '"primary effects" OR "direct outcomes"',
        PlanningLiteratureRole.METHOD_FOUNDATION: '"validated estimator" OR calibration',
        PlanningLiteratureRole.MECHANISM_OR_NULL: '"null explanation" OR mechanism',
        PlanningLiteratureRole.COUNTEREVIDENCE: 'limitations OR "negative results"',
    }[role]
    repair_evidence = {
        PlanningLiteratureRole.DIRECT_CORE: '"bounded effects" OR replication',
        PlanningLiteratureRole.METHOD_FOUNDATION: '"sensitivity analysis" OR uncertainty',
        PlanningLiteratureRole.MECHANISM_OR_NULL: '"alternative pathway" OR confounding',
        PlanningLiteratureRole.COUNTEREVIDENCE: '"failure modes" OR artifacts',
    }[role]
    parent = _role_query(role, f"r1-{suffix}", parent_evidence)
    repair = _role_query(role, f"r2-{suffix}", repair_evidence)
    return ContestDirectionGapRepairRoleQuery.create(
        role=role,
        missing_slots=missing_slots,
        parent_role_query=parent,
        repair_role_query=repair,
    )


def _plan(*roles: PlanningLiteratureRole, round_index: int = 2):  # type: ignore[no-untyped-def]
    return build_contest_direction_gap_repair_plan(
        base_merged_artifact_hash="a" * 64,
        base_merged_catalog_hash="b" * 64,
        trigger_coverage_receipt_hash="c" * 64,
        gap_repair_projection_hash="d" * 64,
        round_index=round_index,
        deficit_roles=roles,
        role_queries=tuple(_repair_query(role) for role in roles),
    )


def _paper(title: str, doi: str) -> AcademicPaper:
    return AcademicPaper(
        title=title,
        authors=["A. Researcher"],
        abstract="A complete abstract reports bounded evidence and uncertainty.",
        publication_date=date(2025, 1, 1),
        venue="Journal of Reproducible Tests",
        doi=doi,
        url=f"https://example.org/{doi.rsplit('/', maxsplit=1)[-1]}",
        citation_count=7,
        citation_count_source="openalex",
        citation_count_as_of=date(2026, 8, 15),
        publication_status="published",
        status_source="crossref",
        status_as_of=date(2026, 8, 15),
        source="fixture",
    )


def test_plan_binds_exactly_the_diagnosed_deficit_roles() -> None:
    direct = _repair_query(PlanningLiteratureRole.DIRECT_CORE, missing_slots=2)
    counter = _repair_query(PlanningLiteratureRole.COUNTEREVIDENCE)
    plan = build_contest_direction_gap_repair_plan(
        base_merged_artifact_hash="a" * 64,
        base_merged_catalog_hash="b" * 64,
        trigger_coverage_receipt_hash="c" * 64,
        gap_repair_projection_hash="d" * 64,
        round_index=2,
        deficit_roles=(
            PlanningLiteratureRole.DIRECT_CORE,
            PlanningLiteratureRole.COUNTEREVIDENCE,
        ),
        role_queries=(direct, counter),
    )

    assert plan.deficit_roles == (
        PlanningLiteratureRole.DIRECT_CORE,
        PlanningLiteratureRole.COUNTEREVIDENCE,
    )
    assert tuple(item.role for item in plan.role_queries) == plan.deficit_roles
    assert plan.total_missing_slots == 3
    assert plan.query_count == 2
    assert plan.query_model_calls == 0

    with pytest.raises(ContestDirectionGapRepairError, match="exactly match"):
        build_contest_direction_gap_repair_plan(
            base_merged_artifact_hash="a" * 64,
            base_merged_catalog_hash="b" * 64,
            trigger_coverage_receipt_hash="c" * 64,
            gap_repair_projection_hash="d" * 64,
            round_index=2,
            deficit_roles=(PlanningLiteratureRole.DIRECT_CORE,),
            role_queries=(direct, counter),
        )


def test_projection_constructor_selects_only_the_diagnosed_r2_role() -> None:
    from autoresearch.competition.contest_planning_literature_gap_repair import (
        diagnose_planning_literature_gap,
        project_planning_literature_query_repair,
    )
    from tests.unit.competition.test_contest_planning_literature_gap_repair import (
        _authority_counter_gap,
        _counter_repair,
        _evidence_inputs,
    )

    diagnosis = diagnose_planning_literature_gap(_authority_counter_gap())
    evidence = _evidence_inputs()
    projection = project_planning_literature_query_repair(
        diagnosis,
        evidence_inputs=evidence,
        repairs=(_counter_repair(evidence),),
    )

    plan = build_contest_direction_gap_repair_plan_from_projection(
        base_merged_artifact_hash="a" * 64,
        base_merged_catalog_hash="b" * 64,
        projection=projection,
    )

    assert plan.deficit_roles == (PlanningLiteratureRole.COUNTEREVIDENCE,)
    assert plan.query_count == 1
    assert plan.trigger_coverage_receipt_hash == projection.coverage_receipt_hash
    assert plan.gap_repair_projection_hash == projection.projection_hash
    query = plan.role_queries[0]
    assert query.missing_slots == 1
    assert query.parent_role_query.query_id != query.repair_role_query.query_id
    assert query.parent_role_query.must_groups[0] == query.repair_role_query.must_groups[0]
    assert query.parent_role_query.must_groups[1] != query.repair_role_query.must_groups[1]


def test_sparse_retrieval_fetches_only_deficit_roles_times_real_sources(
    tmp_path: Path,
) -> None:
    plan = _plan(
        PlanningLiteratureRole.DIRECT_CORE,
        PlanningLiteratureRole.COUNTEREVIDENCE,
    )
    calls: list[tuple[str, str, int]] = []

    def searcher(source: str):  # type: ignore[no-untyped-def]
        def search(query: str, *, limit: int) -> list[AcademicPaper]:
            calls.append((source, query, limit))
            return [
                _paper(
                    f"{source} evidence for query {len(calls)}",
                    f"10.1000/{source}-{len(calls)}",
                )
            ]

        return search

    output = tmp_path / "repair-retrieval.json"
    artifact = retrieve_contest_direction_gap_repair(
        plan=plan,
        searchers={"arxiv": searcher("arxiv"), "openalex": searcher("openalex")},
        max_results_per_search=3,
        retrieved_at=NOW,
        output_path=output,
    )

    assert len(calls) == len(plan.deficit_roles) * 2 == 4
    assert len(artifact.fetches) == 4
    assert artifact.query_count == 2
    assert artifact.source_count == 2
    assert artifact.fetch_pair_count == 4
    assert artifact.query_model_calls == 0
    assert artifact.retrieval_scope == "deficit_roles_only_sparse_source_matrix"
    assert {(item.role, item.source) for item in artifact.fetch_bindings} == {
        (PlanningLiteratureRole.DIRECT_CORE, "arxiv"),
        (PlanningLiteratureRole.DIRECT_CORE, "openalex"),
        (PlanningLiteratureRole.COUNTEREVIDENCE, "arxiv"),
        (PlanningLiteratureRole.COUNTEREVIDENCE, "openalex"),
    }
    fetches = {item.fetch_id: item for item in artifact.fetches}
    assert all(
        pointer.fetch_id in fetches
        for record in artifact.retrieved_records
        for pointer in record.retrievals
    )
    assert load_contest_direction_gap_repair(output, expected_plan=plan) == artifact


def test_failures_and_empty_results_are_retained_without_fabricated_pairs() -> None:
    plan = _plan(PlanningLiteratureRole.DIRECT_CORE)

    def failed(_query: str, *, limit: int) -> list[AcademicPaper]:  # noqa: ARG001
        raise RuntimeError("source unavailable")

    artifact = retrieve_contest_direction_gap_repair(
        plan=plan,
        searchers={
            "empty": lambda query, *, limit: [],  # noqa: ARG005
            "failed": failed,
        },
        retrieved_at=NOW,
    )

    assert len(artifact.fetches) == 2
    assert artifact.retrieved_records == ()
    assert artifact.raw_hit_count == 0
    assert artifact.repair_outcome == "no_valid_records"
    assert {item.status for item in artifact.fetches} == {"succeeded", "failed"}
    assert all(item.returned_count == 0 for item in artifact.fetches)


def test_all_queries_precompile_before_the_first_source_side_effect(monkeypatch: Any) -> None:
    plan = _plan(
        PlanningLiteratureRole.DIRECT_CORE,
        PlanningLiteratureRole.COUNTEREVIDENCE,
    )
    from autoresearch.competition import (  # local import keeps the patched boundary explicit
        contest_direction_gap_repair_retrieval as repair_module,
    )

    original = repair_module.literature_module._compile_source_query
    compiled = 0
    search_calls: list[str] = []

    def compile_or_fail(source: str, query: str, *, compiler_version: str) -> str:
        nonlocal compiled
        compiled += 1
        if compiled == 3:
            raise ValueError("late matrix cell is not compilable")
        return original(source, query, compiler_version=compiler_version)

    monkeypatch.setattr(
        repair_module.literature_module,
        "_compile_source_query",
        compile_or_fail,
    )

    with pytest.raises(ContestDirectionGapRepairError, match="before any source call"):
        retrieve_contest_direction_gap_repair(
            plan=plan,
            searchers={
                "arxiv": lambda query, *, limit: search_calls.append(query) or [],  # noqa: ARG005,E501
                "openalex": lambda query, *, limit: search_calls.append(query) or [],  # noqa: ARG005,E501
            },
            retrieved_at=NOW,
        )

    assert compiled == 3
    assert search_calls == []


def test_repair_artifact_rejects_tampered_fetch_record_and_plan_hash(
    tmp_path: Path,
) -> None:
    plan = _plan(PlanningLiteratureRole.DIRECT_CORE)
    output = tmp_path / "repair.json"
    artifact = retrieve_contest_direction_gap_repair(
        plan=plan,
        searchers={"openalex": lambda query, *, limit: [_paper("Direct evidence", "10.1000/d")]},  # noqa: ARG005,E501
        retrieved_at=NOW,
        output_path=output,
    )

    payload: dict[str, Any] = artifact.model_dump(mode="json")
    payload["fetches"][0]["returned_count"] = 9
    output.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValidationError, match="fetch|count|hash"):
        load_contest_direction_gap_repair(output, expected_plan=plan)

    payload = artifact.model_dump(mode="json")
    payload["plan"]["trigger_coverage_receipt_hash"] = "f" * 64
    output.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises((ValidationError, ContestDirectionGapRepairError), match="plan|hash"):
        load_contest_direction_gap_repair(output, expected_plan=plan)


def test_records_must_replay_from_the_frozen_raw_fetch_payload() -> None:
    plan = _plan(PlanningLiteratureRole.DIRECT_CORE)
    artifact = retrieve_contest_direction_gap_repair(
        plan=plan,
        searchers={
            "openalex": lambda query, *, limit: [  # noqa: ARG005
                _paper("Direct evidence", "10.1000/replayed")
            ]
        },
        retrieved_at=NOW,
    )
    payload = artifact.model_dump(mode="json", exclude={"artifact_hash"})
    payload["retrieved_records"] = []
    payload["deduplicated_count"] = payload["raw_hit_count"]
    payload["repair_outcome"] = "no_valid_records"
    payload["repair_catalog_hash"] = canonical_model_hash({"records": []})
    payload["artifact_hash"] = canonical_model_hash(payload)

    with pytest.raises(ValidationError, match="do not replay"):
        ContestDirectionGapRepairArtifact.model_validate(payload)


def test_role_query_rejects_role_drift() -> None:
    parent = _repair_query(PlanningLiteratureRole.DIRECT_CORE).parent_role_query
    repair = _repair_query(PlanningLiteratureRole.METHOD_FOUNDATION).repair_role_query
    with pytest.raises(ValidationError, match="role"):
        ContestDirectionGapRepairRoleQuery.create(
            role=PlanningLiteratureRole.DIRECT_CORE,
            missing_slots=1,
            parent_role_query=parent,
            repair_role_query=repair,
        )

    unchanged = parent.model_copy(update={"query_id": "r2-unchanged-direct"})
    with pytest.raises(ValidationError, match="replace its second group"):
        ContestDirectionGapRepairRoleQuery.create(
            role=PlanningLiteratureRole.DIRECT_CORE,
            missing_slots=1,
            parent_role_query=parent,
            repair_role_query=unchanged,
        )
