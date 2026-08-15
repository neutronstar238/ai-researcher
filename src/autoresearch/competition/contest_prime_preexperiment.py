"""Real, bounded prime-gap preexperiment for the first Science 125 question.

The runner executes a frozen exploratory protocol on five disjoint integer
intervals.  It generates primes with a segmented sieve, computes tie-aware
ordinal statistics on the observed prime-gap sequence, and compares them with
three seeded null models:

* local block permutations preserve each block's exact gap multiset and local
  non-stationarity while destroying order inside blocks;
* global permutations preserve the interval-wide gap multiset;
* residue-path-conditioned permutations shuffle only within groups sharing a
  local segment and consecutive-prime residues modulo 30 (primary null);
* wheel-210 pseudo-primes preserve endpoints, local counts, and divisibility
  exclusions for 2, 3, 5, and 7, but not deeper prime structure.

This is deliberately an exploratory pilot, not a proof about primes and not the
confirmatory execution described by the earlier broad plan.  The protocol is
frozen and persisted before data generation.  Every raw/result file is bound by
SHA-256, but the evidence is not externally signed; hashes are tamper-evident,
not an unforgeable claim about who ran the program.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import platform
import shutil
import sys
import time
import traceback
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, TypeAlias

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from pydantic import Field, model_validator

from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import StrictFrozenModel

_ARTIFACT_NAME = "prime-preexperiment.json"
_MANIFEST_NAME = "manifest.json"
_METRICS_NAME = "metrics.json"
_PARAMETERS_NAME = "parameters.json"
_ENVIRONMENT_NAME = "environment.json"
_STDOUT_NAME = "logs/stdout.log"
_STDERR_NAME = "logs/stderr.log"

_DEFAULT_INTERVALS = (
    (1_000_000, 2_000_000),
    (5_000_000, 6_000_000),
    (10_000_000, 11_000_000),
    (20_000_000, 21_000_000),
    (50_000_000, 51_000_000),
)
NullModel: TypeAlias = Literal[
    "local_block_permutation",
    "global_permutation",
    "residue_path_conditioned_permutation",
    "wheel_210",
]
FileKind: TypeAlias = Literal[
    "parameters",
    "environment",
    "source_code",
    "source_plan_snapshot",
    "raw_prime_gaps",
    "null_draws",
    "metrics",
    "stdout_log",
    "stderr_log",
    "failure",
]
_NULL_MODELS: tuple[NullModel, ...] = (
    "local_block_permutation",
    "global_permutation",
    "residue_path_conditioned_permutation",
    "wheel_210",
)
_REFERENCES = (
    "Bandt C, Pompe B. Permutation Entropy: A Natural Complexity Measure for "
    "Time Series. Physical Review Letters (2002). "
    "https://doi.org/10.1103/PhysRevLett.88.174102",
    "Gallagher PX. On the distribution of primes in short intervals. "
    "Mathematika (1976). https://doi.org/10.1112/S0025579300016442",
    "Granville A. Harald Cramér and the distribution of prime numbers. "
    "Scandinavian Actuarial Journal (1995). "
    "https://doi.org/10.1080/03461238.1995.10413946",
    "Bian C, Qin C, Ma QDY, Shen Q. Modified permutation-entropy analysis of "
    "heartbeat dynamics. Physical Review E (2012). "
    "https://doi.org/10.1103/PhysRevE.85.021906",
    "Lemke Oliver RJ, Soundararajan K. Unexpected biases in the distribution of "
    "consecutive primes. PNAS (2016). https://doi.org/10.1073/pnas.1605366113",
    "Banks W, Ford K, Tao T. Large prime gaps and probabilistic models. "
    "Inventiones Mathematicae (2023). https://doi.org/10.1007/s00222-023-01199-0; "
    "preprint: https://arxiv.org/abs/1908.08613",
    "Phipson B, Smyth GK. Permutation P-values Should Never Be Zero: Calculating "
    "Exact P-values When Permutations Are Randomly Drawn. Statistical Applications "
    "in Genetics and Molecular Biology (2010). "
    "https://doi.org/10.2202/1544-6115.1585",
)


class ContestPrimePreexperimentError(RuntimeError):
    """Raised after a failed execution has persisted its available evidence."""

    def __init__(
        self,
        message: str,
        *,
        failure_path: Path | None = None,
        manifest_path: Path | None = None,
    ) -> None:
        super().__init__(message)
        self.failure_path = failure_path
        self.manifest_path = manifest_path


class PrimeIntervalSpec(StrictFrozenModel):
    """One half-open, independently analyzed integer interval."""

    start: int = Field(ge=11)
    stop: int = Field(gt=11)

    @model_validator(mode="after")
    def _validate_bounds(self) -> PrimeIntervalSpec:
        if self.stop <= self.start:
            raise ValueError("prime interval stop must be greater than start")
        return self


def _default_interval_specs() -> tuple[PrimeIntervalSpec, ...]:
    return tuple(PrimeIntervalSpec(start=start, stop=stop) for start, stop in _DEFAULT_INTERVALS)


class ContestPrimePreexperimentParameters(StrictFrozenModel):
    """Frozen protocol parameters; defaults are the actual delivery pilot."""

    schema_version: Literal["contest-prime-preexperiment-parameters-v1"] = (
        "contest-prime-preexperiment-parameters-v1"
    )
    intervals: tuple[PrimeIntervalSpec, ...] = Field(
        default_factory=_default_interval_specs,
        min_length=5,
        max_length=5,
    )
    seed: int = 20_260_811
    null_draws: int = Field(default=199, ge=199)
    ordinal_dimension: Literal[5] = 5
    ordinal_delay: Literal[1] = 1
    local_block_size: int = Field(default=256, ge=8)
    residue_path_segment_size: int = Field(default=4_096, ge=256)
    minimum_residue_variable_fraction: float = Field(default=0.8, ge=0.8, le=0.8)
    wheel_modulus: Literal[210] = 210
    wheel_density_segment_width: int = Field(default=100_000, ge=10_000)
    fixed_interval_resampling_draws: int = Field(default=5_000, ge=1_000)
    alpha: float = Field(default=0.05, gt=0.0, lt=1.0)

    @model_validator(mode="after")
    def _validate_disjoint_intervals(self) -> ContestPrimePreexperimentParameters:
        ordered = sorted(self.intervals, key=lambda interval: interval.start)
        for left, right in zip(ordered, ordered[1:], strict=False):
            if left.stop > right.start:
                raise ValueError("prime preexperiment intervals must not overlap")
        return self


class PrimePreexperimentFileEvidence(StrictFrozenModel):
    """Hash binding for one file inside the output directory."""

    relative_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(ge=0)
    kind: FileKind


class PrimeSequenceMetrics(StrictFrozenModel):
    """Metrics calculated directly from one ordered gap sequence."""

    tie_aware_normalized_permutation_entropy_m5: float = Field(ge=0.0, le=1.0)
    quartile_symbol_block_entropy_order2: float = Field(ge=0.0, le=1.0)
    quartile_symbol_lag1_mutual_information: float = Field(ge=0.0)


class PrimeNullSummary(StrictFrozenModel):
    """Observed-versus-null comparison for one interval and one null family."""

    null_model: NullModel
    draw_count: int = Field(ge=199)
    rng_seed: int = Field(ge=0)
    observed_entropy: float = Field(ge=0.0, le=1.0)
    null_mean_entropy: float = Field(ge=0.0, le=1.0)
    null_sd_entropy: float = Field(ge=0.0)
    null_ci95: tuple[float, float]
    delta_observed_minus_null: float
    standardized_effect: float | None
    one_sided_empirical_p_lower: float = Field(gt=0.0, le=1.0)
    holm_adjusted_p_across_intervals: float = Field(gt=0.0, le=1.0)
    residue_conditioned_variable_position_fraction: float | None = Field(
        default=None, ge=0.0, le=1.0
    )


class PrimeIntervalResult(StrictFrozenModel):
    """Observed data and null comparisons for one disjoint interval."""

    interval_index: int = Field(ge=1, le=5)
    start: int
    stop: int
    prime_count: int = Field(ge=2)
    gap_count: int = Field(ge=1)
    mean_gap: float = Field(gt=0.0)
    observed_metrics: PrimeSequenceMetrics
    raw_relative_path: str
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    null_draws_relative_path: str
    null_draws_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    residue_conditioned_variable_position_fraction: float = Field(ge=0.8, le=1.0)
    null_summaries: tuple[PrimeNullSummary, ...] = Field(min_length=4, max_length=4)


class PrimeAggregateNullResult(StrictFrozenModel):
    """Cross-interval descriptive aggregate for one null family."""

    null_model: NullModel
    interval_count: Literal[5] = 5
    draw_count: int = Field(ge=199)
    observed_mean_entropy: float = Field(ge=0.0, le=1.0)
    null_mean_entropy: float = Field(ge=0.0, le=1.0)
    delta_observed_minus_null: float
    standardized_effect: float | None
    one_sided_empirical_p_lower: float = Field(gt=0.0, le=1.0)
    holm_adjusted_p_across_null_models: float = Field(gt=0.0, le=1.0)
    fixed_interval_resampling_delta_ci95: tuple[float, float]
    inference_scope: Literal[
        "descriptive_n5_fixed_benchmark_interval_resampling_not_population_ci"
    ] = "descriptive_n5_fixed_benchmark_interval_resampling_not_population_ci"


class PrimePreexperimentManifest(StrictFrozenModel):
    """Tamper-evident file inventory; no external execution signature is claimed."""

    schema_version: Literal["contest-prime-preexperiment-manifest-v1"] = (
        "contest-prime-preexperiment-manifest-v1"
    )
    run_id: str = Field(pattern=r"^prime-pilot-[0-9a-f]{16}$")
    program_status: Literal["completed", "failed"]
    integrity_scope: Literal["sha256_tamper_evident_not_externally_signed"] = (
        "sha256_tamper_evident_not_externally_signed"
    )
    files: tuple[PrimePreexperimentFileEvidence, ...]
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_hash_and_paths(self) -> PrimePreexperimentManifest:
        paths = tuple(file.relative_path for file in self.files)
        if len(paths) != len(set(paths)):
            raise ValueError("preexperiment manifest contains duplicate paths")
        expected = canonical_model_hash(self.model_dump(mode="json", exclude={"manifest_hash"}))
        if self.manifest_hash != expected:
            raise ValueError("preexperiment manifest hash mismatch")
        return self


class ContestPrimePreexperimentArtifact(StrictFrozenModel):
    """Successful, program-computed result of the bounded pilot."""

    schema_version: Literal["contest-prime-preexperiment-artifact-v1"] = (
        "contest-prime-preexperiment-artifact-v1"
    )
    run_id: str = Field(pattern=r"^prime-pilot-[0-9a-f]{16}$")
    status: Literal["completed"] = "completed"
    study_phase: Literal["exploratory_pilot"] = "exploratory_pilot"
    protocol_status: Literal["protocol_amended_before_execution"] = (
        "protocol_amended_before_execution"
    )
    protocol_amendment_reason_zh: str
    protocol_frozen_before_data_generation: Literal[True] = True
    scientific_question: Literal["素数为何如此特别？"] = "素数为何如此特别？"
    hypothesis_zh: str
    primary_metric: Literal["tie_aware_normalized_permutation_entropy_m5"] = (
        "tie_aware_normalized_permutation_entropy_m5"
    )
    primary_null_model: Literal["residue_path_conditioned_permutation"] = (
        "residue_path_conditioned_permutation"
    )
    required_sensitivity_null_models: tuple[
        Literal["local_block_permutation"],
        Literal["wheel_210"],
    ] = ("local_block_permutation", "wheel_210")
    scientific_boundary_zh: str
    formal_experiment_executed: Literal[False] = False
    mathematical_proof_claimed: Literal[False] = False
    source_plan_path: str | None
    source_plan_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_plan_snapshot_relative_path: str | None
    source_plan_snapshot_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    parameters: ContestPrimePreexperimentParameters
    parameters_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    interval_results: tuple[PrimeIntervalResult, ...] = Field(min_length=5, max_length=5)
    aggregate_results: tuple[PrimeAggregateNullResult, ...] = Field(min_length=4, max_length=4)
    references: tuple[str, ...]
    started_at: datetime
    completed_at: datetime
    runtime_seconds: float = Field(ge=0.0)
    metrics_relative_path: str
    metrics_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stdout_log_relative_path: str
    stdout_log_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stderr_log_relative_path: str
    stderr_log_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_relative_path: Literal["manifest.json"] = "manifest.json"
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_files: tuple[PrimePreexperimentFileEvidence, ...]
    integrity_scope: Literal["sha256_tamper_evident_not_externally_signed"] = (
        "sha256_tamper_evident_not_externally_signed"
    )
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_program_projection(self) -> ContestPrimePreexperimentArtifact:
        if self.parameters_hash != canonical_model_hash(self.parameters):
            raise ValueError("prime preexperiment parameters hash mismatch")
        expected_run_id = _run_id(self.parameters_hash, self.source_plan_sha256)
        if self.run_id != expected_run_id:
            raise ValueError("prime preexperiment run ID mismatch")
        if (self.source_plan_path is None) != (self.source_plan_sha256 is None):
            raise ValueError("source plan path and hash must be present together")
        if (self.source_plan_snapshot_relative_path is None) != (
            self.source_plan_snapshot_sha256 is None
        ):
            raise ValueError("source plan snapshot path and hash must be present together")
        if len(self.interval_results) != len(self.parameters.intervals):
            raise ValueError("interval result count does not match frozen parameters")
        if tuple(result.interval_index for result in self.interval_results) != tuple(
            range(1, len(self.interval_results) + 1)
        ):
            raise ValueError("interval results are not in frozen order")
        if tuple(result.start for result in self.interval_results) != tuple(
            interval.start for interval in self.parameters.intervals
        ):
            raise ValueError("interval starts differ from frozen parameters")
        if tuple(result.stop for result in self.interval_results) != tuple(
            interval.stop for interval in self.parameters.intervals
        ):
            raise ValueError("interval stops differ from frozen parameters")
        expected = canonical_model_hash(self.model_dump(mode="json", exclude={"artifact_hash"}))
        if self.artifact_hash != expected:
            raise ValueError("prime preexperiment artifact hash mismatch")
        return self

    def plan_context_payload(self) -> dict[str, Any]:
        """Project verified observations and boundaries for a Qwen revision call."""

        return {
            "schema_version": "contest-prime-preexperiment-plan-context-v1",
            "execution_status": self.status,
            "study_phase": self.study_phase,
            "protocol_status": self.protocol_status,
            "protocol_amendment_reason_zh": self.protocol_amendment_reason_zh,
            "protocol_frozen_before_data_generation": True,
            "scientific_question": self.scientific_question,
            "hypothesis_zh": self.hypothesis_zh,
            "scientific_boundary_zh": self.scientific_boundary_zh,
            "formal_experiment_executed": False,
            "mathematical_proof_claimed": False,
            "primary_metric": self.primary_metric,
            "primary_null_model": self.primary_null_model,
            "required_sensitivity_null_models": list(self.required_sensitivity_null_models),
            "standardized_effect_definition": (
                "(observed_entropy-null_mean_entropy)/SD(null_draws); "
                "simulation-standardized diagnostic, not a population effect size"
            ),
            "parameters_hash": self.parameters_hash,
            "parameters": self.parameters.model_dump(mode="json"),
            "source_plan": {
                "path": self.source_plan_path,
                "sha256": self.source_plan_sha256,
                "snapshot_relative_path": self.source_plan_snapshot_relative_path,
                "snapshot_sha256": self.source_plan_snapshot_sha256,
            },
            "interval_results": [
                {
                    "interval_index": result.interval_index,
                    "start": result.start,
                    "stop": result.stop,
                    "prime_count": result.prime_count,
                    "gap_count": result.gap_count,
                    "mean_gap": result.mean_gap,
                    "observed_metrics": result.observed_metrics.model_dump(mode="json"),
                    "null_summaries": [
                        summary.model_dump(mode="json") for summary in result.null_summaries
                    ],
                    "raw_relative_path": result.raw_relative_path,
                    "raw_sha256": result.raw_sha256,
                    "null_draws_relative_path": result.null_draws_relative_path,
                    "null_draws_sha256": result.null_draws_sha256,
                    "residue_conditioned_variable_position_fraction": (
                        result.residue_conditioned_variable_position_fraction
                    ),
                }
                for result in self.interval_results
            ],
            "aggregate_results": [
                result.model_dump(mode="json") for result in self.aggregate_results
            ],
            "evidence": {
                "metrics_relative_path": self.metrics_relative_path,
                "metrics_sha256": self.metrics_sha256,
                "stdout_log_relative_path": self.stdout_log_relative_path,
                "stdout_log_sha256": self.stdout_log_sha256,
                "stderr_log_relative_path": self.stderr_log_relative_path,
                "stderr_log_sha256": self.stderr_log_sha256,
                "manifest_relative_path": self.manifest_relative_path,
                "manifest_sha256": self.manifest_sha256,
                "manifest_hash": self.manifest_hash,
                "artifact_hash": self.artifact_hash,
                "integrity_scope": self.integrity_scope,
            },
            "interpretation_rule_zh": (
                "只能把这些数字表述为五个固定有限区间上的探索性预实验观察；"
                "不得外推为素数总体规律、不得声称证明或否定任何开放数论猜想，"
                "并须同时报告残基路径条件置换、局部分块置换、全局置换与wheel-210对照；"
                "若强约束对照不支持简单置换下的差异，不得保留强结构结论。"
            ),
        }


class _IntervalComputation:
    """Mutable in-memory computation, never persisted directly."""

    def __init__(
        self,
        *,
        interval_index: int,
        spec: PrimeIntervalSpec,
        primes: np.ndarray[Any, np.dtype[np.int64]],
        gaps: np.ndarray[Any, np.dtype[np.int64]],
        observed: PrimeSequenceMetrics,
        raw_relative_path: str,
        raw_sha256: str,
        null_relative_path: str,
        null_sha256: str,
        null_metrics: dict[NullModel, np.ndarray[Any, np.dtype[np.float64]]],
        null_seeds: dict[NullModel, int],
        residue_variable_fraction: float,
    ) -> None:
        self.interval_index = interval_index
        self.spec = spec
        self.primes = primes
        self.gaps = gaps
        self.observed = observed
        self.raw_relative_path = raw_relative_path
        self.raw_sha256 = raw_sha256
        self.null_relative_path = null_relative_path
        self.null_sha256 = null_sha256
        self.null_metrics = null_metrics
        self.null_seeds = null_seeds
        self.residue_variable_fraction = residue_variable_fraction


def run_contest_prime_preexperiment(
    *,
    output_dir: Path | str,
    parameters: ContestPrimePreexperimentParameters | Mapping[str, Any] | None = None,
    source_plan_path: Path | str | None = None,
) -> ContestPrimePreexperimentArtifact:
    """Execute and persist the real exploratory prime-gap pilot.

    ``output_dir`` must be absent or empty.  A scientific/runtime failure writes a
    failure artifact, logs, and a manifest before raising
    :class:`ContestPrimePreexperimentError`.  Refusing to overwrite an existing
    directory fails before execution and therefore writes nothing there.
    """

    protocol = _normalize_parameters(parameters)
    root = Path(output_dir).expanduser().resolve()
    _prepare_output_dir(root)
    started_at = datetime.now(timezone.utc)
    clock_start = time.perf_counter()
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    source_path, source_hash, snapshot_relative, snapshot_hash = _snapshot_inputs(
        root=root,
        source_plan_path=source_plan_path,
    )
    parameters_hash = canonical_model_hash(protocol)
    run_id = _run_id(parameters_hash, source_hash)
    _write_json(root / _PARAMETERS_NAME, protocol.model_dump(mode="json"))
    _write_json(root / _ENVIRONMENT_NAME, _environment_payload())
    source_snapshot = root / "inputs/contest_prime_preexperiment.py"
    source_snapshot.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(__file__).resolve(), source_snapshot)
    stdout_lines.extend(
        (
            f"run_id={run_id}",
            "study_phase=exploratory_pilot",
            "protocol_status=protocol_amended_before_execution",
            f"parameters_hash={parameters_hash}",
            "protocol_frozen_before_data_generation=true",
        )
    )

    try:
        computations: list[_IntervalComputation] = []
        for index, interval in enumerate(protocol.intervals, start=1):
            stdout_lines.append(f"interval_{index:02d}_start=[{interval.start},{interval.stop})")
            computation = _run_interval(
                root=root,
                interval_index=index,
                spec=interval,
                parameters=protocol,
            )
            computations.append(computation)
            stdout_lines.append(
                f"interval_{index:02d}_complete=primes:{len(computation.primes)},"
                f"gaps:{len(computation.gaps)}"
            )

        interval_results = _build_interval_results(computations, protocol)
        aggregate_results = _build_aggregate_results(computations, protocol)
        metrics_payload = {
            "schema_version": "contest-prime-preexperiment-metrics-v1",
            "run_id": run_id,
            "status": "completed",
            "study_phase": "exploratory_pilot",
            "protocol_status": "protocol_amended_before_execution",
            "parameters_hash": parameters_hash,
            "primary_metric": "tie_aware_normalized_permutation_entropy_m5",
            "primary_null_model": "residue_path_conditioned_permutation",
            "required_sensitivity_null_models": [
                "local_block_permutation",
                "wheel_210",
            ],
            "standardized_effect_definition": (
                "(observed_entropy-null_mean_entropy)/SD(null_draws); "
                "simulation-standardized diagnostic, not a population effect size"
            ),
            "interval_results": [result.model_dump(mode="json") for result in interval_results],
            "aggregate_results": [result.model_dump(mode="json") for result in aggregate_results],
            "scientific_boundary_zh": _scientific_boundary(),
        }
        _write_json(root / _METRICS_NAME, metrics_payload)
        stdout_lines.append("program_status=completed")
        _write_text(root / _STDOUT_NAME, "\n".join(stdout_lines) + "\n")
        _write_text(root / _STDERR_NAME, "")
        evidence = _collect_evidence(root, include_failure=False)
        manifest = _write_manifest(
            root=root,
            run_id=run_id,
            program_status="completed",
            evidence=evidence,
        )
        completed_at = datetime.now(timezone.utc)
        artifact_payload: dict[str, Any] = {
            "schema_version": "contest-prime-preexperiment-artifact-v1",
            "run_id": run_id,
            "status": "completed",
            "study_phase": "exploratory_pilot",
            "protocol_status": "protocol_amended_before_execution",
            "protocol_amendment_reason_zh": _protocol_amendment_reason(),
            "protocol_frozen_before_data_generation": True,
            "scientific_question": "素数为何如此特别？",
            "hypothesis_zh": _hypothesis(),
            "primary_metric": "tie_aware_normalized_permutation_entropy_m5",
            "primary_null_model": "residue_path_conditioned_permutation",
            "required_sensitivity_null_models": (
                "local_block_permutation",
                "wheel_210",
            ),
            "scientific_boundary_zh": _scientific_boundary(),
            "formal_experiment_executed": False,
            "mathematical_proof_claimed": False,
            "source_plan_path": source_path,
            "source_plan_sha256": source_hash,
            "source_plan_snapshot_relative_path": snapshot_relative,
            "source_plan_snapshot_sha256": snapshot_hash,
            "parameters": protocol.model_dump(mode="json"),
            "parameters_hash": parameters_hash,
            "interval_results": [result.model_dump(mode="json") for result in interval_results],
            "aggregate_results": [result.model_dump(mode="json") for result in aggregate_results],
            "references": list(_REFERENCES),
            "started_at": _json_datetime(started_at),
            "completed_at": _json_datetime(completed_at),
            "runtime_seconds": time.perf_counter() - clock_start,
            "metrics_relative_path": _METRICS_NAME,
            "metrics_sha256": _sha256_file(root / _METRICS_NAME),
            "stdout_log_relative_path": _STDOUT_NAME,
            "stdout_log_sha256": _sha256_file(root / _STDOUT_NAME),
            "stderr_log_relative_path": _STDERR_NAME,
            "stderr_log_sha256": _sha256_file(root / _STDERR_NAME),
            "manifest_relative_path": _MANIFEST_NAME,
            "manifest_sha256": _sha256_file(root / _MANIFEST_NAME),
            "manifest_hash": manifest.manifest_hash,
            "evidence_files": [file.model_dump(mode="json") for file in evidence],
            "integrity_scope": "sha256_tamper_evident_not_externally_signed",
        }
        artifact_payload["artifact_hash"] = canonical_model_hash(artifact_payload)
        artifact = ContestPrimePreexperimentArtifact.model_validate(artifact_payload)
        write_json_model(root / _ARTIFACT_NAME, artifact)
        return artifact
    except Exception as exc:
        if isinstance(exc, ContestPrimePreexperimentError):
            raise
        stderr_lines.extend((f"{type(exc).__name__}: {exc}", traceback.format_exc()))
        stdout_lines.append("program_status=failed")
        _write_text(root / _STDOUT_NAME, "\n".join(stdout_lines) + "\n")
        _write_text(root / _STDERR_NAME, "\n".join(stderr_lines))
        failure_payload = {
            "schema_version": "contest-prime-preexperiment-failure-v1",
            "run_id": run_id,
            "status": "failed",
            "study_phase": "exploratory_pilot",
            "protocol_status": "protocol_amended_before_execution",
            "parameters_hash": parameters_hash,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "stdout_log_relative_path": _STDOUT_NAME,
            "stderr_log_relative_path": _STDERR_NAME,
        }
        failure_path = root / "failure.json"
        _write_json(failure_path, failure_payload)
        evidence = _collect_evidence(root, include_failure=True)
        manifest = _write_manifest(
            root=root,
            run_id=run_id,
            program_status="failed",
            evidence=evidence,
        )
        raise ContestPrimePreexperimentError(
            f"prime preexperiment failed after evidence persistence: {exc}",
            failure_path=failure_path,
            manifest_path=root / _MANIFEST_NAME,
        ) from exc


def load_contest_prime_preexperiment(
    path: Path | str,
    *,
    verify_files: bool = True,
) -> ContestPrimePreexperimentArtifact:
    """Load an artifact and optionally re-hash every manifest-bound file."""

    artifact_path = Path(path).expanduser().resolve()
    artifact = ContestPrimePreexperimentArtifact.model_validate_json(
        artifact_path.read_text(encoding="utf-8")
    )
    root = artifact_path.parent
    manifest_path = root / artifact.manifest_relative_path
    if _sha256_file(manifest_path) != artifact.manifest_sha256:
        raise ContestPrimePreexperimentError("prime preexperiment manifest file hash mismatch")
    manifest = PrimePreexperimentManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    if manifest.manifest_hash != artifact.manifest_hash:
        raise ContestPrimePreexperimentError("prime preexperiment manifest identity mismatch")
    if manifest.run_id != artifact.run_id or manifest.program_status != artifact.status:
        raise ContestPrimePreexperimentError("prime preexperiment manifest status mismatch")
    if tuple(manifest.files) != artifact.evidence_files:
        raise ContestPrimePreexperimentError("artifact evidence list differs from manifest")
    if verify_files:
        for evidence in manifest.files:
            file_path = _inside_root(root, evidence.relative_path)
            if not file_path.is_file():
                raise ContestPrimePreexperimentError(
                    f"manifest-bound file is missing: {evidence.relative_path}"
                )
            if file_path.stat().st_size != evidence.bytes:
                raise ContestPrimePreexperimentError(
                    f"manifest-bound file size mismatch: {evidence.relative_path}"
                )
            if _sha256_file(file_path) != evidence.sha256:
                raise ContestPrimePreexperimentError(
                    f"manifest-bound file hash mismatch: {evidence.relative_path}"
                )
    return artifact


def _normalize_parameters(
    value: ContestPrimePreexperimentParameters | Mapping[str, Any] | None,
) -> ContestPrimePreexperimentParameters:
    if value is None:
        return ContestPrimePreexperimentParameters()
    if isinstance(value, ContestPrimePreexperimentParameters):
        return value
    return ContestPrimePreexperimentParameters.model_validate(value)


def _prepare_output_dir(root: Path) -> None:
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise ContestPrimePreexperimentError(
            "prime preexperiment output_dir must be absent or empty; refusing overwrite"
        )
    root.mkdir(parents=True, exist_ok=True)


def _snapshot_inputs(
    *,
    root: Path,
    source_plan_path: Path | str | None,
) -> tuple[str | None, str | None, str | None, str | None]:
    if source_plan_path is None:
        return None, None, None, None
    source = Path(source_plan_path).expanduser().resolve()
    if not source.is_file():
        raise ContestPrimePreexperimentError(f"source plan does not exist: {source}")
    source_hash = _sha256_file(source)
    suffix = source.suffix if source.suffix else ".bin"
    relative = f"inputs/source-plan{suffix}"
    snapshot = root / relative
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, snapshot)
    if _sha256_file(snapshot) != source_hash:
        raise ContestPrimePreexperimentError("source plan snapshot hash mismatch")
    return source.as_posix(), source_hash, relative, source_hash


def _run_id(parameters_hash: str, source_plan_sha256: str | None) -> str:
    digest = hashlib.sha256(
        f"{parameters_hash}\n{source_plan_sha256 or 'no-source-plan'}".encode()
    ).hexdigest()
    return f"prime-pilot-{digest[:16]}"


def _run_interval(
    *,
    root: Path,
    interval_index: int,
    spec: PrimeIntervalSpec,
    parameters: ContestPrimePreexperimentParameters,
) -> _IntervalComputation:
    primes = _generate_primes_in_interval(spec.start, spec.stop)
    if len(primes) < max(20, parameters.ordinal_dimension + 2):
        raise ValueError(
            f"interval {interval_index} produced too few primes for analysis: {len(primes)}"
        )
    gaps = np.diff(primes)
    observed = _sequence_metrics(gaps, parameters.ordinal_dimension)
    raw_relative = f"raw/interval-{interval_index:02d}-prime-gaps.csv"
    raw_path = root / raw_relative
    _write_prime_gap_csv(raw_path, primes)

    wheel_candidates = _wheel_candidates(spec.start, spec.stop, parameters.wheel_modulus)
    if len(wheel_candidates) < len(primes):
        raise ValueError(
            f"wheel-{parameters.wheel_modulus} candidate count is below observed prime count"
        )
    residue_groups, residue_variable_fraction = _residue_path_groups(
        primes=primes,
        gaps=gaps,
        segment_size=parameters.residue_path_segment_size,
    )
    if residue_variable_fraction < parameters.minimum_residue_variable_fraction:
        raise ValueError(
            "residue-path-conditioned null has insufficient variable positions: "
            f"{residue_variable_fraction:.6f} < "
            f"{parameters.minimum_residue_variable_fraction:.6f}"
        )

    null_rows: list[dict[str, Any]] = []
    null_metrics: dict[NullModel, np.ndarray[Any, np.dtype[np.float64]]] = {}
    null_seeds: dict[NullModel, int] = {}
    for null_model in _NULL_MODELS:
        model_seed = _derive_seed(parameters.seed, interval_index, null_model)
        null_seeds[null_model] = model_seed
        generator = np.random.Generator(np.random.PCG64(model_seed))
        entropy_values = np.empty(parameters.null_draws, dtype=np.float64)
        block_values = np.empty(parameters.null_draws, dtype=np.float64)
        mutual_information_values = np.empty(parameters.null_draws, dtype=np.float64)
        for draw_index in range(parameters.null_draws):
            sequence = _null_gap_sequence(
                null_model=null_model,
                gaps=gaps,
                observed_primes=primes,
                interval=spec,
                wheel_candidates=wheel_candidates,
                prime_count=len(primes),
                local_block_size=parameters.local_block_size,
                wheel_density_segment_width=parameters.wheel_density_segment_width,
                residue_groups=residue_groups,
                generator=generator,
            )
            metrics = _sequence_metrics(sequence, parameters.ordinal_dimension)
            entropy_values[draw_index] = metrics.tie_aware_normalized_permutation_entropy_m5
            block_values[draw_index] = metrics.quartile_symbol_block_entropy_order2
            mutual_information_values[draw_index] = metrics.quartile_symbol_lag1_mutual_information
            null_rows.append(
                {
                    "interval_index": interval_index,
                    "null_model": null_model,
                    "rng_seed": model_seed,
                    "draw_index": draw_index + 1,
                    "tie_aware_normalized_permutation_entropy_m5": entropy_values[draw_index],
                    "quartile_symbol_block_entropy_order2": block_values[draw_index],
                    "quartile_symbol_lag1_mutual_information": (
                        mutual_information_values[draw_index]
                    ),
                    "residue_conditioned_variable_position_fraction": (residue_variable_fraction),
                }
            )
        null_metrics[null_model] = entropy_values
    null_relative = f"null/interval-{interval_index:02d}-null-draws.csv"
    null_path = root / null_relative
    _write_null_draws_csv(null_path, null_rows)
    return _IntervalComputation(
        interval_index=interval_index,
        spec=spec,
        primes=primes,
        gaps=gaps,
        observed=observed,
        raw_relative_path=raw_relative,
        raw_sha256=_sha256_file(raw_path),
        null_relative_path=null_relative,
        null_sha256=_sha256_file(null_path),
        null_metrics=null_metrics,
        null_seeds=null_seeds,
        residue_variable_fraction=residue_variable_fraction,
    )


def _generate_primes_in_interval(
    start: int,
    stop: int,
) -> np.ndarray[Any, np.dtype[np.int64]]:
    """Generate primes in ``[start, stop)`` with a real segmented sieve."""

    if stop <= start:
        return np.empty(0, dtype=np.int64)
    limit = math.isqrt(stop - 1)
    base = bytearray(b"\x01") * (limit + 1)
    if limit >= 0:
        base[0] = 0
    if limit >= 1:
        base[1] = 0
    for candidate in range(2, math.isqrt(limit) + 1):
        if base[candidate]:
            first = candidate * candidate
            count = ((limit - first) // candidate) + 1
            base[first : limit + 1 : candidate] = b"\x00" * count
    base_primes = [index for index, flag in enumerate(base) if flag]

    segment = bytearray(b"\x01") * (stop - start)
    for prime in base_primes:
        first = max(prime * prime, ((start + prime - 1) // prime) * prime)
        if first >= stop:
            continue
        count = ((stop - 1 - first) // prime) + 1
        segment[first - start : stop - start : prime] = b"\x00" * count
    if start < 2:
        for number in range(start, min(stop, 2)):
            segment[number - start] = 0
    flags = np.frombuffer(segment, dtype=np.uint8)
    return np.flatnonzero(flags).astype(np.int64) + start


def _wheel_candidates(
    start: int,
    stop: int,
    modulus: int,
) -> np.ndarray[Any, np.dtype[np.int64]]:
    values = np.arange(start, stop, dtype=np.int64)
    selected = values[np.gcd(values, modulus) == 1]
    return np.asarray(selected, dtype=np.int64)


def _residue_path_groups(
    *,
    primes: np.ndarray[Any, np.dtype[np.int64]],
    gaps: np.ndarray[Any, np.dtype[np.int64]],
    segment_size: int,
) -> tuple[tuple[np.ndarray[Any, np.dtype[np.int64]], ...], float]:
    """Group gap positions by local segment and consecutive-prime residues."""

    grouped: dict[tuple[int, int, int], list[int]] = {}
    for index, (left, right) in enumerate(zip(primes[:-1], primes[1:], strict=True)):
        key = (index // segment_size, int(left % 30), int(right % 30))
        grouped.setdefault(key, []).append(index)
    groups = tuple(np.asarray(indices, dtype=np.int64) for _, indices in sorted(grouped.items()))
    variable_positions = sum(
        len(indices) for indices in groups if len(indices) > 1 and len(np.unique(gaps[indices])) > 1
    )
    return groups, variable_positions / len(gaps)


def _null_gap_sequence(
    *,
    null_model: NullModel,
    gaps: np.ndarray[Any, np.dtype[np.int64]],
    observed_primes: np.ndarray[Any, np.dtype[np.int64]],
    interval: PrimeIntervalSpec,
    wheel_candidates: np.ndarray[Any, np.dtype[np.int64]],
    prime_count: int,
    local_block_size: int,
    wheel_density_segment_width: int,
    residue_groups: tuple[np.ndarray[Any, np.dtype[np.int64]], ...],
    generator: np.random.Generator,
) -> np.ndarray[Any, np.dtype[np.int64]]:
    if null_model == "global_permutation":
        return generator.permutation(gaps)
    if null_model == "local_block_permutation":
        shuffled = gaps.copy()
        full_size = (len(shuffled) // local_block_size) * local_block_size
        if full_size:
            blocks = shuffled[:full_size].reshape(-1, local_block_size)
            shuffled[:full_size] = generator.permuted(blocks, axis=1).reshape(-1)
        if full_size < len(shuffled):
            shuffled[full_size:] = generator.permutation(shuffled[full_size:])
        return shuffled
    if null_model == "residue_path_conditioned_permutation":
        shuffled = gaps.copy()
        for indices in residue_groups:
            if len(indices) > 1:
                shuffled[indices] = generator.permutation(gaps[indices])
        return shuffled
    if null_model == "wheel_210":
        pseudo_primes = _wheel_pseudo_primes(
            observed_primes=observed_primes,
            candidates=wheel_candidates,
            interval=interval,
            segment_width=wheel_density_segment_width,
            generator=generator,
        )
        if len(pseudo_primes) != prime_count:
            raise ValueError("wheel-210 pseudo-prime count differs from observed count")
        return np.diff(pseudo_primes)
    raise ValueError(f"unknown prime-gap null model: {null_model}")


def _wheel_pseudo_primes(
    *,
    observed_primes: np.ndarray[Any, np.dtype[np.int64]],
    candidates: np.ndarray[Any, np.dtype[np.int64]],
    interval: PrimeIntervalSpec,
    segment_width: int,
    generator: np.random.Generator,
) -> np.ndarray[Any, np.dtype[np.int64]]:
    """Sample wheel-admissible points with fixed endpoints and local counts."""

    first_observed = int(observed_primes[0])
    last_observed = int(observed_primes[-1])
    sampled_parts: list[np.ndarray[Any, np.dtype[np.int64]]] = []
    for segment_start in range(interval.start, interval.stop, segment_width):
        segment_stop = min(interval.stop, segment_start + segment_width)
        observed_mask = (observed_primes >= segment_start) & (observed_primes < segment_stop)
        target_count = int(np.count_nonzero(observed_mask))
        if target_count == 0:
            continue
        fixed = [
            value
            for value in (first_observed, last_observed)
            if segment_start <= value < segment_stop
        ]
        candidate_mask = (candidates >= segment_start) & (candidates < segment_stop)
        available = candidates[candidate_mask]
        available = available[(available >= first_observed) & (available <= last_observed)]
        if fixed:
            available = available[~np.isin(available, np.asarray(fixed, dtype=np.int64))]
        sample_count = target_count - len(fixed)
        if sample_count < 0 or sample_count > len(available):
            raise ValueError("wheel-210 local-density sample is infeasible")
        random_part = (
            generator.choice(available, size=sample_count, replace=False)
            if sample_count
            else np.empty(0, dtype=np.int64)
        )
        sampled_parts.append(np.concatenate((np.asarray(fixed, dtype=np.int64), random_part)))
    pseudo_primes = np.concatenate(sampled_parts)
    pseudo_primes.sort()
    if int(pseudo_primes[0]) != first_observed or int(pseudo_primes[-1]) != last_observed:
        raise ValueError("wheel-210 pseudo-prime endpoints are not fixed")
    return np.asarray(pseudo_primes, dtype=np.int64)


def _sequence_metrics(
    sequence: np.ndarray[Any, np.dtype[np.int64]],
    ordinal_dimension: int,
) -> PrimeSequenceMetrics:
    values = np.asarray(sequence, dtype=np.int64)
    if len(values) < ordinal_dimension + 1:
        raise ValueError("gap sequence is too short for ordinal metrics")
    windows = sliding_window_view(values, ordinal_dimension)
    pairwise = windows[:, :, None] > windows[:, None, :]
    ranks = pairwise.sum(axis=2, dtype=np.int64)
    powers = np.power(ordinal_dimension + 1, np.arange(ordinal_dimension), dtype=np.int64)
    codes = ranks @ powers
    _, counts = np.unique(codes, return_counts=True)
    probabilities = counts.astype(np.float64) / counts.sum()
    entropy = -float(np.sum(probabilities * np.log(probabilities)))
    ordered_bell = _ordered_bell_number(ordinal_dimension)
    normalized_permutation_entropy = entropy / math.log(ordered_bell)

    thresholds = np.quantile(values, (0.25, 0.5, 0.75), method="linear")
    symbols = np.searchsorted(thresholds, values, side="right").astype(np.int64)
    pair_codes = symbols[:-1] * 4 + symbols[1:]
    pair_counts = np.bincount(pair_codes, minlength=16).astype(np.float64)
    pair_probabilities = pair_counts / pair_counts.sum()
    nonzero_pairs = pair_probabilities > 0
    block_entropy = -float(
        np.sum(pair_probabilities[nonzero_pairs] * np.log(pair_probabilities[nonzero_pairs]))
    ) / math.log(16)
    joint = pair_counts.reshape(4, 4) / pair_counts.sum()
    left_marginal = joint.sum(axis=1)
    right_marginal = joint.sum(axis=0)
    expected = left_marginal[:, None] * right_marginal[None, :]
    mask = joint > 0
    mutual_information = float(np.sum(joint[mask] * np.log(joint[mask] / expected[mask])))
    normalized_mutual_information = mutual_information / math.log(4)
    return PrimeSequenceMetrics(
        tie_aware_normalized_permutation_entropy_m5=_bounded_unit(normalized_permutation_entropy),
        quartile_symbol_block_entropy_order2=_bounded_unit(block_entropy),
        quartile_symbol_lag1_mutual_information=max(0.0, normalized_mutual_information),
    )


def _ordered_bell_number(order: int) -> int:
    # Sum k! S(n,k), where S is a Stirling number of the second kind.
    stirling = [[0] * (order + 1) for _ in range(order + 1)]
    stirling[0][0] = 1
    for n in range(1, order + 1):
        for k in range(1, n + 1):
            stirling[n][k] = stirling[n - 1][k - 1] + k * stirling[n - 1][k]
    return sum(math.factorial(k) * stirling[order][k] for k in range(order + 1))


def _bounded_unit(value: float) -> float:
    return min(1.0, max(0.0, value))


def _build_interval_results(
    computations: Sequence[_IntervalComputation],
    parameters: ContestPrimePreexperimentParameters,
) -> tuple[PrimeIntervalResult, ...]:
    raw_p_values: dict[NullModel, list[float]] = {model: [] for model in _NULL_MODELS}
    for computation in computations:
        observed = computation.observed.tie_aware_normalized_permutation_entropy_m5
        for model in _NULL_MODELS:
            null = computation.null_metrics[model]
            raw_p_values[model].append(_empirical_lower_p(observed, null))
    holm = {model: _holm_adjust(raw_p_values[model]) for model in _NULL_MODELS}

    results: list[PrimeIntervalResult] = []
    for position, computation in enumerate(computations):
        observed = computation.observed.tie_aware_normalized_permutation_entropy_m5
        summaries: list[PrimeNullSummary] = []
        for model in _NULL_MODELS:
            null = computation.null_metrics[model]
            mean = float(np.mean(null))
            standard_deviation = float(np.std(null, ddof=1))
            delta = observed - mean
            summaries.append(
                PrimeNullSummary(
                    null_model=model,
                    draw_count=parameters.null_draws,
                    rng_seed=computation.null_seeds[model],
                    observed_entropy=observed,
                    null_mean_entropy=mean,
                    null_sd_entropy=standard_deviation,
                    null_ci95=(
                        float(np.quantile(null, 0.025)),
                        float(np.quantile(null, 0.975)),
                    ),
                    delta_observed_minus_null=delta,
                    standardized_effect=(
                        delta / standard_deviation if standard_deviation > 0 else None
                    ),
                    one_sided_empirical_p_lower=raw_p_values[model][position],
                    holm_adjusted_p_across_intervals=holm[model][position],
                    residue_conditioned_variable_position_fraction=(
                        computation.residue_variable_fraction
                        if model == "residue_path_conditioned_permutation"
                        else None
                    ),
                )
            )
        results.append(
            PrimeIntervalResult(
                interval_index=computation.interval_index,
                start=computation.spec.start,
                stop=computation.spec.stop,
                prime_count=len(computation.primes),
                gap_count=len(computation.gaps),
                mean_gap=float(np.mean(computation.gaps)),
                observed_metrics=computation.observed,
                raw_relative_path=computation.raw_relative_path,
                raw_sha256=computation.raw_sha256,
                null_draws_relative_path=computation.null_relative_path,
                null_draws_sha256=computation.null_sha256,
                residue_conditioned_variable_position_fraction=(
                    computation.residue_variable_fraction
                ),
                null_summaries=tuple(summaries),
            )
        )
    return tuple(results)


def _build_aggregate_results(
    computations: Sequence[_IntervalComputation],
    parameters: ContestPrimePreexperimentParameters,
) -> tuple[PrimeAggregateNullResult, ...]:
    observed = np.asarray(
        [
            computation.observed.tie_aware_normalized_permutation_entropy_m5
            for computation in computations
        ],
        dtype=np.float64,
    )
    prepared: dict[
        NullModel,
        tuple[float, float, float | None, float, tuple[float, float]],
    ] = {}
    raw_p_values: list[float] = []
    for model in _NULL_MODELS:
        null_matrix = np.stack([computation.null_metrics[model] for computation in computations])
        null_draw_means = null_matrix.mean(axis=0)
        null_interval_means = null_matrix.mean(axis=1)
        deltas = observed - null_interval_means
        aggregate_delta = float(np.mean(deltas))
        null_sd = float(np.std(null_draw_means, ddof=1))
        resampling_seed = _derive_seed(parameters.seed, 0, f"interval-resampling-{model}")
        resampling_generator = np.random.Generator(np.random.PCG64(resampling_seed))
        indices = resampling_generator.integers(
            0,
            len(deltas),
            size=(parameters.fixed_interval_resampling_draws, len(deltas)),
        )
        resampled_interval_means = deltas[indices].mean(axis=1)
        raw_p = _empirical_lower_p(float(np.mean(observed)), null_draw_means)
        raw_p_values.append(raw_p)
        prepared[model] = (
            float(np.mean(null_draw_means)),
            aggregate_delta,
            aggregate_delta / null_sd if null_sd > 0 else None,
            raw_p,
            (
                float(np.quantile(resampled_interval_means, 0.025)),
                float(np.quantile(resampled_interval_means, 0.975)),
            ),
        )
    adjusted_p_values = _holm_adjust(raw_p_values)
    results: list[PrimeAggregateNullResult] = []
    for position, model in enumerate(_NULL_MODELS):
        null_mean, aggregate_delta, standardized_effect, raw_p, interval_ci = prepared[model]
        results.append(
            PrimeAggregateNullResult(
                null_model=model,
                draw_count=parameters.null_draws,
                observed_mean_entropy=float(np.mean(observed)),
                null_mean_entropy=null_mean,
                delta_observed_minus_null=aggregate_delta,
                standardized_effect=standardized_effect,
                one_sided_empirical_p_lower=raw_p,
                holm_adjusted_p_across_null_models=adjusted_p_values[position],
                fixed_interval_resampling_delta_ci95=interval_ci,
            )
        )
    return tuple(results)


def _empirical_lower_p(
    observed: float,
    null_values: np.ndarray[Any, np.dtype[np.float64]],
) -> float:
    return (1.0 + float(np.count_nonzero(null_values <= observed))) / (len(null_values) + 1.0)


def _holm_adjust(p_values: Sequence[float]) -> list[float]:
    count = len(p_values)
    order = sorted(range(count), key=lambda index: p_values[index])
    adjusted = [1.0] * count
    previous = 0.0
    for rank, index in enumerate(order):
        candidate = min(1.0, (count - rank) * p_values[index])
        previous = max(previous, candidate)
        adjusted[index] = previous
    return adjusted


def _derive_seed(root_seed: int, interval_index: int, tag: str) -> int:
    digest = hashlib.sha256(f"{root_seed}:{interval_index}:{tag}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


def _write_prime_gap_csv(
    path: Path,
    primes: np.ndarray[Any, np.dtype[np.int64]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("prime_left", "prime_right", "gap"))
        for left, right in zip(primes[:-1], primes[1:], strict=True):
            writer.writerow((int(left), int(right), int(right - left)))


def _write_null_draws_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = (
        "interval_index",
        "null_model",
        "rng_seed",
        "draw_index",
        "tie_aware_normalized_permutation_entropy_m5",
        "quartile_symbol_block_entropy_order2",
        "quartile_symbol_lag1_mutual_information",
        "residue_conditioned_variable_position_fraction",
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_manifest(
    *,
    root: Path,
    run_id: str,
    program_status: Literal["completed", "failed"],
    evidence: tuple[PrimePreexperimentFileEvidence, ...],
) -> PrimePreexperimentManifest:
    payload: dict[str, Any] = {
        "schema_version": "contest-prime-preexperiment-manifest-v1",
        "run_id": run_id,
        "program_status": program_status,
        "integrity_scope": "sha256_tamper_evident_not_externally_signed",
        "files": [file.model_dump(mode="json") for file in evidence],
    }
    payload["manifest_hash"] = canonical_model_hash(payload)
    manifest = PrimePreexperimentManifest.model_validate(payload)
    write_json_model(root / _MANIFEST_NAME, manifest)
    return manifest


def _collect_evidence(
    root: Path,
    *,
    include_failure: bool,
) -> tuple[PrimePreexperimentFileEvidence, ...]:
    kinds: dict[str, FileKind] = {
        _PARAMETERS_NAME: "parameters",
        _ENVIRONMENT_NAME: "environment",
        "inputs/contest_prime_preexperiment.py": "source_code",
        _METRICS_NAME: "metrics",
        _STDOUT_NAME: "stdout_log",
        _STDERR_NAME: "stderr_log",
    }
    for path in sorted((root / "inputs").glob("source-plan.*")):
        kinds[path.relative_to(root).as_posix()] = "source_plan_snapshot"
    for path in sorted((root / "raw").glob("*.csv")):
        kinds[path.relative_to(root).as_posix()] = "raw_prime_gaps"
    for path in sorted((root / "null").glob("*.csv")):
        kinds[path.relative_to(root).as_posix()] = "null_draws"
    if include_failure and (root / "failure.json").is_file():
        kinds["failure.json"] = "failure"
    evidence: list[PrimePreexperimentFileEvidence] = []
    for relative, kind in sorted(kinds.items()):
        path = root / relative
        if path.is_file():
            evidence.append(
                PrimePreexperimentFileEvidence(
                    relative_path=relative,
                    sha256=_sha256_file(path),
                    bytes=path.stat().st_size,
                    kind=kind,
                )
            )
    return tuple(evidence)


def _inside_root(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ContestPrimePreexperimentError(
            f"manifest path escapes output directory: {relative_path}"
        ) from exc
    return candidate


def _environment_payload() -> dict[str, Any]:
    return {
        "schema_version": "contest-prime-preexperiment-environment-v1",
        "python_version": sys.version,
        "python_executable": sys.executable,
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "numpy_version": np.__version__,
        "process_id": os.getpid(),
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }


def _json_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _protocol_amendment_reason() -> str:
    return (
        "本轮在读取任何预实验结果之前，将原计划中跨度过大的区间改为五个互不重叠、"
        "各宽一百万的固定区间，并预先加入局部分块置换、全局置换、模30残基路径条件"
        "置换和wheel-210伪素数四类零模型。修改原因是普通工作站可行性和零模型可识别性，"
        "而非依据结果调规则；"
        "因此本轮标记为探索性pilot，不冒充原计划的确认性执行。"
    )


def _hypothesis() -> str:
    return (
        "在五个固定有限区间内，真实素数间隙序列的m=5并列感知归一化排列熵，"
        "相对于同时保持局部段号及相邻素数模30残基路径、但在条件组内破坏间隙"
        "顺序的置换零模型更低；局部分块置换和保持局部点数、端点及wheel-210"
        "可容许性的伪素数作为必要敏感性对照。该单侧假设仅检验有限尺度顺序结构。"
    )


def _scientific_boundary() -> str:
    return (
        "区间是预先固定的计算benchmark，不是从数轴总体随机抽取的自然样本；"
        "经验p值和五区间重采样范围只描述本次n=5固定区间计算，并非总体置信区间。"
        "任何差异都不能证明素数存在"
        "新的深层规律，不能证明或否定黎曼猜想、Cramér猜想等开放问题。wheel-210只控制"
        "2、3、5、7的可除性、局部点数和端点，也不是完整的素数生成零模型；简单置换"
        "若与残基路径条件对照冲突，应优先收缩而不是强化结论。"
    )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
