"""Task 266.3: bounded autonomous development search on the official MDBench panel.

This executes the frozen Task `266.1` budget against the real official archive,
using the fit-once / freeze / predict-many contract that Task `266.2` proved on
synthetic sentinels and that `scientific_contract_official_runner.py` now runs on
real noisy payloads.

Why this exists separately from `autonomous_development.py`
----------------------------------------------------------
That module implements the Task `265.3` single-phase `discover(payload)` search,
whose frozen negative package must stay immutable. Its interface is also the one
that collapsed to the zero null. Per the project rule recorded in
`P-20260801-041`, a protocol change requires a new preregistered lineage rather
than mutation of a frozen parent.

Result-blind discipline
-----------------------
The identity is frozen from metadata only -- plan hash, panel hash, runner hash,
image ID, budget -- before any numeric payload is opened. Candidate generation sees
panel SHAPE metadata and the interface contract, never a system's arrays and never
an official score. Sealed confirmation identities are never read.

Estimand, taken verbatim from the frozen plan
---------------------------------------------
* cell loss: derivative NMSE
* paired effect: ``log(baseline_nmse_clipped / candidate_nmse_clipped)``
* repeated measures: median over condition and seed cells within each system
* system aggregation: median over independent systems
* uncertainty: fixed-seed bootstrap over independent systems
* a failed candidate cell takes the frozen failure loss, never a drop

A search-freeze receipt is issued if and only if every frozen check passes.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import subprocess
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from autoresearch.competition.autonomous_engine import (
    JsonCompletion,
    _call_and_record,
)
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.competition.scientific_contract_harness import (
    _SOURCE_RESPONSE_SCHEMA,
    ScientificContractRuntimeEnvironment,
    ScientificContractSourceResponse,
    build_scientific_interface_contract,
    inspect_scientific_contract_runtime,
    review_scientific_contract_source,
)
from autoresearch.competition.scientific_contract_recovery import (
    load_scientific_contract_recovery_plan,
)
from autoresearch.llm.client import run_llm_json_completion
from autoresearch.schemas import file_hash

_RUNNER_SOURCE = (
    Path(__file__).resolve().parents[3]
    / "deploy"
    / "experiments"
    / "mdbench"
    / "scientific_contract_official_runner.py"
)
_BASELINE_RUNNER_IN_IMAGE = "/opt/autoresearch-mdbench/runner.py"
_IDENTITY_NAME = "official-development-identity.json"
_PACKAGE_NAME = "official-development-search-package.json"
_SPLIT_POLICY = {"train": [0.0, 0.64], "validation": [0.64, 0.8], "test": [0.8, 1.0]}
# Frozen estimand bounds, taken from the Task 266.1 plan.
_LOSS_FLOOR = 1e-12
_LOSS_CAP = 1e12
_FAILURE_LOSS = 1e12
_BOOTSTRAP_RESAMPLES = 2_000
_BOOTSTRAP_SEED = 2663

# Domain-valid baseline methods, matching the frozen Task 266.1 registry and the
# exact parameter keys the pinned runner reads. The registry routes Operon to ODE
# only, because the pinned Operon adapter refuses anything beyond a 1D PDE panel,
# and this panel's PDE systems are 2D and 3D. `sindy_or_pdefind` dispatches SINDy
# for ODE and PDE-FIND for PDE, and the registry's probe recorded PDE-FIND
# succeeding at 2D (1.398e-31) and 3D (2.034e-32).
_ODE_BASELINE_METHOD: dict[str, Any] = {
    "method_id": "operon_gp",
    "family": "genetic_symbolic",
    "max_cpu_cores": 2,
    "parameters": {
        "generations": 100,
        "population_size": 1000,
        "pool_size": 1000,
        "max_evaluations": 20_000,
        "max_time_seconds": 75,
        "random_state": 101,
    },
}
_PDE_BASELINE_METHOD: dict[str, Any] = {
    "method_id": "sindy_or_pdefind",
    "family": "sparse_linear",
    "max_cpu_cores": 2,
    "parameters": {
        # `_baseline_configs` sweeps the cartesian product of these lists.
        "basis_functions": ["polynomial"],
        "optimizer_threshold": [0.01, 0.1],
        "poly_order": [2, 3],
        "optimizer_alpha": [1e-6, 1e-3],
        "pde_derivative_order": [2],
        "pysindy_revision": "1.7.5",
    },
}


def baseline_method_for(data_type: str) -> dict[str, Any]:
    """Return the domain-valid baseline method for one data type."""

    if data_type == "ode":
        return _ODE_BASELINE_METHOD
    return _PDE_BASELINE_METHOD


class OfficialDevelopmentSearchError(RuntimeError):
    """Raised when a Task 266.3 evidence boundary cannot be proved."""


class OfficialCellSpec(StrictFrozenModel):
    """One hash-bound official cell. Frozen before execution."""

    attempt_id: str
    method_kind: Literal["candidate", "baseline"]
    candidate_id: str
    stage: Literal["pilot", "full", "baseline"]
    system_name: str
    data_type: Literal["ode", "pde"]
    condition: Literal["clean", "snr_20"]
    seed: int
    data_relative_path: str
    data_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    spec_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class OfficialCellResult(StrictFrozenModel):
    """One terminal official cell outcome. Failures are retained, never dropped."""

    attempt_id: str
    method_kind: Literal["candidate", "baseline"]
    candidate_id: str
    stage: Literal["pilot", "full", "baseline"]
    system_name: str
    data_type: Literal["ode", "pde"]
    condition: Literal["clean", "snr_20"]
    seed: int
    status: Literal["succeeded", "failed", "timed_out"]
    derivative_nmse: float | None = None
    validation_nmse: float | None = None
    selected_term_count: int | None = None
    equation_changed_on_shuffled_training: bool | None = None
    maximum_equation_prediction_delta: float | None = None
    wall_time_seconds: float | None = None
    failure_reason: str | None = None
    result_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @property
    def loss(self) -> float:
        """Frozen loss: a failed or invalid cell takes the failure loss."""

        if self.status != "succeeded" or self.derivative_nmse is None:
            return _FAILURE_LOSS
        value = float(self.derivative_nmse)
        if not math.isfinite(value):
            return _FAILURE_LOSS
        return min(max(value, _LOSS_FLOOR), _LOSS_CAP)


class OfficialCandidateRecord(StrictFrozenModel):
    """One model-authored candidate, with provenance and static review outcome."""

    candidate_id: str
    generation: Literal[1, 2]
    interaction_id: str
    source_relative_path: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    static_review_approved: bool
    static_review_findings: tuple[str, ...] = ()
    implementation_summary: str
    authored_by_model: Literal[True] = True


class OfficialDevelopmentIdentity(StrictFrozenModel):
    """Result-blind identity, frozen from metadata before any numeric read."""

    schema_version: Literal["official-development-identity-v1"] = (
        "official-development-identity-v1"
    )
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    development_panel_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    sealed_confirmation_panel_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    runner_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_environment_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    image_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    data_root: str
    initial_candidate_count: int = Field(ge=1, le=12)
    pilot_system_count: int = Field(ge=1)
    full_system_count: int = Field(ge=1)
    conditions: tuple[str, ...]
    seeds: tuple[int, ...]
    maximum_official_cells_total: int = Field(ge=1)
    numeric_payload_opened_during_freeze: Literal[False] = False
    confirmation_identity_read_count: Literal[0] = 0
    created_at: datetime
    identity_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_identity(self) -> OfficialDevelopmentIdentity:
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"identity_hash"})
        )
        if self.identity_hash != expected:
            raise OfficialDevelopmentSearchError("official identity hash mismatch")
        return self


class SystemEffect(StrictFrozenModel):
    """One system's paired effect, aggregated over its repeated measures."""

    system_name: str
    data_type: Literal["ode", "pde"]
    candidate_median_loss: float
    baseline_median_loss: float
    paired_log_effect: float
    candidate_cell_count: int = Field(ge=1)
    baseline_cell_count: int = Field(ge=1)
    candidate_success_count: int = Field(ge=0)
    # P-20260802-065: a failure loss correctly penalises a failed CANDIDATE, but when
    # the BASELINE fails there is no comparison at all, so the ratio is not an effect.
    # The first full stage reported a PDE stratum median of +10.641766 that came
    # entirely from two systems whose baseline was absent.
    baseline_available: bool = True

    @property
    def is_paired(self) -> bool:
        """True only when both arms produced a real loss on this system."""

        return self.baseline_available and self.baseline_median_loss < _LOSS_CAP


