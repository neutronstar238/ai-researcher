from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import pytest
from pydantic import ValidationError

from autoresearch.competition import (
    AutonomousConfirmationPanel,
    AutonomousOriginPolicy,
    AutonomousRecoveryError,
    GateADecision,
    GateAPrimaryComparison,
    MDBenchArchiveManifest,
    MDBenchDatasetArtifact,
    MDBenchGateAReport,
    freeze_autonomous_mdbench_research_plan,
    load_autonomous_mdbench_research_plan,
    preregister_mdbench_gate_a,
    preregister_mdbench_gate_a_recovery,
)
from autoresearch.competition.autonomous_recovery import AutonomousRecoverySourceSpec
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.planning import MDBENCH_REVISION

_PARENT_ODE_SYSTEMS = (
    "harmonic-oscillator",
    "van-der-pol-oscillator",
    "lotka-volterra-simple",
    "duffing-equation",
    "brusselator",
    "sir-infection",
    "lorenz-equations-chaotic",
    "rössler-attractor-chaotic",
    "glycolytic-oscillator",
    "autocatalytic-gene-switching",
)
_PARENT_PDE_SYSTEMS = ("advection1d", "burgers", "kdv", "kuramoto_sivishinky")
_RECOVERY_ODE_SYSTEMS = (
    "harmonic-oscillator-damping",
    "lotka-volterra-competition",
    "damped-double-well-oscillator",
    "seir-infection",
    "maxwell-bloch-equations",
    "rössler-attractor-periodic",
    "chen-lee-attractor",
    "lorenz-equations-complex-periodic",
    "apoptosis-model",
    "binocular-rivalry-adaptation",
)
_RECOVERY_PDE_SYSTEMS = (
    "advection1d",
    "burgers",
    "heat_soil_uniform_1d_p1",
    "nls",
)
_UNUSED_ODE_SYSTEMS = tuple(f"fixture-untouched-ode-{index:02d}" for index in range(43))
_UNUSED_PDE_SYSTEMS = tuple(f"fixture_untouched_pde_{index:02d}" for index in range(8))


def test_plan_freezes_autonomous_origin_and_disjoint_sealed_panel(tmp_path: Path) -> None:
    inputs = _formal_negative_cycles(tmp_path)
    output_dir = tmp_path / "autonomous-plan"

    plan = freeze_autonomous_mdbench_research_plan(
        *inputs,
        output_dir,
        source_fetcher=_source_fetcher,
    )

    assert plan.model_interaction_count == 0
    assert plan.generated_candidate_count == 0
    assert plan.result_record_count == 0
    assert plan.manuscript_count == 0
    assert plan.candidate_hypotheses == ()
    assert plan.development_generation_authorized is True
    assert plan.development_execution_authorized is False
    assert plan.confirmation_access_authorized is False
    assert plan.origin_policy.fixed_candidate_catalogue_allowed is False
    assert plan.origin_policy.human_authored_candidate_code_allowed is False
    assert plan.origin_policy.model_generated_exact_code_required is True
    assert plan.origin_policy.manuscript_generated_inside_same_ledger is True
    assert plan.search_policy.minimum_mechanism_families == 3
    assert plan.search_policy.generation_count == 2
    assert len(plan.evidence_sources) == 12
    assert {source.domain for source in plan.evidence_sources} == {
        "autonomous_research",
        "equation_discovery",
    }
    assert len(plan.development_panel.systems) == 14
    assert sum(item.data_type == "ode" for item in plan.development_panel.systems) == 10
    assert sum(item.data_type == "pde" for item in plan.development_panel.systems) == 4

    confirmation = AutonomousConfirmationPanel.model_validate_json(
        Path(plan.confirmation_commitment.sealed_panel_path).read_text(encoding="utf-8")
    )
    assert confirmation.research_agent_read_allowed is False
    assert len(confirmation.systems) == 14
    assert sum(item.data_type == "ode" for item in confirmation.systems) == 10
    assert sum(item.data_type == "pde" for item in confirmation.systems) == 4
    development_keys = {
        (item.data_type, item.system_name) for item in plan.development_panel.systems
    }
    confirmation_keys = {
        (item.data_type, item.system_name) for item in confirmation.systems
    }
    prior_keys = {
        tuple(item.split("/", maxsplit=1)) for item in plan.excluded_prior_systems
    }
    assert not development_keys & confirmation_keys
    assert not (development_keys | confirmation_keys) & prior_keys
    assert {
        item.system_name
        for item in plan.development_panel.systems + confirmation.systems
        if item.data_type == "pde"
    } == set(_UNUSED_PDE_SYSTEMS)
    markdown = Path(plan.markdown_path).read_text(encoding="utf-8")
    assert all(item.system_name not in markdown for item in confirmation.systems)

    assert load_autonomous_mdbench_research_plan(plan.output_path) == plan

    def _must_not_refetch(
        _spec: AutonomousRecoverySourceSpec,
        _timeout_seconds: int,
    ) -> tuple[bytes, str, int]:
        raise AssertionError("idempotent plan load must not refetch primary sources")

    assert (
        freeze_autonomous_mdbench_research_plan(
            *inputs,
            output_dir,
            source_fetcher=_must_not_refetch,
        )
        == plan
    )


