from __future__ import annotations

import hashlib
import io
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from autoresearch.research.opportunity_tournament import (
    LiveResourceProbe,
    ResourceKind,
)
from autoresearch.research.portfolio import (
    NearestWorkDelta,
    PortfolioIntegrityError,
    ResearchSource,
    SourceMaturity,
)
from autoresearch.research.replacement_objective_data_tournament import (
    REPLACEMENT_REPLAY_INPUT_FILENAME,
    CandidateComputeAudit,
    CandidateConstruct,
    CandidateEndpointAudit,
    CandidateLicenseAudit,
    CandidateLineageInventory,
    CandidateReplayInput,
    CandidateResourceSnapshot,
    EndpointKind,
    FrozenResourceArtifact,
    ReplacementCandidateAudit,
    ReplacementCandidateId,
    ReplacementGateVector,
    ReplacementTournamentProjection,
    ReplacementTournamentStatus,
    RightsScope,
    RightsScopeDecision,
    RightsStatus,
    StrongBaselineAvailabilityAudit,
    TaskLineageRecord,
    build_replacement_replay_payload,
    build_replacement_tournament_report,
    load_replacement_tournament,
    parse_autosdt_lineage,
    parse_core_bench_lineage,
    parse_qrdata_lineage,
    parse_scienceagentbench_lineage,
    project_replacement_tournament,
    replacement_tournament_json_schemas,
    run_replacement_tournament_replay,
    write_replacement_tournament,
)

CHECKED_AT = datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in sorted(files.items()):
            archive.writestr(name, content)
    return buffer.getvalue()


def _autosdt_bytes(*, outputs: tuple[str, str] = ("alpha", "beta")) -> bytes:
    return json.dumps(
        [
            {
                "repository_url": "https://github.com/Example/ScienceRepo",
                "source_file_url": (
                    "https://github.com/Example/ScienceRepo/blob/main/a.py"
                ),
                "license": "MIT",
                "output": outputs[0],
            },
            {
                "repository_url": (
                    "https://github.com/example/sciencerepo/tree/main"
                ),
                "source_file_url": (
                    "https://github.com/example/sciencerepo/blob/main/b.py"
                ),
                "license": "MIT",
                "output": outputs[1],
            },
        ]
    ).encode()


def _scienceagentbench_bytes(
    *, ignored_instructions: tuple[str, str] = ("secret-a", "secret-b")
) -> bytes:
    rows = [
        (
            "instance_id,github_name,src_file_or_path,eval_script_name,"
            "gold_program_name,task_inst"
        ),
        (
            "1,example/sciencerepo,src/a.py,eval_a.py,gold_a.py,"
            f"{ignored_instructions[0]}"
        ),
        (
            "2,example/sciencerepo,src/b.py,eval_b.py,gold_b.py,"
            f"{ignored_instructions[1]}"
        ),
    ]
    return ("\n".join(rows) + "\n").encode()


def _core_bytes(*, result_value: str = "secret") -> bytes:
    return json.dumps(
        [
            {
                "capsule_id": "capsule-001",
                "capsule_doi": "10.24433/CO.001",
                "results": [
                    {"answer": f"{result_value}-easy"},
                    {"answer": f"{result_value}-medium"},
                    {"answer": f"{result_value}-hard"},
                ],
            }
        ]
    ).encode()


def _qrdata_bytes(*, answers: tuple[str, str] = ("10", "20")) -> bytes:
    return json.dumps(
        [
            {
                "data_files": ["sheet.csv"],
                "meta_data": {
                    "reference": "https://example.org/source-a",
                    "question_type": "numerical",
                },
                "answer": answers[0],
                "question": "hidden question a",
            },
            {
                "data_files": ["sheet.csv"],
                "meta_data": {
                    "reference": "https://example.org/source-b",
                    "question_type": "multiple_choice",
                },
                "answer": answers[1],
                "question": "hidden question b",
            },
        ]
    ).encode()


