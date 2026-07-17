"""Result-blind preregistration for the first official MDBench Gate A matrix."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import (
    MDBenchArchiveManifest,
    MDBenchDatasetArtifact,
    MDBenchExperimentMatrix,
    MDBenchMatrixAttemptSpec,
    MDBenchMethodSpec,
    MDBenchSystemCase,
    MDBenchTemporalSplit,
)
from autoresearch.competition.planning import MDBENCH_REVISION

_CONDITIONS = ("clean", "snr_20")
_SEEDS = (11, 23, 37)
DataType = Literal["ode", "pde"]
EvaluationSplit = Literal["development", "unseen_test"]
PanelEntry = tuple[str, EvaluationSplit, str]

# This versioned diversity panel is selected from inventory metadata and equation
# families only.  No algorithm output may be read before its matrix hash is written.
_ODE_PANEL: tuple[PanelEntry, ...] = (
    ("harmonic-oscillator", "development", "linear oscillation control"),
    ("van-der-pol-oscillator", "development", "nonlinear limit cycle"),
    ("lotka-volterra-simple", "development", "coupled population interaction"),
    ("duffing-equation", "development", "forced nonlinear oscillator"),
    ("brusselator", "development", "nonlinear reaction oscillator"),
    ("sir-infection", "development", "constrained compartment dynamics"),
    ("lorenz-equations-chaotic", "unseen_test", "held-out chaotic polynomial system"),
    ("rössler-attractor-chaotic", "unseen_test", "held-out chaotic attractor"),
    ("glycolytic-oscillator", "unseen_test", "held-out higher-order biochemical dynamics"),
    (
        "autocatalytic-gene-switching",
        "unseen_test",
        "held-out nonlinear biological switching",
    ),
)
_PDE_PANEL: tuple[PanelEntry, ...] = (
    ("advection1d", "development", "first-order linear transport"),
    ("burgers", "development", "nonlinear transport plus diffusion"),
    ("kdv", "unseen_test", "held-out third-order dispersive dynamics"),
    (
        "kuramoto_sivishinky",
        "unseen_test",
        "held-out fourth-order chaotic dynamics",
    ),
)


class MDBenchPreregistrationError(RuntimeError):
    """Raised when a result-blind official matrix cannot be frozen safely."""


def preregister_mdbench_gate_a(
    archive_manifest: MDBenchArchiveManifest,
    output_path: Path | str,
) -> MDBenchExperimentMatrix:
    """Freeze the official matrix without opening any numerical NPZ payload."""

    if archive_manifest.benchmark_revision != MDBENCH_REVISION:
        raise MDBenchPreregistrationError("archive manifest revision does not match the pin")
    systems = _system_cases(archive_manifest)
    methods = _method_specs()
    split_policy = MDBenchTemporalSplit()
    attempts = _attempt_specs(systems, methods, split_policy)
    selection_policy = (
        "versioned diversity panel selected from official inventory and equation-family "
        "metadata before any method result; six ODE/two PDE development systems and "
        "four ODE/two PDE unseen-test systems"
    )
    metrics = (
        "equation_structure_f1",
        "derivative_nmse",
        "trajectory_extrapolation_nmse_ode",
        "model_complexity",
        "noise_robustness_ratio",
        "wall_time_seconds",
        "peak_rss_mb",
    )
    acceptance_criteria = (
        "all 252 matrix cells terminate as succeeded, failed, or timed_out without human scientific input",
        "all successful cells bind revision, matrix, code, data, config, result, and environment hashes",
        "each method reproduces across seeds 11, 23, and 37",
        "candidate improves unseen-test noisy median derivative NMSE by at least 5 percent versus the strongest baseline",
        "paired bootstrap 95 percent confidence lower bound for that improvement is greater than zero",
        "no post-preregistration system, condition, split, method, seed, or primary metric substitution",
    )
    upstream_divergences = (
        "pinned upstream hyperparameter validation overlaps its shortened training slice; this adapter uses chronological [0,0.64), [0.64,0.8), [0.8,1.0] splits and records indices",
        "upstream evaluator fixes NumPy and Operon seeds at 42; this adapter injects and records 11, 23, and 37",
        "bounded hyperparameter and Operon budgets replace upstream twelve-hour defaults and are disclosed per method",
    )
    payload = {
        "benchmark_revision": archive_manifest.benchmark_revision,
        "dataset_doi": archive_manifest.dataset_doi,
        "dataset_license": archive_manifest.dataset_license,
        "archive_sha256": archive_manifest.archive_sha256,
        "inventory_hash": archive_manifest.inventory_hash,
        "selection_policy": selection_policy,
        "split_policy": split_policy.model_dump(mode="json"),
        "conditions": _CONDITIONS,
        "seeds": _SEEDS,
        "systems": [case.model_dump(mode="json") for case in systems],
        "methods": [method.model_dump(mode="json") for method in methods],
        "attempts": [attempt.model_dump(mode="json") for attempt in attempts],
        "metrics": metrics,
        "acceptance_criteria": acceptance_criteria,
        "upstream_divergences": upstream_divergences,
        "created_before_results": True,
    }
    matrix_hash = canonical_model_hash(payload)
    resolved_output = Path(output_path).resolve()
    matrix = MDBenchExperimentMatrix(
        benchmark_revision=archive_manifest.benchmark_revision,
        dataset_doi=archive_manifest.dataset_doi,
        dataset_license=archive_manifest.dataset_license,
        archive_sha256=archive_manifest.archive_sha256,
        inventory_hash=archive_manifest.inventory_hash,
        selection_policy=selection_policy,
        split_policy=split_policy,
        conditions=_CONDITIONS,
        seeds=_SEEDS,
        systems=systems,
        methods=methods,
        attempts=attempts,
        metrics=metrics,
        acceptance_criteria=acceptance_criteria,
        upstream_divergences=upstream_divergences,
        created_before_results=True,
        matrix_hash=matrix_hash,
        output_path=resolved_output.as_posix(),
    )
    if resolved_output.is_file():
        existing = MDBenchExperimentMatrix.model_validate_json(
            resolved_output.read_text(encoding="utf-8")
        )
        validate_mdbench_preregistration(existing)
        if existing.matrix_hash != matrix.matrix_hash:
            raise MDBenchPreregistrationError(
                "refusing to overwrite a different preregistered matrix"
            )
        return existing
    write_json_model(resolved_output, matrix)
    return matrix


def validate_mdbench_preregistration(matrix: MDBenchExperimentMatrix) -> None:
    """Recompute the pre-result content hash and reject a tampered matrix."""

    payload = matrix.model_dump(
        mode="json",
        exclude={"schema_version", "matrix_hash", "output_path"},
    )
    computed = canonical_model_hash(payload)
    if computed != matrix.matrix_hash:
        raise MDBenchPreregistrationError(
            f"preregistered matrix hash mismatch: {computed} != {matrix.matrix_hash}"
        )


def _system_cases(
    archive_manifest: MDBenchArchiveManifest,
) -> tuple[MDBenchSystemCase, ...]:
    artifacts = {
        (artifact.data_type, artifact.system_name, artifact.condition): artifact
        for artifact in archive_manifest.artifacts
    }
    cases: list[MDBenchSystemCase] = []
    panels: tuple[tuple[DataType, tuple[PanelEntry, ...]], ...] = (
        ("ode", _ODE_PANEL),
        ("pde", _PDE_PANEL),
    )
    for data_type, panel in panels:
        for system_name, evaluation_split, reason in panel:
            selected: dict[str, MDBenchDatasetArtifact] = {}
            for condition in _CONDITIONS:
                artifact = artifacts.get((data_type, system_name, condition))
                if artifact is None:
                    raise MDBenchPreregistrationError(
                        f"official artifact missing: {data_type}/{system_name}/{condition}"
                    )
                selected[condition] = artifact
            cases.append(
                MDBenchSystemCase(
                    data_type=data_type,
                    system_name=system_name,
                    evaluation_split=evaluation_split,
                    selection_reason=reason,
                    artifact_paths={
                        condition: artifact.relative_path
                        for condition, artifact in selected.items()
                    },
                    artifact_sha256={
                        condition: artifact.sha256
                        for condition, artifact in selected.items()
                    },
                )
            )
    return tuple(cases)


def _method_specs() -> tuple[MDBenchMethodSpec, ...]:
    return (
        MDBenchMethodSpec(
            method_id="sindy_or_pdefind",
            family="sparse_linear",
            implementation="pinned MDBench SINDy for ODE and PDE-FIND for PDE",
            applicable_data_types=("ode", "pde"),
            parameters={
                "basis_functions": [["polynomial"], ["polynomial", "sin", "cos"]],
                "optimizer_threshold": [1e-5, 1e-3, 1e-1],
                "optimizer_alpha": [1e-5],
                "poly_order": [1, 2, 3],
                "pde_derivative_order": [1, 2, 3, 4],
                "validation_objective": "MDBench fitness on disjoint validation slice",
            },
            max_seconds_per_attempt=300,
            max_cpu_cores=2,
            max_memory_mb=4096,
        ),
        MDBenchMethodSpec(
            method_id="operon_gp",
            family="genetic_symbolic",
            implementation="pinned MDBench Operon wrapper with bounded explicit seed",
            applicable_data_types=("ode", "pde"),
            parameters={
                "generations": 100,
                "max_evaluations": 20_000,
                "population_size": 200,
                "pool_size": 200,
                "max_time_seconds": 75,
                "random_state": "attempt_seed",
            },
            max_seconds_per_attempt=120,
            max_cpu_cores=2,
            max_memory_mb=4096,
        ),
        MDBenchMethodSpec(
            method_id="stability_sindy",
            family="agent_candidate",
            implementation=(
                "bootstrap stability-selected SINDy/PDE-FIND with train-only "
                "Savitzky-Golay calibration"
            ),
            applicable_data_types=("ode", "pde"),
            parameters={
                "bootstrap_repetitions": 12,
                "subsample_fraction": 0.8,
                "selection_frequency": 0.7,
                "savgol_windows": [5, 9, 15],
                "savgol_polyorder": 3,
                "optimizer_threshold": [1e-5, 1e-3, 1e-1],
                "poly_order": [1, 2, 3],
                "pde_derivative_order": [1, 2, 3, 4],
                "validation_objective": "derivative NMSE then lower complexity on disjoint validation slice",
            },
            max_seconds_per_attempt=300,
            max_cpu_cores=2,
            max_memory_mb=4096,
        ),
    )


def _attempt_specs(
    systems: tuple[MDBenchSystemCase, ...],
    methods: tuple[MDBenchMethodSpec, ...],
    split_policy: MDBenchTemporalSplit,
) -> tuple[MDBenchMatrixAttemptSpec, ...]:
    attempts: list[MDBenchMatrixAttemptSpec] = []
    split_payload = split_policy.model_dump(mode="json")
    for case in systems:
        for condition in _CONDITIONS:
            for seed in _SEEDS:
                for method in methods:
                    if case.data_type not in method.applicable_data_types:
                        continue
                    config_hash = canonical_model_hash(
                        {
                            "artifact_sha256": case.artifact_sha256[condition],
                            "condition": condition,
                            "data_type": case.data_type,
                            "method": method.model_dump(mode="json"),
                            "seed": seed,
                            "split_policy": split_payload,
                            "system_name": case.system_name,
                        }
                    )
                    attempts.append(
                        MDBenchMatrixAttemptSpec(
                            attempt_id=(
                                f"{case.data_type}--{case.system_name}--{condition}--"
                                f"seed-{seed}--{method.method_id}"
                            ),
                            data_type=case.data_type,
                            system_name=case.system_name,
                            evaluation_split=case.evaluation_split,
                            condition=condition,
                            seed=seed,
                            method_id=method.method_id,
                            artifact_path=case.artifact_paths[condition],
                            artifact_sha256=case.artifact_sha256[condition],
                            config_hash=config_hash,
                        )
                    )
    return tuple(attempts)