def test_plan_rejects_contract_and_snapshot_tampering(tmp_path: Path) -> None:
    inputs = _formal_negative_cycles(tmp_path)
    plan = freeze_autonomous_mdbench_research_plan(
        *inputs,
        tmp_path / "autonomous-plan",
        source_fetcher=_source_fetcher,
    )
    plan_path = Path(plan.output_path)
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    payload["development_execution_authorized"] = True
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AutonomousRecoveryError, match="cannot load autonomous recovery plan"):
        load_autonomous_mdbench_research_plan(plan_path)

    payload["development_execution_authorized"] = False
    plan_path.write_text(json.dumps(payload), encoding="utf-8")
    source_path = plan_path.parent / plan.evidence_sources[0].snapshot_relative_path
    source_path.write_text("tampered source", encoding="utf-8")

    with pytest.raises(AutonomousRecoveryError, match="source snapshot hash mismatch"):
        load_autonomous_mdbench_research_plan(plan_path)


def test_plan_rejects_result_markers_and_unverified_sources(tmp_path: Path) -> None:
    inputs = _formal_negative_cycles(tmp_path)
    output_dir = tmp_path / "autonomous-plan"
    (output_dir / "results").mkdir(parents=True)

    with pytest.raises(AutonomousRecoveryError, match="result or candidate marker"):
        freeze_autonomous_mdbench_research_plan(
            *inputs,
            output_dir,
            source_fetcher=_source_fetcher,
        )

    def _missing_marker(
        spec: AutonomousRecoverySourceSpec,
        _timeout_seconds: int,
    ) -> tuple[bytes, str, int]:
        return b"<html>wrong paper</html>", spec.url, 200

    with pytest.raises(AutonomousRecoveryError, match="marker/status failed"):
        freeze_autonomous_mdbench_research_plan(
            *inputs,
            tmp_path / "bad-sources",
            source_fetcher=_missing_marker,
        )


def test_origin_policy_rejects_hidden_human_research() -> None:
    with pytest.raises(ValidationError, match="forbids hidden human"):
        AutonomousOriginPolicy(fixed_candidate_catalogue_allowed=True)
    with pytest.raises(ValidationError, match="multiple families and generations"):
        AutonomousOriginPolicy(minimum_mechanism_families=1)


def _source_fetcher(
    spec: AutonomousRecoverySourceSpec,
    _timeout_seconds: int,
) -> tuple[bytes, str, int]:
    body = (
        f"<html><title>{spec.title}</title><body>{spec.required_marker} "
        f"{spec.source_id}</body></html>"
    ).encode()
    return body, spec.url, 200


def _formal_negative_cycles(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path, Path]:
    manifest_path = tmp_path / "official" / "archive-manifest.json"
    manifest = _write_manifest(manifest_path)
    parent_matrix_path = tmp_path / "parent" / "gate-a-preregistration.json"
    preregister_mdbench_gate_a(manifest, parent_matrix_path)
    parent_report_path = _write_negative_report(
        parent_matrix_path,
        tmp_path / "parent" / "gate-a",
        candidate_method_id="stability_sindy",
    )
    recovery_dir = tmp_path / "recovery"
    recovery_preregistration, recovery_matrix = preregister_mdbench_gate_a_recovery(
        manifest,
        parent_matrix_path,
        parent_report_path,
        recovery_dir,
    )
    recovery_report_path = _write_negative_report(
        Path(recovery_matrix.output_path),
        tmp_path / "recovery" / "gate-a",
        candidate_method_id="weak_stability_sindy",
    )
    return (
        manifest_path,
        parent_matrix_path,
        parent_report_path,
        Path(recovery_preregistration.output_path),
        Path(recovery_matrix.output_path),
        recovery_report_path,
    )