def _candidate_input(
    candidate_id: str,
    *,
    group_count: int = 1,
    admitted: bool = False,
) -> dict[str, Any]:
    capacity_group_ids = [
        f"{candidate_id}-group-{index:03d}" for index in range(group_count)
    ]
    return {
        "candidate_id": candidate_id,
        "task_count": group_count,
        "capacity_group_ids": capacity_group_ids,
        "declared_unlineaged_group_upper_bound": 0,
        "development_group_capacity": 30 if admitted else min(group_count, 1),
        "potential_reserve_group_capacity": 84 if admitted else 0,
        "sealed_reserve_group_capacity": 84 if admitted else 0,
        "gates": {
            "revision": True,
            "lineage": True,
            "license": admitted,
            "objective_endpoint": admitted,
            "construct_coherence": True,
            "strong_baseline": admitted,
            "bounded_local_compute": admitted,
            "reserve_seal": admitted,
        },
    }


def _replay_payload(
    *,
    add_eligible_candidate: bool = False,
) -> dict[str, Any]:
    candidates = [
        _candidate_input(f"candidate-{suffix}") for suffix in ("a", "b", "c", "d")
    ]
    if add_eligible_candidate:
        candidates.append(
            _candidate_input(
                "prospective-new-candidate",
                group_count=114,
                admitted=True,
            )
        )
    return {
        "schema_version": "replacement-objective-data-replay-input-v1",
        "required_development_groups": 30,
        "required_reserve_groups": 84,
        "candidate_model_calls_run": False,
        "outcome_values_included": False,
        "heterogeneous_post_result_combination_allowed": False,
        "candidates": candidates,
    }


def _scope_decisions(
    *,
    required_group_count: int,
) -> list[RightsScopeDecision]:
    return [
        RightsScopeDecision(
            scope=scope,
            status=RightsStatus.BLOCKED,
            covered_group_count=0,
            required_group_count=required_group_count,
            license_ids=[],
            evidence_hashes=[],
            interpretation=f"{scope.value} lacks exact source-level evidence",
        )
        for scope in RightsScope
    ]


def _candidate_audit(
    candidate_id: ReplacementCandidateId,
) -> ReplacementCandidateAudit:
    candidate_slug = candidate_id.value
    artifact = FrozenResourceArtifact.create(
        artifact_id=f"{candidate_slug}-metadata",
        role="metadata",
        url=f"https://example.org/{candidate_slug}/metadata",
        revision=_sha(f"{candidate_slug}-revision")[:40],
        sha256=_sha(f"{candidate_slug}-content"),
        byte_count=10,
        outcome_bearing=False,
    )
    snapshot = CandidateResourceSnapshot.create(
        candidate_id=candidate_id,
        repository_revision=_sha(f"{candidate_slug}-repository")[:40],
        dataset_revision=_sha(f"{candidate_slug}-dataset")[:40],
        last_modified="2026-07-31T08:00:00Z",
        artifacts=[artifact],
    )
    group_id = f"{candidate_slug}-source-group"
    lineage = CandidateLineageInventory.create(
        candidate_id=candidate_id,
        task_count=1,
        declared_unlineaged_task_count=0,
        declared_unlineaged_group_upper_bound=0,
        source_revisions_pinned=True,
        task_records=[
            TaskLineageRecord(
                task_id=f"{candidate_slug}-task",
                source_group_id=group_id,
                source_locator_sha256=_sha(f"{candidate_slug}-source"),
                generator_template_sha256=_sha(f"{candidate_slug}-generator"),
                license_label="unbound",
            )
        ],
    )
    license_audit = CandidateLicenseAudit.create(
        candidate_id=candidate_id,
        required_group_count=1,
        declared_license_group_counts={"unbound": 1},
        exact_source_license_object_group_count=0,
        missing_or_unbound_group_count=1,
        scopes=_scope_decisions(required_group_count=1),
        gate_passed=False,
        blockers=["missing-source-license-evidence"],
    )
    endpoint = CandidateEndpointAudit.create(
        candidate_id=candidate_id,
        construct_kind=CandidateConstruct.SCIENTIFIC_PROGRAM_SYNTHESIS,
        endpoint_kind=EndpointKind.REFERENCE_PROGRAM_CORPUS,
        deterministic=False,
        executable=False,
        llm_or_post_result_human_primary=False,
        best_of_attempts_primary=False,
        packaged_executable_scorer=False,
        construct_coherent=True,
        gate_passed=False,
        evidence_artifact_hashes=[artifact.artifact_hash],
        interpretation="No packaged deterministic primary endpoint.",
    )
    baseline = StrongBaselineAvailabilityAudit.create(
        candidate_id=candidate_id,
        published_comparison_available=True,
        official_baseline_code_available=False,
        exact_reproduction_command_available=False,
        gate_passed=False,
        interpretation="Published numbers lack an exact official replay command.",
    )
    compute = CandidateComputeAudit.create(
        candidate_id=candidate_id,
        audited_download_bytes=10,
        audited_expanded_bytes=10,
        docker_required=False,
        privileged_container_required=False,
        gpu_tasks_present=False,
        mutable_external_service_required=True,
        bounded_local_execution=False,
        interpretation="A mutable external dependency prevents bounded replay.",
    )
    replay_input = CandidateReplayInput(
        candidate_id=candidate_slug,
        task_count=1,
        capacity_group_ids=[group_id],
        declared_unlineaged_group_upper_bound=0,
        development_group_capacity=1,
        potential_reserve_group_capacity=0,
        sealed_reserve_group_capacity=0,
        gates=ReplacementGateVector(
            revision=True,
            lineage=True,
            license=False,
            objective_endpoint=False,
            construct_coherence=True,
            strong_baseline=False,
            bounded_local_compute=False,
            reserve_seal=False,
        ),
    )
    return ReplacementCandidateAudit.create(
        candidate_id=candidate_id,
        resource_snapshot=snapshot,
        lineage=lineage,
        license_audit=license_audit,
        endpoint_audit=endpoint,
        baseline_audit=baseline,
        compute_audit=compute,
        replay_input=replay_input,
        notes=["Synthetic unit fixture; no scientific outcome was accessed."],
    )


