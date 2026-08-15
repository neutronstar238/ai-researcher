"""Tests for an immutable R1-base plus sparse-repair literature view."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from autoresearch.competition.contest_direct_skill_router import (
    ContestDirectLiteratureEvidenceContext,
    build_contest_direct_skill_routing_messages,
)
from autoresearch.competition.contest_direction_gap_repair_retrieval import (
    ContestDirectionGapRepairRoleQuery,
    build_contest_direction_gap_repair_plan,
    retrieve_contest_direction_gap_repair,
)
from autoresearch.competition.contest_direction_layered_literature import (
    ContestDirectionLayeredLiteratureError,
    build_contest_direction_layered_literature,
    load_contest_direction_layered_literature,
)
from autoresearch.competition.contest_direction_merged_literature import (
    ContestDirectionMergedLiteratureArtifact,
    ContestMergedLiteratureOrigin,
    ContestMergedLiteratureRecord,
    ContestMergedLiteratureRetrieval,
)
from autoresearch.competition.contest_planning_literature_coverage import (
    PlanningLiteratureRole,
    role_query_from_boolean,
)
from autoresearch.competition.contest_planning_literature_quality import (
    assess_planning_literature_quality,
)
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.literature.models import AcademicPaper

NOW = datetime(2026, 8, 15, 10, 0, tzinfo=timezone.utc)


def _base_record(
    *,
    stage: str,
    title: str,
    doi: str | None,
    artifact_hash: str,
    catalog_hash: str,
    suffix: str,
    repository_doi: str | None = None,
    authors: tuple[str, ...] = ("R1 Author",),
    venue: str | None = "R1 Journal",
    publication_status: str = "published",
) -> ContestMergedLiteratureRecord:
    origin = ContestMergedLiteratureOrigin(
        stage=stage,
        retrieval_artifact_hash=artifact_hash,
        retrieval_catalog_hash=catalog_hash,
        original_record_id=f"direction-paper-{suffix * 16}",
        original_record_hash=suffix * 64,
        original_paper_hash=("e" if suffix != "e" else "d") * 64,
        title=title,
        doi=doi,
        repository_doi=repository_doi,
        publication_status=publication_status,
        status_source="fixture",
        status_as_of=date(2026, 8, 15),
    )
    retrieval = ContestMergedLiteratureRetrieval(
        stage=stage,
        retrieval_artifact_hash=artifact_hash,
        fetch_id=f"direction-fetch-{suffix * 16}",
        fetch_hash=("f" if suffix != "f" else "e") * 64,
        source="openalex",
        query=f"exact executed R1 query {suffix}",
        retrieved_at=NOW,
    )
    body: dict[str, Any] = {
        "title": title,
        "authors": list(authors),
        "abstract": "Complete R1 abstract with uncertainty and limitations.",
        "publication_date": "2025-01-01",
        "venue": venue,
        "doi": doi,
        "repository_doi": repository_doi,
        "url": f"https://doi.org/{doi or repository_doi}",
        "citation_count": 5,
        "citation_count_source": "openalex",
        "citation_count_as_of": "2026-08-15",
        "publication_status": publication_status,
        "status_source": "fixture",
        "status_as_of": "2026-08-15",
        "origins": [origin.model_dump(mode="json")],
        "retrievals": [retrieval.model_dump(mode="json")],
        "source_stages": [stage],
    }
    digest = canonical_model_hash(body)
    return ContestMergedLiteratureRecord.model_validate(
        {
            **body,
            "record_id": f"merged-direction-paper-{digest[:16]}",
            "record_hash": digest,
        }
    )


def _base(
    *,
    shared_record: ContestMergedLiteratureRecord | None = None,
) -> ContestDirectionMergedLiteratureArtifact:
    targeted_hash = "2" * 64
    broad_hash = "1" * 64
    records = (
        shared_record
        or _base_record(
            stage="targeted_direction",
            title="Shared bounded effect study",
            doi="10.1000/shared",
            artifact_hash=targeted_hash,
            catalog_hash="4" * 64,
            suffix="a",
        ),
        _base_record(
            stage="broad_discovery",
            title="R1-only background study",
            doi="10.1000/base-only",
            artifact_hash=broad_hash,
            catalog_hash="3" * 64,
            suffix="b",
        ),
    )
    body: dict[str, Any] = {
        "schema_version": "contest-direction-merged-literature-v1",
        "parent_direction": "A topic-neutral scientific direction",
        "broad_literature_artifact_hash": broad_hash,
        "broad_literature_catalog_hash": "3" * 64,
        "focus_artifact_hash": "5" * 64,
        "selected_focus_id": "direction-focus-" + ("6" * 16),
        "focused_direction_cn": "检验一个可证伪、题目无关的科学关系。",
        "targeted_retrieval_binding_hash": "7" * 64,
        "targeted_literature_artifact_hash": targeted_hash,
        "targeted_literature_catalog_hash": "4" * 64,
        "records": [item.model_dump(mode="json") for item in records],
        "record_ids": [item.record_id for item in records],
        "broad_record_count": 1,
        "targeted_record_count": 1,
        "merged_record_count": 2,
        "cross_stage_deduplicated_count": 0,
        "merged_catalog_hash": canonical_model_hash(
            {"records": [item.model_dump(mode="json") for item in records]}
        ),
        "retrieval_semantics": "two_distinct_searches_not_one_retrieval",
        "selection_semantics": "unfiltered_catalog_for_program_selection",
    }
    body["artifact_hash"] = canonical_model_hash(body)
    return ContestDirectionMergedLiteratureArtifact.model_validate(body)


def _repair_query(round_index: int = 2) -> ContestDirectionGapRepairRoleQuery:
    parent = role_query_from_boolean(
        PlanningLiteratureRole.DIRECT_CORE,
        "r1-direct",
        '("aurelia systems" OR "borealis systems") AND ' '("primary effects" OR "direct outcomes")',
    )
    repair = role_query_from_boolean(
        PlanningLiteratureRole.DIRECT_CORE,
        f"r{round_index}-direct",
        '("aurelia systems" OR "borealis systems") AND '
        '("bounded effects" OR "replicated outcomes")',
    )
    return ContestDirectionGapRepairRoleQuery.create(
        role=PlanningLiteratureRole.DIRECT_CORE,
        missing_slots=1,
        parent_role_query=parent,
        repair_role_query=repair,
    )


def _paper(title: str, doi: str) -> AcademicPaper:
    return AcademicPaper(
        title=title,
        authors=["Repair Author"],
        abstract="Complete repair abstract with a real bounded comparison.",
        publication_date=date(2026, 1, 1),
        venue="Repair Journal",
        doi=doi,
        url=f"https://doi.org/{doi}",
        citation_count=2,
        citation_count_source="openalex",
        citation_count_as_of=date(2026, 8, 15),
        publication_status="published",
        status_source="fixture",
        status_as_of=date(2026, 8, 15),
        source="openalex",
    )


def _repair(
    base: ContestDirectionMergedLiteratureArtifact,
    *,
    round_index: int = 2,
    papers: tuple[AcademicPaper, ...] | None = None,
):  # type: ignore[no-untyped-def]
    query = _repair_query(round_index)
    plan = build_contest_direction_gap_repair_plan(
        base_merged_artifact_hash=base.artifact_hash,
        base_merged_catalog_hash=base.merged_catalog_hash,
        trigger_coverage_receipt_hash=str(round_index) * 64,
        gap_repair_projection_hash=("d" if round_index == 2 else "e") * 64,
        round_index=round_index,
        deficit_roles=(PlanningLiteratureRole.DIRECT_CORE,),
        role_queries=(query,),
    )
    repair_papers = papers or (
        _paper("Shared bounded effect study, expanded", "10.1000/shared"),
        _paper(f"Repair-only work round {round_index}", f"10.1000/new-{round_index}"),
    )
    return retrieve_contest_direction_gap_repair(
        plan=plan,
        searchers={
            "openalex": lambda query, *, limit: list(repair_papers)  # noqa: ARG005
        },
        retrieved_at=NOW,
    )


def test_layer_promotes_formal_publication_metadata_without_losing_repository_identity() -> None:
    repository_record = _base_record(
        stage="targeted_direction",
        title="Shared bounded effect study",
        doi=None,
        repository_doi="10.5281/zenodo.12345",
        artifact_hash="2" * 64,
        catalog_hash="4" * 64,
        suffix="a",
        authors=("Repair Author",),
        venue="Research repository",
        publication_status="preprint",
    )
    base = _base(shared_record=repository_record)
    repair = _repair(
        base,
        papers=(_paper("Shared bounded effect study", "10.1000/formal"),),
    )

    layered = build_contest_direction_layered_literature(
        base_merged=base,
        repair_artifacts=(repair,),
    )

    assert base.records[0] == repository_record
    assert layered.layered_record_count == 2
    shared = next(item for item in layered.records if len(item.origins) == 2)
    assert shared.doi == "10.1000/formal"
    assert shared.repository_doi == "10.5281/zenodo.12345"
    assert shared.venue == "Repair Journal"
    assert shared.publication_status == "published"
    assert shared.status_source == "fixture"
    assert {item.publication_status for item in shared.origins} == {"preprint", "published"}
    assert {item.doi for item in shared.origins} == {None, "10.1000/formal"}
    assert {item.repository_doi for item in shared.origins} == {
        None,
        "10.5281/zenodo.12345",
    }

    projected = next(
        item
        for item in layered.objective_retrieval_catalog()
        if item["record_id"] == shared.record_id
    )
    quality = assess_planning_literature_quality(projected)
    assert quality.publication_identity_evidence == "publication_doi"
    assert quality.required_anchor_eligible is True


def test_layer_does_not_merge_same_title_author_records_with_conflicting_publication_dois() -> None:
    base = _base(
        shared_record=_base_record(
            stage="targeted_direction",
            title="Shared bounded effect study",
            doi="10.1000/r1-publication",
            artifact_hash="2" * 64,
            catalog_hash="4" * 64,
            suffix="a",
            authors=("Repair Author",),
        )
    )
    repair = _repair(
        base,
        papers=(_paper("Shared bounded effect study", "10.1000/r2-conflicting-publication"),),
    )

    layered = build_contest_direction_layered_literature(
        base_merged=base,
        repair_artifacts=(repair,),
    )

    assert layered.layered_record_count == 3
    assert {item.doi for item in layered.records} >= {
        "10.1000/r1-publication",
        "10.1000/r2-conflicting-publication",
    }
    assert all(len(item.origins) == 1 for item in layered.records)


def test_layer_fails_closed_on_transitive_publication_doi_conflict() -> None:
    repository_record = _base_record(
        stage="targeted_direction",
        title="Shared bounded effect study",
        doi=None,
        repository_doi="10.5281/zenodo.98765",
        artifact_hash="2" * 64,
        catalog_hash="4" * 64,
        suffix="a",
        authors=("Repair Author",),
        venue="Research repository",
        publication_status="preprint",
    )
    base = _base(shared_record=repository_record)
    round_two = _repair(
        base,
        round_index=2,
        papers=(_paper("Shared bounded effect study", "10.1000/formal-a"),),
    )
    round_three = _repair(
        base,
        round_index=3,
        papers=(_paper("Shared bounded effect study", "10.1000/formal-b"),),
    )

    with pytest.raises(ContestDirectionLayeredLiteratureError, match="conflicting doi"):
        build_contest_direction_layered_literature(
            base_merged=base,
            repair_artifacts=(round_two, round_three),
        )


def test_layer_keeps_all_r1_candidates_and_exact_repair_lineage(tmp_path: Path) -> None:
    base = _base()
    repair = _repair(base)
    output = tmp_path / "layered.json"
    layered = build_contest_direction_layered_literature(
        base_merged=base,
        repair_artifacts=(repair,),
        output_path=output,
    )

    assert layered.schema_version == "contest-direction-layered-literature-v1"
    assert layered.base_merged_artifact_hash == base.artifact_hash
    assert layered.base_record_ids == base.record_ids
    assert layered.base_record_count == 2
    assert layered.repair_input_record_count == 2
    assert layered.layered_record_count == 3
    assert layered.cross_layer_deduplicated_count == 1
    assert len(layered.records) == len(layered.record_ids) == 3
    assert layered.retrieval_semantics == ("immutable_r1_base_plus_sparse_role_gap_repair_rounds")
    assert len(layered.base_to_layered_records) == len(base.records)
    assert {item.base_record_id for item in layered.base_to_layered_records} == set(base.record_ids)

    shared = next(item for item in layered.records if item.doi == "10.1000/shared")
    assert len(shared.origins) == 2
    assert len(shared.retrievals) == 2
    assert {item.retrieval_artifact_hash for item in shared.origins} == {
        base.targeted_literature_artifact_hash,
        repair.artifact_hash,
    }
    assert any(item.query == "exact executed R1 query a" for item in shared.retrievals)
    repair_fetch = repair.fetches[0]
    assert any(
        item.fetch_id == repair_fetch.fetch_id
        and item.fetch_hash == repair_fetch.fetch_hash
        and item.query == repair_fetch.query
        for item in shared.retrievals
    )
    shared_binding = next(
        item for item in layered.record_bindings if item.layered_record_id == shared.record_id
    )
    assert shared_binding.base_record_ids == (base.record_ids[0],)
    assert shared_binding.repair_records[0].round_index == 2
    assert shared_binding.repair_records[0].repair_artifact_hash == repair.artifact_hash

    projection = next(
        item
        for item in layered.objective_retrieval_catalog()
        if item["record_id"] == shared.record_id
    )
    assert projection["source_stages"] == ["targeted_direction"]
    assert {item["round_index"] for item in projection["round_query_lineage"]} == {1, 2}
    assert any(item["role"] == "direct_core" for item in projection["round_query_lineage"])
    r1_lineage = next(
        item for item in projection["round_query_lineage"] if item["round_index"] == 1
    )
    assert r1_lineage["logical_query"] is None
    assert r1_lineage["executed_query"] == "exact executed R1 query a"


def test_layer_loader_rederives_base_and_repair_inputs(tmp_path: Path) -> None:
    base = _base()
    repair = _repair(base)
    base_path = write_json_model(tmp_path / "base.json", base)
    repair_path = write_json_model(tmp_path / "repair.json", repair)
    layered_path = tmp_path / "layered.json"
    layered = build_contest_direction_layered_literature(
        base_merged=base,
        repair_artifacts=(repair,),
        output_path=layered_path,
    )

    assert (
        load_contest_direction_layered_literature(
            layered_path,
            base_merged_path=base_path,
            repair_artifact_paths=(repair_path,),
        )
        == layered
    )

    payload = json.loads(layered_path.read_text(encoding="utf-8"))
    payload["focused_direction_cn"] = "未被 R1 focus 绑定的替换方向"
    payload_without_hash = dict(payload)
    payload_without_hash.pop("artifact_hash")
    payload["artifact_hash"] = canonical_model_hash(payload_without_hash)
    layered_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ContestDirectionLayeredLiteratureError, match="rederived"):
        load_contest_direction_layered_literature(
            layered_path,
            base_merged_path=base_path,
            repair_artifact_paths=(repair_path,),
        )


def test_layer_rejects_wrong_base_binding_and_round_order() -> None:
    base = _base()
    repair = _repair(base)
    wrong_plan = repair.plan.model_copy(update={"base_merged_artifact_hash": "f" * 64})
    wrong_repair = repair.model_copy(update={"plan": wrong_plan})
    with pytest.raises(
        (ValidationError, ContestDirectionLayeredLiteratureError), match="base|plan|hash"
    ):
        build_contest_direction_layered_literature(
            base_merged=base,
            repair_artifacts=(wrong_repair,),
        )

    round_three = _repair(base, round_index=3)
    with pytest.raises(ContestDirectionLayeredLiteratureError, match="round"):
        build_contest_direction_layered_literature(
            base_merged=base,
            repair_artifacts=(round_three, repair),
        )


def test_layer_accepts_contiguous_repair_rounds_and_keeps_each_round_lineage() -> None:
    base = _base()
    round_two = _repair(base, round_index=2)
    round_three = _repair(base, round_index=3)

    layered = build_contest_direction_layered_literature(
        base_merged=base,
        repair_artifacts=(round_two, round_three),
    )

    assert tuple(item.round_index for item in layered.repair_rounds) == (2, 3)
    assert layered.repair_input_record_count == 4
    assert layered.layered_record_count == 4
    assert layered.cross_layer_deduplicated_count == 2
    shared = next(item for item in layered.records if item.doi == "10.1000/shared")
    binding = next(
        item for item in layered.record_bindings if item.layered_record_id == shared.record_id
    )
    assert {item.round_index for item in binding.round_query_lineage} == {1, 2, 3}
    assert {item.round_index for item in binding.repair_records} == {2, 3}


def test_layer_requires_a_repair_instead_of_relabelling_plain_v1() -> None:
    with pytest.raises(ContestDirectionLayeredLiteratureError, match="at least one"):
        build_contest_direction_layered_literature(
            base_merged=_base(),
            repair_artifacts=(),
        )


def test_layered_subset_projects_exact_round_query_and_origin_provenance() -> None:
    base = _base()
    repair = _repair(base)
    layered = build_contest_direction_layered_literature(
        base_merged=base,
        repair_artifacts=(repair,),
    )
    shared = next(item for item in layered.records if item.doi == "10.1000/shared")

    evidence = ContestDirectLiteratureEvidenceContext.from_two_stage_artifact(
        layered,
        record_ids=(shared.record_id,),
    )

    assert evidence.evidence_source_kind == "two_stage_with_bounded_gap_repair"
    assert evidence.merged_literature_artifact_hash == layered.artifact_hash
    assert evidence.merged_literature_catalog_hash == layered.merged_catalog_hash
    assert evidence.records[0].record_sha256 == shared.record_hash
    assert len(evidence.records[0].provenance) == len(shared.retrievals)
    assert {item.round_index for item in evidence.records[0].provenance} == {1, 2}
    base_provenance = next(item for item in evidence.records[0].provenance if item.round_index == 1)
    repair_provenance = next(
        item for item in evidence.records[0].provenance if item.round_index == 2
    )
    assert base_provenance.retrieval_kind == "base_targeted"
    assert base_provenance.logical_query is None
    assert base_provenance.original_record_id == base.records[0].origins[0].original_record_id
    assert repair_provenance.retrieval_kind == "gap_repair"
    assert repair_provenance.role == "direct_core"
    assert repair_provenance.query_id == repair.plan.role_queries[0].repair_role_query.query_id
    assert repair_provenance.query_hash == repair.plan.role_queries[0].query_hash
    assert (
        repair_provenance.logical_query == repair.plan.role_queries[0].repair_role_query.raw_query
    )
    assert repair_provenance.original_record_id == repair.retrieved_records[0].record_id

    messages = build_contest_direct_skill_routing_messages(
        question=layered.focused_direction_cn,
        requirements=("形成可执行研究计划。",),
        skill_catalog=(
            {
                "skill_id": "generic-method",
                "name": "通用方法",
                "description": "选择可证伪方法。",
                "content_sha256": "a" * 64,
            },
        ),
        literature_evidence_context=evidence,
    )
    payload = json.loads(messages[2]["content"])
    assert payload["context_kind"] == (
        "program_selected_two_stage_gap_repaired_real_literature_evidence"
    )
    assert payload["records"][0]["abstract"] == shared.abstract
    assert {item["round_index"] for item in payload["records"][0]["provenance"]} == {1, 2}


def test_layered_projection_cannot_bypass_the_whole_record_budget() -> None:
    base = _base()
    layered = build_contest_direction_layered_literature(
        base_merged=base,
        repair_artifacts=(_repair(base),),
    )
    record_id = layered.record_ids[0]
    evidence = ContestDirectLiteratureEvidenceContext.from_two_stage_artifact(
        layered,
        record_ids=(record_id,),
    )
    payload = evidence.model_dump(mode="json")
    payload["records"][0]["abstract"] = "完整记录" * 5_000
    payload["subset_hash"] = canonical_model_hash({"records": payload["records"]})

    with pytest.raises(ValidationError, match="14 KiB UTF-8 routing budget"):
        ContestDirectLiteratureEvidenceContext.model_validate(payload)


def test_plain_merged_projection_keeps_the_frozen_provenance_shape() -> None:
    base = _base()
    evidence = ContestDirectLiteratureEvidenceContext.from_two_stage_artifact(
        base,
        record_ids=(base.record_ids[0],),
    )

    assert evidence.evidence_source_kind == "two_stage_merged"
    provenance = evidence.records[0].provenance[0].model_dump(mode="json")
    assert provenance == {
        "source": "openalex",
        "query": "exact executed R1 query a",
        "retrieved_at": NOW.isoformat(),
        "retrieval_stage": "targeted_direction",
        "retrieval_artifact_hash": base.targeted_literature_artifact_hash,
        "original_record_id": base.records[0].origins[0].original_record_id,
        "original_record_hash": base.records[0].origins[0].original_record_hash,
        "fetch_id": base.records[0].retrievals[0].fetch_id,
        "fetch_hash": base.records[0].retrievals[0].fetch_hash,
    }
