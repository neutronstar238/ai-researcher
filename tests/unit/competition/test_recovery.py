from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import pytest
from pydantic import ValidationError

from autoresearch.competition import (
    GateADecision,
    GateAPrimaryComparison,
    MDBenchArchiveManifest,
    MDBenchDatasetArtifact,
    MDBenchGateAReport,
    MDBenchRecoveryError,
    RecoverySource,
    preregister_mdbench_gate_a,
    preregister_mdbench_gate_a_recovery,
    validate_mdbench_recovery_preregistration,
)
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


def test_recovery_preregistration_freezes_disjoint_result_blind_matrix(
    tmp_path: Path,
) -> None:
    manifest, parent_matrix_path, parent_report_path = _parent_cycle(tmp_path)
    output_dir = tmp_path / "recovery"

    preregistration, matrix = preregister_mdbench_gate_a_recovery(
        manifest,
        parent_matrix_path,
        parent_report_path,
        output_dir,
    )

    assert matrix.conditions == ("clean", "snr_20")
    assert matrix.seeds == (13, 29, 43)
    assert len(matrix.attempts) == 252
    assert {method.method_id for method in matrix.methods} == {
        "sindy_or_pdefind",
        "operon_gp",
        "weak_stability_sindy",
    }
    assert preregistration.mechanisms == (
        "weak_form_projection",
        "bootstrap_support_stability",
    )
    assert preregistration.created_before_results is True
    assert preregistration.parent_decision is GateADecision.NEGATIVE_RESULT
    assert len(preregistration.excluded_parent_unseen_systems) == 6
    assert len(preregistration.recovery_unseen_systems) == 6
    assert {
        (reference.data_type, reference.system_name)
        for reference in preregistration.reused_development_controls
    } == {("pde", "advection1d"), ("pde", "burgers")}
    assert not (
        {
            (reference.data_type, reference.system_name)
            for reference in preregistration.excluded_parent_unseen_systems
        }
        & {
            (reference.data_type, reference.system_name)
            for reference in preregistration.recovery_unseen_systems
        }
    )
    dependency = next(
        source for source in preregistration.sources if source.reuse_policy == "dependency"
    )
    assert dependency.source_id == "pysindy-v1.7.5"
    assert dependency.license_spdx == "MIT"
    assert all(
        source.reuse_policy == "reference_only" and source.license_status == "unverified"
        for source in preregistration.sources
        if source.source_id.startswith("wsindy-")
    )
    validate_mdbench_recovery_preregistration(preregistration, matrix)

    repeated_preregistration, repeated_matrix = preregister_mdbench_gate_a_recovery(
        manifest,
        parent_matrix_path,
        parent_report_path,
        output_dir,
    )
    assert repeated_preregistration == preregistration
    assert repeated_matrix == matrix


def test_recovery_preregistration_rejects_contract_tampering(tmp_path: Path) -> None:
    manifest, parent_matrix_path, parent_report_path = _parent_cycle(tmp_path)
    output_dir = tmp_path / "recovery"
    preregistration, _matrix = preregister_mdbench_gate_a_recovery(
        manifest,
        parent_matrix_path,
        parent_report_path,
        output_dir,
    )
    preregistration_path = Path(preregistration.output_path)
    payload = json.loads(preregistration_path.read_text(encoding="utf-8"))
    payload["hypothesis"] = "post-hoc replacement"
    preregistration_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(MDBenchRecoveryError, match="hash mismatch"):
        preregister_mdbench_gate_a_recovery(
            manifest,
            parent_matrix_path,
            parent_report_path,
            output_dir,
        )


def test_recovery_preregistration_rejects_local_parent_path_tampering(
    tmp_path: Path,
) -> None:
    manifest, parent_matrix_path, parent_report_path = _parent_cycle(tmp_path)
    output_dir = tmp_path / "recovery"
    preregistration, _matrix = preregister_mdbench_gate_a_recovery(
        manifest,
        parent_matrix_path,
        parent_report_path,
        output_dir,
    )
    preregistration_path = Path(preregistration.output_path)
    payload = json.loads(preregistration_path.read_text(encoding="utf-8"))
    payload["parent_matrix_path"] = (tmp_path / "different-parent.json").as_posix()
    preregistration_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(MDBenchRecoveryError, match="parent matrix path mismatch"):
        preregister_mdbench_gate_a_recovery(
            manifest,
            parent_matrix_path,
            parent_report_path,
            output_dir,
        )


def test_recovery_preregistration_requires_negative_parent_decision(
    tmp_path: Path,
) -> None:
    manifest, parent_matrix_path, _parent_report_path = _parent_cycle(tmp_path)
    parent_report_path = _write_parent_report(
        parent_matrix_path,
        tmp_path / "passed-parent",
        decision=GateADecision.PASSED,
        gate_b_allowed=True,
    )

    with pytest.raises(MDBenchRecoveryError, match="negative Gate A decision"):
        preregister_mdbench_gate_a_recovery(
            manifest,
            parent_matrix_path,
            parent_report_path,
            tmp_path / "recovery",
        )