class OfficialDevelopmentSearchPackage(StrictFrozenModel):
    """Complete Task 266.3 development-search evidence."""

    schema_version: Literal["official-development-search-package-v1"] = (
        "official-development-search-package-v1"
    )
    identity: OfficialDevelopmentIdentity
    candidates: tuple[OfficialCandidateRecord, ...] = Field(min_length=1)
    cell_results: tuple[OfficialCellResult, ...] = Field(min_length=1)
    stages_executed: tuple[str, ...] = Field(min_length=1)
    selected_candidate_id: str | None = None
    selection_basis: str
    system_effects: tuple[SystemEffect, ...] = ()
    overall_median_log_effect: float | None = None
    bootstrap_lower: float | None = None
    bootstrap_upper: float | None = None
    ode_stratum_median: float | None = None
    pde_stratum_median: float | None = None
    minimum_overall_log_effect: float
    gate_checks: dict[str, bool] = Field(default_factory=dict)
    search_freeze_receipt_issued: bool = False
    confirmation_identity_read_count: Literal[0] = 0
    system_generated_manuscript_count: Literal[0] = 0
    publication_ready: Literal[False] = False
    package_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str

    @model_validator(mode="after")
    def _validate_package(self) -> OfficialDevelopmentSearchPackage:
        if self.search_freeze_receipt_issued and not all(self.gate_checks.values()):
            raise OfficialDevelopmentSearchError(
                "a receipt was issued while a frozen gate check failed"
            )
        if self.search_freeze_receipt_issued and self.selected_candidate_id is None:
            raise OfficialDevelopmentSearchError("a receipt requires a selected candidate")
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"package_hash", "output_path"})
        )
        if self.package_hash != expected:
            raise OfficialDevelopmentSearchError("official search package hash mismatch")
        return self


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    count = len(ordered)
    middle = count // 2
    if count % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _bootstrap_interval(
    values: Sequence[float],
    *,
    resamples: int = _BOOTSTRAP_RESAMPLES,
    seed: int = _BOOTSTRAP_SEED,
) -> tuple[float, float]:
    if not values:
        raise OfficialDevelopmentSearchError("bootstrap requires at least one system")
    generator = random.Random(seed)
    count = len(values)
    medians = []
    for _ in range(resamples):
        medians.append(_median([values[generator.randrange(count)] for _ in range(count)]))
    medians.sort()
    return medians[int(0.025 * (resamples - 1))], medians[int(0.975 * (resamples - 1))]


