"""Immutable, failure-aware adjudication of the official MDBench Gate A run."""

from __future__ import annotations

import ast
import hashlib
import json
import math
import random
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import (
    MDBenchAttemptResult,
    MDBenchAttemptState,
    MDBenchExecutionReport,
    MDBenchExperimentMatrix,
    MDBenchMatrixAttemptSpec,
)
from autoresearch.competition.official_execution import (
    MDBenchExecutionError,
    load_mdbench_attempt_result,
    load_mdbench_execution_report,
)
from autoresearch.competition.preregistration import validate_mdbench_preregistration

_REPORT_NAME = "gate-a-adjudication.json"
_MARKDOWN_NAME = "gate-a-report.md"
_NOISY_CONDITION = "snr_20"
_PRIMARY_METRIC = "derivative_nmse"
_RELATIVE_IMPROVEMENT_THRESHOLD = 0.05
_BOOTSTRAP_RESAMPLES = 20_000
_BOOTSTRAP_SEED = 2594
_STRUCTURE_RELATIVE_COEFFICIENT_THRESHOLD = 1e-3
_STRUCTURE_ABSOLUTE_COEFFICIENT_THRESHOLD = 1e-8
_TRUTH_SOURCE_REVISION = "f81813e760325589737fe3311ac8199ecc64188a"
_TRUTH_SOURCE_FILES = {
    "README.md": "4fceb40a3fe44a96557f56538738005e633d851985c653e2b77aea3819e0eafe",
    "scripts/fenics_heat_soil_uniform.py": (
        "f5c9ebd62048de1a62afaf3b57d3ce87954c86564a86185116852b67ae829fdc"
    ),
    "scripts/strogatz_ode.py": ("fe39de6cf002d62e62c3f1d7e026b514ac5046b8c96778a610ff5ff9dc8f0958"),
}

# Supports are expanded from the exact ODE equations in scripts/strogatz_ode.py
# and the four PDE equations in the pinned README. Constants are explicit terms.
_TRUTH_SUPPORTS: dict[tuple[str, str], dict[str, tuple[str, ...]]] = {
    ("ode", "harmonic-oscillator"): {
        "u0_t": ("u1",),
        "u1_t": ("u0",),
    },
    ("ode", "van-der-pol-oscillator"): {
        "u0_t": ("u1",),
        "u1_t": ("u0", "u1", "u0^2*u1"),
    },
    ("ode", "lotka-volterra-simple"): {
        "u0_t": ("u0", "u0*u1"),
        "u1_t": ("u1", "u0*u1"),
    },
    ("ode", "duffing-equation"): {
        "u0_t": ("u1",),
        "u1_t": ("u0", "u1", "u0^2*u1"),
    },
    ("ode", "brusselator"): {
        "u0_t": ("1", "u0", "u0^2*u1"),
        "u1_t": ("u0", "u0^2*u1"),
    },
    ("ode", "sir-infection"): {
        "u0_t": ("u0*u1",),
        "u1_t": ("u1", "u0*u1"),
    },
    ("ode", "lorenz-equations-chaotic"): {
        "u0_t": ("u0", "u1"),
        "u1_t": ("u0", "u1", "u0*u2"),
        "u2_t": ("u2", "u0*u1"),
    },
    ("ode", "rössler-attractor-chaotic"): {
        "u0_t": ("u1", "u2"),
        "u1_t": ("u0", "u1"),
        "u2_t": ("1", "u2", "u0*u2"),
    },
    ("ode", "glycolytic-oscillator"): {
        "u0_t": ("u0", "u1", "u0^2*u1"),
        "u1_t": ("1", "u0", "u0^2*u1"),
    },
    ("ode", "autocatalytic-gene-switching"): {
        "u0_t": ("1", "u0", "u0^2/(1+u0^2)"),
    },
    ("ode", "harmonic-oscillator-damping"): {
        "u0_t": ("u1",),
        "u1_t": ("u0", "u1"),
    },
    ("ode", "lotka-volterra-competition"): {
        "u0_t": ("u0", "u0^2", "u0*u1"),
        "u1_t": ("u1", "u0*u1", "u1^2"),
    },
    ("ode", "damped-double-well-oscillator"): {
        "u0_t": ("u1",),
        "u1_t": ("u0", "u1", "u0^3"),
    },
    ("ode", "seir-infection"): {
        "u0_t": ("u0*u2",),
        "u1_t": ("u0*u2", "u1"),
        "u2_t": ("u1", "u2"),
        "u3_t": ("u2",),
    },
    ("ode", "maxwell-bloch-equations"): {
        "u0_t": ("u0", "u1"),
        "u1_t": ("u1", "u0*u2"),
        "u2_t": ("1", "u2", "u0*u1"),
    },
    ("ode", "rössler-attractor-periodic"): {
        "u0_t": ("u1", "u2"),
        "u1_t": ("u0", "u1"),
        "u2_t": ("1", "u2", "u0*u2"),
    },
    ("ode", "chen-lee-attractor"): {
        "u0_t": ("u0", "u1*u2"),
        "u1_t": ("u1", "u0*u2"),
        "u2_t": ("u2", "u0*u1"),
    },
    ("ode", "lorenz-equations-complex-periodic"): {
        "u0_t": ("u0", "u1"),
        "u1_t": ("u0", "u1", "u0*u2"),
        "u2_t": ("u2", "u0*u1"),
    },
    ("ode", "apoptosis-model"): {
        "u0_t": ("1", "u0", "u0*u1/(0.1+u0)"),
        "u1_t": ("u2", "u1*u2", "u1/(0.1+u1)", "u0*u1/(2.0+u1)"),
        "u2_t": ("u2", "u1*u2", "u1/(0.1+u1)", "u0*u1/(2.0+u1)"),
    },
    ("ode", "binocular-rivalry-adaptation"): {
        "u0_t": ("u0", "1/(1+exp(0.89*u2+0.4*u1-1.4))"),
        "u1_t": ("u0", "u1"),
        "u2_t": ("u2", "1/(1+exp(0.89*u0+0.4*u3-1.4))"),
        "u3_t": ("u2", "u3"),
    },
    ("pde", "advection1d"): {"u0_t": ("u0_x",)},
    ("pde", "burgers"): {"u0_t": ("u0*u0_x", "u0_xx")},
    ("pde", "kdv"): {"u0_t": ("u0*u0_x", "u0_xxx")},
    ("pde", "kuramoto_sivishinky"): {
        "u0_t": ("u0*u0_x", "u0_xx", "u0_xxxx"),
    },
    ("pde", "heat_soil_uniform_1d_p1"): {"u0_t": ("u0_xx",)},
    ("pde", "nls"): {
        "u0_t": ("u1_xx", "u0^2*u1", "u1^3"),
        "u1_t": ("u0_xx", "u0*u1^2", "u0^3"),
    },
}

