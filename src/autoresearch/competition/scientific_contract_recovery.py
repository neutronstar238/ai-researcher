"""Result-blind Task 266 scientific-contract recovery plan.

The plan fixes the defect exposed by Task 265.3 without changing that run.  It
binds the immutable negative ledger, snapshots primary implementation and
license evidence, materializes analytic ODE/PDE sentinels, and freezes a
two-phase fit/freeze/predict contract before any new official score exists.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import subprocess
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import Field, ValidationError, model_validator

from autoresearch.competition.autonomous_development import (
    AutonomousDevelopmentSearchPackage,
    load_autonomous_development_search_package,
)
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import StrictFrozenModel

_PROTOCOL_ID = "mdbench-scientific-contract-recovery-v1"
_PLAN_NAME = "scientific-contract-recovery-plan.json"
_MARKDOWN_NAME = "scientific-contract-recovery-plan.md"
_BASELINE_PROBE_NAME = "baseline-probe.json"
_BENCHMARK_REVISION = "f81813e760325589737fe3311ac8199ecc64188a"
_PYSINDY_REVISION = "4c32d2603cbf1aa476efae72bc78436cb1e6fc75"
_IMAGE_NAME = "autoresearch-mdbench:task260"
_MAX_SOURCE_BYTES = 8 * 1024 * 1024
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_BASELINE_PROBE_PATH = (
    _REPOSITORY_ROOT
    / "deploy"
    / "experiments"
    / "mdbench"
    / "scientific_contract_baseline_probe.py"
)
_SCHEMA_MODELS: tuple[type[StrictFrozenModel], ...]

DataType = Literal["ode", "pde"]
AxisName = Literal["x", "y", "z"]
SourceKind = Literal["paper", "implementation", "license", "package_metadata"]
SourceFetcher = Callable[["ScientificContractSourceSpec", int], tuple[bytes, str, int]]
BaselineProbe = Callable[[str], "DomainBaselineProbe"]


def _registry_hash(items: Sequence[StrictFrozenModel]) -> str:
    return canonical_model_hash(
        {"items": [item.model_dump(mode="json") for item in items]}
    )


class ScientificContractRecoveryError(RuntimeError):
    """Raised when the recovery plan leaks, drifts, or lacks executable evidence."""


class ScientificContractSourceSpec(StrictFrozenModel):
    """One primary source and the only design claim it may support."""

    source_id: str
    kind: SourceKind
    title: str
    url: str
    required_marker: str
    revision: str | None = None
    license_spdx: str | None = None
    supports_claim: str


_SOURCE_SPECS: tuple[ScientificContractSourceSpec, ...] = (
    ScientificContractSourceSpec(
        source_id="mdbench-paper",
        kind="paper",
        title="MDBench: Benchmarking Data-Driven Methods for Model Discovery",
        url="https://arxiv.org/abs/2509.20529",
        required_marker="MDBench: Benchmarking Data-Driven Methods",
        supports_claim=(
            "MDBench evaluates ODE and PDE discovery separately and reports that linear "
            "methods generally have lower PDE prediction error while GP is strong on ODEs."
        ),
    ),
    ScientificContractSourceSpec(
        source_id="mdbench-fit-predict-interface",
        kind="implementation",
        title="Pinned MDBench method interface",
        url=(
            "https://raw.githubusercontent.com/gryaklab/mdbench/"
            f"{_BENCHMARK_REVISION}/README.md"
        ),
        required_marker="fit(t_train, u_train, u_dot_train)",
        revision=_BENCHMARK_REVISION,
        supports_claim=(
            "The official method contract separates fit, predict, complexity, and to_str; "
            "a stateless query-only candidate is not benchmark-equivalent."
        ),
    ),
    ScientificContractSourceSpec(
        source_id="mdbench-license",
        kind="license",
        title="Pinned MDBench MIT license",
        url=(
            "https://raw.githubusercontent.com/gryaklab/mdbench/"
            f"{_BENCHMARK_REVISION}/LICENSE"
        ),
        required_marker="MIT License",
        revision=_BENCHMARK_REVISION,
        license_spdx="MIT",
        supports_claim="The pinned official baseline wrappers may be executed as MIT software.",
    ),
    ScientificContractSourceSpec(
        source_id="pysindy-paper",
        kind="paper",
        title="PySINDy: A comprehensive Python package for robust system identification",
        url="https://arxiv.org/abs/2111.08481",
        required_marker="PySINDy",
        supports_claim=(
            "PySINDy supplies explicit sparse ODE/PDE libraries and fitted coefficient models."
        ),
    ),
    ScientificContractSourceSpec(
        source_id="pysindy-license",
        kind="license",
        title="Pinned PySINDy MIT license",
        url=(
            "https://raw.githubusercontent.com/dynamicslab/pysindy/"
            f"{_PYSINDY_REVISION}/LICENSE"
        ),
        required_marker="MIT License",
        revision=_PYSINDY_REVISION,
        license_spdx="MIT",
        supports_claim="The exact PySINDy 1.7.5 dependency lineage is MIT licensed.",
    ),
    ScientificContractSourceSpec(
        source_id="pysindy-weak-library",
        kind="implementation",
        title="Pinned PySINDy WeakPDELibrary implementation",
        url=(
            "https://raw.githubusercontent.com/dynamicslab/pysindy/"
            f"{_PYSINDY_REVISION}/pysindy/feature_library/weak_pde_library.py"
        ),
        required_marker="class WeakPDELibrary",
        revision=_PYSINDY_REVISION,
        supports_claim=(
            "Weak-form projection is an admissible generated mechanism, but it must still "
            "produce a concrete frozen equation and independent predictions."
        ),
    ),
    ScientificContractSourceSpec(
        source_id="pyoperon-implementation",
        kind="implementation",
        title="PyOperon v0.5.0 implementation",
        url=(
            "https://raw.githubusercontent.com/heal-research/pyoperon/"
            "v0.5.0/README.md"
        ),
        required_marker="scikit-learn regressor",
        revision="v0.5.0",
        supports_claim="The pinned ODE comparator exposes a fitted symbolic regressor.",
    ),
    ScientificContractSourceSpec(
        source_id="pyoperon-license",
        kind="license",
        title="PyOperon v0.5.0 MIT license",
        url=(
            "https://raw.githubusercontent.com/heal-research/pyoperon/"
            "v0.5.0/LICENSE"
        ),
        required_marker="MIT License",
        revision="v0.5.0",
        license_spdx="MIT",
        supports_claim="The exact PyOperon release is MIT licensed.",
    ),
    ScientificContractSourceSpec(
        source_id="pyoperon-pypi-0.5.0",
        kind="package_metadata",
        title="PyPI metadata for pyoperon 0.5.0",
        url="https://pypi.org/pypi/pyoperon/0.5.0/json",
        required_marker="0.5.0",
        revision="0.5.0",
        license_spdx="MIT",
        supports_claim=(
            "The container dependency version and Python 3.9 wheel line are publicly resolvable."
        ),
    ),
)


class ScientificContractSourceSnapshot(StrictFrozenModel):
    """Content-addressed live snapshot of one source."""

    source_id: str
    kind: SourceKind
    title: str
    source_url: str
    final_url: str
    status_code: int = Field(ge=200, le=299)
    required_marker: str
    marker_verified: Literal[True] = True
    revision: str | None = None
    license_spdx: str | None = None
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_relative_path: str
    retrieved_at: datetime
    primary_source: Literal[True] = True
    redistribution_authorized: Literal[False] = False
    supports_claim: str


class TensorPayload(StrictFrozenModel):
    """Finite row-major tensor stored without a scientific dependency."""

    shape: tuple[int, ...] = Field(min_length=1)
    values: tuple[float, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_tensor(self) -> TensorPayload:
        if any(size < 1 for size in self.shape):
            raise ValueError("tensor dimensions must be positive")
        if math.prod(self.shape) != len(self.values):
            raise ValueError("tensor value count differs from its shape")
        if any(not math.isfinite(value) for value in self.values):
            raise ValueError("tensor contains a non-finite value")
        return self


class EquationFactor(StrictFrozenModel):
    """One state factor or spatial derivative in an explicit equation term."""

    field: str = Field(pattern=r"^u[0-9]+$")
    derivative_axes: tuple[AxisName, ...] = ()
    power: int = Field(default=1, ge=1, le=6)


class EquationTerm(StrictFrozenModel):
    """Concrete numeric coefficient times one or more explicit factors."""

    coefficient: float = Field(allow_inf_nan=False)
    factors: tuple[EquationFactor, ...] = Field(min_length=1, max_length=6)


class ConcreteEquation(StrictFrozenModel):
    """One target derivative with only numeric coefficients and typed terms."""

    target: str = Field(pattern=r"^u[0-9]+_t$")
    intercept: float = Field(default=0.0, allow_inf_nan=False)
    terms: tuple[EquationTerm, ...] = Field(min_length=1, max_length=64)


class SentinelQuery(StrictFrozenModel):
    """One target-free query and evaluator-owned expected derivative."""

    query_id: str
    time: float = Field(allow_inf_nan=False)
    state: TensorPayload
    expected_derivative: TensorPayload

    @model_validator(mode="after")
    def _validate_query(self) -> SentinelQuery:
        if self.state.shape != self.expected_derivative.shape:
            raise ValueError("query state and derivative shapes differ")
        return self


class ScientificSentinelFixture(StrictFrozenModel):
    """Analytic fit-once/query-many fixture plus controls."""

    schema_version: Literal["scientific-sentinel-fixture-v1"] = (
        "scientific-sentinel-fixture-v1"
    )
    sentinel_id: str
    data_type: DataType
    spatial_dimensions: int = Field(ge=0, le=3)
    field_names: tuple[str, ...] = Field(min_length=1, max_length=6)
    spatial_coordinates: dict[AxisName, tuple[float, ...]]
    train_times: tuple[float, ...] = Field(min_length=6)
    train_state: TensorPayload
    train_derivative: TensorPayload
    alternative_train_state: TensorPayload
    alternative_train_derivative: TensorPayload
    train_derivative_shuffle_order: tuple[int, ...]
    expected_equations: tuple[ConcreteEquation, ...]
    alternative_expected_equations: tuple[ConcreteEquation, ...]
    queries: tuple[SentinelQuery, SentinelQuery, SentinelQuery]
    term_support_f1_minimum: float = 1.0
    coefficient_relative_error_maximum: float = 0.05
    prediction_nmse_maximum: float = 1e-6
    equation_prediction_max_abs_delta: float = 1e-9
    zero_null_relative_improvement_minimum: float = 0.5
    shuffled_nmse_ratio_minimum: float = 5.0
    fit_call_count_required: Literal[1] = 1
    minimum_query_count: Literal[3] = 3
    fixture_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_fixture(self) -> ScientificSentinelFixture:
        expected_dimensions = 0 if self.data_type == "ode" else self.spatial_dimensions
        if self.data_type == "ode" and self.spatial_dimensions != 0:
            raise ValueError("ODE sentinel cannot declare spatial dimensions")
        if self.data_type == "pde" and expected_dimensions < 1:
            raise ValueError("PDE sentinel needs at least one spatial dimension")
        if len(self.spatial_coordinates) != expected_dimensions:
            raise ValueError("sentinel spatial-coordinate count mismatch")
        if len(self.expected_equations) != len(self.field_names):
            raise ValueError("sentinel needs one equation per field")
        if len(self.alternative_expected_equations) != len(self.field_names):
            raise ValueError("alternative sentinel needs one equation per field")
        if self.train_state.shape != self.train_derivative.shape:
            raise ValueError("sentinel train state and derivative shapes differ")
        if self.alternative_train_state.shape != self.alternative_train_derivative.shape:
            raise ValueError("alternative sentinel state and derivative shapes differ")
        if self.train_state.shape != self.alternative_train_state.shape:
            raise ValueError("primary and alternative sentinel shapes differ")
        expected_rows = math.prod(self.train_state.shape[:-1])
        if sorted(self.train_derivative_shuffle_order) != list(range(expected_rows)):
            raise ValueError("shuffle order is not a complete row permutation")
        thresholds = (
            self.term_support_f1_minimum,
            self.coefficient_relative_error_maximum,
            self.prediction_nmse_maximum,
            self.equation_prediction_max_abs_delta,
            self.zero_null_relative_improvement_minimum,
            self.shuffled_nmse_ratio_minimum,
        )
        if thresholds != (1.0, 0.05, 1e-6, 1e-9, 0.5, 5.0):
            raise ValueError("scientific sentinel thresholds changed")
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"fixture_hash"})
        )
        if self.fixture_hash != expected:
            raise ValueError("scientific sentinel fixture hash mismatch")
        return self


class ScientificFitRequest(StrictFrozenModel):
    """Candidate-visible fit request; all values belong to train context."""

    schema_version: Literal["scientific-fit-request-v1"] = "scientific-fit-request-v1"
    fit_id: str
    candidate_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sentinel_id: str
    data_type: DataType
    field_names: tuple[str, ...]
    spatial_coordinates: dict[AxisName, tuple[float, ...]]
    train_times: tuple[float, ...]
    train_state: TensorPayload
    train_derivative: TensorPayload
    training_context_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class EquationFieldScaling(StrictFrozenModel):
    """Per-field affine scaling provenance for a physical-unit equation."""

    field: str = Field(pattern=r"^u[0-9]+$")
    state_offset: float = Field(allow_inf_nan=False)
    state_scale: float = Field(gt=0, allow_inf_nan=False)
    derivative_offset: float = Field(allow_inf_nan=False)
    derivative_scale: float = Field(gt=0, allow_inf_nan=False)


class EquationFitDiagnostics(StrictFrozenModel):
    """Bounded numeric diagnostics retained from the train-only fit."""

    solver_id: str = Field(min_length=1, max_length=128)
    training_sample_count: int = Field(ge=1)
    design_feature_count: int = Field(ge=1)
    selected_term_count: int = Field(ge=1)
    training_nmse: float = Field(ge=0, allow_inf_nan=False)
    fit_wall_seconds: float = Field(ge=0, allow_inf_nan=False)
    warnings: tuple[str, ...] = Field(default=(), max_length=32)


class FrozenEquationArtifact(StrictFrozenModel):
    """Serializable learned law frozen before any validation/test query."""

    schema_version: Literal["frozen-equation-artifact-v1"] = (
        "frozen-equation-artifact-v1"
    )
    fit_id: str
    candidate_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_context_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    data_type: DataType
    field_names: tuple[str, ...]
    equations: tuple[ConcreteEquation, ...]
    equation_coordinate_system: Literal["physical-unscaled-v1"] = (
        "physical-unscaled-v1"
    )
    field_scaling: tuple[EquationFieldScaling, ...]
    diagnostics: EquationFitDiagnostics
    fit_call_count: Literal[1] = 1
    fit_completed_before_query: Literal[True] = True
    free_symbol_count: Literal[0] = 0
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_artifact(self) -> FrozenEquationArtifact:
        if len(self.equations) != len(self.field_names):
            raise ValueError("frozen artifact needs one concrete equation per field")
        if tuple(item.field for item in self.field_scaling) != self.field_names:
            raise ValueError("field scaling must match artifact field order exactly")
        selected_term_count = sum(len(equation.terms) for equation in self.equations)
        if self.diagnostics.selected_term_count != selected_term_count:
            raise ValueError("diagnostic selected-term count differs from equations")
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"artifact_hash"})
        )
        if self.artifact_hash != expected:
            raise ValueError("frozen equation artifact hash mismatch")
        return self


class ScientificPredictRequest(StrictFrozenModel):
    """Target-free query against one already-frozen learned artifact."""

    schema_version: Literal["scientific-predict-request-v1"] = (
        "scientific-predict-request-v1"
    )
    query_id: str
    artifact: FrozenEquationArtifact
    time: float = Field(allow_inf_nan=False)
    spatial_coordinates: dict[AxisName, tuple[float, ...]]
    state: TensorPayload
    expected_derivative_present: Literal[False] = False


class ScientificPredictResponse(StrictFrozenModel):
    """Prediction plus telemetry proving no fit occurred after the query."""

    schema_version: Literal["scientific-predict-response-v1"] = (
        "scientific-predict-response-v1"
    )
    query_id: str
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    derivative_prediction: TensorPayload
    fit_calls_during_prediction: Literal[0] = 0
    artifact_mutation_count: Literal[0] = 0
    equation_evaluator_id: Literal["trusted-equation-evaluator-v1"] = (
        "trusted-equation-evaluator-v1"
    )


_SCHEMA_MODELS = (
    ScientificFitRequest,
    FrozenEquationArtifact,
    ScientificPredictRequest,
    ScientificPredictResponse,
)


class ContractSchemaArtifact(StrictFrozenModel):
    """One persisted JSON Schema and its byte hash."""

    model_name: str
    relative_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SentinelArtifact(StrictFrozenModel):
    """One persisted analytic sentinel and its identity."""

    sentinel_id: str
    data_type: DataType
    spatial_dimensions: int = Field(ge=0, le=3)
    field_count: int = Field(ge=1, le=6)
    relative_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fixture_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class DomainBaselineProbeResult(StrictFrozenModel):
    """One implementation-level synthetic baseline probe."""

    baseline_id: Literal["operon_gp_ode", "pdefind_pde"]
    data_type: DataType
    spatial_dimensions: int | None = Field(default=None, ge=1, le=3)
    dependency: str
    dependency_version: str
    implementation_module: str
    implementation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fit_predict_nmse: float = Field(ge=0, allow_inf_nan=False)
    prediction_shape: list[int] | None = None
    equation: str
    model_complexity: int = Field(ge=1)
    synthetic_only: Literal[True] = True
    passed: Literal[True] = True


class DomainBaselineProbe(StrictFrozenModel):
    """Offline image and dependency evidence for both domain comparators."""

    schema_version: Literal["domain-baseline-probe-v1"] = "domain-baseline-probe-v1"
    image: str
    image_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    benchmark_revision: Literal["f81813e760325589737fe3311ac8199ecc64188a"] = (
        "f81813e760325589737fe3311ac8199ecc64188a"
    )
    probe_runner_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    python_version: Literal["3.9.23"] = "3.9.23"
    dependencies: dict[str, str]
    network_used: Literal[False] = False
    official_artifact_reads: Literal[0] = 0
    probes: tuple[
        DomainBaselineProbeResult,
        DomainBaselineProbeResult,
        DomainBaselineProbeResult,
    ]
    passed: Literal[True] = True
    probe_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_probe(self) -> DomainBaselineProbe:
        if self.dependencies != {
            "numpy": "1.26.4",
            "pyoperon": "0.5.0",
            "pysindy": "1.7.5",
            "scikit_learn": "1.5.2",
            "scipy": "1.13.1",
        }:
            raise ValueError("domain baseline dependency floor changed")
        identities = [
            (item.baseline_id, item.spatial_dimensions) for item in self.probes
        ]
        if identities != [
            ("operon_gp_ode", None),
            ("pdefind_pde", 2),
            ("pdefind_pde", 3),
        ]:
            raise ValueError("domain baseline probe coverage changed")
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"probe_hash"})
        )
        if self.probe_hash != expected:
            raise ValueError("domain baseline probe hash mismatch")
        return self


class DomainBaselineSpec(StrictFrozenModel):
    """Applicable strongest comparator under the common resource envelope."""

    baseline_id: Literal["operon_gp_ode", "pdefind_pde"]
    data_type: DataType
    family: Literal["genetic_symbolic", "sparse_linear"]
    implementation: str
    source_ids: tuple[str, ...]
    dependency_versions: dict[str, str]
    spatial_dimensions: tuple[int, ...]
    multi_field_supported: bool
    maximum_seconds: Literal[300] = 300
    maximum_cpu_cores: Literal[2] = 2
    maximum_memory_mb: Literal[4096] = 4096
    required_methods: tuple[Literal["fit", "predict", "complexity", "to_str"], ...] = (
        "fit",
        "predict",
        "complexity",
        "to_str",
    )
    license_spdx: Literal["MIT"] = "MIT"
    baseline_failure_policy: Literal[
        "any required baseline cell failure blocks receipt; never impute candidate advantage"
    ] = "any required baseline cell failure blocks receipt; never impute candidate advantage"


class ScientificContractGate(StrictFrozenModel):
    """Frozen pre-official-score admission rules for Task 266.2 candidates."""

    concrete_numeric_equations_required: Literal[True] = True
    free_symbol_count_maximum: Literal[0] = 0
    term_support_f1_minimum: float = 1.0
    clean_coefficient_relative_error_maximum: float = 0.05
    clean_prediction_nmse_maximum: float = 1e-6
    equation_prediction_max_abs_delta: float = 1e-9
    zero_null_relative_improvement_minimum: float = 0.5
    shuffled_nmse_ratio_minimum: float = 5.0
    artifact_hash_must_change_on_alternative_training: Literal[True] = True
    fit_call_count: Literal[1] = 1
    fit_calls_during_prediction: Literal[0] = 0
    minimum_queries_per_fit: Literal[3] = 3
    query_contains_target_derivative: Literal[False] = False
    query_time_slices: Literal[1] = 1
    required_capabilities: tuple[str, ...] = (
        "ode",
        "pde_1d_advection",
        "pde_1d_diffusion",
        "pde_2d",
        "pde_3d",
        "pde_multi_field",
    )
    maximum_fit_seconds_per_sentinel: Literal[20] = 20
    maximum_predict_seconds_per_query: Literal[2] = 2
    maximum_memory_mb: Literal[512] = 512
    network_default_deny: Literal[True] = True
    official_development_results_allowed: Literal[0] = 0

    @model_validator(mode="after")
    def _validate_numeric_thresholds(self) -> ScientificContractGate:
        thresholds = (
            self.term_support_f1_minimum,
            self.clean_coefficient_relative_error_maximum,
            self.clean_prediction_nmse_maximum,
            self.equation_prediction_max_abs_delta,
            self.zero_null_relative_improvement_minimum,
            self.shuffled_nmse_ratio_minimum,
        )
        if thresholds != (1.0, 0.05, 1e-6, 1e-9, 0.5, 5.0):
            raise ValueError("scientific-contract thresholds changed")
        return self


class RecoverySearchBudget(StrictFrozenModel):
    """Two-generation budget fixed before Task 266.3 scores exist."""

    initial_candidate_count: Literal[8] = 8
    minimum_mechanism_family_count: Literal[3] = 3
    maximum_total_candidate_count: Literal[12] = 12
    maximum_generations: Literal[2] = 2
    maximum_synthetic_revisions_per_candidate: Literal[6] = 6
    maximum_mechanism_cycles: Literal[4] = 4
    pilot_ode_system_count: Literal[3] = 3
    pilot_pde_system_count: Literal[3] = 3
    pilot_conditions: tuple[Literal["clean", "snr_20"], ...] = ("clean", "snr_20")
    pilot_seed_count: Literal[1] = 1
    pilot_candidate_cell_budget: Literal[96] = 96
    mechanism_ode_system_count: Literal[2] = 2
    mechanism_pde_system_count: Literal[2] = 2
    mechanism_conditions: tuple[Literal["clean", "snr_20"], ...] = (
        "clean",
        "snr_20",
    )
    matched_cells_per_cycle: Literal[8] = 8
    maximum_mechanism_candidate_cell_budget: Literal[32] = 32
    full_finalist_count: Literal[3] = 3
    full_units_per_candidate: Literal[84] = 84
    full_candidate_cell_budget: Literal[252] = 252
    domain_baseline_cell_budget: Literal[84] = 84
    maximum_official_candidate_cells: Literal[380] = 380
    maximum_official_cells_total: Literal[464] = 464
    maximum_model_interactions: Literal[80] = 80
    maximum_parallel_cells: Literal[4] = 4
    maximum_seconds_per_cell: Literal[300] = 300
    maximum_cpu_cores_per_cell: Literal[2] = 2
    maximum_memory_mb_per_cell: Literal[4096] = 4096


class PowerAuditPoint(StrictFrozenModel):
    """Exact sign-gate probability under a stated per-system direction probability."""

    positive_system_probability: float = Field(gt=0, lt=1)
    probability_at_least_12_of_14_positive: float = Field(ge=0, le=1)
    probability_all_4_pde_positive: float = Field(ge=0, le=1)


class RecoveryPowerAudit(StrictFrozenModel):
    """Prospective limitation audit; not a post-hoc significance calculation."""

    independent_system_count: Literal[14] = 14
    ode_system_count: Literal[10] = 10
    pde_system_count: Literal[4] = 4
    conditions_per_system: Literal[2] = 2
    seeds_per_condition: Literal[3] = 3
    independent_unit: Literal[
        "system; condition and seed cells are repeated measures within system"
    ] = "system; condition and seed cells are repeated measures within system"
    power_surrogate: Literal[
        "exact probability of at least 12 positive systems out of 14"
    ] = "exact probability of at least 12 positive systems out of 14"
    points: tuple[PowerAuditPoint, ...]
    pde_limitation: Literal[
        "four PDE systems support a directional qualification gate, not a standalone PDE significance claim"
    ] = (
        "four PDE systems support a directional qualification gate, not a standalone PDE significance claim"
    )
    development_interval_scope: Literal[
        "exploratory selection evidence only; never publication significance"
    ] = "exploratory selection evidence only; never publication significance"


class RecoveryEstimand(StrictFrozenModel):
    """Failure-aware domain-stratified development estimand and receipt rule."""

    cell_loss: Literal["derivative_nmse"] = "derivative_nmse"
    finite_loss_floor: float = 1e-12
    finite_loss_cap: float = 1e12
    candidate_failure_loss: float = 1e12
    paired_effect: Literal[
        "log((baseline_nmse_clipped)/(candidate_nmse_clipped))"
    ] = "log((baseline_nmse_clipped)/(candidate_nmse_clipped))"
    repeated_measure_aggregation: Literal[
        "median over condition and seed cells within each system"
    ] = "median over condition and seed cells within each system"
    system_aggregation: Literal["median over independent systems"] = (
        "median over independent systems"
    )
    uncertainty: Literal[
        "2000 fixed-seed bootstrap resamples over independent systems"
    ] = "2000 fixed-seed bootstrap resamples over independent systems"
    minimum_overall_log_effect: float = Field(default=-math.log(0.95), gt=0)
    exploratory_lower_bound_minimum: float = 0.0
    ode_stratum_median_minimum: float = 0.0
    pde_stratum_median_minimum: float = 0.0
    all_candidate_full_cells_must_succeed: Literal[True] = True
    all_domain_baseline_cells_must_succeed: Literal[True] = True
    all_scientific_contract_gates_must_pass: Literal[True] = True
    receipt_if_and_only_if_all_checks_pass: Literal[True] = True
    original_confirmation_relative_improvement_gate: float = 0.05
    original_confirmation_lower_bound_gate: float = 0.0

    @model_validator(mode="after")
    def _validate_numeric_thresholds(self) -> RecoveryEstimand:
        if (
            self.finite_loss_floor != 1e-12
            or self.finite_loss_cap != 1e12
            or self.candidate_failure_loss != 1e12
            or not math.isclose(self.minimum_overall_log_effect, -math.log(0.95))
            or self.exploratory_lower_bound_minimum != 0.0
            or self.ode_stratum_median_minimum != 0.0
            or self.pde_stratum_median_minimum != 0.0
            or self.original_confirmation_relative_improvement_gate != 0.05
            or self.original_confirmation_lower_bound_gate != 0.0
        ):
            raise ValueError("recovery estimand thresholds changed")
        return self


class NegativeDevelopmentBinding(StrictFrozenModel):
    """Immutable parent ledger and explicit confirmation-denial evidence."""

    package_path: str
    package_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    identity_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    development_result_set_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_candidate_id: str
    selected_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["autonomous_development_negative_stop"] = (
        "autonomous_development_negative_stop"
    )
    search_freeze_receipt_created: Literal[False] = False
    confirmation_identity_read_count: Literal[0] = 0
    confirmation_result_count: Literal[0] = 0
    system_generated_manuscript_count: Literal[0] = 0
    parent_mutation_allowed: Literal[False] = False


class ScientificContractRecoveryPlan(StrictFrozenModel):
    """Terminal Task 266.1 plan; authorizes only score-blind Harness implementation."""

    schema_version: Literal["scientific-contract-recovery-plan-v1"] = (
        "scientific-contract-recovery-plan-v1"
    )
    protocol_id: Literal["mdbench-scientific-contract-recovery-v1"] = (
        "mdbench-scientific-contract-recovery-v1"
    )
    negative_binding: NegativeDevelopmentBinding
    sources: tuple[ScientificContractSourceSnapshot, ...]
    source_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    schemas: tuple[ContractSchemaArtifact, ...]
    schema_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    sentinels: tuple[SentinelArtifact, ...]
    sentinel_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_probe: DomainBaselineProbe
    baselines: tuple[DomainBaselineSpec, DomainBaselineSpec]
    baseline_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    contract_gate: ScientificContractGate
    search_budget: RecoverySearchBudget
    estimand: RecoveryEstimand
    power_audit: RecoveryPowerAudit
    result_blind_freeze: Literal[True] = True
    new_official_development_result_count: Literal[0] = 0
    confirmation_identity_read_count: Literal[0] = 0
    confirmation_result_count: Literal[0] = 0
    candidate_answer_count: Literal[0] = 0
    model_interaction_count: Literal[0] = 0
    harness_implementation_authorized: Literal[True] = True
    official_development_execution_authorized: Literal[False] = False
    confirmation_authorized: Literal[False] = False
    manuscript_authorized: Literal[False] = False
    publication_ready: Literal[False] = False
    public_release_authorized: Literal[False] = False
    submission_authorized: Literal[False] = False
    next_required_task: Literal["266.2"] = "266.2"
    created_at: datetime
    output_path: str
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_plan(self) -> ScientificContractRecoveryPlan:
        if len(self.sources) != len(_SOURCE_SPECS):
            raise ValueError("scientific-contract source registry is incomplete")
        if self.source_registry_hash != _registry_hash(self.sources):
            raise ValueError("scientific-contract source registry hash mismatch")
        if self.schema_registry_hash != _registry_hash(self.schemas):
            raise ValueError("scientific-contract schema registry hash mismatch")
        if self.sentinel_registry_hash != _registry_hash(self.sentinels):
            raise ValueError("scientific sentinel registry hash mismatch")
        if self.baseline_registry_hash != _registry_hash(self.baselines):
            raise ValueError("domain baseline registry hash mismatch")
        if [(item.baseline_id, item.data_type) for item in self.baselines] != [
            ("operon_gp_ode", "ode"),
            ("pdefind_pde", "pde"),
        ]:
            raise ValueError("domain baseline routing changed")
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"plan_hash", "output_path"})
        )
        if self.plan_hash != expected:
            raise ValueError("scientific-contract recovery plan hash mismatch")
        return self


def freeze_scientific_contract_recovery_plan(
    negative_package_path: Path | str,
    output_dir: Path | str,
    *,
    image: str = _IMAGE_NAME,
    timeout_seconds: int = 30,
    source_fetcher: SourceFetcher | None = None,
    baseline_probe: BaselineProbe | None = None,
    clock: Callable[[], datetime] | None = None,
) -> ScientificContractRecoveryPlan:
    """Freeze Task 266.1 without opening confirmation or new development results."""

    root = Path(output_dir).resolve()
    plan_path = root / _PLAN_NAME
    if plan_path.is_file():
        return load_scientific_contract_recovery_plan(plan_path)
    if root.exists() and any(root.iterdir()):
        raise ScientificContractRecoveryError(
            "refusing a non-empty unbound Task 266.1 directory; retain it as failure evidence"
        )
    package = load_autonomous_development_search_package(negative_package_path)
    _validate_negative_parent(package)
    root.mkdir(parents=True, exist_ok=True)
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    fetcher = source_fetcher or _fetch_source
    sources = _snapshot_sources(root, fetcher, timeout_seconds, now)
    schemas = _materialize_schemas(root)
    sentinels = _materialize_sentinels(root)
    probe = (baseline_probe or probe_domain_baselines)(image)
    write_json_model(root / _BASELINE_PROBE_NAME, probe)
    baselines = _baseline_specs(probe)
    binding = NegativeDevelopmentBinding(
        package_path=Path(negative_package_path).resolve().as_posix(),
        package_hash=package.package_hash,
        identity_hash=package.identity.identity_hash,
        development_result_set_hash=package.development_result_set_hash,
        selected_candidate_id=package.selection.selected_candidate_id,
        selected_source_sha256=package.selection.selected_source_sha256,
    )
    payload: dict[str, Any] = {
        "schema_version": "scientific-contract-recovery-plan-v1",
        "protocol_id": _PROTOCOL_ID,
        "negative_binding": binding.model_dump(mode="json"),
        "sources": [item.model_dump(mode="json") for item in sources],
        "source_registry_hash": _registry_hash(sources),
        "schemas": [item.model_dump(mode="json") for item in schemas],
        "schema_registry_hash": _registry_hash(schemas),
        "sentinels": [item.model_dump(mode="json") for item in sentinels],
        "sentinel_registry_hash": _registry_hash(sentinels),
        "baseline_probe": probe.model_dump(mode="json"),
        "baselines": [item.model_dump(mode="json") for item in baselines],
        "baseline_registry_hash": _registry_hash(baselines),
        "contract_gate": ScientificContractGate().model_dump(mode="json"),
        "search_budget": RecoverySearchBudget().model_dump(mode="json"),
        "estimand": RecoveryEstimand().model_dump(mode="json"),
        "power_audit": _power_audit().model_dump(mode="json"),
        "result_blind_freeze": True,
        "new_official_development_result_count": 0,
        "confirmation_identity_read_count": 0,
        "confirmation_result_count": 0,
        "candidate_answer_count": 0,
        "model_interaction_count": 0,
        "harness_implementation_authorized": True,
        "official_development_execution_authorized": False,
        "confirmation_authorized": False,
        "manuscript_authorized": False,
        "publication_ready": False,
        "public_release_authorized": False,
        "submission_authorized": False,
        "next_required_task": "266.2",
        "created_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "output_path": plan_path.as_posix(),
    }
    payload["plan_hash"] = canonical_model_hash(
        {key: value for key, value in payload.items() if key != "output_path"}
    )
    plan = ScientificContractRecoveryPlan.model_validate(payload)
    write_json_model(plan_path, plan)
    (root / _MARKDOWN_NAME).write_text(_render_markdown(plan), encoding="utf-8")
    return load_scientific_contract_recovery_plan(plan_path)


def load_scientific_contract_recovery_plan(
    path: Path | str,
) -> ScientificContractRecoveryPlan:
    """Strictly load and recursively verify one Task 266.1 plan."""

    plan_path = Path(path).resolve()
    try:
        plan = ScientificContractRecoveryPlan.model_validate_json(
            plan_path.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as exc:
        raise ScientificContractRecoveryError(
            f"cannot load scientific-contract recovery plan: {exc}"
        ) from exc
    if Path(plan.output_path).resolve() != plan_path:
        raise ScientificContractRecoveryError("scientific-contract output path changed")
    root = plan_path.parent
    package = load_autonomous_development_search_package(
        plan.negative_binding.package_path
    )
    _validate_negative_parent(package)
    if (
        package.package_hash != plan.negative_binding.package_hash
        or package.identity.identity_hash != plan.negative_binding.identity_hash
        or package.development_result_set_hash
        != plan.negative_binding.development_result_set_hash
    ):
        raise ScientificContractRecoveryError("negative parent binding changed")
    expected_files = {_PLAN_NAME, _MARKDOWN_NAME, _BASELINE_PROBE_NAME}
    for source in plan.sources:
        source_path = _inside(root, source.snapshot_relative_path)
        if _sha256_file(source_path) != source.content_sha256:
            raise ScientificContractRecoveryError(
                f"scientific-contract source snapshot changed: {source.source_id}"
            )
        expected_files.add(source.snapshot_relative_path)
    for schema in plan.schemas:
        schema_path = _inside(root, schema.relative_path)
        if _sha256_file(schema_path) != schema.sha256:
            raise ScientificContractRecoveryError(
                f"scientific-contract schema changed: {schema.model_name}"
            )
        expected_files.add(schema.relative_path)
    for sentinel in plan.sentinels:
        sentinel_path = _inside(root, sentinel.relative_path)
        if _sha256_file(sentinel_path) != sentinel.sha256:
            raise ScientificContractRecoveryError(
                f"scientific sentinel changed: {sentinel.sentinel_id}"
            )
        try:
            fixture = ScientificSentinelFixture.model_validate_json(
                sentinel_path.read_text(encoding="utf-8")
            )
        except (OSError, ValidationError) as exc:
            raise ScientificContractRecoveryError(
                f"invalid scientific sentinel {sentinel.sentinel_id}: {exc}"
            ) from exc
        if fixture.fixture_hash != sentinel.fixture_hash:
            raise ScientificContractRecoveryError(
                f"scientific sentinel identity changed: {sentinel.sentinel_id}"
            )
        expected_files.add(sentinel.relative_path)
    probe_path = root / _BASELINE_PROBE_NAME
    try:
        persisted_probe = DomainBaselineProbe.model_validate_json(
            probe_path.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as exc:
        raise ScientificContractRecoveryError(f"invalid baseline probe: {exc}") from exc
    if persisted_probe != plan.baseline_probe:
        raise ScientificContractRecoveryError("baseline probe differs from plan")
    actual_files = {
        item.relative_to(root).as_posix() for item in root.rglob("*") if item.is_file()
    }
    if actual_files != expected_files:
        raise ScientificContractRecoveryError(
            "scientific-contract package file set changed: "
            f"missing={sorted(expected_files - actual_files)} "
            f"extra={sorted(actual_files - expected_files)}"
        )
    return plan


def probe_domain_baselines(image: str = _IMAGE_NAME) -> DomainBaselineProbe:
    """Probe exact ODE/PDE baseline implementations using only synthetic data."""

    if not _BASELINE_PROBE_PATH.is_file():
        raise ScientificContractRecoveryError(
            f"domain baseline probe runner is missing: {_BASELINE_PROBE_PATH}"
        )
    try:
        inspected = subprocess.run(
            ["docker", "image", "inspect", image],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        records = json.loads(inspected.stdout)
        if not isinstance(records, list) or len(records) != 1:
            raise ValueError("Docker image inspection returned an invalid record set")
        image_record = records[0]
        image_id = str(image_record["Id"])
        labels = image_record.get("Config", {}).get("Labels", {}) or {}
        benchmark_revision = str(labels.get("org.opencontainers.image.revision", ""))
        if benchmark_revision != _BENCHMARK_REVISION:
            raise ValueError("baseline image benchmark revision changed")
        completed = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--read-only",
                "--cpus",
                "2",
                "--memory",
                "4096m",
                "--pids-limit",
                "256",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=256m",
                "--mount",
                _bind_mount(
                    _BASELINE_PROBE_PATH,
                    "/input/scientific_contract_baseline_probe.py",
                ),
                "--entrypoint",
                "python",
                image,
                "/input/scientific_contract_baseline_probe.py",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        payload = json.loads(completed.stdout)
    except (
        FileNotFoundError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
        KeyError,
        ValueError,
    ) as exc:
        raise ScientificContractRecoveryError(
            f"cannot prove domain baseline runtime: {exc}"
        ) from exc
    try:
        probe_results = tuple(
            DomainBaselineProbeResult.model_validate(item)
            for item in payload.get("probes", [])
        )
    except ValidationError as exc:
        raise ScientificContractRecoveryError(
            f"domain baseline probe result is invalid: {exc}"
        ) from exc
    draft: dict[str, Any] = {
        "schema_version": "domain-baseline-probe-v1",
        "image": image,
        "image_id": image_id,
        "benchmark_revision": benchmark_revision,
        "probe_runner_sha256": _sha256_file(_BASELINE_PROBE_PATH),
        "python_version": payload.get("python_version"),
        "dependencies": payload.get("dependencies"),
        "network_used": payload.get("network_used"),
        "official_artifact_reads": payload.get("official_artifact_reads"),
        "probes": [item.model_dump(mode="json") for item in probe_results],
        "passed": payload.get("passed"),
    }
    draft["probe_hash"] = canonical_model_hash(draft)
    try:
        return DomainBaselineProbe.model_validate(draft)
    except ValidationError as exc:
        raise ScientificContractRecoveryError(
            f"domain baseline probe evidence is invalid: {exc}"
        ) from exc


def _validate_negative_parent(package: AutonomousDevelopmentSearchPackage) -> None:
    if package.selection.decision != "autonomous_development_negative_stop":
        raise ScientificContractRecoveryError("Task 266.1 requires the Task 265.3 negative")
    if package.search_freeze_receipt_created or package.search_freeze_receipt is not None:
        raise ScientificContractRecoveryError("qualified Task 265.3 package cannot be recovered")
    if (
        package.confirmation_identity_read_count != 0
        or package.confirmation_result_count != 0
        or package.system_generated_manuscript_count != 0
    ):
        raise ScientificContractRecoveryError(
            "Task 265.3 confirmation/manuscript isolation was not preserved"
        )


def _snapshot_sources(
    root: Path,
    fetcher: SourceFetcher,
    timeout_seconds: int,
    retrieved_at: datetime,
) -> tuple[ScientificContractSourceSnapshot, ...]:
    snapshots: list[ScientificContractSourceSnapshot] = []
    source_root = root / "sources"
    source_root.mkdir(parents=True, exist_ok=True)
    for spec in _SOURCE_SPECS:
        try:
            body, final_url, status_code = fetcher(spec, timeout_seconds)
        except Exception as exc:
            raise ScientificContractRecoveryError(
                f"cannot retrieve scientific-contract source {spec.source_id}: {exc}"
            ) from exc
        if len(body) > _MAX_SOURCE_BYTES:
            raise ScientificContractRecoveryError(
                f"scientific-contract source is too large: {spec.source_id}"
            )
        if not 200 <= status_code <= 299:
            raise ScientificContractRecoveryError(
                f"scientific-contract source returned HTTP {status_code}: {spec.source_id}"
            )
        if spec.required_marker.encode("utf-8") not in body:
            raise ScientificContractRecoveryError(
                f"scientific-contract source marker missing: {spec.source_id}"
            )
        relative_path = f"sources/{spec.source_id}.source"
        (root / relative_path).write_bytes(body)
        snapshots.append(
            ScientificContractSourceSnapshot(
                source_id=spec.source_id,
                kind=spec.kind,
                title=spec.title,
                source_url=spec.url,
                final_url=final_url,
                status_code=status_code,
                required_marker=spec.required_marker,
                revision=spec.revision,
                license_spdx=spec.license_spdx,
                content_sha256=hashlib.sha256(body).hexdigest(),
                snapshot_relative_path=relative_path,
                retrieved_at=retrieved_at,
                supports_claim=spec.supports_claim,
            )
        )
    return tuple(snapshots)


def _fetch_source(
    spec: ScientificContractSourceSpec,
    timeout_seconds: int,
) -> tuple[bytes, str, int]:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            request = Request(
                spec.url,
                headers={"User-Agent": "AutoResearch-Task266/1.0"},
            )
            with urlopen(request, timeout=timeout_seconds) as response:
                body = response.read(_MAX_SOURCE_BYTES + 1)
                return body, response.geturl(), int(response.status)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(1.0 + attempt)
    raise ScientificContractRecoveryError(
        f"source retrieval exhausted three attempts: {last_error}"
    )


def _materialize_schemas(root: Path) -> tuple[ContractSchemaArtifact, ...]:
    artifacts: list[ContractSchemaArtifact] = []
    schema_root = root / "schemas"
    schema_root.mkdir(parents=True, exist_ok=True)
    for model in _SCHEMA_MODELS:
        relative_path = f"schemas/{model.__name__}.schema.json"
        write_json_model(root / relative_path, model.model_json_schema())
        artifacts.append(
            ContractSchemaArtifact(
                model_name=model.__name__,
                relative_path=relative_path,
                sha256=_sha256_file(root / relative_path),
            )
        )
    return tuple(artifacts)


def _materialize_sentinels(root: Path) -> tuple[SentinelArtifact, ...]:
    artifacts: list[SentinelArtifact] = []
    sentinel_root = root / "sentinels"
    sentinel_root.mkdir(parents=True, exist_ok=True)
    for index, fixture in enumerate(_sentinel_fixtures(), start=1):
        relative_path = f"sentinels/{index:02d}-{fixture.sentinel_id}.json"
        write_json_model(root / relative_path, fixture)
        artifacts.append(
            SentinelArtifact(
                sentinel_id=fixture.sentinel_id,
                data_type=fixture.data_type,
                spatial_dimensions=fixture.spatial_dimensions,
                field_count=len(fixture.field_names),
                relative_path=relative_path,
                sha256=_sha256_file(root / relative_path),
                fixture_hash=fixture.fixture_hash,
            )
        )
    return tuple(artifacts)


def _sentinel_fixtures() -> tuple[ScientificSentinelFixture, ...]:
    return (
        _build_sentinel("ode-linear-2field", "ode", 0, ("u0", "u1"), (0.5, 0.25)),
        _build_sentinel("pde-advection-1d", "pde", 1, ("u0",), (0.2,)),
        _build_sentinel("pde-diffusion-1d", "pde", 1, ("u0",), (0.12,)),
        _build_sentinel("pde-advection-diffusion-2d", "pde", 2, ("u0",), (0.2, 0.1)),
        _build_sentinel("pde-heat-3d", "pde", 3, ("u0",), (0.08,)),
        _build_sentinel(
            "pde-diffusion-1d-2field",
            "pde",
            1,
            ("u0", "u1"),
            (0.1, 0.2),
        ),
    )


def _build_sentinel(
    sentinel_id: str,
    data_type: DataType,
    spatial_dimensions: int,
    field_names: tuple[str, ...],
    parameters: tuple[float, ...],
) -> ScientificSentinelFixture:
    axes = _sentinel_axes(spatial_dimensions)
    train_times = tuple(index / 10.0 for index in range(6))
    query_times = (0.65, 0.8, 1.0)
    alternative = _alternative_parameters(sentinel_id, parameters)
    train_state, train_derivative = _evaluate_sentinel(
        sentinel_id, axes, train_times, parameters, len(field_names)
    )
    alt_state, alt_derivative = _evaluate_sentinel(
        sentinel_id, axes, train_times, alternative, len(field_names)
    )
    queries = tuple(
        SentinelQuery(
            query_id=f"{sentinel_id}-query-{index:02d}",
            time=query_time,
            state=_evaluate_sentinel(
                sentinel_id,
                axes,
                (query_time,),
                parameters,
                len(field_names),
            )[0],
            expected_derivative=_evaluate_sentinel(
                sentinel_id,
                axes,
                (query_time,),
                parameters,
                len(field_names),
            )[1],
        )
        for index, query_time in enumerate(query_times, start=1)
    )
    row_count = math.prod(train_state.shape[:-1])
    order = list(range(row_count))
    random.Random(2660100 + sum(ord(char) for char in sentinel_id)).shuffle(order)
    payload: dict[str, Any] = {
        "schema_version": "scientific-sentinel-fixture-v1",
        "sentinel_id": sentinel_id,
        "data_type": data_type,
        "spatial_dimensions": spatial_dimensions,
        "field_names": field_names,
        "spatial_coordinates": axes,
        "train_times": train_times,
        "train_state": train_state.model_dump(mode="json"),
        "train_derivative": train_derivative.model_dump(mode="json"),
        "alternative_train_state": alt_state.model_dump(mode="json"),
        "alternative_train_derivative": alt_derivative.model_dump(mode="json"),
        "train_derivative_shuffle_order": order,
        "expected_equations": [
            item.model_dump(mode="json")
            for item in _sentinel_equations(sentinel_id, parameters)
        ],
        "alternative_expected_equations": [
            item.model_dump(mode="json")
            for item in _sentinel_equations(sentinel_id, alternative)
        ],
        "queries": [item.model_dump(mode="json") for item in queries],
        "term_support_f1_minimum": 1.0,
        "coefficient_relative_error_maximum": 0.05,
        "prediction_nmse_maximum": 1e-6,
        "equation_prediction_max_abs_delta": 1e-9,
        "zero_null_relative_improvement_minimum": 0.5,
        "shuffled_nmse_ratio_minimum": 5.0,
        "fit_call_count_required": 1,
        "minimum_query_count": 3,
    }
    payload["fixture_hash"] = canonical_model_hash(payload)
    return ScientificSentinelFixture.model_validate(payload)


def _sentinel_axes(spatial_dimensions: int) -> dict[AxisName, tuple[float, ...]]:
    names: tuple[AxisName, ...] = ("x", "y", "z")
    sizes = (17, 11, 7)
    return {
        names[index]: tuple(
            2.0 * math.pi * point / (sizes[index] - 1)
            for point in range(sizes[index])
        )
        for index in range(spatial_dimensions)
    }


def _alternative_parameters(
    sentinel_id: str,
    parameters: tuple[float, ...],
) -> tuple[float, ...]:
    if sentinel_id == "ode-linear-2field":
        return (0.8, 0.4)
    if sentinel_id == "pde-advection-diffusion-2d":
        return (0.35, 0.18)
    return tuple(value * 1.7 for value in parameters)


def _tensor_shape(
    axes: dict[AxisName, tuple[float, ...]],
    times: Sequence[float],
    field_count: int,
) -> tuple[int, ...]:
    return tuple(len(values) for values in axes.values()) + (len(times), field_count)


def _evaluate_sentinel(
    sentinel_id: str,
    axes: dict[AxisName, tuple[float, ...]],
    times: Sequence[float],
    parameters: tuple[float, ...],
    field_count: int,
) -> tuple[TensorPayload, TensorPayload]:
    spatial_values: Sequence[tuple[float, ...]] = tuple(axes.values())
    coordinate_rows = product(*spatial_values) if spatial_values else [()]
    states: list[float] = []
    derivatives: list[float] = []
    for coordinates in coordinate_rows:
        for current_time in times:
            state_row, derivative_row = _sentinel_value(
                sentinel_id,
                tuple(coordinates),
                float(current_time),
                parameters,
            )
            if len(state_row) != field_count or len(derivative_row) != field_count:
                raise ScientificContractRecoveryError("sentinel field count changed")
            states.extend(state_row)
            derivatives.extend(derivative_row)
    shape = _tensor_shape(axes, times, field_count)
    return (
        TensorPayload(shape=shape, values=tuple(states)),
        TensorPayload(shape=shape, values=tuple(derivatives)),
    )


def _sentinel_value(
    sentinel_id: str,
    coordinates: tuple[float, ...],
    current_time: float,
    parameters: tuple[float, ...],
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    if sentinel_id == "ode-linear-2field":
        decay, growth = parameters
        ode_state = (
            math.exp(-decay * current_time),
            0.4 * math.exp(growth * current_time),
        )
        return ode_state, (-decay * ode_state[0], growth * ode_state[1])
    if sentinel_id == "pde-advection-1d":
        speed = parameters[0]
        phase = coordinates[0] - speed * current_time
        return (math.sin(phase),), (-speed * math.cos(phase),)
    if sentinel_id == "pde-diffusion-1d":
        diffusivity = parameters[0]
        x_value = coordinates[0]
        first = math.exp(-diffusivity * current_time) * math.sin(x_value)
        second = 0.4 * math.exp(-4.0 * diffusivity * current_time) * math.sin(2.0 * x_value)
        return (first + second,), (-diffusivity * first - 4.0 * diffusivity * second,)
    if sentinel_id == "pde-advection-diffusion-2d":
        speed, diffusivity = parameters
        x_value, y_value = coordinates
        first_phase = x_value - speed * current_time
        second_phase = 2.0 * (x_value - speed * current_time)
        first = math.exp(-diffusivity * current_time) * math.sin(first_phase) * math.cos(y_value)
        second = (
            0.3
            * math.exp(-4.0 * diffusivity * current_time)
            * math.sin(second_phase)
            * math.cos(2.0 * y_value)
        )
        derivative = (
            -speed
            * math.exp(-diffusivity * current_time)
            * math.cos(first_phase)
            * math.cos(y_value)
            - diffusivity * first
            - 0.6
            * speed
            * math.exp(-4.0 * diffusivity * current_time)
            * math.cos(second_phase)
            * math.cos(2.0 * y_value)
            - 4.0 * diffusivity * second
        )
        return (first + second,), (derivative,)
    if sentinel_id == "pde-heat-3d":
        diffusivity = parameters[0]
        x_value, y_value, z_value = coordinates
        modes = (
            (1.0, (1, 1, 1)),
            (0.3, (2, 1, 1)),
            (0.2, (1, 2, 1)),
            (0.1, (1, 1, 2)),
        )
        state_total = 0.0
        derivative = 0.0
        for amplitude, wave_numbers in modes:
            squared_sum = sum(number * number for number in wave_numbers)
            value = amplitude * math.exp(-diffusivity * squared_sum * current_time)
            value *= math.sin(wave_numbers[0] * x_value)
            value *= math.sin(wave_numbers[1] * y_value)
            value *= math.sin(wave_numbers[2] * z_value)
            state_total += value
            derivative -= diffusivity * squared_sum * value
        return (state_total,), (derivative,)
    if sentinel_id == "pde-diffusion-1d-2field":
        first_diffusivity, second_diffusivity = parameters
        x_value = coordinates[0]
        first = math.exp(-first_diffusivity * current_time) * math.sin(x_value)
        first += 0.25 * math.exp(-4 * first_diffusivity * current_time) * math.sin(2 * x_value)
        second = 0.5 * math.exp(-4 * second_diffusivity * current_time) * math.cos(2 * x_value)
        second += 0.2 * math.exp(-9 * second_diffusivity * current_time) * math.cos(3 * x_value)
        first_derivative = -first_diffusivity * (
            math.exp(-first_diffusivity * current_time) * math.sin(x_value)
            + 4
            * 0.25
            * math.exp(-4 * first_diffusivity * current_time)
            * math.sin(2 * x_value)
        )
        second_derivative = -second_diffusivity * (
            4
            * 0.5
            * math.exp(-4 * second_diffusivity * current_time)
            * math.cos(2 * x_value)
            + 9
            * 0.2
            * math.exp(-9 * second_diffusivity * current_time)
            * math.cos(3 * x_value)
        )
        return (first, second), (first_derivative, second_derivative)
    raise ScientificContractRecoveryError(f"unknown scientific sentinel: {sentinel_id}")


def _factor(field: str, *axes: AxisName) -> EquationFactor:
    return EquationFactor(field=field, derivative_axes=axes)


def _equation(target: str, *terms: tuple[float, EquationFactor]) -> ConcreteEquation:
    return ConcreteEquation(
        target=target,
        terms=tuple(
            EquationTerm(coefficient=coefficient, factors=(factor,))
            for coefficient, factor in terms
        ),
    )


def _sentinel_equations(
    sentinel_id: str,
    parameters: tuple[float, ...],
) -> tuple[ConcreteEquation, ...]:
    if sentinel_id == "ode-linear-2field":
        return (
            _equation("u0_t", (-parameters[0], _factor("u0"))),
            _equation("u1_t", (parameters[1], _factor("u1"))),
        )
    if sentinel_id == "pde-advection-1d":
        return (_equation("u0_t", (-parameters[0], _factor("u0", "x"))),)
    if sentinel_id == "pde-diffusion-1d":
        return (_equation("u0_t", (parameters[0], _factor("u0", "x", "x"))),)
    if sentinel_id == "pde-advection-diffusion-2d":
        return (
            _equation(
                "u0_t",
                (-parameters[0], _factor("u0", "x")),
                (parameters[1], _factor("u0", "y", "y")),
            ),
        )
    if sentinel_id == "pde-heat-3d":
        return (
            _equation(
                "u0_t",
                (parameters[0], _factor("u0", "x", "x")),
                (parameters[0], _factor("u0", "y", "y")),
                (parameters[0], _factor("u0", "z", "z")),
            ),
        )
    if sentinel_id == "pde-diffusion-1d-2field":
        return (
            _equation("u0_t", (parameters[0], _factor("u0", "x", "x"))),
            _equation("u1_t", (parameters[1], _factor("u1", "x", "x"))),
        )
    raise ScientificContractRecoveryError(f"unknown sentinel equation: {sentinel_id}")


def _baseline_specs(
    probe: DomainBaselineProbe,
) -> tuple[DomainBaselineSpec, DomainBaselineSpec]:
    dependencies = probe.dependencies
    return (
        DomainBaselineSpec(
            baseline_id="operon_gp_ode",
            data_type="ode",
            family="genetic_symbolic",
            implementation=(
                "pinned MDBench Operon wrapper at f81813e with explicit attempt seed; "
                "ODE only because Task 265.3 proved the query adapter is not PDE-valid"
            ),
            source_ids=(
                "mdbench-paper",
                "mdbench-fit-predict-interface",
                "mdbench-license",
                "pyoperon-implementation",
                "pyoperon-license",
                "pyoperon-pypi-0.5.0",
            ),
            dependency_versions={"pyoperon": dependencies["pyoperon"]},
            spatial_dimensions=(),
            multi_field_supported=True,
        ),
        DomainBaselineSpec(
            baseline_id="pdefind_pde",
            data_type="pde",
            family="sparse_linear",
            implementation=(
                "pinned MDBench PDE-FIND wrapper at f81813e backed by PySINDy 1.7.5; "
                "official set_spatial_grid plus fit/predict/to_str"
            ),
            source_ids=(
                "mdbench-paper",
                "mdbench-fit-predict-interface",
                "mdbench-license",
                "pysindy-paper",
                "pysindy-license",
                "pysindy-weak-library",
            ),
            dependency_versions={"pysindy": dependencies["pysindy"]},
            spatial_dimensions=(1, 2, 3),
            multi_field_supported=True,
        ),
    )


def _power_audit() -> RecoveryPowerAudit:
    points = []
    for probability in (0.6, 0.7, 0.8, 0.9):
        tail = sum(
            math.comb(14, successes)
            * probability**successes
            * (1.0 - probability) ** (14 - successes)
            for successes in range(12, 15)
        )
        points.append(
            PowerAuditPoint(
                positive_system_probability=probability,
                probability_at_least_12_of_14_positive=tail,
                probability_all_4_pde_positive=probability**4,
            )
        )
    return RecoveryPowerAudit(points=tuple(points))


def _render_markdown(plan: ScientificContractRecoveryPlan) -> str:
    source_lines = "\n".join(
        f"- `{item.source_id}`: {item.title} — `{item.content_sha256}`"
        for item in plan.sources
    )
    sentinel_lines = "\n".join(
        f"- `{item.sentinel_id}`: {item.data_type}, {item.spatial_dimensions}D, "
        f"{item.field_count} field(s), `{item.fixture_hash}`"
        for item in plan.sentinels
    )
    baseline_lines = "\n".join(
        f"- `{item.data_type}` → `{item.baseline_id}`; {item.implementation}"
        for item in plan.baselines
    )
    return f"""# Task 266.1 — result-blind scientific-contract recovery

