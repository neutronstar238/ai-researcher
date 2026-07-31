from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from autoresearch.kernel.contracts import canonical_sha256
from autoresearch.research.opportunity_tournament import (
    LiveResourceProbe,
    ResourceKind,
)
from autoresearch.research.portfolio import (
    NearestWorkDelta,
    ResearchSource,
    SourceMaturity,
)
from autoresearch.research.search_policy_study import ExactPairedPowerScenario
from autoresearch.research.workload_qualified_opportunity import (
    InterpreterRuntime,
    MechanismTrackKind,
    MechanismTrackPlan,
    ResultBlindnessAudit,
    TrackProspectivePowerPlan,
    TrackResourceAudit,
    WorkloadPhase,
    WorkloadProbeObservation,
    WorkloadProbeSpec,
    WorkloadQualificationCertificate,
    WorkloadQualifiedOpportunityEntry,
    WorkloadQualifiedOpportunityReport,
    load_workload_qualified_opportunity,
    workload_qualified_opportunity_json_schemas,
    write_workload_qualified_opportunity,
)

CHECKED_AT = datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc)
EMPTY_SHA = hashlib.sha256(b"").hexdigest()


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _runtime(role_id: str) -> InterpreterRuntime:
    return InterpreterRuntime.create(
        role_id=role_id,
        executable_locator_hash=_sha(f"{role_id}-locator"),
        executable_sha256=_sha(f"{role_id}-executable"),
        python_version="Python 3.10.20",
    )


def _observation(
    *,
    track_id: MechanismTrackKind,
    phase: WorkloadPhase,
    runtime: InterpreterRuntime,
    input_hash: str,
    runner_sha256: str,
    concurrency: int,
    repeat_index: int,
    lane_index: int,
    observed_at: datetime,
    deadline_seconds: float,
    projection_hash: str,
) -> WorkloadProbeObservation:
    return WorkloadProbeObservation.create(
        batch_id=(
            f"{track_id.value}-{phase.value}-{runtime.role_id}-"
            f"c{concurrency}-r{repeat_index}"
        ),
        track_id=track_id,
        phase=phase,
        interpreter_role_id=runtime.role_id,
        interpreter_environment_hash=runtime.environment_hash,
        input_hash=input_hash,
        runner_sha256=runner_sha256,
        command_hash=_sha(
            f"{runtime.role_id}-{track_id.value}-{concurrency}-{repeat_index}-{lane_index}"
        ),
        planned_concurrency=concurrency,
        repeat_index=repeat_index,
        lane_index=lane_index,
        algorithmic_work_units=100,
        algorithmic_elapsed_seconds=0.08,
        algorithmic_cpu_seconds=0.07,
        peak_traced_bytes=4096,
        subprocess_wall_seconds=0.1,
        batch_wall_seconds=0.12,
        orchestration_deadline_seconds=deadline_seconds,
        exit_code=0,
        timed_out=False,
        timeout_origin="none",
        telemetry_complete=True,
        output_valid=True,
        projection_hash=projection_hash,
        stdout_sha256=_sha("stdout"),
        stderr_sha256=EMPTY_SHA,
        observed_at=observed_at,
    )