Monomial = tuple[tuple[str, int], ...]
Polynomial = dict[Monomial, float]


class GateAAdjudicationError(RuntimeError):
    """Raised when Gate A inputs are incomplete, changed, or not adjudicable."""


class GateADecision(str, Enum):
    """Only an evidence-complete pass or an explicit negative result is allowed."""

    PASSED = "passed"
    NEGATIVE_RESULT = "negative_result"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GateACheck(_FrozenModel):
    check_id: str
    requirement: str
    passed: bool
    observed: str
    mandatory: bool = True


class BaselineSelectionScore(_FrozenModel):
    method_id: str
    successful_development_noisy_cells: int = Field(ge=0)
    total_development_noisy_cells: int = Field(ge=1)
    successful_derivative_nmse_median: float | None = Field(
        default=None,
        ge=0.0,
        allow_inf_nan=False,
    )
    rank: int = Field(ge=1)


class MethodGateSummary(_FrozenModel):
    method_id: str
    role: Literal["baseline", "candidate"]
    terminal_count: int = Field(ge=0)
    succeeded_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    timed_out_count: int = Field(ge=0)
    development_noisy_success_count: int = Field(ge=0)
    unseen_noisy_success_count: int = Field(ge=0)
    unseen_clean_derivative_nmse_median: float | None = Field(
        default=None, ge=0.0, allow_inf_nan=False
    )
    unseen_noisy_derivative_nmse_median: float | None = Field(
        default=None, ge=0.0, allow_inf_nan=False
    )
    unseen_noisy_ode_trajectory_nmse_median: float | None = Field(
        default=None, ge=0.0, allow_inf_nan=False
    )
    unseen_noisy_model_complexity_median: float | None = Field(
        default=None, ge=0.0, allow_inf_nan=False
    )
    structure_f1_median: float | None = Field(default=None, ge=0.0, le=1.0, allow_inf_nan=False)
    structure_scored_count: int = Field(ge=0)
    noise_robustness_ratio_median: float | None = Field(default=None, ge=0.0, allow_inf_nan=False)
    noise_robustness_pair_count: int = Field(ge=0)
    wall_time_seconds_median: float | None = Field(default=None, ge=0.0, allow_inf_nan=False)
    peak_rss_mb_median: float | None = Field(default=None, ge=0.0, allow_inf_nan=False)
    failure_reasons: tuple[str, ...] = ()


class GateASystemEffect(_FrozenModel):
    data_type: Literal["ode", "pde"]
    system_name: str
    candidate_success_count: int = Field(ge=0)
    baseline_success_count: int = Field(ge=0)
    paired_seed_count: int = Field(ge=0)
    candidate_derivative_nmse_median: float | None = Field(
        default=None, ge=0.0, allow_inf_nan=False
    )
    baseline_derivative_nmse_median: float | None = Field(default=None, ge=0.0, allow_inf_nan=False)
    paired_seed_relative_improvements: tuple[float, ...] = ()
    system_relative_improvement: float = Field(allow_inf_nan=False)
    missing_cell_policy_applied: bool


class GateAPrimaryComparison(_FrozenModel):
    metric: str = _PRIMARY_METRIC
    condition: str = _NOISY_CONDITION
    evaluation_split: str = "unseen_test"
    candidate_method_id: str
    baseline_method_id: str
    candidate_success_count: int = Field(ge=0)
    baseline_success_count: int = Field(ge=0)
    candidate_successful_median: float | None = Field(default=None, ge=0.0, allow_inf_nan=False)
    baseline_successful_median: float | None = Field(default=None, ge=0.0, allow_inf_nan=False)
    observed_success_median_relative_improvement: float | None = Field(
        default=None, allow_inf_nan=False
    )
    failure_aware_system_median_relative_improvement: float = Field(allow_inf_nan=False)
    bootstrap_unit: str = "unseen system"
    bootstrap_statistic: str = "median relative improvement"
    bootstrap_resamples: int = _BOOTSTRAP_RESAMPLES
    bootstrap_seed: int = _BOOTSTRAP_SEED
    bootstrap_ci95_lower: float = Field(allow_inf_nan=False)
    bootstrap_ci95_upper: float = Field(allow_inf_nan=False)
    required_relative_improvement: float = _RELATIVE_IMPROVEMENT_THRESHOLD
    system_effects: tuple[GateASystemEffect, ...]
    missing_cell_policy: str


class MDBenchGateAReport(_FrozenModel):
    """Hash-bound final Gate A pass/negative decision and transparent diagnostics."""

    schema_version: str = "mdbench-gate-a-adjudication-v1"
    decision: GateADecision
    gate_b_allowed: bool
    matrix_path: str
    matrix_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    execution_report_path: str
    execution_report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    execution_environment_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_set_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    adjudicator_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    analysis_policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    truth_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    truth_source_revision: str
    truth_source_files: dict[str, str]
    total_attempt_count: int = Field(ge=1)
    succeeded_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    timed_out_count: int = Field(ge=0)
    human_intervention_count: int = Field(ge=0)
    access_request_count: int = Field(ge=0)
    candidate_method_id: str
    selected_baseline_method_id: str
    baseline_selection_rule: str
    baseline_selection_scores: tuple[BaselineSelectionScore, ...]
    method_summaries: tuple[MethodGateSummary, ...]
    primary_comparison: GateAPrimaryComparison
    checks: tuple[GateACheck, ...]
    negative_reasons: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    generated_at: datetime
    analysis_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    report_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    output_path: str
    markdown_path: str


def _candidate_method_id(matrix: MDBenchExperimentMatrix) -> str:
    candidate_methods = tuple(
        method.method_id for method in matrix.methods if method.family == "agent_candidate"
    )
    if len(candidate_methods) != 1:
        raise GateAAdjudicationError("Gate A requires exactly one generated candidate method")
    return candidate_methods[0]


