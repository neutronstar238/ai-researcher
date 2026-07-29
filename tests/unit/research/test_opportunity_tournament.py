from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from autoresearch.kernel.contracts import canonical_sha256
from autoresearch.research.opportunity_tournament import (
    BaselineExecutionSmoke,
    LiveResourceProbe,
    OpportunityTournamentEntry,
    OpportunityTournamentReport,
    PowerSensitivityAudit,
    ResourceKind,
    TrackFeasibilityAudit,
    blocked_baseline_smoke,
    load_opportunity_tournament,
    opportunity_tournament_json_schemas,
    probe_web_resource,
    run_baseline_command_smoke,
    write_opportunity_tournament,
)
from autoresearch.research.portfolio import (
    BaselineReproductionPlan,
    MetricDirection,
    NearestWorkDelta,
    PortfolioIntegrityError,
    PrimaryMetricSpec,
    ProspectivePowerPlan,
    PublicationEndpoint,
    ResearchBudget,
    ResearchDataSplit,
    ResearchOpportunity,
    ResearchQuestionCertificate,
    ResearchSource,
    SourceMaturity,
)

CHECKED_AT = datetime(2026, 7, 29, 10, 0, tzinfo=timezone.utc)


def _sha(label: str) -> str:
    return canonical_sha256({"label": label})


def _probe(
    resource_id: str,
    kind: ResourceKind,
    *,
    reachable: bool = True,
) -> LiveResourceProbe:
    body = f"verified:{resource_id}".encode()
    return LiveResourceProbe.create(
        resource_id=resource_id,
        kind=kind,
        requested_url=f"https://example.org/{resource_id}",
        resolved_url=f"https://example.org/{resource_id}",
        status_code=200 if reachable else 503,
        sample_bytes=len(body) if reachable else 0,
        sample_sha256=(
            canonical_sha256({"body": body.decode()})
            if reachable
            else canonical_sha256({"body": ""})
        ),
        reachable=reachable,
        checked_at=CHECKED_AT,
        error=None if reachable else "HTTP 503",
    )


def _power(
    track_id: str,
    *,
    target_power: float = 0.80,
) -> PowerSensitivityAudit:
    return PowerSensitivityAudit.create(
        track_id=track_id,
        analysis_unit="independent research task",
        independent_unit_count=12,
        alpha=0.05,
        target_power=target_power,
        minimum_detectable_effect=0.25,
        assumed_unit_sd=0.30,
        sensitivity_effects=[0.15, 0.20, 0.25, 0.30],
    )