def _certificate(
    track_id: MechanismTrackKind,
    *,
    unstable: bool = False,
) -> WorkloadQualificationCertificate:
    runtimes = [_runtime("clean-a"), _runtime("clean-b")]
    runner_sha256 = _sha("frozen-runner")
    input_hash = canonical_sha256(
        {
            "algorithmic_work_units": 100,
            "input_seed": 26364,
            "stratum_id": "representative-development",
            "track_id": track_id.value,
        }
    )
    projection_hash = _sha(f"{track_id.value}-projection")
    calibration = [
        _observation(
            track_id=track_id,
            phase=WorkloadPhase.CALIBRATION,
            runtime=runtime,
            input_hash=input_hash,
            runner_sha256=runner_sha256,
            concurrency=concurrency,
            repeat_index=0,
            lane_index=lane,
            observed_at=CHECKED_AT,
            deadline_seconds=30.0,
            projection_hash=projection_hash,
        )
        for runtime in runtimes
        for concurrency in (1, 2)
        for lane in range(concurrency)
    ]
    frozen_at = CHECKED_AT + timedelta(seconds=1)
    specification = WorkloadProbeSpec.create(
        track_id=track_id,
        stratum_id="representative-development",
        input_seed=26364,
        runner_sha256=runner_sha256,
        interpreter_runtimes=runtimes,
        planned_concurrency_levels=[1, 2],
        qualification_repeat_count=3,
        algorithmic_work_units=100,
        algorithmic_cpu_seconds_budget=1.0,
        calibration_observation_hashes=[
            item.observation_hash for item in calibration
        ],
        calibration_max_subprocess_wall_seconds=0.1,
        orchestration_deadline_seconds=2.0,
        minimum_timeout_slack_ratio=8.0,
        required_telemetry_fields=[
            "algorithmic_cpu_seconds",
            "algorithmic_elapsed_seconds",
            "batch_wall_seconds",
            "peak_traced_bytes",
            "subprocess_wall_seconds",
        ],
        frozen_at=frozen_at,
    )
    qualification = [
        _observation(
            track_id=track_id,
            phase=WorkloadPhase.QUALIFICATION,
            runtime=runtime,
            input_hash=input_hash,
            runner_sha256=runner_sha256,
            concurrency=concurrency,
            repeat_index=repeat_index,
            lane_index=lane,
            observed_at=frozen_at + timedelta(seconds=1),
            deadline_seconds=2.0,
            projection_hash=(
                _sha("unstable-projection")
                if unstable
                and runtime.role_id == "clean-b"
                and concurrency == 2
                and repeat_index == 2
                and lane == 1
                else projection_hash
            ),
        )
        for runtime in runtimes
        for concurrency in (1, 2)
        for repeat_index in range(3)
        for lane in range(concurrency)
    ]
    return WorkloadQualificationCertificate.create(
        specification=specification,
        calibration_observations=calibration,
        qualification_observations=qualification,
    )


def _probe(
    resource_id: str,
    kind: ResourceKind,
    *,
    reachable: bool = True,
) -> LiveResourceProbe:
    sample = f"{resource_id}-sample".encode()
    return LiveResourceProbe.create(
        resource_id=resource_id,
        kind=kind,
        requested_url=f"https://example.org/{resource_id}",
        resolved_url=f"https://example.org/{resource_id}",
        status_code=200 if reachable else 404,
        sample_bytes=len(sample) if reachable else 0,
        sample_sha256=hashlib.sha256(sample if reachable else b"").hexdigest(),
        reachable=reachable,
        checked_at=CHECKED_AT,
        error=None if reachable else "not found",
    )


def _power_plan(
    track_id: MechanismTrackKind,
    unit_count: int,
) -> TrackProspectivePowerPlan:
    probabilities = {
        0.15: (0.25, 0.10),
        0.20: (0.30, 0.10),
        0.25: (0.35, 0.10),
    }
    scenarios = [
        ExactPairedPowerScenario.create(
            independent_unit_count=max(1, unit_count),
            alpha=0.05,
            target_power=0.8,
            minimum_effect=effect,
            favorable_probability=favorable,
            unfavorable_probability=unfavorable,
        )
        for effect, (favorable, unfavorable) in probabilities.items()
    ]
    return TrackProspectivePowerPlan.create(
        track_id=track_id,
        endpoint="paired objective correctness per independent source group",
        accessible_independent_unit_count=unit_count,
        scenarios=scenarios,
    )