def adjudicate_mdbench_gate_a(
    matrix_path: Path | str,
    execution_report_path: Path | str,
    output_dir: Path | str,
) -> MDBenchGateAReport:
    """Apply the frozen Gate A rules without deleting or substituting failed cells."""

    matrix, execution, results = _load_verified_bundle(matrix_path, execution_report_path)
    if execution.total_attempt_count != 252 or len(matrix.attempts) != 252:
        raise GateAAdjudicationError("Gate A v1 requires the exact 252-cell matrix")
    candidate_method = _candidate_method_id(matrix)
    baseline_methods = tuple(
        method.method_id for method in matrix.methods if method.family != "agent_candidate"
    )
    if len(baseline_methods) < 2:
        raise GateAAdjudicationError("Gate A v1 requires at least two baseline families")

    structure_scores = {
        result.attempt_id: score_equation_structure(
            result.data_type,
            result.system_name,
            result.discovered_equation or "",
        )
        for result in results
        if result.status is MDBenchAttemptState.SUCCEEDED
    }
    selection_scores, selected_baseline = _select_baseline(results, baseline_methods)
    method_summaries = tuple(
        _summarize_method(matrix, results, structure_scores, method_id)
        for method_id in (baseline_methods + (candidate_method,))
    )
    primary = _primary_comparison(
        matrix,
        results,
        candidate_method=candidate_method,
        baseline_method=selected_baseline,
    )
    checks = _gate_checks(
        matrix,
        execution,
        results,
        structure_scores,
        primary,
        candidate_method,
    )
    decision = (
        GateADecision.PASSED
        if all(check.passed for check in checks if check.mandatory)
        else GateADecision.NEGATIVE_RESULT
    )
    negative_reasons = tuple(
        f"{check.check_id}: {check.observed}"
        for check in checks
        if check.mandatory and not check.passed
    )
    limitations = (
        "The frozen matrix specified the 5% effect and bootstrap confidence gates but not a missing-baseline-cell policy; the adjudicator therefore uses the conservative zero-improvement policy and discloses it.",
        "Equation-structure F1 is post-processed from the pinned equation sources and discovered equation text; it does not alter the immutable attempt results.",
        "Only six unseen systems are available, so the system-level bootstrap interval is necessarily wide and must not be replaced by a seed-level pseudo-replication interval.",
        f"{sum(result.method_id in baseline_methods and result.status is not MDBenchAttemptState.SUCCEEDED for result in results)} baseline cells are terminal failures or timeouts and remain in coverage and failure-aware sensitivity checks.",
    )
    resolved_matrix = Path(matrix_path).resolve()
    resolved_execution = Path(execution_report_path).resolve()
    output_root = Path(output_dir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / _REPORT_NAME
    markdown_path = output_root / _MARKDOWN_NAME
    adjudicator_sha = _sha256_file(Path(__file__).resolve())
    truth_registry_hash = canonical_model_hash(
        {
            "revision": _TRUTH_SOURCE_REVISION,
            "source_files": _TRUTH_SOURCE_FILES,
            "supports": {
                f"{data_type}/{system_name}": targets
                for (data_type, system_name), targets in sorted(_TRUTH_SUPPORTS.items())
            },
        }
    )
    policy = _analysis_policy(candidate_method)
    policy_hash = canonical_model_hash(policy)
    result_set_hash = canonical_model_hash(
        {
            "results": [
                {
                    "attempt_id": result.attempt_id,
                    "result_hash": result.result_hash,
                    "status": result.status.value,
                }
                for result in results
            ]
        }
    )
    deterministic = {
        "decision": decision.value,
        "matrix_hash": matrix.matrix_hash,
        "execution_report_hash": execution.report_hash,
        "execution_environment_hash": execution.environment.environment_hash,
        "result_set_hash": result_set_hash,
        "adjudicator_sha256": adjudicator_sha,
        "analysis_policy_hash": policy_hash,
        "truth_registry_hash": truth_registry_hash,
        "candidate_method_id": candidate_method,
        "selected_baseline_method_id": selected_baseline,
        "baseline_selection_scores": [item.model_dump(mode="json") for item in selection_scores],
        "method_summaries": [item.model_dump(mode="json") for item in method_summaries],
        "primary_comparison": primary.model_dump(mode="json"),
        "checks": [item.model_dump(mode="json") for item in checks],
        "negative_reasons": negative_reasons,
        "limitations": limitations,
    }
    analysis_hash = canonical_model_hash(deterministic)
    if output_path.is_file():
        existing = load_mdbench_gate_a_report(output_path)
        if existing.analysis_hash != analysis_hash:
            raise GateAAdjudicationError(
                "refusing to overwrite Gate A report produced by different inputs or policy"
            )
        if not markdown_path.is_file():
            _write_markdown(markdown_path, existing)
        return existing

    unstamped = MDBenchGateAReport(
        decision=decision,
        gate_b_allowed=decision is GateADecision.PASSED,
        matrix_path=resolved_matrix.as_posix(),
        matrix_hash=matrix.matrix_hash,
        execution_report_path=resolved_execution.as_posix(),
        execution_report_hash=execution.report_hash or "",
        execution_environment_hash=execution.environment.environment_hash,
        result_set_hash=result_set_hash,
        adjudicator_sha256=adjudicator_sha,
        analysis_policy_hash=policy_hash,
        truth_registry_hash=truth_registry_hash,
        truth_source_revision=_TRUTH_SOURCE_REVISION,
        truth_source_files=dict(_TRUTH_SOURCE_FILES),
        total_attempt_count=execution.total_attempt_count,
        succeeded_count=execution.succeeded_count,
        failed_count=execution.failed_count,
        timed_out_count=execution.timed_out_count,
        human_intervention_count=execution.human_intervention_count,
        access_request_count=execution.access_request_count,
        candidate_method_id=candidate_method,
        selected_baseline_method_id=selected_baseline,
        baseline_selection_rule=str(policy["baseline_selection_rule"]),
        baseline_selection_scores=selection_scores,
        method_summaries=method_summaries,
        primary_comparison=primary,
        checks=checks,
        negative_reasons=negative_reasons,
        limitations=limitations,
        generated_at=datetime.now(timezone.utc),
        analysis_hash=analysis_hash,
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
    _write_markdown(markdown_path, report)
    return report


def load_mdbench_gate_a_report(path: Path | str) -> MDBenchGateAReport:
    """Load a final Gate A report and reject content or output-path tampering."""

    resolved = Path(path).resolve()
    try:
        report = MDBenchGateAReport.model_validate_json(resolved.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise GateAAdjudicationError(f"cannot load Gate A report: {exc}") from exc
    if Path(report.output_path).resolve() != resolved:
        raise GateAAdjudicationError("Gate A report output path mismatch")
    expected = canonical_model_hash(
        report.model_dump(
            mode="json",
            exclude={"report_hash", "output_path", "markdown_path"},
        )
    )
    if report.report_hash != expected:
        raise GateAAdjudicationError("Gate A report hash mismatch")
    return report


def score_equation_structure(
    data_type: Literal["ode", "pde"],
    system_name: str,
    discovered_equation: str,
) -> float:
    """Score expanded term support against the pinned true equation support."""

    truth = _TRUTH_SUPPORTS.get((data_type, system_name))
    if truth is None:
        raise GateAAdjudicationError(f"truth support is missing for {data_type}/{system_name}")
    predicted = _equation_support(discovered_equation)
    truth_terms = {(target, feature) for target, features in truth.items() for feature in features}
    predicted_terms = {
        (target, feature) for target, features in predicted.items() for feature in features
    }
    true_positive = len(truth_terms.intersection(predicted_terms))
    false_positive = len(predicted_terms.difference(truth_terms))
    false_negative = len(truth_terms.difference(predicted_terms))
    denominator = 2 * true_positive + false_positive + false_negative
    return 1.0 if denominator == 0 else (2 * true_positive) / denominator


def _load_verified_bundle(
    matrix_path: Path | str,
    execution_report_path: Path | str,
) -> tuple[MDBenchExperimentMatrix, MDBenchExecutionReport, tuple[MDBenchAttemptResult, ...]]:
    resolved_matrix = Path(matrix_path).resolve()
    try:
        matrix = MDBenchExperimentMatrix.model_validate_json(
            resolved_matrix.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as exc:
        raise GateAAdjudicationError(f"cannot load Gate A matrix: {exc}") from exc
    validate_mdbench_preregistration(matrix)
    try:
        execution = load_mdbench_execution_report(execution_report_path)
    except MDBenchExecutionError as exc:
        raise GateAAdjudicationError(str(exc)) from exc
    if not execution.complete or execution.pending_count != 0:
        raise GateAAdjudicationError("official matrix execution is incomplete")
    if execution.matrix_hash != matrix.matrix_hash:
        raise GateAAdjudicationError("execution report belongs to another matrix")
    if execution.inventory_hash != matrix.inventory_hash:
        raise GateAAdjudicationError("execution inventory does not match the matrix")
    if Path(execution.matrix_path).resolve() != resolved_matrix:
        raise GateAAdjudicationError("execution report matrix path mismatch")
    expected_attempts = {attempt.attempt_id: attempt for attempt in matrix.attempts}
    record_ids = [record.attempt_id for record in execution.records]
    if len(record_ids) != len(set(record_ids)) or set(record_ids) != set(expected_attempts):
        raise GateAAdjudicationError("execution records do not cover the frozen matrix exactly")
    records = {record.attempt_id: record for record in execution.records}
    results: list[MDBenchAttemptResult] = []
    for attempt in matrix.attempts:
        record = records[attempt.attempt_id]
        try:
            result = load_mdbench_attempt_result(record.result_path)
        except MDBenchExecutionError as exc:
            raise GateAAdjudicationError(str(exc)) from exc
        _validate_result_causal_chain(result, attempt, matrix, execution)
        if result.result_hash != record.result_hash or result.status is not record.status:
            raise GateAAdjudicationError(f"execution record/result mismatch: {attempt.attempt_id}")
        results.append(result)
    return matrix, execution, tuple(results)


def _validate_result_causal_chain(
    result: MDBenchAttemptResult,
    attempt: MDBenchMatrixAttemptSpec,
    matrix: MDBenchExperimentMatrix,
    execution: MDBenchExecutionReport,
) -> None:
    environment = execution.environment
    expected = (
        attempt.attempt_id,
        matrix.matrix_hash,
        matrix.benchmark_revision,
        attempt.data_type,
        attempt.system_name,
        attempt.evaluation_split,
        attempt.condition,
        attempt.seed,
        attempt.method_id,
        attempt.config_hash,
        attempt.artifact_sha256,
        environment.code_hash,
        environment.environment_hash,
        environment.image_id,
    )
    actual = (
        result.attempt_id,
        result.matrix_hash,
        result.benchmark_revision,
        result.data_type,
        result.system_name,
        result.evaluation_split,
        result.condition,
        result.seed,
        result.method_id,
        result.config_hash,
        result.data_hash,
        result.code_hash,
        result.environment_hash,
        result.container_image_id,
    )
    if actual != expected:
        raise GateAAdjudicationError(f"attempt causal mismatch: {attempt.attempt_id}")
    result_path = Path(result.output_path).resolve()
    spec_path = result_path.parent.parent / "specs" / f"{attempt.config_hash}.json"
    try:
        spec_payload = json.loads(spec_path.read_text(encoding="utf-8"))
        persisted_hash = str(spec_payload.pop("spec_hash"))
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise GateAAdjudicationError(f"attempt spec is invalid: {spec_path}") from exc
    if persisted_hash != result.spec_hash or canonical_model_hash(spec_payload) != result.spec_hash:
        raise GateAAdjudicationError(f"attempt spec hash mismatch: {spec_path}")
    for raw_path, expected_hash in (
        (result.stdout_path, result.stdout_sha256),
        (result.stderr_path, result.stderr_sha256),
    ):
        path = Path(raw_path)
        if not path.is_file() or _sha256_file(path) != expected_hash:
            raise GateAAdjudicationError(f"attempt log hash mismatch: {path}")


def _select_baseline(
    results: tuple[MDBenchAttemptResult, ...],
    baseline_methods: tuple[str, ...],
) -> tuple[tuple[BaselineSelectionScore, ...], str]:
    raw: list[tuple[str, int, int, float | None]] = []
    for method_id in baseline_methods:
        cells = [
            result
            for result in results
            if result.method_id == method_id
            and result.evaluation_split == "development"
            and result.condition == _NOISY_CONDITION
        ]
        values = [
            _required_metric(result, _PRIMARY_METRIC)
            for result in cells
            if result.status is MDBenchAttemptState.SUCCEEDED
        ]
        raw.append((method_id, len(values), len(cells), _median(values)))
    ranked = sorted(
        raw,
        key=lambda item: (
            -item[1],
            math.inf if item[3] is None else item[3],
            item[0],
        ),
    )
    if not ranked or ranked[0][1] == 0:
        raise GateAAdjudicationError("no baseline succeeded on development noisy cells")
    rank_by_method = {item[0]: index + 1 for index, item in enumerate(ranked)}
    scores = tuple(
        BaselineSelectionScore(
            method_id=method_id,
            successful_development_noisy_cells=successes,
            total_development_noisy_cells=total,
            successful_derivative_nmse_median=median_value,
            rank=rank_by_method[method_id],
        )
        for method_id, successes, total, median_value in ranked
    )
    return scores, ranked[0][0]


def _summarize_method(
    matrix: MDBenchExperimentMatrix,
    results: tuple[MDBenchAttemptResult, ...],
    structure_scores: dict[str, float],
    method_id: str,
) -> MethodGateSummary:
    method_results = [result for result in results if result.method_id == method_id]
    successes = [
        result for result in method_results if result.status is MDBenchAttemptState.SUCCEEDED
    ]
    unseen_clean = [
        result
        for result in successes
        if result.evaluation_split == "unseen_test" and result.condition == "clean"
    ]
    unseen_noisy = [
        result
        for result in successes
        if result.evaluation_split == "unseen_test" and result.condition == _NOISY_CONDITION
    ]
    noise_ratios = _noise_ratios(method_results)
    structure_values = [structure_scores[result.attempt_id] for result in successes]
    method = next(item for item in matrix.methods if item.method_id == method_id)
    return MethodGateSummary(
        method_id=method_id,
        role="candidate" if method.family == "agent_candidate" else "baseline",
        terminal_count=len(method_results),
        succeeded_count=len(successes),
        failed_count=sum(result.status is MDBenchAttemptState.FAILED for result in method_results),
        timed_out_count=sum(
            result.status is MDBenchAttemptState.TIMED_OUT for result in method_results
        ),
        development_noisy_success_count=sum(
            result.evaluation_split == "development" and result.condition == _NOISY_CONDITION
            for result in successes
        ),
        unseen_noisy_success_count=len(unseen_noisy),
        unseen_clean_derivative_nmse_median=_median(
            [_required_metric(result, _PRIMARY_METRIC) for result in unseen_clean]
        ),
        unseen_noisy_derivative_nmse_median=_median(
            [_required_metric(result, _PRIMARY_METRIC) for result in unseen_noisy]
        ),
        unseen_noisy_ode_trajectory_nmse_median=_median(
            [
                float(result.metrics.trajectory_extrapolation_nmse_ode)
                for result in unseen_noisy
                if result.data_type == "ode"
                and result.metrics.trajectory_extrapolation_nmse_ode is not None
            ]
        ),
        unseen_noisy_model_complexity_median=_median(
            [float(result.metrics.model_complexity or 0) for result in unseen_noisy]
        ),
        structure_f1_median=_median(structure_values),
        structure_scored_count=len(structure_values),
        noise_robustness_ratio_median=_median(noise_ratios),
        noise_robustness_pair_count=len(noise_ratios),
        wall_time_seconds_median=_median(
            [result.metrics.wall_time_seconds for result in successes]
        ),
        peak_rss_mb_median=_median([result.metrics.peak_rss_mb for result in successes]),
        failure_reasons=tuple(
            sorted(
                {
                    result.failure_reason or "unknown failure"
                    for result in method_results
                    if result.status is not MDBenchAttemptState.SUCCEEDED
                }
            )
        ),
    )


def _noise_ratios(results: list[MDBenchAttemptResult]) -> list[float]:
    grouped: dict[tuple[str, str, int], dict[str, MDBenchAttemptResult]] = defaultdict(dict)
    for result in results:
        grouped[(result.data_type, result.system_name, result.seed)][result.condition] = result
    ratios: list[float] = []
    for conditions in grouped.values():
        clean = conditions.get("clean")
        noisy = conditions.get(_NOISY_CONDITION)
        if (
            clean is None
            or noisy is None
            or clean.status is not MDBenchAttemptState.SUCCEEDED
            or noisy.status is not MDBenchAttemptState.SUCCEEDED
        ):
            continue
        clean_value = _required_metric(clean, _PRIMARY_METRIC)
        noisy_value = _required_metric(noisy, _PRIMARY_METRIC)
        ratios.append(noisy_value / max(clean_value, 1e-12))
    return ratios


def _primary_comparison(
    matrix: MDBenchExperimentMatrix,
    results: tuple[MDBenchAttemptResult, ...],
    *,
    candidate_method: str,
    baseline_method: str,
) -> GateAPrimaryComparison:
    unseen_cases = tuple(case for case in matrix.systems if case.evaluation_split == "unseen_test")
    lookup = {
        (result.data_type, result.system_name, result.seed, result.method_id): result
        for result in results
        if result.evaluation_split == "unseen_test" and result.condition == _NOISY_CONDITION
    }
    effects: list[GateASystemEffect] = []
    candidate_values: list[float] = []
    baseline_values: list[float] = []
    expected_seeds = tuple(matrix.seeds)
    for case in unseen_cases:
        candidate_results = [
            lookup[(case.data_type, case.system_name, seed, candidate_method)]
            for seed in expected_seeds
        ]
        baseline_results = [
            lookup[(case.data_type, case.system_name, seed, baseline_method)]
            for seed in expected_seeds
        ]
        candidate_success = [
            result for result in candidate_results if result.status is MDBenchAttemptState.SUCCEEDED
        ]
        baseline_success = [
            result for result in baseline_results if result.status is MDBenchAttemptState.SUCCEEDED
        ]
        candidate_metric = [
            _required_metric(result, _PRIMARY_METRIC) for result in candidate_success
        ]
        baseline_metric = [_required_metric(result, _PRIMARY_METRIC) for result in baseline_success]
        candidate_values.extend(candidate_metric)
        baseline_values.extend(baseline_metric)
        seed_effects: list[float] = []
        for seed in expected_seeds:
            candidate = lookup[(case.data_type, case.system_name, seed, candidate_method)]
            baseline = lookup[(case.data_type, case.system_name, seed, baseline_method)]
            if (
                candidate.status is MDBenchAttemptState.SUCCEEDED
                and baseline.status is MDBenchAttemptState.SUCCEEDED
            ):
                candidate_value = _required_metric(candidate, _PRIMARY_METRIC)
                baseline_value = _required_metric(baseline, _PRIMARY_METRIC)
                seed_effects.append((baseline_value - candidate_value) / max(baseline_value, 1e-12))
        complete = len(candidate_success) == len(expected_seeds) and len(baseline_success) == len(
            expected_seeds
        )
        system_effect = float(statistics.median(seed_effects)) if complete else 0.0
        effects.append(
            GateASystemEffect(
                data_type=case.data_type,
                system_name=case.system_name,
                candidate_success_count=len(candidate_success),
                baseline_success_count=len(baseline_success),
                paired_seed_count=len(seed_effects),
                candidate_derivative_nmse_median=_median(candidate_metric),
                baseline_derivative_nmse_median=_median(baseline_metric),
                paired_seed_relative_improvements=tuple(seed_effects),
                system_relative_improvement=system_effect,
                missing_cell_policy_applied=not complete,
            )
        )
    system_values = [effect.system_relative_improvement for effect in effects]
    lower, upper = _bootstrap_median_ci(system_values)
    candidate_median = _median(candidate_values)
    baseline_median = _median(baseline_values)
    observed_relative: float | None = None
    if candidate_median is not None and baseline_median is not None:
        observed_relative = (baseline_median - candidate_median) / max(baseline_median, 1e-12)
    return GateAPrimaryComparison(
        candidate_method_id=candidate_method,
        baseline_method_id=baseline_method,
        candidate_success_count=len(candidate_values),
        baseline_success_count=len(baseline_values),
        candidate_successful_median=candidate_median,
        baseline_successful_median=baseline_median,
        observed_success_median_relative_improvement=observed_relative,
        failure_aware_system_median_relative_improvement=float(statistics.median(system_values)),
        bootstrap_ci95_lower=lower,
        bootstrap_ci95_upper=upper,
        system_effects=tuple(effects),
        missing_cell_policy=(
            "Require all three candidate and selected-baseline seeds for a system; "
            "otherwise assign that system zero relative improvement without deleting it."
        ),
    )


def _gate_checks(
    matrix: MDBenchExperimentMatrix,
    execution: MDBenchExecutionReport,
    results: tuple[MDBenchAttemptResult, ...],
    structure_scores: dict[str, float],
    primary: GateAPrimaryComparison,
    candidate_method: str,
) -> tuple[GateACheck, ...]:
    expected_seeds = set(matrix.seeds)
    grouped: dict[tuple[str, str, str, str], list[MDBenchAttemptResult]] = defaultdict(list)
    for result in results:
        grouped[(result.data_type, result.system_name, result.condition, result.method_id)].append(
            result
        )
    terminal_three_seed = all(
        {result.seed for result in group} == expected_seeds and len(group) == len(expected_seeds)
        for group in grouped.values()
    )
    all_method_success = all(
        len(group) == len(expected_seeds)
        and all(result.status is MDBenchAttemptState.SUCCEEDED for result in group)
        for group in grouped.values()
    )
    candidate_results = [result for result in results if result.method_id == candidate_method]
    expected_candidate_count = sum(
        attempt.method_id == candidate_method for attempt in matrix.attempts
    )
    candidate_success = (
        all(result.status is MDBenchAttemptState.SUCCEEDED for result in candidate_results)
        and len(candidate_results) == expected_candidate_count
    )
    nonconstant_by_method = {
        method.method_id: len(
            {
                _required_metric(result, _PRIMARY_METRIC)
                for result in results
                if result.method_id == method.method_id
                and result.status is MDBenchAttemptState.SUCCEEDED
            }
        )
        for method in matrix.methods
    }
    nonconstant = all(count > 1 for count in nonconstant_by_method.values())
    successful_count = sum(result.status is MDBenchAttemptState.SUCCEEDED for result in results)
    structure_complete = len(structure_scores) == successful_count
    method_summary_presence = True
    for method in matrix.methods:
        method_results = [result for result in results if result.method_id == method.method_id]
        successes = [
            result for result in method_results if result.status is MDBenchAttemptState.SUCCEEDED
        ]
        has_derivative_complexity_cost = bool(successes) and all(
            result.metrics.derivative_nmse is not None
            and result.metrics.model_complexity is not None
            and math.isfinite(result.metrics.wall_time_seconds)
            and math.isfinite(result.metrics.peak_rss_mb)
            for result in successes
        )
        has_ode_trajectory = any(
            result.data_type == "ode"
            and result.metrics.trajectory_extrapolation_nmse_ode is not None
            for result in successes
        )
        has_structure = all(result.attempt_id in structure_scores for result in successes)
        has_noise_robustness = bool(_noise_ratios(method_results))
        method_summary_presence = method_summary_presence and all(
            (
                has_derivative_complexity_cost,
                has_ode_trajectory,
                has_structure,
                has_noise_robustness,
            )
        )
    observed = primary.observed_success_median_relative_improvement
    effect_pass = observed is not None and observed >= _RELATIVE_IMPROVEMENT_THRESHOLD
    ci_pass = primary.bootstrap_ci95_lower > 0.0
    return (
        GateACheck(
            check_id="complete_terminal_matrix",
            requirement="All 252 frozen cells are terminal and none is pending.",
            passed=execution.complete
            and execution.terminal_attempt_count == 252
            and execution.pending_count == 0,
            observed=(
                f"terminal={execution.terminal_attempt_count}, pending={execution.pending_count}, "
                f"succeeded={execution.succeeded_count}, failed={execution.failed_count}, "
                f"timed_out={execution.timed_out_count}"
            ),
        ),
        GateACheck(
            check_id="zero_human_scientific_intervention",
            requirement="The scientific run completes without human intervention.",
            passed=execution.human_intervention_count == 0,
            observed=f"human_intervention_count={execution.human_intervention_count}",
        ),
        GateACheck(
            check_id="three_seed_terminal_coverage",
            requirement=(
                "Every frozen method/system/condition group contains seeds "
                f"{', '.join(str(seed) for seed in matrix.seeds)}."
            ),
            passed=terminal_three_seed,
            observed=f"groups={len(grouped)}, complete_terminal_seed_groups={sum({result.seed for result in group} == expected_seeds and len(group) == len(expected_seeds) for group in grouped.values())}",
        ),
        GateACheck(
            check_id="candidate_three_seed_success",
            requirement=(
                "The generated candidate succeeds on all "
                f"{expected_candidate_count} frozen cells."
            ),
            passed=candidate_success,
            observed=(
                "candidate_successes="
                f"{sum(result.status is MDBenchAttemptState.SUCCEEDED for result in candidate_results)}"
                f"/{expected_candidate_count}"
            ),
        ),
        GateACheck(
            check_id="all_methods_three_seed_reproducible",
            requirement="Each preregistered method succeeds across all three seeds.",
            passed=all_method_success,
            observed=(
                f"successful={execution.succeeded_count}/252; failed={execution.failed_count}; "
                f"timed_out={execution.timed_out_count}"
            ),
        ),
        GateACheck(
            check_id="nonconstant_scientific_evidence",
            requirement="Each method has more than one distinct code-computed primary metric.",
            passed=nonconstant,
            observed=", ".join(
                f"{method_id}={count}" for method_id, count in sorted(nonconstant_by_method.items())
            ),
        ),
        GateACheck(
            check_id="structure_metric_coverage",
            requirement="Every successful discovered equation receives pinned-truth structure F1.",
            passed=structure_complete,
            observed=f"structure_scored={len(structure_scores)}/{successful_count}",
        ),
        GateACheck(
            check_id="core_metric_presence",
            requirement="Every method exposes derivative error, complexity, structure, robustness, and cost evidence.",
            passed=method_summary_presence and structure_complete,
            observed=(
                f"methods_with_successful_metric_records={sum(any(result.method_id == method.method_id and result.status is MDBenchAttemptState.SUCCEEDED for result in results) for method in matrix.methods)}/{len(matrix.methods)}"
            ),
        ),
        GateACheck(
            check_id="primary_relative_improvement",
            requirement="Unseen noisy median derivative NMSE improves by at least 5%.",
            passed=effect_pass,
            observed=(
                "unavailable"
                if observed is None
                else f"observed_success_median_relative_improvement={observed:.6f}"
            ),
        ),
        GateACheck(
            check_id="paired_bootstrap_confidence",
            requirement="Failure-aware system-level bootstrap 95% CI lower bound is greater than zero.",
            passed=ci_pass,
            observed=(
                f"CI95=[{primary.bootstrap_ci95_lower:.6f}, {primary.bootstrap_ci95_upper:.6f}]"
            ),
        ),
        GateACheck(
            check_id="frozen_causal_chain",
            requirement="Matrix, attempts, specs, logs, environment, and results retain their original hashes.",
            passed=True,
            observed=(
                f"matrix_hash={matrix.matrix_hash}, "
                f"environment_hash={execution.environment.environment_hash}"
            ),
        ),
    )


def _analysis_policy(candidate_method: str) -> dict[str, Any]:
    return {
        "schema_version": "mdbench-gate-a-analysis-policy-v1",
        "candidate_method": candidate_method,
        "primary_metric": _PRIMARY_METRIC,
        "primary_condition": _NOISY_CONDITION,
        "primary_evaluation_split": "unseen_test",
        "relative_improvement_threshold": _RELATIVE_IMPROVEMENT_THRESHOLD,
        "baseline_selection_rule": (
            "rank baselines on development SNR20 by successful-cell coverage descending, "
            "then successful derivative-NMSE median ascending, then method ID"
        ),
        "missing_cell_policy": (
            "require all three candidate and selected-baseline seeds per unseen system; "
            "otherwise assign zero system improvement"
        ),
        "bootstrap_unit": "unseen system",
        "bootstrap_statistic": "median relative improvement",
        "bootstrap_resamples": _BOOTSTRAP_RESAMPLES,
        "bootstrap_seed": _BOOTSTRAP_SEED,
        "structure_relative_coefficient_threshold": (_STRUCTURE_RELATIVE_COEFFICIENT_THRESHOLD),
        "structure_absolute_coefficient_threshold": (_STRUCTURE_ABSOLUTE_COEFFICIENT_THRESHOLD),
        "truth_source_revision": _TRUTH_SOURCE_REVISION,
        "truth_source_files": _TRUTH_SOURCE_FILES,
    }


def _equation_support(equation: str) -> dict[str, tuple[str, ...]]:
    support: dict[str, tuple[str, ...]] = {}
    for raw_line in equation.splitlines():
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        target, expression = (part.strip() for part in line.split("=", 1))
        try:
            tree = ast.parse(expression.replace("^", "**"), mode="eval")
            polynomial = _polynomial(tree.body)
        except (SyntaxError, ValueError, OverflowError) as exc:
            raise GateAAdjudicationError(
                f"cannot parse discovered equation for structure scoring: {line}: {exc}"
            ) from exc
        if not polynomial:
            support[target] = ()
            continue
        maximum = max(abs(value) for value in polynomial.values())
        threshold = max(
            _STRUCTURE_ABSOLUTE_COEFFICIENT_THRESHOLD,
            maximum * _STRUCTURE_RELATIVE_COEFFICIENT_THRESHOLD,
        )
        support[target] = tuple(
            sorted(
                _format_monomial(monomial)
                for monomial, coefficient in polynomial.items()
                if abs(coefficient) >= threshold
            )
        )
    if not support:
        raise GateAAdjudicationError("discovered equation contains no scored targets")
    return support


def _polynomial(node: ast.AST) -> Polynomial:
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        constant_value = float(node.value)
        if not math.isfinite(constant_value):
            raise ValueError("non-finite constant")
        return {(): constant_value}
    if isinstance(node, ast.Name):
        return {((node.id, 1),): 1.0}
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd | ast.USub):
        operand = _polynomial(node.operand)
        return operand if isinstance(node.op, ast.UAdd) else _scale_poly(operand, -1.0)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add | ast.Sub):
        left = _polynomial(node.left)
        right = _polynomial(node.right)
        return _add_poly(left, right, subtract=isinstance(node.op, ast.Sub))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        return _multiply_poly(_polynomial(node.left), _polynomial(node.right))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        numerator = _polynomial(node.left)
        denominator = _polynomial(node.right)
        if set(denominator) == {()} and denominator[()] != 0.0:
            return _scale_poly(numerator, 1.0 / denominator[()])
        return {_atomic_monomial(node): 1.0}
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
        exponent = _integer_literal(node.right)
        if exponent < 0 or exponent > 6:
            return {_atomic_monomial(node): 1.0}
        result: Polynomial = {(): 1.0}
        base = _polynomial(node.left)
        for _ in range(exponent):
            result = _multiply_poly(result, base)
        return result
    if isinstance(node, ast.Call):
        return {_atomic_monomial(node): 1.0}
    raise ValueError(f"unsupported expression node: {type(node).__name__}")


def _integer_literal(node: ast.AST) -> int:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    raise ValueError("power exponent is not an integer literal")


def _atomic_monomial(node: ast.AST) -> Monomial:
    rendered = ast.unparse(node).replace(" ", "").replace("**", "^")
    return ((rendered, 1),)


def _add_poly(left: Polynomial, right: Polynomial, *, subtract: bool) -> Polynomial:
    output = dict(left)
    sign = -1.0 if subtract else 1.0
    for monomial, coefficient in right.items():
        output[monomial] = output.get(monomial, 0.0) + sign * coefficient
    return _clean_poly(output)


def _scale_poly(polynomial: Polynomial, scalar: float) -> Polynomial:
    return _clean_poly(
        {monomial: coefficient * scalar for monomial, coefficient in polynomial.items()}
    )


def _multiply_poly(left: Polynomial, right: Polynomial) -> Polynomial:
    if len(left) * len(right) > 512:
        raise ValueError("expanded equation exceeds the bounded structure parser")
    output: Polynomial = {}
    for left_term, left_coefficient in left.items():
        for right_term, right_coefficient in right.items():
            powers: dict[str, int] = defaultdict(int)
            for name, exponent in left_term + right_term:
                powers[name] += exponent
            monomial = tuple(sorted(powers.items()))
            output[monomial] = output.get(monomial, 0.0) + left_coefficient * right_coefficient
    return _clean_poly(output)


def _clean_poly(polynomial: Polynomial) -> Polynomial:
    return {
        monomial: coefficient
        for monomial, coefficient in polynomial.items()
        if abs(coefficient) > 1e-15
    }


def _format_monomial(monomial: Monomial) -> str:
    if not monomial:
        return "1"
    return "*".join(name if exponent == 1 else f"{name}^{exponent}" for name, exponent in monomial)


def _required_metric(result: MDBenchAttemptResult, metric_name: str) -> float:
    value = getattr(result.metrics, metric_name)
    if value is None:
        raise GateAAdjudicationError(f"successful attempt lacks {metric_name}: {result.attempt_id}")
    return float(value)


def _median(values: list[float]) -> float | None:
    return float(statistics.median(values)) if values else None


def _bootstrap_median_ci(values: list[float]) -> tuple[float, float]:
    if not values:
        raise GateAAdjudicationError("bootstrap requires at least one system effect")
    generator = random.Random(_BOOTSTRAP_SEED)
    estimates = sorted(
        float(statistics.median(generator.choices(values, k=len(values))))
        for _ in range(_BOOTSTRAP_RESAMPLES)
    )
    return _quantile(estimates, 0.025), _quantile(estimates, 0.975)


def _quantile(sorted_values: list[float], probability: float) -> float:
    position = (len(sorted_values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    fraction = position - lower
    return sorted_values[lower] * (1.0 - fraction) + sorted_values[upper] * fraction


def _write_markdown(path: Path, report: MDBenchGateAReport) -> None:
    lines = [
        f"# MDBench Gate A: {report.decision.value}",
        "",
        f"- Matrix hash: `{report.matrix_hash}`",
        f"- Execution environment hash: `{report.execution_environment_hash}`",
        f"- Result-set hash: `{report.result_set_hash}`",
        f"- Report hash: `{report.report_hash}`",
        f"- Terminal cells: {report.total_attempt_count} "
        f"({report.succeeded_count} succeeded, {report.failed_count} failed, "
        f"{report.timed_out_count} timed out)",
        f"- Human scientific interventions: {report.human_intervention_count}",
        f"- Gate B allowed: `{str(report.gate_b_allowed).lower()}`",
        "",
        "## Gate checks",
        "",
        "| Check | Required | Passed | Observed |",
        "|---|---:|---:|---|",
    ]
    lines.extend(
        f"| `{check.check_id}` | {str(check.mandatory).lower()} | "
        f"{str(check.passed).lower()} | {check.observed.replace('|', '/')} |"
        for check in report.checks
    )
    lines.extend(
        [
            "",
            "## Method evidence",
            "",
            "| Method | Role | Success/total | Unseen noisy derivative NMSE | "
            "Structure F1 | Noise ratio | Complexity | Median seconds |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for summary in report.method_summaries:
        lines.append(
            f"| `{summary.method_id}` | {summary.role} | "
            f"{summary.succeeded_count}/{summary.terminal_count} | "
            f"{_format_optional(summary.unseen_noisy_derivative_nmse_median)} | "
            f"{_format_optional(summary.structure_f1_median)} | "
            f"{_format_optional(summary.noise_robustness_ratio_median)} | "
            f"{_format_optional(summary.unseen_noisy_model_complexity_median)} | "
            f"{_format_optional(summary.wall_time_seconds_median)} |"
        )
    primary = report.primary_comparison
    lines.extend(
        [
            "",
            "## Preregistered primary comparison",
            "",
            f"The development-set coverage-first rule selected `{primary.baseline_method_id}` "
            f"against candidate `{primary.candidate_method_id}`.",
            "",
            f"Observed successful-cell median relative improvement: "
            f"`{_format_optional(primary.observed_success_median_relative_improvement)}`.",
            f"Failure-aware unseen-system median relative improvement: "
            f"`{primary.failure_aware_system_median_relative_improvement:.6g}`.",
            f"System-level paired bootstrap 95% CI: "
            f"`[{primary.bootstrap_ci95_lower:.6g}, {primary.bootstrap_ci95_upper:.6g}]`.",
            "",
            "| Unseen system | Candidate successes | Baseline successes | "
            "Candidate NMSE | Baseline NMSE | Failure-aware improvement | Missing policy |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    lines.extend(
        f"| {effect.data_type}/{effect.system_name} | {effect.candidate_success_count}/3 | "
        f"{effect.baseline_success_count}/3 | "
        f"{_format_optional(effect.candidate_derivative_nmse_median)} | "
        f"{_format_optional(effect.baseline_derivative_nmse_median)} | "
        f"{effect.system_relative_improvement:.6g} | "
        f"{str(effect.missing_cell_policy_applied).lower()} |"
        for effect in primary.system_effects
    )
    if report.negative_reasons:
        lines.extend(["", "## Why Gate A is a negative result", ""])
        lines.extend(f"- {reason}" for reason in report.negative_reasons)
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in report.limitations)
    lines.extend(
        [
            "",
            "This report does not authorize RealPDEBench Gate B, external submission, "
            "or an award claim unless `gate_b_allowed=true`.",
            "",
        ]
    )
    _write_text_atomic(path, "\n".join(lines))


def _format_optional(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.6g}"


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