## Verdict

Task 265.3 remains an immutable autonomous negative. Its package hash is
`{plan.negative_binding.package_hash}` and it issued no receipt. This plan observes no new official
development score, no confirmation identity/result, no candidate answer, and no manuscript.

The corrected scientific interface is `fit(train-only) → freeze(concrete numeric equation) →
predict(target-free single-slice queries)`. The trusted evaluator independently evaluates the
frozen equations and rejects prediction disagreement, free coefficients, zero-null equivalence,
training insensitivity, shuffle non-degradation, fit-after-query, and unsupported dimensions.

## Why this changes the failed path

MDBench itself requires separate `fit`, `predict`, `complexity`, and `to_str` methods. The old
stateless query contract did not require a learned equation and allowed one-slice finite differences
to collapse to zero. The domain baseline is also corrected: Operon is the ODE comparator, while the
official PDE-FIND/PySINDy implementation is the PDE comparator. A baseline failure blocks a receipt;
it can never be converted into candidate advantage.

## Primary and implementation evidence

{source_lines}

Registry hash: `{plan.source_registry_hash}`.

## Frozen sentinels

{sentinel_lines}

Every sentinel contains primary and alternative training contexts, a deterministic derivative-row
shuffle, three target-free queries, and evaluator-owned analytic derivatives. Registry hash:
`{plan.sentinel_registry_hash}`.

