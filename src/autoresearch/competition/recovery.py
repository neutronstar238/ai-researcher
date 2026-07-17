"""Result-blind recovery preregistration after a negative MDBench Gate A cycle."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, model_validator

from autoresearch.competition.gate_a import (
    GateAAdjudicationError,
    GateADecision,
    MDBenchGateAReport,
    load_mdbench_gate_a_report,
)
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import (
    MDBenchArchiveManifest,
    MDBenchDatasetArtifact,
    MDBenchExperimentMatrix,
    MDBenchMatrixAttemptSpec,
    MDBenchMethodSpec,
    MDBenchSystemCase,
    MDBenchTemporalSplit,
    StrictFrozenModel,
)
from autoresearch.competition.planning import MDBENCH_REVISION
from autoresearch.competition.preregistration import (
    MDBenchPreregistrationError,
    validate_mdbench_preregistration,
)

_PROTOCOL_ID = "mdbench-gate-a-recovery-v1"
_HYPOTHESIS_ID = "hypothesis_weak_form_support_stability_v1"
_CANDIDATE_METHOD_ID = "weak_stability_sindy"
_PARENT_CANDIDATE_METHOD_ID = "stability_sindy"
_CONDITIONS = ("clean", "snr_20")
_SEEDS = (13, 29, 43)
_MATRIX_NAME = "gate-a-recovery-matrix.json"
_PREREGISTRATION_NAME = "gate-a-recovery-preregistration.json"
_RESULT_MARKERS = (
    "attempts",
    "execution",
    "execution-report.json",
    "gate-a-adjudication.json",
    "results",
)

DataType = Literal["ode", "pde"]
EvaluationSplit = Literal["development", "unseen_test"]
PanelEntry = tuple[str, EvaluationSplit, str]

# The old cycle's unseen systems are never reused.  The two repeated PDEs were
# development controls in that cycle and remain development controls here.
_ODE_PANEL: tuple[PanelEntry, ...] = (
    ("harmonic-oscillator-damping", "development", "damped linear control"),
    ("lotka-volterra-competition", "development", "competitive population dynamics"),
    ("damped-double-well-oscillator", "development", "damped bistable nonlinear dynamics"),
    ("seir-infection", "development", "four-compartment epidemiological dynamics"),
    ("maxwell-bloch-equations", "development", "coupled nonlinear optical dynamics"),
    ("rössler-attractor-periodic", "development", "periodic attractor control"),
    ("chen-lee-attractor", "unseen_test", "fresh held-out chaotic system"),
    (
        "lorenz-equations-complex-periodic",
        "unseen_test",
        "fresh held-out complex periodic system",
    ),
    ("apoptosis-model", "unseen_test", "fresh held-out biochemical dynamics"),
    (
        "binocular-rivalry-adaptation",
        "unseen_test",
        "fresh held-out neural adaptation dynamics",
    ),
)
_PDE_PANEL: tuple[PanelEntry, ...] = (
    ("advection1d", "development", "reused linear transport development control"),
    ("burgers", "development", "reused nonlinear transport development control"),
    (
        "heat_soil_uniform_1d_p1",
        "unseen_test",
        "fresh held-out one-dimensional diffusion system",
    ),
    ("nls", "unseen_test", "fresh held-out two-channel dispersive system"),
)


class MDBenchRecoveryError(RuntimeError):
    """Raised when a recovery cycle cannot be frozen without leakage or tampering."""


class MDBenchRecoverySystemRef(StrictFrozenModel):
    """Compact immutable system identity used by the recovery leakage contract."""

    data_type: DataType
    system_name: str


class RecoverySource(StrictFrozenModel):
    """Versioned paper/software evidence and its permitted reuse policy."""

    source_id: str
    source_type: Literal["paper", "software"]
    title: str
    url: str
    doi: str | None = None
    revision: str | None = None
    license_spdx: str | None = None
    license_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    reuse_policy: Literal["concept_only", "dependency", "reference_only"]
    license_status: Literal["not_applicable", "verified", "unverified"]

    @model_validator(mode="after")
    def _require_safe_reuse_policy(self) -> RecoverySource:
        if self.reuse_policy == "dependency":
            if self.source_type != "software":
                raise ValueError("a dependency source must be software")
            if not self.revision:
                raise ValueError("a dependency source requires an immutable revision")
            if self.license_status != "verified":
                raise ValueError("a dependency source requires a verified license")
            if not self.license_spdx or not self.license_sha256:
                raise ValueError("a dependency source requires license identity and hash")
        if self.reuse_policy == "reference_only" and self.source_type != "software":
            raise ValueError("reference-only sources must be software repositories")
        return self


class MDBenchGateARecoveryPreregistration(StrictFrozenModel):
    """Hash-bound recovery hypothesis, leakage policy, sources, and matrix."""

    schema_version: str = "mdbench-gate-a-recovery-preregistration-v1"
    protocol_id: str
    parent_matrix_path: str
    parent_matrix_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_report_path: str
    parent_report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_decision: GateADecision
    hypothesis_id: str
    hypothesis: str
    mechanisms: tuple[str, ...]
    falsification_rule: str
    leakage_policy: str
    excluded_parent_unseen_systems: tuple[MDBenchRecoverySystemRef, ...]
    recovery_unseen_systems: tuple[MDBenchRecoverySystemRef, ...]
    reused_development_controls: tuple[MDBenchRecoverySystemRef, ...]
    sources: tuple[RecoverySource, ...]
    matrix_path: str
    matrix_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_before_results: bool = True
    recovery_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str

    @model_validator(mode="after")
    def _require_bounded_distinct_recovery(self) -> MDBenchGateARecoveryPreregistration:
        if self.parent_decision is not GateADecision.NEGATIVE_RESULT:
            raise ValueError("a recovery preregistration requires a negative parent decision")
        if len(self.mechanisms) != 2 or len(set(self.mechanisms)) != 2:
            raise ValueError("the recovery candidate must contain exactly two mechanisms")
        excluded = _system_ref_keys(self.excluded_parent_unseen_systems)
        recovery = _system_ref_keys(self.recovery_unseen_systems)
        controls = _system_ref_keys(self.reused_development_controls)
        if len(excluded) != len(self.excluded_parent_unseen_systems):
            raise ValueError("excluded parent unseen systems must be unique")
        if len(recovery) != len(self.recovery_unseen_systems):
            raise ValueError("recovery unseen systems must be unique")
        if excluded & recovery:
            raise ValueError("recovery unseen systems overlap the parent unseen set")
        if recovery & controls:
            raise ValueError("recovery unseen systems cannot be reused development controls")
        source_ids = {source.source_id for source in self.sources}
        if len(source_ids) != len(self.sources):
            raise ValueError("recovery source IDs must be unique")
        if not any(source.reuse_policy == "dependency" for source in self.sources):
            raise ValueError("the recovery contract requires a verified software dependency")
        if self.created_before_results is not True:
            raise ValueError("the recovery contract must be created before results")
        return self


def preregister_mdbench_gate_a_recovery(
    archive_manifest: MDBenchArchiveManifest,
    parent_matrix_path: Path | str,
    parent_report_path: Path | str,
    output_dir: Path | str,
) -> tuple[MDBenchGateARecoveryPreregistration, MDBenchExperimentMatrix]:
    """Freeze a fresh recovery matrix without opening numerical payloads or results."""

    parent_matrix_file = Path(parent_matrix_path).resolve()
    parent_report_file = Path(parent_report_path).resolve()
    output_root = Path(output_dir).resolve()
    _reject_result_markers(output_root)
    parent_matrix, parent_report = _load_and_validate_parent(
        parent_matrix_file,
        parent_report_file,
    )
    _validate_archive_lineage(archive_manifest, parent_matrix)

    systems = _system_cases(archive_manifest)
    _validate_panel_isolation(parent_matrix, systems)
    methods = _method_specs(parent_matrix)
    split_policy = MDBenchTemporalSplit()
    attempts = _attempt_specs(
        systems,
        methods,
        split_policy,
        conditions=_CONDITIONS,
        seeds=_SEEDS,
    )
    selection_policy = (
        "result-blind recovery panel selected from inventory/equation-family metadata after "
        "closing the parent cycle; no parent unseen system is reused, every recovery unseen "
        "system is absent from the full parent matrix, and only two parent development PDE "
        "controls are retained"
    )
    metrics = parent_matrix.metrics
    acceptance_criteria = (
        "all 252 frozen cells terminate without human scientific input",
        "all successful cells bind revision, matrix, code, data, config, result, and environment hashes",
        "each method reproduces across fresh seeds 13, 29, and 43",
        "candidate improves unseen-test noisy median derivative NMSE by at least 5 percent versus the strongest baseline",
        "system-level paired bootstrap 95 percent confidence lower bound for that improvement is greater than zero",
        "equation structure, trajectory, complexity, noise robustness, and cost remain reported without unsupported superiority claims",
        "no post-preregistration system, condition, split, method, seed, mechanism, or primary metric substitution",
        "failure of any mandatory gate closes this cycle as a credible negative result and does not unlock Gate B",
    )
    upstream_divergences = parent_matrix.upstream_divergences + (
        "the candidate uses the MIT-licensed PySINDy v1.7.5 weak-form API; WSINDy repositories without a detected license are reference-only and no code is copied or vendored",
    )
    matrix_path = output_root / _MATRIX_NAME
    matrix = _build_matrix(
        archive_manifest=archive_manifest,
        selection_policy=selection_policy,
        split_policy=split_policy,
        systems=systems,
        methods=methods,
        attempts=attempts,
        metrics=metrics,
        acceptance_criteria=acceptance_criteria,
        upstream_divergences=upstream_divergences,
        output_path=matrix_path,
    )

    preregistration_path = output_root / _PREREGISTRATION_NAME
    preregistration = _build_recovery_contract(
        parent_matrix=parent_matrix,
        parent_matrix_path=parent_matrix_file,
        parent_report=parent_report,
        parent_report_path=parent_report_file,
        matrix=matrix,
        matrix_path=matrix_path,
        output_path=preregistration_path,
    )
    matrix_exists = matrix_path.is_file()
    preregistration_exists = preregistration_path.is_file()
    if matrix_exists != preregistration_exists:
        raise MDBenchRecoveryError(
            "refusing a partial recovery preregistration; matrix and contract must coexist"
        )
    if matrix_exists:
        existing_matrix = _load_matrix(matrix_path)
        existing_preregistration = _load_recovery_contract(preregistration_path)
        validate_mdbench_recovery_preregistration(
            existing_preregistration,
            existing_matrix,
        )
        if Path(existing_preregistration.parent_matrix_path).resolve() != parent_matrix_file:
            raise MDBenchRecoveryError("recovery parent matrix path mismatch")
        if Path(existing_preregistration.parent_report_path).resolve() != parent_report_file:
            raise MDBenchRecoveryError("recovery parent report path mismatch")
        if (
            existing_matrix.matrix_hash != matrix.matrix_hash
            or existing_preregistration.recovery_hash != preregistration.recovery_hash
        ):
            raise MDBenchRecoveryError(
                "refusing to overwrite a different frozen recovery preregistration"
            )
        return existing_preregistration, existing_matrix

    write_json_model(matrix_path, matrix)
    write_json_model(preregistration_path, preregistration)
    return preregistration, matrix


def validate_mdbench_recovery_preregistration(
    preregistration: MDBenchGateARecoveryPreregistration,
    matrix: MDBenchExperimentMatrix,
) -> None:
    """Recompute both content hashes and reject leakage-contract tampering."""

    validate_mdbench_preregistration(matrix)
    computed = canonical_model_hash(_recovery_hash_payload(preregistration))
    if computed != preregistration.recovery_hash:
        raise MDBenchRecoveryError(
            "recovery preregistration hash mismatch: "
            f"{computed} != {preregistration.recovery_hash}"
        )
    if preregistration.matrix_hash != matrix.matrix_hash:
        raise MDBenchRecoveryError("recovery contract matrix hash mismatch")
    if Path(preregistration.matrix_path).resolve() != Path(matrix.output_path).resolve():
        raise MDBenchRecoveryError("recovery contract matrix path mismatch")
    if matrix.conditions != _CONDITIONS or matrix.seeds != _SEEDS:
        raise MDBenchRecoveryError("recovery matrix conditions or fresh seeds changed")
    expected_panel = {
        (data_type, system_name): evaluation_split
        for data_type, panel in (("ode", _ODE_PANEL), ("pde", _PDE_PANEL))
        for system_name, evaluation_split, _reason in panel
    }
    actual_panel = {
        (case.data_type, case.system_name): case.evaluation_split for case in matrix.systems
    }
    if actual_panel != expected_panel:
        raise MDBenchRecoveryError("recovery system panel or split changed")
    candidate_methods = [
        method.method_id for method in matrix.methods if method.family == "agent_candidate"
    ]
    if candidate_methods != [_CANDIDATE_METHOD_ID]:
        raise MDBenchRecoveryError("recovery candidate method changed")
    matrix_unseen = _system_ref_keys(
        _refs(case for case in matrix.systems if case.evaluation_split == "unseen_test")
    )
    contract_unseen = _system_ref_keys(preregistration.recovery_unseen_systems)
    if matrix_unseen != contract_unseen:
        raise MDBenchRecoveryError("recovery unseen-system contract does not match the matrix")
    excluded = _system_ref_keys(preregistration.excluded_parent_unseen_systems)
    if excluded & set(actual_panel):
        raise MDBenchRecoveryError("a parent unseen system appears in the recovery matrix")
    expected_controls: set[tuple[DataType, str]] = {
        ("pde", "advection1d"),
        ("pde", "burgers"),
    }
    if _system_ref_keys(preregistration.reused_development_controls) != expected_controls:
        raise MDBenchRecoveryError("reused development-control contract changed")
    candidate = next(
        method for method in matrix.methods if method.method_id == _CANDIDATE_METHOD_ID
    )
    if candidate.parameters.get("mechanisms") != list(preregistration.mechanisms):
        raise MDBenchRecoveryError("candidate mechanisms do not match the recovery contract")
    source_by_id = {source.source_id: source for source in preregistration.sources}
    dependency = source_by_id.get("pysindy-v1.7.5")
    if (
        dependency is None
        or dependency.revision != "4c32d2603cbf1aa476efae72bc78436cb1e6fc75"
        or dependency.license_spdx != "MIT"
        or dependency.reuse_policy != "dependency"
    ):
        raise MDBenchRecoveryError("verified PySINDy dependency contract changed")
    for source_id in ("wsindy-ode-reference", "wsindy-pde-reference"):
        source = source_by_id.get(source_id)
        if (
            source is None
            or source.reuse_policy != "reference_only"
            or source.license_status != "unverified"
        ):
            raise MDBenchRecoveryError("WSINDy reference-only boundary changed")


def _load_and_validate_parent(
    matrix_path: Path,
    report_path: Path,
) -> tuple[MDBenchExperimentMatrix, MDBenchGateAReport]:
    try:
        matrix = MDBenchExperimentMatrix.model_validate_json(
            matrix_path.read_text(encoding="utf-8")
        )
        validate_mdbench_preregistration(matrix)
        report = load_mdbench_gate_a_report(report_path)
    except (
        GateAAdjudicationError,
        MDBenchPreregistrationError,
        OSError,
        ValidationError,
    ) as exc:
        raise MDBenchRecoveryError(f"cannot load verified parent cycle: {exc}") from exc
    if Path(matrix.output_path).resolve() != matrix_path:
        raise MDBenchRecoveryError("parent matrix output path mismatch")
    if Path(report.matrix_path).resolve() != matrix_path:
        raise MDBenchRecoveryError("parent report does not bind the supplied matrix path")
    if report.matrix_hash != matrix.matrix_hash:
        raise MDBenchRecoveryError("parent report matrix hash mismatch")
    if report.report_hash is None:
        raise MDBenchRecoveryError("parent Gate A report is missing its final report hash")
    if report.decision is not GateADecision.NEGATIVE_RESULT or report.gate_b_allowed:
        raise MDBenchRecoveryError("recovery is allowed only after a negative Gate A decision")
    if report.candidate_method_id != _PARENT_CANDIDATE_METHOD_ID:
        raise MDBenchRecoveryError("unexpected parent candidate method")
    return matrix, report


def _validate_archive_lineage(
    archive_manifest: MDBenchArchiveManifest,
    parent_matrix: MDBenchExperimentMatrix,
) -> None:
    if archive_manifest.benchmark_revision != MDBENCH_REVISION:
        raise MDBenchRecoveryError("archive manifest revision does not match the pin")
    lineage = (
        (archive_manifest.archive_sha256, parent_matrix.archive_sha256, "archive SHA-256"),
        (archive_manifest.inventory_hash, parent_matrix.inventory_hash, "inventory hash"),
        (archive_manifest.dataset_doi, parent_matrix.dataset_doi, "dataset DOI"),
        (archive_manifest.dataset_license, parent_matrix.dataset_license, "dataset license"),
    )
    for observed, expected, label in lineage:
        if observed != expected:
            raise MDBenchRecoveryError(f"recovery {label} differs from the parent matrix")


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
                    raise MDBenchRecoveryError(
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


def _validate_panel_isolation(
    parent_matrix: MDBenchExperimentMatrix,
    recovery_systems: tuple[MDBenchSystemCase, ...],
) -> None:
    parent_all = {(case.data_type, case.system_name) for case in parent_matrix.systems}
    parent_unseen = {
        (case.data_type, case.system_name)
        for case in parent_matrix.systems
        if case.evaluation_split == "unseen_test"
    }
    recovery_all = {(case.data_type, case.system_name) for case in recovery_systems}
    recovery_unseen = {
        (case.data_type, case.system_name)
        for case in recovery_systems
        if case.evaluation_split == "unseen_test"
    }
    allowed_reuse: set[tuple[DataType, str]] = {
        ("pde", "advection1d"),
        ("pde", "burgers"),
    }
    if recovery_all & parent_unseen:
        raise MDBenchRecoveryError("the recovery panel reuses a parent unseen system")
    if recovery_unseen & parent_all:
        raise MDBenchRecoveryError("a recovery unseen system appeared anywhere in the parent matrix")
    if recovery_all & parent_all != allowed_reuse:
        raise MDBenchRecoveryError("only the two parent development PDE controls may be reused")
    parent_splits = {
        (case.data_type, case.system_name): case.evaluation_split for case in parent_matrix.systems
    }
    if any(parent_splits[key] != "development" for key in allowed_reuse):
        raise MDBenchRecoveryError("reused PDE controls were not parent development systems")


def _method_specs(parent_matrix: MDBenchExperimentMatrix) -> tuple[MDBenchMethodSpec, ...]:
    baselines = tuple(
        method for method in parent_matrix.methods if method.family != "agent_candidate"
    )
    if {method.method_id for method in baselines} != {"sindy_or_pdefind", "operon_gp"}:
        raise MDBenchRecoveryError("the parent baseline set changed")
    candidate = MDBenchMethodSpec(
        method_id=_CANDIDATE_METHOD_ID,
        family="agent_candidate",
        implementation=(
            "PySINDy v1.7.5 WeakPDELibrary projection followed by bootstrap "
            "support-stability selection"
        ),
        applicable_data_types=("ode", "pde"),
        parameters={
            "mechanisms": ["weak_form_projection", "bootstrap_support_stability"],
            "pysindy_revision": "4c32d2603cbf1aa476efae72bc78436cb1e6fc75",
            "weak_library": "WeakPDELibrary",
            "weak_subdomains": 100,
            "bootstrap_repetitions": 20,
            "subsample_fraction": 0.8,
            "selection_frequency": 0.7,
            "optimizer_threshold": [1e-5, 1e-3, 1e-1],
            "poly_order": [1, 2, 3],
            "pde_derivative_order": [1, 2, 3, 4],
            "validation_objective": (
                "derivative NMSE then lower complexity on the disjoint validation slice"
            ),
        },
        max_seconds_per_attempt=300,
        max_cpu_cores=2,
        max_memory_mb=4096,
    )
    return (*baselines, candidate)


def _attempt_specs(
    systems: tuple[MDBenchSystemCase, ...],
    methods: tuple[MDBenchMethodSpec, ...],
    split_policy: MDBenchTemporalSplit,
    *,
    conditions: tuple[str, ...],
    seeds: tuple[int, ...],
) -> tuple[MDBenchMatrixAttemptSpec, ...]:
    attempts: list[MDBenchMatrixAttemptSpec] = []
    split_payload = split_policy.model_dump(mode="json")
    for case in systems:
        for condition in conditions:
            for seed in seeds:
                for method in methods:
                    if case.data_type not in method.applicable_data_types:
                        continue
                    config_hash = canonical_model_hash(
                        {
                            "artifact_sha256": case.artifact_sha256[condition],
                            "condition": condition,
                            "data_type": case.data_type,
                            "method": method.model_dump(mode="json"),
                            "protocol_id": _PROTOCOL_ID,
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


def _build_matrix(
    *,
    archive_manifest: MDBenchArchiveManifest,
    selection_policy: str,
    split_policy: MDBenchTemporalSplit,
    systems: tuple[MDBenchSystemCase, ...],
    methods: tuple[MDBenchMethodSpec, ...],
    attempts: tuple[MDBenchMatrixAttemptSpec, ...],
    metrics: tuple[str, ...],
    acceptance_criteria: tuple[str, ...],
    upstream_divergences: tuple[str, ...],
    output_path: Path,
) -> MDBenchExperimentMatrix:
    payload: dict[str, Any] = {
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
    return MDBenchExperimentMatrix(
        **payload,
        matrix_hash=canonical_model_hash(payload),
        output_path=output_path.as_posix(),
    )


def _build_recovery_contract(
    *,
    parent_matrix: MDBenchExperimentMatrix,
    parent_matrix_path: Path,
    parent_report: MDBenchGateAReport,
    parent_report_path: Path,
    matrix: MDBenchExperimentMatrix,
    matrix_path: Path,
    output_path: Path,
) -> MDBenchGateARecoveryPreregistration:
    parent_unseen = _refs(
        case for case in parent_matrix.systems if case.evaluation_split == "unseen_test"
    )
    recovery_unseen = _refs(
        case for case in matrix.systems if case.evaluation_split == "unseen_test"
    )
    reused_controls = _refs(
        case
        for case in matrix.systems
        if (case.data_type, case.system_name)
        in {("pde", "advection1d"), ("pde", "burgers")}
    )
    payload: dict[str, Any] = {
        "protocol_id": _PROTOCOL_ID,
        "parent_matrix_hash": parent_matrix.matrix_hash,
        "parent_report_hash": parent_report.report_hash,
        "parent_decision": parent_report.decision,
        "hypothesis_id": _HYPOTHESIS_ID,
        "hypothesis": (
            "Weak-form projection will reduce pointwise derivative-noise sensitivity, "
            "while bootstrap support stability will reduce sparse-support variance across "
            "systems and fresh seeds."
        ),
        "mechanisms": ("weak_form_projection", "bootstrap_support_stability"),
        "falsification_rule": (
            "Close as a negative result unless the candidate beats the strongest frozen "
            "baseline by at least 5 percent on unseen noisy derivative NMSE and the "
            "system-level bootstrap 95 percent confidence lower bound is above zero; do "
            "not retry these mechanisms on the revealed recovery unseen systems."
        ),
        "leakage_policy": (
            "Parent unseen systems are excluded from the full recovery panel; recovery "
            "unseen systems are absent from the full parent panel; only parent-development "
            "advection1d and burgers controls may be reused, and neither becomes unseen."
        ),
        "excluded_parent_unseen_systems": parent_unseen,
        "recovery_unseen_systems": recovery_unseen,
        "reused_development_controls": reused_controls,
        "sources": _sources(),
        "matrix_hash": matrix.matrix_hash,
        "created_before_results": True,
    }
    recovery_hash = canonical_model_hash(_jsonable(payload))
    return MDBenchGateARecoveryPreregistration(
        **payload,
        parent_matrix_path=parent_matrix_path.as_posix(),
        parent_report_path=parent_report_path.as_posix(),
        matrix_path=matrix_path.as_posix(),
        recovery_hash=recovery_hash,
        output_path=output_path.as_posix(),
    )


def _sources() -> tuple[RecoverySource, ...]:
    return (
        RecoverySource(
            source_id="wendy-paper",
            source_type="paper",
            title="Weak-form Estimation of Nonlinear Dynamics",
            url="https://arxiv.org/abs/2302.13271",
            doi="10.1007/s11538-023-01208-6",
            reuse_policy="concept_only",
            license_status="not_applicable",
        ),
        RecoverySource(
            source_id="weak-form-latent-paper",
            source_type="paper",
            title="Weak-form latent space dynamics identification",
            url="https://arxiv.org/abs/2311.12880",
            doi="10.1016/j.cma.2024.116998",
            reuse_policy="concept_only",
            license_status="not_applicable",
        ),
        RecoverySource(
            source_id="ensemble-sindy-paper",
            source_type="paper",
            title="Robust learning of differential equations from data using ensemble methods",
            url="https://doi.org/10.1098/rspa.2021.0904",
            doi="10.1098/rspa.2021.0904",
            reuse_policy="concept_only",
            license_status="not_applicable",
        ),
        RecoverySource(
            source_id="pysindy-v1.7.5",
            source_type="software",
            title="PySINDy",
            url="https://github.com/dynamicslab/pysindy",
            doi="10.21105/joss.03994",
            revision="4c32d2603cbf1aa476efae72bc78436cb1e6fc75",
            license_spdx="MIT",
            license_sha256=(
                "abfa7f391ee1d5b6f51d473de5928e75ffae6e3cdbd21c19db78c98437efcbdd"
            ),
            reuse_policy="dependency",
            license_status="verified",
        ),
        RecoverySource(
            source_id="wsindy-ode-reference",
            source_type="software",
            title="WSINDy ODE reference implementation",
            url="https://github.com/MathBioCU/WSINDy_ODE",
            revision="72d8d6e5be2b80bcfe5015dced399ace1ceca43f",
            reuse_policy="reference_only",
            license_status="unverified",
        ),
        RecoverySource(
            source_id="wsindy-pde-reference",
            source_type="software",
            title="WSINDy PDE reference implementation",
            url="https://github.com/MathBioCU/WSINDy_PDE",
            revision="d9296be4c17c5e0b4df14472f4cd8276a8ae4eed",
            reuse_policy="reference_only",
            license_status="unverified",
        ),
    )


def _refs(cases: Any) -> tuple[MDBenchRecoverySystemRef, ...]:
    return tuple(
        MDBenchRecoverySystemRef(data_type=case.data_type, system_name=case.system_name)
        for case in cases
    )


def _system_ref_keys(
    references: tuple[MDBenchRecoverySystemRef, ...],
) -> set[tuple[DataType, str]]:
    return {(reference.data_type, reference.system_name) for reference in references}


def _recovery_hash_payload(
    preregistration: MDBenchGateARecoveryPreregistration,
) -> dict[str, Any]:
    return preregistration.model_dump(
        mode="json",
        exclude={
            "schema_version",
            "parent_matrix_path",
            "parent_report_path",
            "matrix_path",
            "recovery_hash",
            "output_path",
        },
    )


def _jsonable(payload: dict[str, Any]) -> dict[str, Any]:
    temporary = MDBenchGateARecoveryPreregistration.model_construct(
        **payload,
        parent_matrix_path="excluded",
        parent_report_path="excluded",
        matrix_path="excluded",
        recovery_hash="0" * 64,
        output_path="excluded",
    )
    return _recovery_hash_payload(temporary)


def _reject_result_markers(output_root: Path) -> None:
    for marker in _RESULT_MARKERS:
        if (output_root / marker).exists():
            raise MDBenchRecoveryError(
                f"result marker exists before recovery preregistration: {marker}"
            )


def _load_matrix(path: Path) -> MDBenchExperimentMatrix:
    try:
        matrix = MDBenchExperimentMatrix.model_validate_json(path.read_text(encoding="utf-8"))
        validate_mdbench_preregistration(matrix)
    except (MDBenchPreregistrationError, OSError, ValidationError) as exc:
        raise MDBenchRecoveryError(f"cannot load recovery matrix: {exc}") from exc
    if Path(matrix.output_path).resolve() != path:
        raise MDBenchRecoveryError("recovery matrix output path mismatch")
    return matrix


def _load_recovery_contract(path: Path) -> MDBenchGateARecoveryPreregistration:
    try:
        contract = MDBenchGateARecoveryPreregistration.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as exc:
        raise MDBenchRecoveryError(f"cannot load recovery preregistration: {exc}") from exc
    if Path(contract.output_path).resolve() != path:
        raise MDBenchRecoveryError("recovery preregistration output path mismatch")
    return contract