def _entry(
    track_id: str,
    *,
    smoke_passed: bool = True,
    data_available: bool = True,
    license_clear: bool = True,
    compute_feasible: bool = True,
    target_power: float = 0.80,
    peer_reviewed_count: int = 2,
    baseline_cost_usd: float = 10.0,
    source_after_cutoff: bool = False,
) -> OpportunityTournamentEntry:
    source_probes = [
        _probe(f"{track_id}-source-{index}", ResourceKind.LITERATURE)
        for index in range(1, 4)
    ]
    sources = [
        ResearchSource(
            source_id=probe.resource_id,
            title=f"Adjacent work {index} for {track_id}",
            year=2027 if source_after_cutoff and index == 3 else 2026,
            locator=f"doi:10.0000/{track_id}.{index}",
            source_url=probe.requested_url,
            maturity=(
                SourceMaturity.PEER_REVIEWED
                if index <= peer_reviewed_count
                else SourceMaturity.PREPRINT
            ),
            source_fingerprint=probe.sample_sha256,
        )
        for index, probe in enumerate(source_probes, start=1)
    ]
    repository_probe = _probe(
        f"{track_id}-repository",
        ResourceKind.REPOSITORY,
    )
    dataset_probe = _probe(f"{track_id}-dataset", ResourceKind.DATASET)
    license_probe = _probe(f"{track_id}-license", ResourceKind.LICENSE)
    resource_probes = [repository_probe, dataset_probe, license_probe]
    environment_hash = _sha(f"{track_id}-environment")
    command = ["python", "-c", f"print('{track_id}-baseline')"]
    baseline_id = f"{track_id}-strong-baseline"
    smoke = (
        BaselineExecutionSmoke.create(
            track_id=track_id,
            baseline_id=baseline_id,
            command=command,
            environment_hash=environment_hash,
            attempted=True,
            exit_code=0,
            timed_out=False,
            passed=True,
            stdout_sha256=_sha(f"{track_id}-stdout"),
            stderr_sha256=_sha(f"{track_id}-stderr"),
            artifact_hashes=[_sha(f"{track_id}-baseline-artifact")],
            checked_at=CHECKED_AT,
            blocked_reason=None,
        )
        if smoke_passed
        else blocked_baseline_smoke(
            track_id=track_id,
            baseline_id=baseline_id,
            command=command,
            environment_hash=environment_hash,
            checked_at=CHECKED_AT,
            artifact_hashes=[_sha(f"{track_id}-baseline-artifact")],
            reason="pre-execution hard gate denied the baseline",
        )
    )
    power = _power(track_id, target_power=target_power)
    certificate = ResearchQuestionCertificate.create(
        certificate_id=f"{track_id}-certificate",
        literature_cutoff=date(2026, 7, 29),
        question=f"Does the {track_id} intervention improve the frozen metric?",
        primitives=[
            "A scientific unit is one independent task.",
            "A seed is a within-unit repeat and never a new scientific unit.",
        ],
        assumptions=["The same deterministic evaluator is used for every arm."],
        mechanism_model=(
            "The proposed mechanism changes task-level outcomes under an equal budget."
        ),
        nearest_work_tension=(
            "Adjacent systems do not isolate this intervention under the frozen split."
        ),
        main_claim=(
            f"The {track_id} policy improves confirmed task success by at least 0.25."
        ),
        falsifier=(
            "The confirmatory interval misses the threshold or any hard gate fails."
        ),
        failure_update=(
            "Retain a diagnostic negative and do not retune on the confirmatory panel."
        ),
        minimal_decisive_test=(
            "Compare paired task-level effects on a sealed independent panel."
        ),
        primary_metric=PrimaryMetricSpec(
            metric_id=f"{track_id}-confirmed-success",
            name="Confirmed task success difference",
            direction=MetricDirection.MAXIMIZE,
            unit="proportion",
            meaningful_effect_threshold=0.25,
            evaluator_description=(
                "Deterministic conjunction of execution, effect, evidence, and replay."
            ),
        ),
        strong_baseline_ids=[baseline_id],
        null_or_control_ids=[f"{track_id}-rule-null"],
        required_ablation_ids=[f"{track_id}-mechanism-ablation"],
        source_ids=[source.source_id for source in sources],
        power_plan=ProspectivePowerPlan(
            analysis_unit=power.analysis_unit,
            confirmatory_independent_unit_count=power.independent_unit_count,
            within_unit_repeat_count=3,
            target_power=power.target_power,
            alpha=power.alpha,
            minimum_detectable_effect=power.minimum_detectable_effect,
            uncertainty_method="paired task-level interval",
            bootstrap_resamples=20_000,
            heterogeneity_plan="Report every unit and a failure-aware aggregate.",
            analysis_artifact_hash=power.audit_hash,
        ),
        data_split=ResearchDataSplit(
            development_unit_ids=[
                f"{track_id}-dev-{index:02d}" for index in range(1, 5)
            ],
            confirmatory_unit_ids=[
                f"{track_id}-confirm-{index:02d}" for index in range(1, 13)
            ],
            confirmatory_access_policy=(
                "Only the independent runner may reveal each task once."
            ),
        ),
        budget=ResearchBudget(
            max_cost_usd=max(100.0, baseline_cost_usd * 4),
            max_walltime_minutes=2_000,
            max_model_tokens=500_000,
            max_trials=200,
        ),
        publication_endpoint=PublicationEndpoint.SYSTEM_CONTRIBUTION,
        endpoint_rationale="The claim concerns a causal research-policy intervention.",
    )
    baseline_plan = BaselineReproductionPlan.create(
        baseline_id=baseline_id,
        source_ids=[source.source_id for source in sources[:2]],
        expected_metric_id=certificate.primary_metric.metric_id,
        reproduction_tolerance=0.01,
        exact_command_hash=smoke.command_hash,
        environment_hash=smoke.environment_hash,
    )
    feasibility = TrackFeasibilityAudit.create(
        track_id=track_id,
        repository_probe_ids=[repository_probe.resource_id],
        dataset_probe_ids=[dataset_probe.resource_id],
        license_probe_ids=[license_probe.resource_id],
        code_license_id="Apache-2.0" if license_clear else "NOASSERTION",
        data_license_id="CC-BY-4.0",
        code_license_verified=license_clear,
        data_license_verified=True,
        data_access_verified=data_available,
        required_compute="CPU and one bounded local model endpoint",
        available_compute="CPU and one bounded local model endpoint",
        compute_feasible=compute_feasible,
        estimated_baseline_cost_usd=baseline_cost_usd,
        estimated_baseline_walltime_minutes=60,
    )
    opportunity = ResearchOpportunity.create(
        opportunity_id=track_id,
        certificate=certificate,
        sources=sources,
        nearest_work=[
            NearestWorkDelta(
                source_id=source.source_id,
                shared_scope="Automated evidence-bound research.",
                claimed_delta="Adds one frozen causal comparison.",
                overlap_risk="The orchestration primitives may partially overlap.",
                decisive_comparison="Use equal budgets and independent task units.",
            )
            for source in sources
        ],
        objective_evaluator_hash=_sha(f"{track_id}-evaluator"),
        baseline_plan=baseline_plan,
        baseline_smoke_passed=smoke.passed,
        baseline_reproduction=None,
        data_available=feasibility.data_access_verified,
        license_clear=feasibility.license_clear,
        compute_feasible=feasibility.compute_feasible,
        source_snapshot_complete=True,
    )
    return OpportunityTournamentEntry.create(
        track_id=track_id,
        opportunity=opportunity,
        source_probes=source_probes,
        resource_probes=resource_probes,
        baseline_smoke=smoke,
        power_audit=power,
        feasibility_audit=feasibility,
    )