def test_recovery_preregistration_rejects_parent_matrix_mismatch(tmp_path: Path) -> None:
    manifest, parent_matrix_path, _parent_report_path = _parent_cycle(tmp_path)
    parent_report_path = _write_parent_report(
        parent_matrix_path,
        tmp_path / "mismatched-parent",
        matrix_hash="f" * 64,
    )

    with pytest.raises(MDBenchRecoveryError, match="matrix hash mismatch"):
        preregister_mdbench_gate_a_recovery(
            manifest,
            parent_matrix_path,
            parent_report_path,
            tmp_path / "recovery",
        )


def test_recovery_preregistration_refuses_existing_result_markers(tmp_path: Path) -> None:
    manifest, parent_matrix_path, parent_report_path = _parent_cycle(tmp_path)
    output_dir = tmp_path / "recovery"
    (output_dir / "results").mkdir(parents=True)

    with pytest.raises(MDBenchRecoveryError, match="result marker exists"):
        preregister_mdbench_gate_a_recovery(
            manifest,
            parent_matrix_path,
            parent_report_path,
            output_dir,
        )


def test_recovery_source_rejects_unlicensed_dependency() -> None:
    with pytest.raises(ValidationError, match="verified license"):
        RecoverySource(
            source_id="unsafe-dependency",
            source_type="software",
            title="Unsafe dependency",
            url="https://example.test/repository",
            revision="a" * 40,
            reuse_policy="dependency",
            license_status="unverified",
        )


def _parent_cycle(
    tmp_path: Path,
) -> tuple[MDBenchArchiveManifest, Path, Path]:
    manifest = _manifest()
    parent_matrix_path = tmp_path / "parent" / "gate-a-preregistration.json"
    parent_matrix_path.parent.mkdir(parents=True)
    preregister_mdbench_gate_a(manifest, parent_matrix_path)
    parent_report_path = _write_parent_report(
        parent_matrix_path,
        tmp_path / "parent" / "gate-a",
    )
    return manifest, parent_matrix_path, parent_report_path


def _manifest() -> MDBenchArchiveManifest:
    artifacts: list[MDBenchDatasetArtifact] = []
    panels: tuple[tuple[Literal["ode", "pde"], tuple[str, ...]], ...] = (
        ("ode", tuple(dict.fromkeys(_PARENT_ODE_SYSTEMS + _RECOVERY_ODE_SYSTEMS))),
        ("pde", tuple(dict.fromkeys(_PARENT_PDE_SYSTEMS + _RECOVERY_PDE_SYSTEMS))),
    )
    for data_type, systems in panels:
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
    return MDBenchArchiveManifest(
        repository_url="https://github.com/gryaklab/mdbench",
        benchmark_revision=MDBENCH_REVISION,
        dataset_doi="10.5281/zenodo.17611099",
        dataset_license="mit-license",
        archive_path="C:/fixture/processed.zip",
        archive_size_bytes=1,
        archive_md5="0" * 32,
        archive_sha256="1" * 64,
        extracted_root="C:/fixture/processed",
        artifacts=tuple(artifacts),
        ode_systems=tuple(dict.fromkeys(_PARENT_ODE_SYSTEMS + _RECOVERY_ODE_SYSTEMS)),
        pde_systems=tuple(dict.fromkeys(_PARENT_PDE_SYSTEMS + _RECOVERY_PDE_SYSTEMS)),
        noise_conditions=("snr_20",),
        inventory_hash="2" * 64,
        output_path="C:/fixture/archive-manifest.json",
    )


def _write_parent_report(
    matrix_path: Path,
    output_dir: Path,
    *,
    decision: GateADecision = GateADecision.NEGATIVE_RESULT,
    gate_b_allowed: bool = False,
    matrix_hash: str | None = None,
) -> Path:
    matrix_payload = json.loads(matrix_path.read_text(encoding="utf-8"))
    output_path = (output_dir / "gate-a-adjudication.json").resolve()
    markdown_path = (output_dir / "gate-a-report.md").resolve()
    comparison = GateAPrimaryComparison(
        candidate_method_id="stability_sindy",
        baseline_method_id="operon_gp",
        candidate_success_count=18,
        baseline_success_count=16,
        failure_aware_system_median_relative_improvement=0.37,
        bootstrap_ci95_lower=-0.20,
        bootstrap_ci95_upper=0.89,
        system_effects=(),
        missing_cell_policy="failed cells receive the preregistered worst-case effect",
    )
    unstamped = MDBenchGateAReport(
        decision=decision,
        gate_b_allowed=gate_b_allowed,
        matrix_path=matrix_path.resolve().as_posix(),
        matrix_hash=matrix_hash or matrix_payload["matrix_hash"],
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
        succeeded_count=244,
        failed_count=8,
        timed_out_count=0,
        human_intervention_count=0,
        access_request_count=0,
        candidate_method_id="stability_sindy",
        selected_baseline_method_id="operon_gp",
        baseline_selection_rule="frozen fixture baseline rule",
        baseline_selection_scores=(),
        method_summaries=(),
        primary_comparison=comparison,
        checks=(),
        negative_reasons=("fixture negative result",),
        limitations=(),
        generated_at=datetime(2026, 7, 17, tzinfo=timezone.utc),
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