def _probe(source_id: str) -> LiveResourceProbe:
    sample = f"{source_id}-sample".encode()
    return LiveResourceProbe.create(
        resource_id=source_id,
        kind=ResourceKind.LITERATURE,
        requested_url=f"https://example.org/{source_id}",
        resolved_url=f"https://example.org/{source_id}",
        status_code=200,
        sample_bytes=len(sample),
        sample_sha256=hashlib.sha256(sample).hexdigest(),
        reachable=True,
        checked_at=CHECKED_AT,
        error=None,
    )


def _source_material() -> tuple[
    list[ResearchSource],
    list[NearestWorkDelta],
    list[LiveResourceProbe],
]:
    probes = [_probe(f"source-{index}") for index in range(4)]
    sources = [
        ResearchSource(
            source_id=probe.resource_id,
            title=f"Primary source {index}",
            year=2026,
            locator=f"arXiv:2607.0000{index}",
            source_url=probe.requested_url,
            maturity=SourceMaturity.PREPRINT,
            source_fingerprint=probe.sample_sha256,
        )
        for index, probe in enumerate(probes)
    ]
    nearest = [
        NearestWorkDelta(
            source_id=source.source_id,
            shared_scope="automated scientific benchmark execution",
            claimed_delta="result-blind source-level admission audit",
            overlap_risk="a benchmark card can overstate independent usable units",
            decisive_comparison="task count versus licensed sealed source groups",
        )
        for source in sources
    ]
    return sources, nearest, probes


def test_parsers_collapse_pseudoreplicates_to_independent_source_groups() -> None:
    autosdt = parse_autosdt_lineage(_autosdt_bytes(), expected_task_count=2)
    scienceagentbench = parse_scienceagentbench_lineage(
        _scienceagentbench_bytes(),
        declared_publication_count=1,
        expected_task_count=2,
    )
    core = parse_core_bench_lineage(
        _core_bytes(),
        declared_total_papers=1,
        expected_train_papers=1,
    )
    qrdata = parse_qrdata_lineage(
        _qrdata_bytes(),
        _zip_bytes({"data/sheet.csv": b"x,y\n1,2\n"}),
        expected_task_count=2,
    )

    assert len(autosdt.inventory.source_group_ids) == 1
    assert len(scienceagentbench.inventory.source_group_ids) == 1
    assert len(core.inventory.source_group_ids) == 1
    assert core.inventory.task_count == 3
    assert len(qrdata.inventory.source_group_ids) == 1