def test_tournament_selects_only_the_conjunctive_admission() -> None:
    report = OpportunityTournamentReport.create(
        tournament_id="task2633-fixture",
        created_at=CHECKED_AT,
        entries=[
            _entry(
                "track-neural-operator",
                smoke_passed=False,
                compute_feasible=False,
            ),
            _entry("track-search-policy"),
            _entry("track-sequential-falsification", license_clear=False),
        ],
    )

    assert report.eligible_track_ids == ["track-search-policy"]
    assert report.ranked_track_ids == ["track-search-policy"]
    assert report.selected_track_id == "track-search-policy"
    assert report.novelty_search_started is False
    assert report.external_submission_authorized is False


def test_tournament_permits_every_track_to_fail() -> None:
    report = OpportunityTournamentReport.create(
        tournament_id="task2633-all-blocked",
        created_at=CHECKED_AT,
        entries=[
            _entry("track-a", smoke_passed=False),
            _entry("track-b", data_available=False),
            _entry("track-c", compute_feasible=False),
        ],
    )

    assert report.eligible_track_ids == []
    assert report.ranked_track_ids == []
    assert report.selected_track_id is None


def test_ranking_is_evidence_driven_and_not_input_order() -> None:
    entries = [
        _entry(
            "track-cheap-preprint",
            peer_reviewed_count=1,
            baseline_cost_usd=1,
        ),
        _entry(
            "track-peer-reviewed-expensive",
            peer_reviewed_count=3,
            baseline_cost_usd=20,
        ),
        _entry(
            "track-peer-reviewed-cheap",
            peer_reviewed_count=3,
            baseline_cost_usd=5,
        ),
    ]

    first = OpportunityTournamentReport.create(
        tournament_id="ranking-one",
        created_at=CHECKED_AT,
        entries=entries,
    )
    second = OpportunityTournamentReport.create(
        tournament_id="ranking-two",
        created_at=CHECKED_AT,
        entries=list(reversed(entries)),
    )

    expected = [
        "track-peer-reviewed-cheap",
        "track-peer-reviewed-expensive",
        "track-cheap-preprint",
    ]
    assert first.ranked_track_ids == expected
    assert second.ranked_track_ids == expected


def test_time_cut_violation_blocks_an_otherwise_feasible_track() -> None:
    entry = _entry("track-future-source", source_after_cutoff=True)

    assert entry.assessment.admitted is False
    assert entry.assessment.blockers == ["time_cut_respected"]


def test_insufficient_prospective_power_blocks_track() -> None:
    entry = _entry("track-underpowered", target_power=0.95)

    assert entry.power_audit.power_sufficient is False
    assert "power_target_met" in entry.assessment.blockers