def _entry(
    track_id: MechanismTrackKind,
    *,
    unit_count: int,
    baseline_available: bool = True,
    evaluator_available: bool = True,
    compute_feasible: bool = True,
) -> WorkloadQualifiedOpportunityEntry:
    prefix = track_id.value
    source_probes = [
        _probe(f"{prefix}-source-{index}", ResourceKind.LITERATURE)
        for index in range(3)
    ]
    sources = [
        ResearchSource(
            source_id=probe.resource_id,
            title=f"Primary work {index}",
            year=2026,
            locator=f"doi:10.example/{prefix}.{index}",
            source_url=probe.requested_url,
            maturity=SourceMaturity.PEER_REVIEWED,
            source_fingerprint=probe.sample_sha256,
        )
        for index, probe in enumerate(source_probes)
    ]
    nearest_work = [
        NearestWorkDelta(
            source_id=source.source_id,
            shared_scope="automated scientific reasoning",
            claimed_delta="objective result-blind paired evaluation",
            overlap_risk="mechanism overlap may remove novelty",
            decisive_comparison="same-unit strong-baseline ablation",
        )
        for source in sources
    ]
    resource_probes = [
        _probe(f"{prefix}-repo", ResourceKind.REPOSITORY),
        _probe(f"{prefix}-dataset", ResourceKind.DATASET),
        _probe(f"{prefix}-license", ResourceKind.LICENSE),
    ]
    resource = TrackResourceAudit.create(
        track_id=track_id,
        strong_baseline_id=f"{prefix}-strong-baseline",
        strong_baseline_description="clean-room deterministic reference baseline",
        strong_baseline_spec_sha256=_sha(f"{prefix}-baseline-spec"),
        strong_baseline_reference_available=baseline_available,
        objective_evaluator_id=f"{prefix}-objective-evaluator",
        objective_evaluator_description="exact answer-key comparison without an LLM judge",
        objective_evaluator_sha256=_sha(f"{prefix}-evaluator"),
        objective_evaluator_specification_available=evaluator_available,
        dataset_id=f"{prefix}-dataset",
        dataset_inventory_sha256=_sha(f"{prefix}-inventory"),
        data_access_verified=True,
        accessible_independent_unit_count=unit_count,
        independence_grouping_basis=(
            "one provisional source-group folder per paired analysis unit"
        ),
        reference_code_license="Apache-2.0 reference; clean-room implementation",
        dataset_license="ODC-By-1.0",
        reference_code_license_verified=True,
        dataset_license_verified=True,
        estimated_development_cost_usd=25.0,
        estimated_development_walltime_hours=16.0,
        required_compute="two local CPU interpreters",
        available_compute="two local CPU interpreters",
        compute_feasible=compute_feasible,
        human_responsibility_boundary=(
            "humans approve data use, scientific freeze, interpretation, and release"
        ),
        excluded_resource_reasons=["unlicensed code cannot be reused"],
        repository_probe_ids=[f"{prefix}-repo"],
        dataset_probe_ids=[f"{prefix}-dataset"],
        license_probe_ids=[f"{prefix}-license"],
    )
    result_blindness = ResultBlindnessAudit.create(
        forbidden_lineage_hashes=[_sha("consumed-panel")],
        accessed_input_hashes=[
            _sha(f"{prefix}-literature"),
            _sha(f"{prefix}-resource-inventory"),
        ],
    )
    plan = MechanismTrackPlan.create(
        track_id=track_id,
        literature_cutoff=CHECKED_AT.date(),
        main_claim="The mechanism improves objective paired correctness by at least .20",
        mechanism="one frozen mechanism with deterministic evaluator feedback",
        primary_endpoint="paired objective correctness per independent source group",
        strong_baseline_comparison="same-unit comparison against the strongest open baseline",
        falsification_rule="reject when exact McNemar power or paired effect misses the freeze",
        failure_case_update="record the negative mechanism boundary in the Vault",
        required_ablations=[
            "remove mechanism while holding budget fixed",
            "replace mechanism with a rule-only control",
        ],
        sources=sources,
        nearest_work=nearest_work,
        source_probes=source_probes,
        resource_probes=resource_probes,
        resource_audit=resource,
        power_plan=_power_plan(track_id, unit_count),
        workload_certificate=_certificate(track_id),
        result_blindness_audit=result_blindness,
        result_blind_publication_endpoint=(
            "positive method, system contribution, or diagnostic negative result"
        ),
    )
    return WorkloadQualifiedOpportunityEntry.create(plan)


def _report() -> WorkloadQualifiedOpportunityReport:
    return WorkloadQualifiedOpportunityReport.create(
        tournament_id="task26364-unit",
        created_at=CHECKED_AT,
        entries=[
            _entry(
                MechanismTrackKind.STRUCTURED_WORLD_MODEL,
                unit_count=20,
                baseline_available=False,
            ),
            _entry(
                MechanismTrackKind.SOCRATIC_FALSIFICATION,
                unit_count=189,
            ),
            _entry(
                MechanismTrackKind.EXTERNAL_FEEDBACK,
                unit_count=20,
                evaluator_available=False,
                compute_feasible=False,
            ),
        ],
    )


