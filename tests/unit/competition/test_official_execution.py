from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

import pytest
from pydantic import ValidationError

from autoresearch.competition import (
    MDBenchArchiveManifest,
    MDBenchAttemptState,
    MDBenchContainerEnvironment,
    MDBenchContainerOutcome,
    MDBenchDatasetArtifact,
    MDBenchExecutionError,
    MDBenchSplitIndices,
    execute_mdbench_matrix,
    load_mdbench_attempt_result,
    preregister_mdbench_gate_a,
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


def _official_inputs(
    tmp_path: Path,
) -> tuple[Path, Path, MDBenchContainerEnvironment, str]:
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
                artifacts.append(
                    MDBenchDatasetArtifact(
                        relative_path=relative_path,
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
    matrix = preregister_mdbench_gate_a(manifest, matrix_path)
    first_attempt = matrix.attempts[0]
    mounted_artifact = extracted_root / first_attempt.artifact_path
    mounted_artifact.parent.mkdir(parents=True, exist_ok=True)
    mounted_artifact.write_bytes(b"ode/harmonic-oscillator/clean")
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
    return matrix_path, manifest_path, environment, first_attempt.attempt_id


def _successful_executor(environment: MDBenchContainerEnvironment):
    def execute(invocation):
        return MDBenchContainerOutcome(
            return_code=0,
            stdout="official runner stdout",
            stderr="",
            elapsed_seconds=0.25,
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
                "selected_hyperparameters": {"optimizer_threshold": 0.001},
                "discovered_equation": "u0_t = 1.0*(u1)",
                "coefficients": [
                    {
                        "target": "u0_t",
                        "terms": [{"feature": "u1", "coefficient": 1.0}],
                    }
                ],
                "validation_nmse": 0.2,
                "derivative_nmse": 0.25,
                "trajectory_extrapolation_nmse_ode": 0.3,
                "model_complexity": 3,
                "wall_time_seconds": 0.2,
                "peak_rss_mb": 64.0,
                "failure_reason": None,
            },
        )

    return execute


def test_execution_persists_hash_bound_result_and_resumes_without_rerun(
    tmp_path: Path,
) -> None:
    matrix_path, manifest_path, environment, first_attempt_id = _official_inputs(tmp_path)
    output_dir = tmp_path / "execution"
    first = execute_mdbench_matrix(
        matrix_path,
        manifest_path,
        output_dir,
        image=environment.image,
        max_attempts=1,
        environment_probe=lambda _image: environment,
        attempt_executor=_successful_executor(environment),
    )

    assert first.terminal_attempt_count == 1
    assert first.succeeded_count == 1
    assert first.pending_count == 251
    assert first.human_intervention_count == 0
    assert first.records[0].attempt_id == first_attempt_id
    result = load_mdbench_attempt_result(first.records[0].result_path)
    assert result.status is MDBenchAttemptState.SUCCEEDED
    assert result.split_indices is not None
    assert result.split_indices.train_end == result.split_indices.validation_start
    assert result.split_indices.validation_end == result.split_indices.test_start
    assert result.result_hash == first.records[0].result_hash

    def forbidden_rerun(_invocation):
        raise AssertionError("a valid terminal result must be reused")

    resumed = execute_mdbench_matrix(
        matrix_path,
        manifest_path,
        output_dir,
        image=environment.image,
        max_attempts=1,
        attempt_ids=(first_attempt_id,),
        environment_probe=lambda _image: environment,
        attempt_executor=forbidden_rerun,
    )
    assert resumed.terminal_attempt_count == 1
    assert resumed.records[0].reused_this_invocation is True


def test_execution_rejects_tampered_terminal_result(tmp_path: Path) -> None:
    matrix_path, manifest_path, environment, _first_attempt_id = _official_inputs(tmp_path)
    output_dir = tmp_path / "execution"
    report = execute_mdbench_matrix(
        matrix_path,
        manifest_path,
        output_dir,
        image=environment.image,
        max_attempts=1,
        environment_probe=lambda _image: environment,
        attempt_executor=_successful_executor(environment),
    )
    result_path = Path(report.records[0].result_path)
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload["metrics"]["derivative_nmse"] = 0.0
    result_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(MDBenchExecutionError, match="result hash mismatch"):
        execute_mdbench_matrix(
            matrix_path,
            manifest_path,
            output_dir,
            image=environment.image,
            max_attempts=1,
            environment_probe=lambda _image: environment,
            attempt_executor=_successful_executor(environment),
        )


def test_execution_rejects_tampered_runner_spec(tmp_path: Path) -> None:
    matrix_path, manifest_path, environment, _first_attempt_id = _official_inputs(tmp_path)
    output_dir = tmp_path / "execution"
    report = execute_mdbench_matrix(
        matrix_path,
        manifest_path,
        output_dir,
        image=environment.image,
        max_attempts=1,
        environment_probe=lambda _image: environment,
        attempt_executor=_successful_executor(environment),
    )
    result = load_mdbench_attempt_result(report.records[0].result_path)
    spec_path = output_dir / "specs" / f"{result.config_hash}.json"
    payload = json.loads(spec_path.read_text(encoding="utf-8"))
    payload["execution_contract"]["test_target"] = "tampered post-hoc target"
    spec_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(MDBenchExecutionError, match="spec hash mismatch"):
        execute_mdbench_matrix(
            matrix_path,
            manifest_path,
            output_dir,
            image=environment.image,
            max_attempts=1,
            environment_probe=lambda _image: environment,
            attempt_executor=_successful_executor(environment),
        )


def test_execution_persists_infrastructure_failure_as_terminal_evidence(
    tmp_path: Path,
) -> None:
    matrix_path, manifest_path, environment, _first_attempt_id = _official_inputs(tmp_path)

    def failed_executor(_invocation):
        return MDBenchContainerOutcome(
            return_code=125,
            stdout="",
            stderr="docker failure",
            elapsed_seconds=0.1,
            failure_reason="container exited 125 without a payload",
        )

    report = execute_mdbench_matrix(
        matrix_path,
        manifest_path,
        tmp_path / "execution",
        image=environment.image,
        max_attempts=1,
        environment_probe=lambda _image: environment,
        attempt_executor=failed_executor,
    )
    assert report.failed_count == 1
    result = load_mdbench_attempt_result(report.records[0].result_path)
    assert result.status is MDBenchAttemptState.FAILED
    assert result.failure_reason == "container exited 125 without a payload"
    assert Path(result.stderr_path).read_text(encoding="utf-8") == "docker failure"


def test_concrete_split_indices_reject_overlap() -> None:
    with pytest.raises(ValidationError, match="contiguous and disjoint"):
        MDBenchSplitIndices(
            time_axis_size=150,
            train_start=0,
            train_end=96,
            validation_start=95,
            validation_end=120,
            test_start=120,
            test_end=150,
        )