def test_source_fingerprint_drift_is_rejected() -> None:
    entry = _entry("track-source-drift")
    opportunity = entry.opportunity.model_copy(deep=True)
    opportunity.sources[0].source_fingerprint = _sha("tampered-source")

    with pytest.raises(
        (ValidationError, PortfolioIntegrityError),
        match="source|opportunity_hash",
    ):
        OpportunityTournamentEntry.create(
            track_id=entry.track_id,
            opportunity=opportunity,
            source_probes=entry.source_probes,
            resource_probes=entry.resource_probes,
            baseline_smoke=entry.baseline_smoke,
            power_audit=entry.power_audit,
            feasibility_audit=entry.feasibility_audit,
        )


def test_in_memory_nested_smoke_mutation_fails_integrity() -> None:
    entry = _entry("track-smoke-drift")
    mutated = entry.model_copy(
        update={
            "baseline_smoke": entry.baseline_smoke.model_copy(
                update={"exit_code": 9}
            )
        }
    )

    with pytest.raises(
        PortfolioIntegrityError,
        match="baseline execution smoke_hash mismatch",
    ):
        mutated.verify_integrity()


def test_power_audit_round_trip_recomputes_calculation() -> None:
    power = _power("track-power")
    loaded = PowerSensitivityAudit.model_validate_json(power.model_dump_json())

    assert loaded == power
    assert loaded.achieved_power >= 0.80
    assert len(loaded.sensitivity_by_effect) == 4


class _FakeResponse:
    status_code = 206
    url = "https://resolved.example/resource"

    def iter_content(self, *, chunk_size: int) -> list[bytes]:
        assert chunk_size == 8_192
        return [b"a" * 10, b"b" * 10]

    def close(self) -> None:
        return None


class _FakeSession:
    def get(self, *_args: Any, **kwargs: Any) -> _FakeResponse:
        assert kwargs["stream"] is True
        assert kwargs["allow_redirects"] is True
        return _FakeResponse()


def test_web_probe_bounds_the_observed_prefix() -> None:
    probe = probe_web_resource(
        resource_id="bounded-source",
        kind=ResourceKind.LITERATURE,
        url="https://example.org/source",
        checked_at=CHECKED_AT,
        session=_FakeSession(),  # type: ignore[arg-type]
        max_sample_bytes=12,
    )

    assert probe.reachable is True
    assert probe.sample_bytes == 12
    assert probe.resolved_url == "https://resolved.example/resource"


def test_baseline_command_smoke_executes_without_a_shell(tmp_path: Path) -> None:
    smoke = run_baseline_command_smoke(
        track_id="track-command-smoke",
        baseline_id="baseline-command-smoke",
        command=[sys.executable, "-c", "print('verified baseline')"],
        cwd=tmp_path,
        environment_hash=_sha("command-environment"),
        checked_at=CHECKED_AT,
        artifact_hashes=[_sha("command-artifact")],
        timeout_seconds=30,
    )

    assert smoke.attempted is True
    assert smoke.passed is True
    assert smoke.exit_code == 0
    assert smoke.blocked_reason is None


def test_report_write_load_and_artifact_inventory(tmp_path: Path) -> None:
    report = OpportunityTournamentReport.create(
        tournament_id="task2633-write-load",
        created_at=CHECKED_AT,
        entries=[
            _entry("track-one"),
            _entry("track-two", smoke_passed=False),
            _entry("track-three", license_clear=False),
        ],
    )

    manifest = write_opportunity_tournament(tmp_path, report)
    loaded = load_opportunity_tournament(tmp_path / "opportunity-tournament.json")
    markdown = (tmp_path / "opportunity-tournament.md").read_text(
        encoding="utf-8"
    )
    raw_manifest = json.loads(
        (tmp_path / "artifact-manifest.json").read_text(encoding="utf-8")
    )

    assert loaded == report
    assert manifest.report_hash == report.report_hash
    assert raw_manifest["manifest_hash"] == manifest.manifest_hash
    assert "Track gate" in markdown
    assert "Novelty search started: `false`" in markdown
    table_text = markdown[: markdown.index("\n\n## ")]
    assert table_text.count("| `track-") == 3
    assert "## track-" not in table_text


def test_tournament_schema_bundle_is_deterministic() -> None:
    first = opportunity_tournament_json_schemas()
    second = opportunity_tournament_json_schemas()

    assert first == second
    assert list(first) == sorted(first)
    assert len(first) == 8
    assert canonical_sha256(first) == canonical_sha256(second)
