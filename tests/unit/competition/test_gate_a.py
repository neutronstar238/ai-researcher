from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import pytest

from autoresearch.competition import (
    GateAAdjudicationError,
    GateADecision,
    MDBenchArchiveManifest,
    MDBenchContainerEnvironment,
    MDBenchContainerInvocation,
    MDBenchContainerOutcome,
    MDBenchDatasetArtifact,
    adjudicate_mdbench_gate_a,
    execute_mdbench_matrix,
    load_mdbench_gate_a_report,
    preregister_mdbench_gate_a,
    score_equation_structure,
)
from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.planning import MDBENCH_REVISION

_ODE_SYSTEMS = (
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
_PDE_SYSTEMS = ("advection1d", "burgers", "kdv", "kuramoto_sivishinky")
_UNSEEN_CANDIDATE_FACTORS = {
    "lorenz-equations-chaotic": 1.4,
    "rössler-attractor-chaotic": 0.8,
    "glycolytic-oscillator": 0.2,
    "autocatalytic-gene-switching": 0.1,
    "kdv": 0.3,
    "kuramoto_sivishinky": 0.9,
}


def test_gate_a_adjudicator_retains_failures_and_is_idempotent(tmp_path: Path) -> None:
    matrix_path, manifest_path, environment = _official_inputs(tmp_path)
    execution_dir = tmp_path / "execution"
    execution = execute_mdbench_matrix(
        matrix_path,
        manifest_path,
        execution_dir,
        image=environment.image,
        environment_probe=lambda _image: environment,
        attempt_executor=_fixture_executor(environment),
    )
    assert execution.terminal_attempt_count == 252
    assert execution.failed_count == 3

    report = adjudicate_mdbench_gate_a(
        matrix_path,
        execution.output_path,
        tmp_path / "gate-a",
    )
    assert report.decision is GateADecision.NEGATIVE_RESULT
    assert report.gate_b_allowed is False
    assert report.selected_baseline_method_id == "operon_gp"
    assert report.primary_comparison.bootstrap_ci95_lower <= 0.0
    assert any(
        check.check_id == "all_methods_three_seed_reproducible" and not check.passed
        for check in report.checks
    )
    assert "negative_result" in Path(report.markdown_path).read_text(encoding="utf-8")

    resumed = adjudicate_mdbench_gate_a(
        matrix_path,
        execution.output_path,
        tmp_path / "gate-a",
    )
    assert resumed.report_hash == report.report_hash
    assert resumed.generated_at == report.generated_at
    assert load_mdbench_gate_a_report(report.output_path).analysis_hash == report.analysis_hash

    first_result = Path(execution.records[0].result_path)
    result_payload = json.loads(first_result.read_text(encoding="utf-8"))
    spec_path = execution_dir / "specs" / f"{result_payload['config_hash']}.json"
    spec_payload = json.loads(spec_path.read_text(encoding="utf-8"))
    spec_payload["execution_contract"]["test_target"] = "post-hoc tampering"
    spec_path.write_text(json.dumps(spec_payload), encoding="utf-8")
    with pytest.raises(GateAAdjudicationError, match="spec hash mismatch"):
        adjudicate_mdbench_gate_a(
            matrix_path,
            execution.output_path,
            tmp_path / "tampered-gate-a",
        )


def test_structure_scoring_expands_nested_operon_and_pde_terms() -> None:
    harmonic = score_equation_structure(
        "ode",
        "harmonic-oscillator",
        "u0_t = 0.000000001 + 2.0*u1\nu1_t = -2.1*u0",
    )
    kdv = score_equation_structure(
        "pde",
        "kdv",
        "u0_t = -1.0*u0_xxx - 6.0*((u0^1)*(u0_x))",
    )
    assert harmonic == 1.0
    assert kdv == 1.0


def _official_inputs(
    tmp_path: Path,
) -> tuple[Path, Path, MDBenchContainerEnvironment]:
    extracted_root = tmp_path / "extracted"
    artifacts: list[MDBenchDatasetArtifact] = []
    panels: tuple[tuple[Literal["ode", "pde"], tuple[str, ...]], ...] = (
        ("ode", _ODE_SYSTEMS),
        ("pde", _PDE_SYSTEMS),
    )
    for data_type, systems in panels:
        for system_name in systems:
            for condition in ("clean", "snr_20"):
                suffix = "" if condition == "clean" else "_snr_20"
                relative_path = (
                    f"processed/data/{data_type}/{system_name}/{system_name}{suffix}.npz"
                )
                payload = f"{data_type}/{system_name}/{condition}".encode()
                artifact = MDBenchDatasetArtifact(
                    relative_path=relative_path,
                    data_type=data_type,
                    system_name=system_name,
                    condition=condition,
                    size_bytes=len(payload),
                    sha256=hashlib.sha256(payload).hexdigest(),
                )
                artifacts.append(artifact)
                path = extracted_root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
    archive_sha256 = "1" * 64
    inventory_hash = canonical_model_hash(
        {
            "archive_sha256": archive_sha256,
            "artifacts": [artifact.model_dump(mode="json") for artifact in artifacts],
        }
    )
    manifest_path = tmp_path / "archive-manifest.json"
    manifest = MDBenchArchiveManifest(
        repository_url="https://github.com/gryaklab/mdbench",
        benchmark_revision=MDBENCH_REVISION,
        dataset_doi="10.5281/zenodo.17611099",
        dataset_license="mit-license",
        archive_path=(tmp_path / "processed.zip").as_posix(),
        archive_size_bytes=1,
        archive_md5="0" * 32,
        archive_sha256=archive_sha256,
        extracted_root=extracted_root.as_posix(),
        artifacts=tuple(artifacts),
        ode_systems=_ODE_SYSTEMS,
        pde_systems=_PDE_SYSTEMS,
        noise_conditions=("snr_20",),
        inventory_hash=inventory_hash,
        output_path=manifest_path.as_posix(),
    )
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    matrix_path = tmp_path / "gate-a-preregistration.json"
    preregister_mdbench_gate_a(manifest, matrix_path)
    environment = MDBenchContainerEnvironment(
        image="fixture-mdbench:latest",
        image_id=f"sha256:{'a' * 64}",
        benchmark_revision=MDBENCH_REVISION,
        runner_sha256="b" * 64,
        requirements_sha256="c" * 64,
        dockerfile_sha256="d" * 64,
        orchestrator_sha256="1" * 64,
        preregistration_sha256="2" * 64,
        contract_sha256="3" * 64,
        code_hash="e" * 64,
        environment_hash="f" * 64,
    )
    return matrix_path, manifest_path, environment


def _fixture_executor(
    environment: MDBenchContainerEnvironment,
) -> Callable[[MDBenchContainerInvocation], MDBenchContainerOutcome]:
    def execute(invocation: MDBenchContainerInvocation) -> MDBenchContainerOutcome:
        attempt = invocation.attempt
        if (
            attempt.method_id == "sindy_or_pdefind"
            and attempt.evaluation_split == "development"
            and attempt.condition == "snr_20"
            and attempt.system_name == "harmonic-oscillator"
            and attempt.seed == 11
        ) or (
            attempt.method_id == "operon_gp"
            and attempt.system_name == "rössler-attractor-chaotic"
            and attempt.condition == "snr_20"
            and attempt.seed in {11, 23}
        ):
            return MDBenchContainerOutcome(
                return_code=1,
                stdout="",
                stderr="bounded fixture failure",
                elapsed_seconds=0.01,
                payload={
                    "spec_hash": invocation.spec_hash,
                    "runner_sha256": environment.runner_sha256,
                    "status": "failed",
                    "failure_reason": "bounded fixture failure",
                },
            )
        system_offset = (_ODE_SYSTEMS + _PDE_SYSTEMS).index(attempt.system_name) * 0.001
        seed_offset = {11: 0.0, 23: 0.0001, 37: 0.0002}[attempt.seed]
        if attempt.method_id == "stability_sindy":
            base = _UNSEEN_CANDIDATE_FACTORS.get(attempt.system_name, 0.5)
        elif attempt.method_id == "operon_gp":
            base = 1.0
        else:
            base = 0.2
        derivative = base + system_offset + seed_offset
        if attempt.condition == "clean":
            derivative *= 0.2
        equation = "u0_t = -1.0*u0_x" if attempt.data_type == "pde" else "u0_t = 1.0*u0"
        return MDBenchContainerOutcome(
            return_code=0,
            stdout="fixture stdout",
            stderr="",
            elapsed_seconds=0.02,
            payload={
                "spec_hash": invocation.spec_hash,
                "runner_sha256": environment.runner_sha256,
                "status": "succeeded",
                "split_indices": {
                    "time_axis_size": 150,
                    "train_start": 0,
                    "train_end": 96,
                    "validation_start": 96,
                    "validation_end": 120,
                    "test_start": 120,
                    "test_end": 150,
                },
                "selected_hyperparameters": {"fixture": True},
                "discovered_equation": equation,
                "coefficients": [],
                "validation_nmse": derivative * 1.1,
                "derivative_nmse": derivative,
                "trajectory_extrapolation_nmse_ode": (
                    derivative * 1.2 if attempt.data_type == "ode" else None
                ),
                "model_complexity": 3,
                "wall_time_seconds": 0.01 + system_offset,
                "peak_rss_mb": 64.0 + system_offset,
                "failure_reason": None,
            },
        )

    return execute