## Domain baselines

{baseline_lines}

The offline synthetic probe used image `{plan.baseline_probe.image}` / `{plan.baseline_probe.image_id}`,
Python `{plan.baseline_probe.python_version}`, read zero official artifacts, and has hash
`{plan.baseline_probe.probe_hash}`.

## Frozen search and evidence rule

- Initial/generated candidates: 8; total maximum: 12; mechanism cycles: at most 4.
- Official candidate cells: at most 380; domain baseline cells: 84; total: 464.
- Independent unit: system, not seed or condition. ODE and PDE effects are reported separately.
- Receipt requires all candidate and baseline cells to succeed, overall median error reduction of at
  least 5%, exploratory system-bootstrap lower bound above zero, positive ODE and PDE medians, and
  every scientific-contract gate.
- Four PDE systems are not enough for a standalone PDE significance claim. Development intervals
  select a method only; the original one-use confirmation gate remains unchanged.

## Authorization boundary

Task 266.2 may implement and test the Harness only. Official development execution, confirmation,
manuscript generation, publication, release, and submission remain blocked.

Plan hash: `{plan.plan_hash}`.
"""


def _bind_mount(source: Path, target: str) -> str:
    return f"type=bind,source={source.resolve().as_posix()},target={target},readonly"


def _inside(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ScientificContractRecoveryError(
            f"artifact path escapes scientific-contract root: {relative_path}"
        ) from exc
    if not candidate.is_file():
        raise ScientificContractRecoveryError(
            f"scientific-contract artifact is missing: {relative_path}"
        )
    return candidate


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "ContractSchemaArtifact",
    "ConcreteEquation",
    "DomainBaselineProbe",
    "DomainBaselineProbeResult",
    "DomainBaselineSpec",
    "EquationFieldScaling",
    "EquationFitDiagnostics",
    "EquationFactor",
    "EquationTerm",
    "FrozenEquationArtifact",
    "NegativeDevelopmentBinding",
    "RecoveryEstimand",
    "RecoveryPowerAudit",
    "RecoverySearchBudget",
    "ScientificContractGate",
    "ScientificContractRecoveryError",
    "ScientificContractRecoveryPlan",
    "ScientificContractSourceSnapshot",
    "ScientificFitRequest",
    "ScientificPredictRequest",
    "ScientificPredictResponse",
    "ScientificSentinelFixture",
    "SentinelArtifact",
    "SentinelQuery",
    "TensorPayload",
    "freeze_scientific_contract_recovery_plan",
    "load_scientific_contract_recovery_plan",
    "probe_domain_baselines",
]