def test_sensitive_outcome_mutation_cannot_change_lineage_projection() -> None:
    first_autosdt = parse_autosdt_lineage(_autosdt_bytes()).inventory
    second_autosdt = parse_autosdt_lineage(
        _autosdt_bytes(outputs=("changed-a", "changed-b"))
    ).inventory
    first_sab = parse_scienceagentbench_lineage(
        _scienceagentbench_bytes(), declared_publication_count=1
    ).inventory
    second_sab = parse_scienceagentbench_lineage(
        _scienceagentbench_bytes(
            ignored_instructions=("changed-a", "changed-b")
        ),
        declared_publication_count=1,
    ).inventory
    first_core = parse_core_bench_lineage(
        _core_bytes(result_value="first"),
        declared_total_papers=1,
    ).inventory
    second_core = parse_core_bench_lineage(
        _core_bytes(result_value="second"),
        declared_total_papers=1,
    ).inventory
    archive = _zip_bytes({"sheet.csv": b"x,y\n1,2\n"})
    first_qrdata = parse_qrdata_lineage(
        _qrdata_bytes(answers=("1", "2")),
        archive,
    ).inventory
    second_qrdata = parse_qrdata_lineage(
        _qrdata_bytes(answers=("999", "888")),
        archive,
    ).inventory

    assert first_autosdt.lineage_hash == second_autosdt.lineage_hash
    assert first_sab.lineage_hash == second_sab.lineage_hash
    assert first_core.lineage_hash == second_core.lineage_hash
    assert first_qrdata.lineage_hash == second_qrdata.lineage_hash


def test_all_candidates_may_fail_and_publication_stays_false() -> None:
    projection = project_replacement_tournament(_replay_payload())

    assert (
        projection.decision.status
        is ReplacementTournamentStatus.ALL_CANDIDATES_REJECTED
    )
    assert projection.decision.selected_candidate_id is None
    assert projection.decision.eligible_candidate_ids == []
    assert projection.decision.baseline_reproduction_authorized is False
    assert projection.decision.research_question_issued is False
    assert projection.decision.publication_claim_authorized is False
    assert projection.decision.submission_authorized is False


def test_tournament_has_no_hardcoded_winner() -> None:
    projection = project_replacement_tournament(
        _replay_payload(add_eligible_candidate=True)
    )

    assert (
        projection.decision.status
        is ReplacementTournamentStatus.CANDIDATE_QUALIFIED_FOR_BASELINE_REPRODUCTION
    )
    assert (
        projection.decision.selected_candidate_id
        == "prospective-new-candidate"
    )
    assert projection.decision.baseline_reproduction_authorized is True
    assert projection.decision.evaluator_or_critic_construction_authorized is False
    assert projection.decision.publication_claim_authorized is False


def test_duplicate_groups_and_outcome_bearing_replay_are_rejected() -> None:
    duplicate = _replay_payload()
    duplicate["candidates"][0]["capacity_group_ids"] = [
        "duplicated-group",
        "duplicated-group",
    ]
    duplicate["candidates"][0]["task_count"] = 2
    with pytest.raises(ValidationError, match="unique"):
        project_replacement_tournament(duplicate)

    contaminated = _replay_payload()
    contaminated["outcome_values_included"] = True
    with pytest.raises(ValueError, match="outcome values"):
        project_replacement_tournament(contaminated)


def test_missing_source_license_objects_fail_closed_by_use_scope() -> None:
    audit = CandidateLicenseAudit.create(
        candidate_id=ReplacementCandidateId.QRDATA,
        required_group_count=1,
        declared_license_group_counts={"global-license-only": 1},
        exact_source_license_object_group_count=0,
        missing_or_unbound_group_count=1,
        scopes=[
            RightsScopeDecision(
                scope=scope,
                status=RightsStatus.VERIFIED,
                covered_group_count=1,
                required_group_count=1,
                license_ids=["CC-BY-NC-4.0"],
                evidence_hashes=[_sha(scope.value)],
                interpretation=f"{scope.value} has only global evidence",
            )
            for scope in RightsScope
        ],
        gate_passed=False,
        blockers=["source-level-license-object-missing"],
    )

    assert {item.scope for item in audit.scopes} == set(RightsScope)
    assert audit.gate_passed is False
    assert audit.exact_source_license_object_group_count == 0