def _write_manifest(path: Path) -> MDBenchArchiveManifest:
    ode_systems = tuple(
        dict.fromkeys(_PARENT_ODE_SYSTEMS + _RECOVERY_ODE_SYSTEMS + _UNUSED_ODE_SYSTEMS)
    )
    pde_systems = tuple(
        dict.fromkeys(_PARENT_PDE_SYSTEMS + _RECOVERY_PDE_SYSTEMS + _UNUSED_PDE_SYSTEMS)
    )
    artifacts: list[MDBenchDatasetArtifact] = []
    inventories: tuple[tuple[Literal["ode", "pde"], tuple[str, ...]], ...] = (
        ("ode", ode_systems),
        ("pde", pde_systems),
    )
    for data_type, systems in inventories:
        for system_name in systems:
            for condition in ("clean", "snr_20"):
                payload = f"{data_type}/{system_name}/{condition}".encode()
                artifacts.append(
                    MDBenchDatasetArtifact(
                        relative_path=(
                            f"processed/data/{data_type}/{system_name}/"
                            f"{system_name}{'' if condition == 'clean' else '_snr_20'}.npz"
                        ),
                        data_type=data_type,
                        system_name=system_name,
                        condition=condition,
                        size_bytes=len(payload),
                        sha256=hashlib.sha256(payload).hexdigest(),
                    )
                )
    archive_sha256 = "1" * 64
    inventory_hash = canonical_model_hash(
        {
            "artifacts": [item.model_dump(mode="json") for item in artifacts],
            "archive_sha256": archive_sha256,
        }
    )
    manifest = MDBenchArchiveManifest(
        repository_url="https://github.com/gryaklab/mdbench",
        benchmark_revision=MDBENCH_REVISION,
        dataset_doi="10.5281/zenodo.17611099",
        dataset_license="mit-license",
        archive_path=(path.parent / "processed.zip").resolve().as_posix(),
        archive_size_bytes=1,
        archive_md5="0" * 32,
        archive_sha256=archive_sha256,
        extracted_root=(path.parent / "processed").resolve().as_posix(),
        artifacts=tuple(artifacts),
        ode_systems=ode_systems,
        pde_systems=pde_systems,
        noise_conditions=("snr_20",),
        inventory_hash=inventory_hash,
        output_path=path.resolve().as_posix(),
    )
    write_json_model(path, manifest)
    return manifest


def _write_negative_report(
    matrix_path: Path,
    output_dir: Path,
    *,
    candidate_method_id: str,
) -> Path:
    matrix_payload = json.loads(matrix_path.read_text(encoding="utf-8"))
    output_path = (output_dir / "gate-a-adjudication.json").resolve()
    markdown_path = (output_dir / "gate-a-report.md").resolve()
    comparison = GateAPrimaryComparison(
        candidate_method_id=candidate_method_id,
        baseline_method_id="operon_gp",
        candidate_success_count=18,
        baseline_success_count=17,
        failure_aware_system_median_relative_improvement=-0.31,
        bootstrap_ci95_lower=-0.80,
        bootstrap_ci95_upper=0.12,
        system_effects=(),
        missing_cell_policy="failed cells receive zero improvement",
    )
    unstamped = MDBenchGateAReport(
        decision=GateADecision.NEGATIVE_RESULT,
        gate_b_allowed=False,
        matrix_path=matrix_path.resolve().as_posix(),
        matrix_hash=matrix_payload["matrix_hash"],
        execution_report_path=(output_dir / "execution-report.json").resolve().as_posix(),
        execution_report_hash="3" * 64,
        execution_environment_hash="4" * 64,
        result_set_hash="5" * 64,
        adjudicator_sha256="6" * 64,
        analysis_policy_hash="7" * 64,
        truth_registry_hash="8" * 64,
        truth_source_revision=MDBENCH_REVISION,
        truth_source_files={"fixture": "9" * 64},
        total_attempt_count=252,
        succeeded_count=240,
        failed_count=12,
        timed_out_count=0,
        human_intervention_count=0,
        access_request_count=0,
        candidate_method_id=candidate_method_id,
        selected_baseline_method_id="operon_gp",
        baseline_selection_rule="frozen fixture rule",
        baseline_selection_scores=(),
        method_summaries=(),
        primary_comparison=comparison,
        checks=(),
        negative_reasons=("fixture negative result",),
        limitations=(),
        generated_at=datetime(2026, 7, 31, tzinfo=timezone.utc),
        analysis_hash="a" * 64,
        output_path=output_path.as_posix(),
        markdown_path=markdown_path.as_posix(),
    )
    report_hash = canonical_model_hash(
        unstamped.model_dump(
            mode="json",
            exclude={"report_hash", "output_path", "markdown_path"},
        )
    )
    report = unstamped.model_copy(update={"report_hash": report_hash})
    write_json_model(output_path, report)
    return output_path