def test_exact_power_is_source_group_level_and_requires_84_units() -> None:
    plan = _power_plan(MechanismTrackKind.SOCRATIC_FALSIFICATION, 189)
    primary = next(item for item in plan.scenarios if item.minimum_effect == 0.2)

    assert primary.required_independent_unit_count == 84
    assert plan.power_target_met is True
    assert plan.seed_or_runtime_repeats_are_independent_units is False
    assert [
        item.required_independent_unit_count for item in plan.scenarios
    ] == [129, 84, 60]


def test_workload_certificate_rejects_trajectory_instability() -> None:
    certificate = _certificate(
        MechanismTrackKind.SOCRATIC_FALSIFICATION,
        unstable=True,
    )

    assert certificate.qualified is False
    assert certificate.exact_projection_hash is None
    assert certificate.blockers == ["exact_scientific_projection_replay"]


def test_workload_observation_tamper_is_rejected() -> None:
    certificate = _certificate(MechanismTrackKind.SOCRATIC_FALSIFICATION)
    payload = certificate.qualification_observations[0].model_dump(mode="json")
    payload["projection_hash"] = _sha("tampered")

    with pytest.raises(ValidationError, match="observation_hash mismatch"):
        WorkloadProbeObservation.model_validate(payload)


def test_tournament_selects_only_the_conjunctive_track_without_science_freeze() -> None:
    report = _report()

    assert report.selected_track_id is MechanismTrackKind.SOCRATIC_FALSIFICATION
    assert report.eligible_track_ids == [
        MechanismTrackKind.SOCRATIC_FALSIFICATION
    ]
    assert report.research_question_certificate_issued is False
    assert report.confirmatory_panel_created is False
    assert report.novelty_search_started is False
    assert report.external_submission_authorized is False
    structured = next(
        item
        for item in report.entries
        if item.plan.track_id is MechanismTrackKind.STRUCTURED_WORLD_MODEL
    )
    assert structured.assessment.admitted is False
    assert "strong_baseline_reference_available" in structured.assessment.blockers
    assert "independent_unit_power_sufficient" in structured.assessment.blockers


def test_all_tracks_may_fail_without_a_hardcoded_winner() -> None:
    entries = [
        _entry(
            track,
            unit_count=20,
            baseline_available=False,
            evaluator_available=False,
            compute_feasible=False,
        )
        for track in MechanismTrackKind
    ]
    report = WorkloadQualifiedOpportunityReport.create(
        tournament_id="task26364-all-fail",
        created_at=CHECKED_AT,
        entries=entries,
    )

    assert report.selected_track_id is None
    assert report.eligible_track_ids == []
    assert report.all_tracks_may_fail is True
    assert report.hardcoded_winner_used is False


def test_report_round_trip_manifest_and_schemas_are_deterministic(
    tmp_path: Path,
) -> None:
    report = _report()
    manifest = write_workload_qualified_opportunity(tmp_path, report)
    loaded = load_workload_qualified_opportunity(
        tmp_path / "workload-qualified-opportunity.json"
    )
    markdown = (tmp_path / "workload-qualified-opportunity.md").read_text(
        encoding="utf-8"
    )
    raw_manifest: dict[str, Any] = json.loads(
        (tmp_path / "artifact-manifest.json").read_text(encoding="utf-8")
    )
    first_schemas = workload_qualified_opportunity_json_schemas()
    second_schemas = workload_qualified_opportunity_json_schemas()

    assert loaded == report
    assert manifest.report_hash == report.report_hash
    assert raw_manifest["manifest_hash"] == manifest.manifest_hash
    assert "Research Question Certificate issued: `false`" in markdown
    assert "socratic-falsification" in markdown
    assert first_schemas == second_schemas
    assert list(first_schemas) == sorted(first_schemas)
    assert len(first_schemas) == 12
    assert canonical_sha256(first_schemas) == canonical_sha256(second_schemas)