def test_frozen_runner_replays_exactly_and_projection_tamper_is_rejected(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[3]
    runner_path = (
        repository_root
        / "src"
        / "autoresearch"
        / "research"
        / "assets"
        / "frozen_replacement_objective_data_probe_v1.py"
    )
    replay_payload = _replay_payload()
    expected = project_replacement_tournament(replay_payload)
    certificate = run_replacement_tournament_replay(
        replay_payload=replay_payload,
        input_path=tmp_path / REPLACEMENT_REPLAY_INPUT_FILENAME,
        runner_path=runner_path,
        interpreters={
            "unit-runtime-a": Path(sys.executable),
            "unit-runtime-b": Path(sys.executable),
        },
        expected_projection=expected,
        observed_at=CHECKED_AT,
    )

    assert certificate.exact is True
    assert certificate.retry_count == 0
    assert len(certificate.observations) == 2
    assert {
        item.projection_sha256 for item in certificate.observations
    } == {expected.projection_sha256}

    tampered = expected.model_dump(mode="json")
    tampered["projection_sha256"] = _sha("tampered")
    with pytest.raises(
        ValidationError,
        match="tournament projection hash mismatch",
    ):
        ReplacementTournamentProjection.model_validate(tampered)


def test_report_manifest_schema_and_tamper_checks_are_deterministic(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[3]
    runner_path = (
        repository_root
        / "src"
        / "autoresearch"
        / "research"
        / "assets"
        / "frozen_replacement_objective_data_probe_v1.py"
    )
    audits = [_candidate_audit(candidate_id) for candidate_id in ReplacementCandidateId]
    replay_payload = build_replacement_replay_payload(audits)
    projection = project_replacement_tournament(replay_payload)
    certificate = run_replacement_tournament_replay(
        replay_payload=replay_payload,
        input_path=tmp_path / REPLACEMENT_REPLAY_INPUT_FILENAME,
        runner_path=runner_path,
        interpreters={
            "unit-runtime-a": Path(sys.executable),
            "unit-runtime-b": Path(sys.executable),
        },
        expected_projection=projection,
        observed_at=CHECKED_AT,
    )
    sources, nearest, probes = _source_material()
    report = build_replacement_tournament_report(
        study_id="task26366-unit",
        created_at=CHECKED_AT,
        literature_cutoff=CHECKED_AT.date(),
        research_questions=[
            "Which candidate passes all result-blind admission gates?",
            "What is the independent scientific unit for each candidate?",
            "Can the strong baseline be replayed within bounded local compute?",
        ],
        intended_reader="AutoResearch technical research lead",
        review_angle="Task scale versus licensed executable sealed source groups",
        sources=sources,
        nearest_work=nearest,
        source_probes=probes,
        candidate_audits=audits,
        replay_certificate=certificate,
    )
    manifest = write_replacement_tournament(
        report,
        tmp_path,
        runner_path=runner_path,
    )
    loaded_report, loaded_manifest = load_replacement_tournament(tmp_path)
    first_schemas = replacement_tournament_json_schemas()
    second_schemas = replacement_tournament_json_schemas()

    assert loaded_report == report
    assert loaded_manifest == manifest
    assert first_schemas == second_schemas
    assert list(first_schemas) == sorted(first_schemas)
    assert len(first_schemas) == 19

    markdown_path = tmp_path / "replacement-objective-data-tournament.md"
    markdown_path.write_text(
        markdown_path.read_text(encoding="utf-8") + "\ntampered\n",
        encoding="utf-8",
    )
    with pytest.raises(PortfolioIntegrityError, match="artifact tamper"):
        load_replacement_tournament(tmp_path)