def _canonical(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def freeze_official_identity(
    *,
    plan_path: Path | str,
    autonomous_plan_path: Path | str,
    data_root: Path | str,
    output_dir: Path | str,
    initial_candidate_count: int = 8,
    clock: Callable[[], datetime] | None = None,
    runtime_environment: ScientificContractRuntimeEnvironment | None = None,
) -> tuple[OfficialDevelopmentIdentity, dict[str, Any]]:
    """Freeze identity from METADATA ONLY, before any numeric payload is opened."""

    now = clock or (lambda: datetime.now(timezone.utc))
    output_root = Path(output_dir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    plan = load_scientific_contract_recovery_plan(plan_path)
    autonomous = json.loads(Path(autonomous_plan_path).read_text(encoding="utf-8"))
    panel = autonomous["development_panel"]
    commitment = autonomous["confirmation_commitment"]
    if commitment.get("research_agent_read_allowed") is not False:
        raise OfficialDevelopmentSearchError(
            "sealed confirmation panel must remain unreadable to research agents"
        )

    runner_path = output_root / "runner" / _RUNNER_SOURCE.name
    runner_path.parent.mkdir(parents=True, exist_ok=True)
    if not runner_path.is_file():
        runner_path.write_bytes(_RUNNER_SOURCE.read_bytes())
    runtime = runtime_environment or inspect_scientific_contract_runtime()

    budget = plan.search_budget.model_dump(mode="json") if hasattr(
        plan, "search_budget"
    ) else json.loads(Path(plan_path).read_text(encoding="utf-8"))["search_budget"]

    panel_hash = _canonical(panel)
    payload: dict[str, Any] = {
        "schema_version": "official-development-identity-v1",
        "plan_hash": plan.plan_hash,
        "development_panel_hash": panel_hash,
        "sealed_confirmation_panel_hash": commitment["panel_hash"],
        "runner_sha256": file_hash(runner_path),
        "runtime_environment_hash": runtime.environment_hash,
        "image_id": runtime.image_id,
        "data_root": Path(data_root).resolve().as_posix(),
        "initial_candidate_count": initial_candidate_count,
        "pilot_system_count": int(budget["pilot_ode_system_count"])
        + int(budget["pilot_pde_system_count"]),
        "full_system_count": len(panel["systems"]),
        "conditions": tuple(panel["conditions"]),
        "seeds": tuple(panel["seeds"]),
        "maximum_official_cells_total": int(budget["maximum_official_cells_total"]),
        "numeric_payload_opened_during_freeze": False,
        "confirmation_identity_read_count": 0,
        "created_at": now().astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    payload["identity_hash"] = canonical_model_hash(payload)
    identity = OfficialDevelopmentIdentity.model_validate(payload)
    write_json_model(output_root / _IDENTITY_NAME, identity)
    return identity, panel


def _generation_brief(panel: dict[str, Any], budget: dict[str, Any]) -> dict[str, Any]:
    """Panel SHAPE metadata plus the interface contract. No arrays, no scores."""

    shapes = []
    for system in panel["systems"]:
        shapes.append(
            {
                "data_type": system["data_type"],
                # Names are public development identities, not sealed ones.
                "system_name": system["system_name"],
            }
        )
    return {
        "task": (
            "author a fit-once/freeze/predict equation-discovery candidate for the "
            "official MDBench development panel"
        ),
        "objective": (
            "minimise held-out derivative NMSE under clean and SNR20 noise; you are "
            "compared against a tuned symbolic-regression baseline"
        ),
        "panel": {
            "systems": shapes,
            "conditions": panel["conditions"],
            "split_policy": _SPLIT_POLICY,
            "note": (
                "Real measured data with noise. Exact recovery is not expected; "
                "robustness to noise matters more than interpolating the training split."
            ),
        },
        "interface_contract": build_scientific_interface_contract(),
        "budget": {
            "maximum_seconds_per_cell": budget["maximum_seconds_per_cell"],
            "maximum_memory_mb_per_cell": budget["maximum_memory_mb_per_cell"],
            "maximum_cpu_cores_per_cell": budget["maximum_cpu_cores_per_cell"],
        },
    }


def generate_official_candidates(
    *,
    identity: OfficialDevelopmentIdentity,
    panel: dict[str, Any],
    budget: dict[str, Any],
    output_dir: Path | str,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    provider_timeout_seconds: int = 300,
    completion: JsonCompletion = run_llm_json_completion,
    clock: Callable[[], datetime] | None = None,
) -> tuple[OfficialCandidateRecord, ...]:
    """Ask the model for N INDEPENDENT candidates. Score-blind by construction."""

    now = clock or (lambda: datetime.now(timezone.utc))
    output_root = Path(output_dir).resolve()
    brief = _generation_brief(panel, budget)
    records: list[OfficialCandidateRecord] = []
    for index in range(1, identity.initial_candidate_count + 1):
        candidate_id = f"official-{index:02d}"
        interaction_id = f"official-generate-{index:02d}"
        messages = [
            {
                "role": "system",
                "content": (
                    "You are the autonomous scientist authoring an equation-discovery "
                    "method for real noisy measured data. Return exactly one JSON "
                    "object matching the supplied schema. Encode exact standalone "
                    "Python as the JSON array source_lines, one array element per "
                    "physical line, with no newline escapes anywhere. Define exactly "
                    "the two top-level functions fit_equations(payload) and "
                    "predict_derivative(payload). Obey static_source_contract in the "
                    "supplied interface_contract: only allowlisted imports, no "
                    "classes, no lambdas, no async, no while loops, no attribute "
                    "mutation, no print, no dunder access, no dynamic execution, and "
                    "no top-level statements other than imports, literal constants, "
                    "and function definitions. Fit ONLY on the training arrays in the "
                    "fit payload; predict_derivative may read only the frozen "
                    "artifact and one query slice."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {**brief, "candidate_index": index},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            },
        ]
        result, _ = _call_and_record(
            completion=completion,
            messages=messages,
            config_path=config_path,
            env_path=env_path,
            timeout_seconds=provider_timeout_seconds,
            max_tokens=12_000,
            response_schema=_SOURCE_RESPONSE_SCHEMA,
            response_schema_name="scientific_contract_source",
            interaction_id=interaction_id,
            stage="scientific_contract_implementation",
            candidate_id=candidate_id,
            output_root=output_root,
            now=now,
        )
        response = ScientificContractSourceResponse.model_validate(result.parsed_json)
        source_text = response.source_text
        source_path = output_root / "candidates" / candidate_id / "candidate.py"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        with source_path.open("w", encoding="utf-8", newline="") as handle:
            handle.write(source_text)
        review = review_scientific_contract_source(source_text)
        records.append(
            OfficialCandidateRecord(
                candidate_id=candidate_id,
                generation=1,
                interaction_id=interaction_id,
                source_relative_path=source_path.relative_to(output_root).as_posix(),
                source_sha256=review.source_sha256,
                static_review_approved=review.approved,
                static_review_findings=tuple(
                    f"{item.code}: {item.message[:160]}" for item in review.findings
                ),
                implementation_summary=response.implementation_summary,
            )
        )
    write_json_model(
        output_root / "candidates" / "candidate-registry.json",
        {"candidates": [item.model_dump(mode="json") for item in records]},
    )
    return tuple(records)


def _npz_time_length(path: Path) -> int:
    """Read the time-axis length from the NPZ header without importing NumPy."""

    import zipfile

    with zipfile.ZipFile(path) as archive, archive.open("t.npy") as handle:
        header = handle.read(256)
    marker = header.split(b"'shape': (", 1)[1].split(b")", 1)[0]
    return int(marker.split(b",")[0].strip())


def build_official_cell_specs(
    *,
    identity: OfficialDevelopmentIdentity,
    candidates: Sequence[OfficialCandidateRecord],
    stage: Literal["pilot", "full", "baseline"],
    systems: Sequence[dict[str, Any]],
    seeds: Sequence[int],
    output_dir: Path | str,
) -> tuple[OfficialCellSpec, ...]:
    """Freeze every cell for one stage before any of them executes."""

    output_root = Path(output_dir).resolve()
    specs: list[OfficialCellSpec] = []
    method_records: list[tuple[str, str | None, str | None]] = []
    if stage == "baseline":
        method_records.append(("operon_or_pdefind", None, None))
    else:
        for record in candidates:
            if not record.static_review_approved:
                continue
            method_records.append(
                (
                    record.candidate_id,
                    record.source_sha256,
                    record.source_relative_path,
                )
            )

    for candidate_id, source_sha256, _ in method_records:
        for system in systems:
            for condition in identity.conditions:
                for seed in seeds:
                    relative = system["artifact_paths"][condition]
                    payload: dict[str, Any] = {
                        "attempt_id": (
                            f"{stage}-{candidate_id}-{system['system_name']}"
                            f"-{condition}-{seed}"
                        ),
                        "method_kind": "baseline" if stage == "baseline" else "candidate",
                        "candidate_id": candidate_id,
                        "stage": stage,
                        "system_name": system["system_name"],
                        "data_type": system["data_type"],
                        "condition": condition,
                        "seed": int(seed),
                        "data_relative_path": relative,
                        "data_sha256": system["artifact_sha256"][condition],
                        "candidate_source_sha256": source_sha256,
                    }
                    payload["spec_hash"] = canonical_model_hash(payload)
                    specs.append(OfficialCellSpec.model_validate(payload))

    if len(specs) > identity.maximum_official_cells_total:
        raise OfficialDevelopmentSearchError(
            f"stage {stage} would exceed the frozen cell budget: "
            f"{len(specs)} > {identity.maximum_official_cells_total}"
        )
    write_json_model(
        output_root / "cells" / f"{stage}-specs.json",
        {"specs": [item.model_dump(mode="json") for item in specs]},
    )
    return tuple(specs)


def _execute_one_cell(
    *,
    spec: OfficialCellSpec,
    identity: OfficialDevelopmentIdentity,
    output_root: Path,
    candidate_paths: dict[str, Path],
    runner_path: Path,
    baseline_runner_sha256: str,
    baseline_method: dict[str, Any],
    timeout_seconds: int,
) -> OfficialCellResult:
    """Run one cell in a disposable, network-disabled container."""

    cell_dir = output_root / "cells" / spec.stage / spec.attempt_id
    cell_dir.mkdir(parents=True, exist_ok=True)
    result_path = cell_dir / "result.json"
    if result_path.is_file():
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        return _result_from_payload(spec, payload)

    data_path = Path(identity.data_root) / spec.data_relative_path
    runner_spec: dict[str, Any] = {
        "attempt": {
            "attempt_id": spec.attempt_id,
            "system_name": spec.system_name,
            "condition": spec.condition,
            "data_type": spec.data_type,
            "seed": spec.seed,
        },
        "method_kind": spec.method_kind,
        "candidate_source_sha256": spec.candidate_source_sha256,
        "expected_data_sha256": spec.data_sha256,
        "expected_baseline_runner_sha256": baseline_runner_sha256,
        "baseline_method": baseline_method,
        "split_policy": _SPLIT_POLICY,
        "maximum_fit_seconds": timeout_seconds - 30,
        "maximum_predict_seconds": 10,
    }
    runner_spec["spec_hash"] = _canonical(runner_spec)
    spec_path = cell_dir / "spec.json"
    spec_path.write_text(json.dumps(runner_spec, sort_keys=True), encoding="utf-8")

    candidate_path = candidate_paths.get(spec.candidate_id)
    if spec.method_kind == "candidate" and candidate_path is None:
        raise OfficialDevelopmentSearchError(
            f"no source recorded for candidate {spec.candidate_id}"
        )
    mount_candidate = candidate_path or runner_path

    command = [
        "docker", "run", "--rm", "--network", "none", "--read-only",
        "--cpus", "2", "--memory", "4096m", "--memory-swap", "4096m",
        "--pids-limit", "64", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=256m",
        "--mount",
        f"type=bind,src={runner_path.resolve().as_posix()},dst=/harness/runner.py,readonly",
        "--mount",
        f"type=bind,src={mount_candidate.resolve().as_posix()},"
        "dst=/candidate/candidate.py,readonly",
        "--mount",
        f"type=bind,src={spec_path.resolve().as_posix()},dst=/spec/spec.json,readonly",
        "--mount",
        f"type=bind,src={data_path.resolve().as_posix()},dst=/data/data.npz,readonly",
        "--mount", f"type=bind,src={cell_dir.resolve().as_posix()},dst=/out",
        "--entrypoint", "python",
        identity.image_id,
        "/harness/runner.py",
        "--spec", "/spec/spec.json",
        "--data", "/data/data.npz",
        "--candidate", "/candidate/candidate.py",
        "--output", "/out/result.json",
    ]
    try:
        subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds + 60,
            check=False,
        )
    except subprocess.TimeoutExpired:
        payload = {
            "status": "timed_out",
            "failure_reason": "container wall-time budget exceeded",
            "result_hash": "0" * 64,
        }
        result_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        return _result_from_payload(spec, payload)

    if not result_path.is_file():
        payload = {
            "status": "failed",
            "failure_reason": "runner produced no result payload",
            "result_hash": "0" * 64,
        }
        result_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    return _result_from_payload(spec, payload)


def _result_from_payload(
    spec: OfficialCellSpec, payload: dict[str, Any]
) -> OfficialCellResult:
    status = payload.get("status", "failed")
    if status not in {"succeeded", "failed", "timed_out"}:
        status = "failed"
    digest = payload.get("result_hash")
    if not isinstance(digest, str) or len(digest) != 64:
        digest = _canonical(payload)
    return OfficialCellResult(
        attempt_id=spec.attempt_id,
        method_kind=spec.method_kind,
        candidate_id=spec.candidate_id,
        stage=spec.stage,
        system_name=spec.system_name,
        data_type=spec.data_type,
        condition=spec.condition,
        seed=spec.seed,
        status=status,  # type: ignore[arg-type]
        derivative_nmse=payload.get("derivative_nmse"),
        validation_nmse=payload.get("validation_nmse"),
        selected_term_count=payload.get("selected_term_count"),
        equation_changed_on_shuffled_training=payload.get(
            "equation_changed_on_shuffled_training"
        ),
        maximum_equation_prediction_delta=payload.get(
            "maximum_equation_prediction_delta"
        ),
        wall_time_seconds=payload.get("wall_time_seconds"),
        failure_reason=payload.get("failure_reason"),
        result_hash=digest,
    )


def execute_official_stage(
    *,
    identity: OfficialDevelopmentIdentity,
    specs: Sequence[OfficialCellSpec],
    candidates: Sequence[OfficialCandidateRecord],
    output_dir: Path | str,
    baseline_method: dict[str, Any] | None = None,
    timeout_seconds: int = 300,
    maximum_parallel_cells: int = 4,
    research_plan: Any | None = None,
    plan_decision: Any | None = None,
    ledger: Any | None = None,
) -> tuple[OfficialCellResult, ...]:
    """Execute one frozen stage, retaining every failure.

    Pass `baseline_method=None` to route each cell to its domain-valid baseline.

    Two gates run BEFORE any container starts, so neither can be bypassed by a
    partially executed stage:

    * The Task `267.4` research-plan gate. When `research_plan` is supplied,
      `require_approved_plan` must authorize it, and the approved plan hash is
      bound into the persisted stage record. This is the confirmation step the
      project requires between a generated plan and any experiment.
    * The Task `266.3` spend ledger (`P-20260802-066`). When `ledger` is supplied,
      a stage that would cross a frozen limit is refused before spending anything.
    """

    output_root = Path(output_dir).resolve()

    bound_plan_hash: str | None = None
    if research_plan is not None:
        from autoresearch.research.plan_confirmation import require_approved_plan

        # Raises unless a human recorded an approval against this exact plan.
        bound_plan_hash = require_approved_plan(
            plan=research_plan, decision=plan_decision
        )

    if ledger is not None:
        candidate_cells = sum(1 for item in specs if item.method_kind == "candidate")
        baseline_cells = sum(1 for item in specs if item.method_kind == "baseline")
        ledger.check(
            candidate_cells=candidate_cells,
            baseline_cells=baseline_cells,
        )
    runner_path = output_root / "runner" / _RUNNER_SOURCE.name
    if file_hash(runner_path) != identity.runner_sha256:
        raise OfficialDevelopmentSearchError("packaged runner bytes changed")
    candidate_paths = {
        record.candidate_id: output_root / record.source_relative_path
        for record in candidates
    }
    baseline_runner_sha256 = _baseline_runner_sha256(identity)

    def run(spec: OfficialCellSpec) -> OfficialCellResult:
        # Each cell gets the baseline that is valid for ITS domain.
        method = baseline_method or baseline_method_for(spec.data_type)
        return _execute_one_cell(
            spec=spec,
            identity=identity,
            output_root=output_root,
            candidate_paths=candidate_paths,
            runner_path=runner_path,
            baseline_runner_sha256=baseline_runner_sha256,
            baseline_method=method,
            timeout_seconds=timeout_seconds,
        )

    with ThreadPoolExecutor(max_workers=maximum_parallel_cells) as pool:
        results = tuple(pool.map(run, specs))
    stage_record: dict[str, Any] = {
        "results": [item.model_dump(mode="json") for item in results]
    }
    if bound_plan_hash is not None:
        # Binds this execution to the exact plan text a human approved.
        stage_record["approved_research_plan_hash"] = bound_plan_hash
    write_json_model(
        output_root / "cells" / f"{specs[0].stage}-results.json",
        stage_record,
    )
    return results


def _baseline_runner_sha256(identity: OfficialDevelopmentIdentity) -> str:
    """Read the pinned baseline runner hash from inside the image."""

    completed = subprocess.run(
        [
            "docker", "run", "--rm", "--network", "none", "--entrypoint", "python",
            identity.image_id, "-c",
            "import hashlib,pathlib;"
            "print(hashlib.sha256("
            f"pathlib.Path('{_BASELINE_RUNNER_IN_IMAGE}').read_bytes()).hexdigest())",
        ],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    digest = completed.stdout.strip()
    if len(digest) != 64:
        raise OfficialDevelopmentSearchError(
            f"cannot read pinned baseline runner hash: {completed.stderr[:300]}"
        )
    return digest


def compute_system_effects(
    *,
    candidate_id: str,
    candidate_results: Sequence[OfficialCellResult],
    baseline_results: Sequence[OfficialCellResult],
) -> tuple[SystemEffect, ...]:
    """Aggregate repeated measures within system, then form the paired log effect."""

    systems = sorted({item.system_name for item in candidate_results})
    effects: list[SystemEffect] = []
    for system in systems:
        candidate_cells = [
            item
            for item in candidate_results
            if item.system_name == system and item.candidate_id == candidate_id
        ]
        baseline_cells = [item for item in baseline_results if item.system_name == system]
        if not candidate_cells or not baseline_cells:
            continue
        candidate_loss = _median([item.loss for item in candidate_cells])
        baseline_loss = _median([item.loss for item in baseline_cells])
        # A system whose baseline never produced a real loss is UNPAIRED. Recording
        # it as a candidate victory is what inflated the first PDE stratum median.
        baseline_available = any(
            item.status == "succeeded" for item in baseline_cells
        ) and baseline_loss < _LOSS_CAP
        effects.append(
            SystemEffect(
                system_name=system,
                data_type=candidate_cells[0].data_type,
                candidate_median_loss=candidate_loss,
                baseline_median_loss=baseline_loss,
                paired_log_effect=math.log(
                    min(max(baseline_loss, _LOSS_FLOOR), _LOSS_CAP)
                    / min(max(candidate_loss, _LOSS_FLOOR), _LOSS_CAP)
                ),
                candidate_cell_count=len(candidate_cells),
                baseline_cell_count=len(baseline_cells),
                candidate_success_count=sum(
                    item.status == "succeeded" for item in candidate_cells
                ),
                baseline_available=baseline_available,
            )
        )
    return tuple(effects)


def aggregate_paired_effects(
    effects: Sequence[SystemEffect],
) -> dict[str, Any]:
    """Aggregate using PAIRED systems only, and report coverage gaps separately.

    `P-20260802-065`: including an unpaired system credits the candidate for the
    baseline's failure. The first full stage's PDE stratum median of `+10.641766`
    came entirely from `heat_laser` and `heat_soil_uniform_2d_p1`, whose baseline
    took the failure loss; the two PDE systems with a real pair were `-1.2872` and
    `-5.6029`.
    """

    paired = [item for item in effects if item.is_paired]
    unpaired = [item for item in effects if not item.is_paired]
    if not paired:
        return {
            "paired_system_count": 0,
            "unpaired_system_names": tuple(item.system_name for item in unpaired),
            "overall_median_log_effect": None,
            "bootstrap_lower": None,
            "bootstrap_upper": None,
            "ode_stratum_median": None,
            "pde_stratum_median": None,
            "candidate_win_count": 0,
        }
    values = [item.paired_log_effect for item in paired]
    ode = [item.paired_log_effect for item in paired if item.data_type == "ode"]
    pde = [item.paired_log_effect for item in paired if item.data_type == "pde"]
    lower, upper = _bootstrap_interval(values)
    return {
        "paired_system_count": len(paired),
        "unpaired_system_names": tuple(item.system_name for item in unpaired),
        "baseline_coverage_gap_count": len(unpaired),
        "overall_median_log_effect": _median(values),
        "bootstrap_lower": lower,
        "bootstrap_upper": upper,
        "ode_stratum_median": _median(ode) if ode else None,
        "pde_stratum_median": _median(pde) if pde else None,
        "candidate_win_count": sum(1 for value in values if value > 0.0),
    }


def build_candidate_self_observation(
    *,
    candidate_id: str,
    results: Sequence[OfficialCellResult],
) -> dict[str, Any]:
    """Objective, score-blind feedback about ONE candidate's own behaviour.

    Deliberately excludes the baseline's losses and every other candidate's
    results, so a revision cannot be tuned toward the comparison it is measured by.
    What it does expose is the candidate's own generalization gap and term count,
    which is exactly the signal that let Task `266.2` fix its overfitting: pilot v2
    showed `official-01` selecting 57 terms with a validation-to-test gap of
    `+83.14`, and `official-04` fitting validation to `8.32e-27` then testing at
    `2.888e-26`.
    """

    cells = [item for item in results if item.candidate_id == candidate_id]
    if not cells:
        return {"executed_cell_count": 0}
    succeeded = [item for item in cells if item.status == "succeeded"]
    observations: list[dict[str, Any]] = []
    for item in succeeded:
        gap = None
        if item.validation_nmse is not None and item.derivative_nmse is not None:
            gap = float(item.derivative_nmse) - float(item.validation_nmse)
        observations.append(
            {
                "data_type": item.data_type,
                "condition": item.condition,
                "your_selected_term_count": item.selected_term_count,
                "your_validation_nmse": item.validation_nmse,
                "your_held_out_nmse": item.derivative_nmse,
                "your_generalization_gap": gap,
                "your_fit_depended_on_training_target": (
                    item.equation_changed_on_shuffled_training
                ),
            }
        )
    failures: dict[str, int] = {}
    for item in cells:
        if item.status == "succeeded":
            continue
        key = (item.failure_reason or item.status).split(":")[0][:80]
        failures[key] = failures.get(key, 0) + 1
    return {
        "executed_cell_count": len(cells),
        "succeeded_cell_count": len(succeeded),
        "your_cells": observations,
        "your_failure_counts": failures,
        "note": (
            "These are YOUR OWN measurements only. No baseline loss and no other "
            "candidate's result is included. A large positive generalization gap "
            "means you fitted the validation window instead of learning the law."
        ),
    }


def revise_official_candidates(
    *,
    panel: dict[str, Any],
    budget: dict[str, Any],
    candidates: Sequence[OfficialCandidateRecord],
    results: Sequence[OfficialCellResult],
    output_dir: Path | str,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    provider_timeout_seconds: int = 300,
    completion: JsonCompletion = run_llm_json_completion,
    clock: Callable[[], datetime] | None = None,
) -> tuple[OfficialCandidateRecord, ...]:
    """Let each candidate re-author itself from its OWN objective failures.

    This closes the gap that made the first pilot uninformative as science: the
    engine generated eight candidates once and judged them immediately, so no
    candidate ever saw its own behaviour. Task `266.2` only reached a passing gate
    after its candidates could see their own diagnostics.

    Score-blind by construction: a candidate receives only its own metrics, never
    the baseline's losses and never another candidate's source or results.
    """

    now = clock or (lambda: datetime.now(timezone.utc))
    output_root = Path(output_dir).resolve()
    brief = _generation_brief(panel, budget)
    revised: list[OfficialCandidateRecord] = []
    for record in candidates:
        if not record.static_review_approved:
            continue
        observation = build_candidate_self_observation(
            candidate_id=record.candidate_id, results=results
        )
        if not observation.get("executed_cell_count"):
            continue
        parent_source = (output_root / record.source_relative_path).read_text(
            encoding="utf-8"
        )
        revised_id = f"{record.candidate_id}-r2"
        interaction_id = f"official-revise-{record.candidate_id}"
        messages = [
            {
                "role": "system",
                "content": (
                    "You are the autonomous scientist improving YOUR OWN "
                    "equation-discovery method after seeing objective measurements of "
                    "its behaviour. Return exactly one JSON object matching the "
                    "supplied schema, with the complete revised program as "
                    "source_lines, one array element per physical line and no newline "
                    "escapes. Keep the same two top-level functions and obey the same "
                    "static_source_contract. You are NOT told any baseline score or "
                    "any other candidate's result, so do not try to guess them; "
                    "improve your method on its own merits."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        **brief,
                        "your_previous_source": parent_source,
                        "your_previous_measurements": observation,
                        "instruction": (
                            "Diagnose why your method behaved this way and return a "
                            "complete improved replacement. A large positive "
                            "generalization gap means you fitted the validation "
                            "window rather than learning a law that transfers; "
                            "consider selecting model complexity on held-out "
                            "evidence rather than fitting once at maximum capacity."
                        ),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            },
        ]
        result, _ = _call_and_record(
            completion=completion,
            messages=messages,
            config_path=config_path,
            env_path=env_path,
            timeout_seconds=provider_timeout_seconds,
            max_tokens=12_000,
            response_schema=_SOURCE_RESPONSE_SCHEMA,
            response_schema_name="scientific_contract_source",
            interaction_id=interaction_id,
            stage="scientific_contract_repair",
            candidate_id=revised_id,
            output_root=output_root,
            now=now,
        )
        response = ScientificContractSourceResponse.model_validate(result.parsed_json)
        source_text = response.source_text
        source_path = output_root / "candidates" / revised_id / "candidate.py"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        with source_path.open("w", encoding="utf-8", newline="") as handle:
            handle.write(source_text)
        review = review_scientific_contract_source(source_text)
        revised.append(
            OfficialCandidateRecord(
                candidate_id=revised_id,
                generation=2,
                interaction_id=interaction_id,
                source_relative_path=source_path.relative_to(output_root).as_posix(),
                source_sha256=review.source_sha256,
                static_review_approved=review.approved,
                static_review_findings=tuple(
                    f"{item.code}: {item.message[:160]}" for item in review.findings
                ),
                implementation_summary=response.implementation_summary,
            )
        )
    write_json_model(
        output_root / "candidates" / "revised-registry.json",
        {"candidates": [item.model_dump(mode="json") for item in revised]},
    )
    return tuple(revised)


def select_official_candidate(
    *,
    candidates: Sequence[OfficialCandidateRecord],
    results: Sequence[OfficialCellResult],
) -> tuple[str | None, str]:
    """Deterministic, replayable selection on TRAIN-adjacent evidence only.

    Uses validation NMSE, never the held-out test loss that forms the reported
    effect, so selection cannot be contaminated by the outcome being measured.
    """

    eligible = [item.candidate_id for item in candidates if item.static_review_approved]
    best_id, best_loss = None, math.inf
    for candidate_id in sorted(eligible):
        cells = [item for item in results if item.candidate_id == candidate_id]
        if not cells:
            continue
        losses = [
            float(item.validation_nmse)
            if item.status == "succeeded" and item.validation_nmse is not None
            else _FAILURE_LOSS
            for item in cells
        ]
        candidate_loss = _median(losses)
        if candidate_loss < best_loss:
            best_id, best_loss = candidate_id, candidate_loss
    return best_id, "median validation NMSE over executed cells, failures penalised"
