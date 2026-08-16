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

import ast
import hashlib
import json
import math
import random
import subprocess
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, model_serializer, model_validator

from autoresearch.competition.autonomous_engine import (
    AutonomousModelInteraction,
    JsonCompletion,
    _call_and_record,
)
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.competition.plan_execution_contract import (
    CandidatePlanAlignmentAudit,
    PlanExecutionContract,
    ProspectiveCandidatePlanAlignmentAudit,
    ProspectivePlanExecutionContract,
    audit_candidate_plan_alignment,
    audit_prospective_candidate_plan_alignment,
    build_prospective_candidate_execution_declaration,
    compile_plan_execution_contract,
    compile_system_authored_plan_execution_contract,
    load_plan_execution_contract,
    load_prospective_plan_execution_contract,
    require_candidate_plan_alignment,
    require_prospective_candidate_plan_alignment,
    write_plan_execution_contract,
)
from autoresearch.competition.scientific_contract_harness import (
    _SOURCE_RESPONSE_SCHEMA,
    ScientificContractRuntimeEnvironment,
    ScientificContractSourceResponse,
    ScientificContractStaticReview,
    build_scientific_interface_contract,
    inspect_scientific_contract_runtime,
    review_scientific_contract_source,
)
from autoresearch.competition.scientific_contract_recovery import (
    load_scientific_contract_recovery_plan,
)
from autoresearch.llm.client import run_llm_json_completion
from autoresearch.schemas import ResearchPlan, file_hash

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

# Bounded local-conformance repair attempts per candidate. Bounded so a model that
# cannot satisfy the contract fails loudly instead of looping on the frozen budget.
_GENERATION_CONFORMANCE_ATTEMPTS = 3
_AUTHORING_ATTEMPT_NAME = "authoring-attempt.json"

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


class OfficialCandidateAuthoringAttempt(StrictFrozenModel):
    """Durable proof that one frozen candidate slot was actually attempted.

    The marker is written before the first logical model turn.  A provider exception
    can therefore strand neither candidate spend nor the identity needed to resume
    the same generation safely.
    """

    schema_version: Literal["official-candidate-authoring-attempt-v1"] = (
        "official-candidate-authoring-attempt-v1"
    )
    stage: Literal["generate-gen1", "revise-gen2"]
    generation: Literal[1, 2]
    candidate_id: str
    base_interaction_id: str
    parent_source_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    created_at: datetime
    attempt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_attempt_hash(self) -> OfficialCandidateAuthoringAttempt:
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"attempt_hash"})
        )
        if self.attempt_hash != expected:
            raise ValueError("candidate authoring-attempt hash mismatch")
        if (self.generation == 1) != (self.stage == "generate-gen1"):
            raise ValueError("candidate authoring-attempt generation/stage mismatch")
        if (self.generation == 1) != (self.parent_source_sha256 is None):
            raise ValueError("candidate authoring-attempt parent binding mismatch")
        return self


def _register_candidate_authoring_attempt(
    *,
    output_root: Path,
    stage: Literal["generate-gen1", "revise-gen2"],
    generation: Literal[1, 2],
    candidate_id: str,
    base_interaction_id: str,
    parent_source_sha256: str | None,
    now: Callable[[], datetime],
) -> OfficialCandidateAuthoringAttempt:
    """Create once or verify the exact pre-call candidate marker."""

    path = output_root / "candidates" / candidate_id / _AUTHORING_ATTEMPT_NAME
    expected = {
        "stage": stage,
        "generation": generation,
        "candidate_id": candidate_id,
        "base_interaction_id": base_interaction_id,
        "parent_source_sha256": parent_source_sha256,
    }
    if path.is_file():
        try:
            retained = OfficialCandidateAuthoringAttempt.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValidationError) as exc:
            raise OfficialDevelopmentSearchError(
                f"invalid retained candidate authoring attempt for {candidate_id}: {exc}"
            ) from exc
        if any(getattr(retained, key) != value for key, value in expected.items()):
            raise OfficialDevelopmentSearchError(
                f"retained candidate authoring attempt drifted for {candidate_id}"
            )
        return retained
    payload: dict[str, Any] = {
        "schema_version": "official-candidate-authoring-attempt-v1",
        **expected,
        "created_at": now()
        .astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
    }
    payload["attempt_hash"] = canonical_model_hash(payload)
    attempt = OfficialCandidateAuthoringAttempt.model_validate(payload)
    write_json_model(path, attempt)
    return attempt


class OfficialLogicalModelTurnRegistration(StrictFrozenModel):
    """Pre-call registration for one budgeted logical model turn."""

    schema_version: Literal["official-logical-model-turn-registration-v1"] = (
        "official-logical-model-turn-registration-v1"
    )
    interaction_id: str
    candidate_id: str
    stage: Literal[
        "scientific_contract_implementation", "scientific_contract_repair"
    ]
    logical_attempt_index: int = Field(ge=1, le=_GENERATION_CONFORMANCE_ATTEMPTS)
    request_messages_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    response_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    max_tokens: Literal[12_000] = 12_000
    registered_at: datetime
    registration_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_registration_hash(self) -> OfficialLogicalModelTurnRegistration:
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"registration_hash"})
        )
        if self.registration_hash != expected:
            raise ValueError("logical model-turn registration hash mismatch")
        return self


def _register_logical_model_turn(
    *,
    output_root: Path,
    interaction_id: str,
    candidate_id: str,
    stage: Literal[
        "scientific_contract_implementation", "scientific_contract_repair"
    ],
    logical_attempt_index: int,
    messages: Sequence[Mapping[str, str]],
    now: Callable[[], datetime],
) -> OfficialLogicalModelTurnRegistration:
    path = output_root / "interactions" / f"{interaction_id}.logical-turn.json"
    expected = {
        "interaction_id": interaction_id,
        "candidate_id": candidate_id,
        "stage": stage,
        "logical_attempt_index": logical_attempt_index,
        "request_messages_sha256": canonical_model_hash(
            {"messages": [dict(item) for item in messages]}
        ),
        "response_schema_sha256": canonical_model_hash(_SOURCE_RESPONSE_SCHEMA),
        "max_tokens": 12_000,
    }
    if path.is_file():
        try:
            retained = OfficialLogicalModelTurnRegistration.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValidationError) as exc:
            raise OfficialDevelopmentSearchError(
                f"invalid retained logical-turn registration {interaction_id}: {exc}"
            ) from exc
        if any(getattr(retained, key) != value for key, value in expected.items()):
            raise OfficialDevelopmentSearchError(
                f"retained logical-turn registration drifted: {interaction_id}"
            )
        return retained
    payload: dict[str, Any] = {
        "schema_version": "official-logical-model-turn-registration-v1",
        **expected,
        "registered_at": now()
        .astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
    }
    payload["registration_hash"] = canonical_model_hash(payload)
    registration = OfficialLogicalModelTurnRegistration.model_validate(payload)
    write_json_model(path, registration)
    return registration


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
    # Optional only for immutable pre-270.4 registries. New candidates bind the
    # exact accepted interaction (including a repair interaction when that is the
    # response whose source was persisted).
    interaction_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_relative_path: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    static_review_approved: bool
    static_review_findings: tuple[str, ...] = ()
    implementation_summary: str
    authored_by_model: Literal[True] = True
    # Optional only for retained pre-270.2 registries. Every newly generated formal
    # lineage writes all three fields, and the execution entry point refuses their
    # absence before a container can start.
    approved_plan_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    plan_contract_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    plan_alignment: CandidatePlanAlignmentAudit | None = None
    prospective_plan_alignment: ProspectiveCandidatePlanAlignmentAudit | None = None

    @model_validator(mode="after")
    def _validate_plan_alignment(self) -> OfficialCandidateRecord:
        bound = (
            self.approved_plan_hash,
            self.plan_contract_hash,
        )
        audits = (self.plan_alignment, self.prospective_plan_alignment)
        if all(item is None for item in audits):
            if any(item is not None for item in bound):
                raise OfficialDevelopmentSearchError(
                    "candidate plan hashes require exactly one matching alignment audit"
                )
            return self
        if sum(item is not None for item in audits) != 1:
            raise OfficialDevelopmentSearchError(
                "legacy and prospective plan-alignment audits are mutually exclusive"
            )
        if any(item is None for item in bound):
            raise OfficialDevelopmentSearchError(
                "candidate plan binding must include plan hash, contract hash, and one audit"
            )
        if self.plan_alignment is not None:
            if self.plan_alignment.approved_plan_hash != self.approved_plan_hash:
                raise OfficialDevelopmentSearchError(
                    "candidate plan-alignment audit binds a different approved plan"
                )
            if self.plan_alignment.plan_contract_hash != self.plan_contract_hash:
                raise OfficialDevelopmentSearchError(
                    "candidate plan-alignment audit binds a different execution contract"
                )
            if self.plan_alignment.source_sha256 != self.source_sha256:
                raise OfficialDevelopmentSearchError(
                    "candidate plan-alignment audit binds different source bytes"
                )
            if self.static_review_approved and not self.plan_alignment.passed:
                raise OfficialDevelopmentSearchError(
                    "a plan-misaligned candidate cannot pass static review"
                )
        if self.prospective_plan_alignment is not None:
            if (
                self.prospective_plan_alignment.approved_plan_hash
                != self.approved_plan_hash
            ):
                raise OfficialDevelopmentSearchError(
                    "prospective candidate audit binds a different approved plan"
                )
            if (
                self.prospective_plan_alignment.plan_contract_hash
                != self.plan_contract_hash
            ):
                raise OfficialDevelopmentSearchError(
                    "prospective candidate audit binds a different execution contract"
                )
            if self.prospective_plan_alignment.source_sha256 != self.source_sha256:
                raise OfficialDevelopmentSearchError(
                    "prospective candidate audit binds different source bytes"
                )
            if self.static_review_approved and not self.prospective_plan_alignment.passed:
                raise OfficialDevelopmentSearchError(
                    "a prospective-plan-misaligned candidate cannot pass static review"
                )
        return self

    @model_serializer(mode="wrap")
    def _serialize_with_legacy_compatibility(self, handler: Any) -> dict[str, Any]:
        """Do not inject null plan fields into immutable pre-270.2 records.

        Retained package hashes cover candidate serialization. Emitting three new
        ``null`` keys while loading an old candidate would invalidate real evidence.
        New records carry non-null bindings and therefore serialize all three keys.
        """

        payload = dict(handler(self))
        if self.interaction_hash is None:
            payload.pop("interaction_hash", None)
        if self.plan_alignment is None and self.prospective_plan_alignment is None:
            payload.pop("approved_plan_hash", None)
            payload.pop("plan_contract_hash", None)
        if self.plan_alignment is None:
            payload.pop("plan_alignment", None)
        if self.prospective_plan_alignment is None:
            payload.pop("prospective_plan_alignment", None)
        return payload


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


_AnyPlanExecutionContract = PlanExecutionContract | ProspectivePlanExecutionContract


def _compile_requested_plan_execution_contract(
    research_plan: Any | None,
) -> _AnyPlanExecutionContract | None:
    """Compile the exact contract family carried by the caller.

    Historical ``ResearchPlan`` inputs keep the token-based v1 path.  A formal
    system-authored artifact must retain its complete prospective lineage and is
    therefore compiled through the v2 entry point.  Supplying an already compiled
    contract is useful to stage-local callers and never downgrades it.
    """

    if research_plan is None:
        return None
    if isinstance(research_plan, PlanExecutionContract | ProspectivePlanExecutionContract):
        return research_plan
    schema_version = (
        research_plan.get("schema_version")
        if isinstance(research_plan, Mapping)
        else getattr(research_plan, "schema_version", None)
    )
    if schema_version == "plan-execution-contract-v1":
        return PlanExecutionContract.model_validate(research_plan)
    if schema_version == "plan-execution-contract-v2":
        return ProspectivePlanExecutionContract.model_validate(research_plan)
    if schema_version == "system-authored-research-plan-v2":
        return compile_system_authored_plan_execution_contract(research_plan)
    return compile_plan_execution_contract(research_plan)


def _approval_plan(research_plan: Any) -> ResearchPlan:
    """Recover the exact human-approved ``ResearchPlan`` from the caller's input.

    The plan gate must fire before any execution-contract compilation, so this
    derives the approved plan directly rather than from a compiled contract.
    Historical ``ResearchPlan`` inputs are the plan themselves; a formal
    system-authored artifact carries the complete plan in its ``plan`` field; a
    compiled prospective contract carries it in ``approved_plan``.
    """

    if isinstance(research_plan, ResearchPlan):
        return research_plan
    if isinstance(research_plan, ProspectivePlanExecutionContract):
        return ResearchPlan.model_validate(research_plan.approved_plan)
    if isinstance(research_plan, PlanExecutionContract):
        raise OfficialDevelopmentSearchError(
            "a detached legacy v1 execution contract does not contain the complete "
            "ResearchPlan required for human approval"
        )
    schema_version = (
        research_plan.get("schema_version")
        if isinstance(research_plan, Mapping)
        else getattr(research_plan, "schema_version", None)
    )
    if schema_version == "system-authored-research-plan-v2":
        plan_payload = (
            research_plan.get("plan")
            if isinstance(research_plan, Mapping)
            else research_plan.plan
        )
        return ResearchPlan.model_validate(plan_payload)
    if schema_version == "plan-execution-contract-v2":
        approved = (
            research_plan.get("approved_plan")
            if isinstance(research_plan, Mapping)
            else research_plan.approved_plan
        )
        return ResearchPlan.model_validate(approved)
    if schema_version == "plan-execution-contract-v1":
        raise OfficialDevelopmentSearchError(
            "a detached legacy v1 execution contract does not contain the complete "
            "ResearchPlan required for human approval"
        )
    return ResearchPlan.model_validate(research_plan)


def _load_matching_plan_execution_contract(
    *, output_root: Path, expected: _AnyPlanExecutionContract
) -> _AnyPlanExecutionContract:
    retained: _AnyPlanExecutionContract
    if isinstance(expected, ProspectivePlanExecutionContract):
        retained = load_prospective_plan_execution_contract(output_root)
    else:
        retained = load_plan_execution_contract(output_root)
    if retained != expected:
        raise OfficialDevelopmentSearchError(
            "retained plan execution contract differs from the approved plan"
        )
    return retained


def _audit_source_against_contract(
    *, candidate_id: str, source_text: str, contract: _AnyPlanExecutionContract
) -> tuple[
    CandidatePlanAlignmentAudit | None,
    ProspectiveCandidatePlanAlignmentAudit | None,
    tuple[str, ...],
]:
    if isinstance(contract, ProspectivePlanExecutionContract):
        prospective = audit_prospective_candidate_plan_alignment(
            candidate_id=candidate_id,
            source_text=source_text,
            contract=contract,
        )
        findings = tuple(
            f"PROSPECTIVE_PLAN_NOT_IMPLEMENTED: {item}"
            for item in prospective.findings
        )
        return None, prospective, findings
    legacy = audit_candidate_plan_alignment(
        candidate_id=candidate_id,
        source_text=source_text,
        contract=contract,
    )
    findings = (
        (
            "PLAN_METHOD_NOT_IMPLEMENTED: reachable source is missing approved "
            f"method tokens {list(legacy.missing_method_tokens)}"
        ),
    ) if not legacy.passed else ()
    return legacy, None, findings


def _require_candidates_match_contract(
    *,
    candidates: Sequence[OfficialCandidateRecord],
    contract: _AnyPlanExecutionContract,
    output_root: Path,
) -> None:
    """Dispatch the family-specific gate; v2 also re-audits retained source bytes."""

    if isinstance(contract, PlanExecutionContract):
        require_candidate_plan_alignment(candidates=candidates, contract=contract)
        return
    require_prospective_candidate_plan_alignment(candidates=candidates, contract=contract)
    failures: list[str] = []
    for candidate in candidates:
        source_path = (output_root / candidate.source_relative_path).resolve()
        try:
            source_path.relative_to(output_root)
        except ValueError:
            failures.append(f"{candidate.candidate_id}: source path escapes output root")
            continue
        if not source_path.is_file():
            failures.append(f"{candidate.candidate_id}: retained source is missing")
            continue
        source_text = source_path.read_text(encoding="utf-8")
        _legacy, fresh, topology = _audit_source_against_contract(
            candidate_id=candidate.candidate_id,
            source_text=source_text,
            contract=contract,
        )
        if fresh != candidate.prospective_plan_alignment:
            failures.append(
                f"{candidate.candidate_id}: retained prospective audit does not match "
                "the current source bytes"
            )
        failures.extend(f"{candidate.candidate_id}: {item}" for item in topology)
        if not candidate.static_review_approved:
            failures.append(f"{candidate.candidate_id}: static review is not approved")
    if failures:
        raise OfficialDevelopmentSearchError(
            "formal prospective candidate failed retained-source verification: "
            + "; ".join(failures)
        )


def _formal_prospective_source_contract(
    contract: ProspectivePlanExecutionContract,
) -> dict[str, Any]:
    """Return the exact v2 source shape Qwen must author without code injection."""

    declaration = build_prospective_candidate_execution_declaration(contract)
    declaration_payload = declaration.model_dump(mode="python")
    anchor = contract.implementation_anchor
    return {
        "schema_version": "formal-prospective-source-contract-v2",
        "candidate_execution_declaration_schema_version": declaration.schema_version,
        "candidate_alignment_audit_schema_version": (
            "candidate-plan-alignment-audit-v3"
        ),
        "module_constant_name": "PROSPECTIVE_EXECUTION_DECLARATION",
        "exact_python_assignment": (
            "PROSPECTIVE_EXECUTION_DECLARATION = " f"{declaration_payload!r}"
        ),
        "literal_only": True,
        "declaration_read_only": True,
        "declaration_alias_argument_container_store_del_forbidden": True,
        "dead_code_reads_do_not_count": True,
        "implementation_anchor_helper": anchor,
        "implementation_anchor_definition_count": 1,
        "runtime_binding_payload_key": "prospective_execution_binding",
        "identity_guards": [
            {
                "runtime_path": (
                    "prospective_execution_binding.plan_execution_contract_hash"
                ),
                "declaration_path": "plan_execution_contract_hash",
                "operator": "!=",
                "on_mismatch": "raise",
            },
            {
                "runtime_path": (
                    "prospective_execution_binding.selected_intervention_hash"
                ),
                "declaration_path": (
                    "selected_intervention_identity.intervention_hash"
                ),
                "operator": "!=",
                "on_mismatch": "raise",
            },
            {
                "runtime_path": "prospective_execution_binding.pair_contract_hash",
                "declaration_path": "paired_control_treatment.pair_hash",
                "operator": "!=",
                "on_mismatch": "raise",
            },
        ],
        "identity_guards_must_precede_arm_selection": True,
        "runtime_configuration_selector": {
            "runtime_path": (
                "prospective_execution_binding.configuration["
                "PROSPECTIVE_EXECUTION_DECLARATION."
                "paired_control_treatment.intervention_key]"
            ),
            "control_declaration_path": (
                "paired_control_treatment.control_configuration["
                "paired_control_treatment.intervention_key]"
            ),
            "treatment_declaration_path": (
                "paired_control_treatment.treatment_configuration["
                "paired_control_treatment.intervention_key]"
            ),
            "comparison_operator": "==",
        },
        "control_helper": f"{anchor}__control",
        "treatment_helper": f"{anchor}__treatment",
        "control_treatment_helpers_must_be_distinct": True,
        "helper_bodies_are_scientific_not_topology": True,
        "unknown_arm_action": "raise",
        "public_hooks_must_directly_return_dispatcher": list(contract.public_hooks),
        "ordinary_top_level_helpers_allowed": True,
        "orchestrator_may_inject_or_rewrite_source": False,
    }


def _formal_prospective_topology_instruction(
    contract: ProspectivePlanExecutionContract,
    *,
    revision: bool,
) -> str:
    """Describe the restricted dispatcher; only Qwen may author the resulting code."""

    verb = "Preserve" if revision else "Copy"
    anchor = contract.implementation_anchor
    return (
        f"{verb} the supplied exact module-level "
        "PROSPECTIVE_EXECUTION_DECLARATION v2 assignment. Never alias, pass, "
        "return, wrap in a container, mutate, Store, or Del that declaration; "
        "reads hidden under if False do not count. Define exactly one top-level "
        f"restricted dispatcher named {anchor}. Before any scientific return, it "
        "must execute exactly the three identity guards in prospective_source_contract "
        "against the runtime prospective_execution_binding and raise on every "
        "mismatch. It must then consume the runtime prospective_execution_binding "
        "configuration at the declared intervention key, select the declared control "
        "and treatment levels, call distinct control and treatment helpers, and raise "
        "for every unknown arm. The control and treatment helper bodies contain the "
        "scientific implementation; do not put scientific computation in the "
        "dispatcher. Every selected public hook must directly return the dispatcher "
        "with no fallback or bypass. The complete source must be authored in your "
        "source_lines response; the orchestrator will not inject or rewrite code."
    )


def _generation_brief(
    panel: dict[str, Any],
    budget: dict[str, Any],
    *,
    plan_execution_contract: _AnyPlanExecutionContract | None = None,
) -> dict[str, Any]:
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
    brief: dict[str, Any] = {
        "task": (
            "author a fit-once/freeze/predict equation-discovery candidate for the "
            "official MDBench development panel"
        ),
        # P-20260802-068: the prior lineage's selected candidate returned zero terms
        # on one system, so its sparse selection collapsed to the empty set on that
        # system's scaling. This states the REQUIREMENT; the candidate still chooses
        # its own library, estimator, thresholds, and fallback strategy.
        "non_empty_support_requirement": (
            "Every returned equation must contain at least one concrete term. If your "
            "sparse selection retains nothing on a given system, fall back to a "
            "minimal non-empty support rather than returning an empty term list, "
            "because an empty equation is rejected by the contract and scores as a "
            "failed cell."
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
    if plan_execution_contract is not None:
        # This is the scientific content that was actually approved, not merely its
        # hash. It is retained in the interaction prompt and therefore auditable.
        brief["approved_research_plan_execution_contract"] = (
            plan_execution_contract.model_dump(mode="json")
        )
        if isinstance(plan_execution_contract, ProspectivePlanExecutionContract):
            contract = plan_execution_contract
            if contract.implementation_anchor in contract.public_hooks:
                raise OfficialDevelopmentSearchError(
                    "formal prospective implementation_anchor must be a helper distinct "
                    "from every public hook"
                )
            declaration = build_prospective_candidate_execution_declaration(contract)
            brief["prospective_candidate_execution_declaration"] = (
                declaration.model_dump(mode="json")
            )
            source_contract = _formal_prospective_source_contract(contract)
            brief["prospective_source_contract"] = source_contract
            static_contract = brief["interface_contract"]["static_source_contract"]
            static_contract["formal_prospective_extension"] = {
                "schema_version": "formal-prospective-static-extension-v2",
                "required_alignment_audit": "candidate-plan-alignment-audit-v3",
                "required_module_literal": "PROSPECTIVE_EXECUTION_DECLARATION",
                "required_unique_implementation_anchor_helper": (
                    contract.implementation_anchor
                ),
                "required_runtime_binding_payload_key": (
                    "prospective_execution_binding"
                ),
                "required_identity_guard_count": 3,
                "identity_guards_must_precede_arm_selection": True,
                "runtime_configuration_must_select_distinct_arm_helpers": True,
                "unknown_arm_must_raise": True,
                "every_declared_public_hook_must_directly_return_anchor": list(
                    contract.public_hooks
                ),
                "declaration_must_remain_read_only_without_alias_or_escape": True,
                "additional_ordinary_helpers_allowed": True,
            }
            brief["plan_alignment_requirement"] = (
                "Implement the exact selected prospective intervention, not an "
                "alternative method and not a token-level approximation. Copy "
                "prospective_source_contract.exact_python_assignment verbatim as one "
                "module-level literal assignment named "
                "PROSPECTIVE_EXECUTION_DECLARATION; do not construct, mutate, or "
                "replace it at runtime. Author the exact three reachable identity "
                "guards, runtime prospective_execution_binding configuration selector, "
                "two distinct arm helpers, terminal unknown-arm raise, and direct "
                "public-hook dispatcher returns described by prospective_source_contract. "
                "Do not satisfy any requirement in dead code. Ordinary scientific "
                "helpers are allowed, but the orchestrator will never add missing code."
            )
        else:
            brief["plan_alignment_requirement"] = (
                "Implement the approved plan, not an alternative method. Every item in "
                "required_method_tokens must occur in a callable actually reached from "
                "fit_equations or predict_derivative. Comments, prose, docstrings, "
                "variable names, and unused helper functions do not count."
            )
    return brief


def _format_field_error(error: Mapping[str, Any]) -> str:
    """Render one pydantic error as `field: message`, so the model can act on it."""

    location = ".".join(str(part) for part in error.get("loc", ())) or "(root)"
    return f"{location}: {error.get('msg', 'invalid')}"


_REPAIRABLE_STATIC_TOPOLOGY_CODES = frozenset(
    {"missing_interface", "invalid_interface"}
)
_METHOD_NARRATIVE_FIELDS = (
    "observation",
    "problem",
    "hypothesis",
    "intervention",
    "expected_effect",
    "implementation_summary",
)


def _method_narrative(response: ScientificContractSourceResponse) -> tuple[str, ...]:
    return tuple(str(getattr(response, field)) for field in _METHOD_NARRATIVE_FIELDS)


def _source_call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _source_call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _scientific_method_signature(
    source_text: str,
    *,
    plan_contract: _AnyPlanExecutionContract | None,
) -> str:
    """Fingerprint scientific literals/operators while ignoring allowed topology glue."""

    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    ignored_calls: set[str] = set()
    ignored_topology_functions: set[str] = set()
    if isinstance(plan_contract, ProspectivePlanExecutionContract):
        ignored_calls = {
            plan_contract.implementation_anchor,
            *plan_contract.public_hooks,
        }
        ignored_topology_functions = set(ignored_calls)
    ignored_strings = {
        "plan_execution_contract_hash",
        "selected_intervention_identity",
        "paired_control_treatment",
    }
    science: list[tuple[str, str]] = []
    for statement in tree.body:
        if (
            isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef)
            and statement.name in ignored_topology_functions
        ):
            # The v3 audit restricts these functions to identity guards, arm routing,
            # and direct hook dispatch.  Scientific work must live in the two arm
            # helpers, whose complete bodies remain in this fingerprint.
            continue
        if isinstance(statement, ast.Assign | ast.AnnAssign):
            targets = (
                statement.targets
                if isinstance(statement, ast.Assign)
                else (statement.target,)
            )
            if any(
                isinstance(target, ast.Name)
                and target.id == "PROSPECTIVE_EXECUTION_DECLARATION"
                for target in targets
            ):
                continue
        for node in ast.walk(statement):
            if isinstance(node, ast.Constant):
                if isinstance(node.value, str) and node.value in ignored_strings:
                    continue
                science.append(("constant", repr(node.value)))
            elif isinstance(node, ast.Call):
                name = _source_call_name(node.func)
                if name and name.split(".")[-1] not in ignored_calls:
                    science.append(("call", name))
            elif isinstance(
                node,
                ast.operator | ast.unaryop | ast.boolop | ast.cmpop,
            ):
                science.append(("operator", type(node).__name__))
            elif isinstance(node, ast.Import):
                science.extend(("import", alias.name) for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                science.append(("import_from", node.module or ""))
    return canonical_model_hash({"scientific_method_features": science})


def _source_assessment(
    *,
    candidate_id: str,
    source_text: str,
    plan_contract: _AnyPlanExecutionContract | None,
) -> tuple[
    ScientificContractStaticReview,
    CandidatePlanAlignmentAudit | None,
    ProspectiveCandidatePlanAlignmentAudit | None,
    tuple[str, ...],
]:
    review = review_scientific_contract_source(source_text)
    legacy_alignment: CandidatePlanAlignmentAudit | None = None
    prospective_alignment: ProspectiveCandidatePlanAlignmentAudit | None = None
    alignment_findings: tuple[str, ...] = ()
    if plan_contract is not None:
        legacy_alignment, prospective_alignment, alignment_findings = (
            _audit_source_against_contract(
                candidate_id=candidate_id,
                source_text=source_text,
                contract=plan_contract,
            )
        )
    return review, legacy_alignment, prospective_alignment, alignment_findings


def _repairable_topology_findings(
    *,
    review: ScientificContractStaticReview,
    prospective_alignment: ProspectiveCandidatePlanAlignmentAudit | None,
) -> tuple[str, ...]:
    """Return only structural findings that a topology-only turn may change."""

    non_topology = [
        item for item in review.findings if item.code not in _REPAIRABLE_STATIC_TOPOLOGY_CODES
    ]
    if non_topology:
        return ()
    findings = [
        f"{item.code}: {item.message}" for item in review.findings
    ]
    if prospective_alignment is not None and not prospective_alignment.passed:
        findings.extend(prospective_alignment.findings)
    return tuple(dict.fromkeys(findings))


def _author_source_with_bounded_repairs(
    *,
    completion: JsonCompletion,
    messages: list[dict[str, str]],
    config_path: Path | str,
    env_path: Path | str,
    provider_timeout_seconds: int,
    base_interaction_id: str,
    first_stage: Literal[
        "scientific_contract_implementation", "scientific_contract_repair"
    ],
    candidate_id: str,
    output_root: Path,
    now: Callable[[], datetime],
    plan_contract: _AnyPlanExecutionContract | None,
    failure_label: str,
) -> tuple[
    ScientificContractSourceResponse,
    AutonomousModelInteraction,
    ScientificContractStaticReview,
    CandidatePlanAlignmentAudit | None,
    ProspectiveCandidatePlanAlignmentAudit | None,
    tuple[str, ...],
]:
    """Use at most three logical turns for schema and topology conformance together."""

    attempt_messages = list(messages)
    schema_errors: list[str] = []
    topology_basis: ScientificContractSourceResponse | None = None
    topology_basis_science_signature: str | None = None
    first_response_narrative: dict[str, str] = {}
    first_response_science_signature: str | None = None
    schema_repair_pending = False
    method_drift_findings: tuple[str, ...] = ()
    last_assessment: tuple[
        ScientificContractSourceResponse,
        AutonomousModelInteraction,
        ScientificContractStaticReview,
        CandidatePlanAlignmentAudit | None,
        ProspectiveCandidatePlanAlignmentAudit | None,
        tuple[str, ...],
    ] | None = None
    for attempt in range(1, _GENERATION_CONFORMANCE_ATTEMPTS + 1):
        interaction_id = (
            base_interaction_id
            if attempt == 1
            else f"{base_interaction_id}-repair{attempt}"
        )
        interaction_stage = (
            first_stage if attempt == 1 else "scientific_contract_repair"
        )
        _register_logical_model_turn(
            output_root=output_root,
            interaction_id=interaction_id,
            candidate_id=candidate_id,
            stage=interaction_stage,
            logical_attempt_index=attempt,
            messages=attempt_messages,
            now=now,
        )
        result, interaction = _call_and_record(
            completion=completion,
            messages=attempt_messages,
            config_path=config_path,
            env_path=env_path,
            timeout_seconds=provider_timeout_seconds,
            max_tokens=12_000,
            response_schema=_SOURCE_RESPONSE_SCHEMA,
            response_schema_name="scientific_contract_source",
            interaction_id=interaction_id,
            stage=interaction_stage,
            candidate_id=candidate_id,
            output_root=output_root,
            now=now,
        )
        if attempt == 1 and isinstance(result.parsed_json, Mapping):
            first_response_narrative = {
                field: value
                for field in _METHOD_NARRATIVE_FIELDS
                if isinstance(
                    (value := result.parsed_json.get(field)),
                    str,
                )
            }
            initial_source_lines = result.parsed_json.get("source_lines")
            if isinstance(initial_source_lines, list) and all(
                isinstance(item, str) for item in initial_source_lines
            ):
                first_response_science_signature = _scientific_method_signature(
                    "\n".join(initial_source_lines),
                    plan_contract=plan_contract,
                )
        try:
            response = ScientificContractSourceResponse.model_validate(result.parsed_json)
        except ValidationError as exc:
            schema_repair_pending = True
            schema_errors = [_format_field_error(item) for item in exc.errors()]
            if attempt == _GENERATION_CONFORMANCE_ATTEMPTS:
                break
            attempt_messages = [
                *messages,
                {
                    "role": "user",
                    "content": (
                        "Your previous json object failed strict local validation with "
                        "these errors: "
                        + "; ".join(schema_errors)
                        + ". Return the corrected json object with every required field "
                        "present. Change only what the errors name; keep the scientific "
                        "method, all six scientific narrative fields, and source_lines "
                        "otherwise identical. Every subsequent response is mechanically "
                        "compared with the scientific content of this first response. "
                        "Previous json: "
                        + json.dumps(result.parsed_json, ensure_ascii=False, sort_keys=True)
                    ),
                },
            ]
            continue

        review, legacy, prospective, alignment_findings = _source_assessment(
            candidate_id=candidate_id,
            source_text=response.source_text,
            plan_contract=plan_contract,
        )
        current_science_signature = _scientific_method_signature(
            response.source_text, plan_contract=plan_contract
        )
        schema_repair_drift_fields = tuple(
            field
            for field, frozen_value in first_response_narrative.items()
            if str(getattr(response, field)) != frozen_value
        )
        schema_repair_science_drift = bool(
            first_response_science_signature is not None
            and current_science_signature != first_response_science_signature
        )
        drift_findings: list[str] = []
        if schema_repair_pending and (
            schema_repair_drift_fields or schema_repair_science_drift
        ):
            drift_findings.append(
                "REPAIR_SCIENTIFIC_NARRATIVE_DRIFT: schema repair changed frozen "
                "scientific narrative or arm-helper implementation"
            )
        if topology_basis is not None and (
            _method_narrative(response) != _method_narrative(topology_basis)
            or current_science_signature != topology_basis_science_signature
        ):
            drift_findings.append(
                "TOPOLOGY_REPAIR_METHOD_DRIFT: topology repair changed one or more "
                "frozen scientific-method narrative fields or arm-helper bodies"
            )
        method_drift_findings = tuple(dict.fromkeys(drift_findings))
        if not method_drift_findings:
            schema_repair_pending = False
        last_assessment = (
            response,
            interaction,
            review,
            legacy,
            prospective,
            (*alignment_findings, *method_drift_findings),
        )
        topology_findings = _repairable_topology_findings(
            review=review,
            prospective_alignment=prospective,
        )
        if method_drift_findings:
            topology_findings = (*topology_findings, *method_drift_findings)
        if not topology_findings or attempt == _GENERATION_CONFORMANCE_ATTEMPTS:
            return last_assessment

        if topology_basis is None:
            topology_basis = response
            topology_basis_science_signature = current_science_signature
        attempt_messages = [
            *messages,
            {
                "role": "user",
                "content": (
                    "The exact source passed JSON schema validation but failed only "
                    "deterministic static/prospective topology checks: "
                    + "; ".join(topology_findings)
                    + ". Return the complete corrected JSON object. This is a "
                    "topology-only repair: preserve the scientific method, equations, "
                    "feature library, coefficients, thresholds, fitting logic, "
                    "prediction mathematics, and all six scientific narrative fields "
                    "exactly. Do not change the control and treatment helper bodies. Change "
                    "only the exact execution declaration, selected implementation-anchor "
                    "dispatcher, three identity guards, runtime "
                    "configuration selector and its two helper call sites, terminal "
                    "unknown-arm raise, and direct public-hook dispatcher returns needed "
                    "by those findings. Never hide a read under if False or introduce an "
                    "alias, fallback, or bypass. Frozen scientific narrative: "
                    + json.dumps(
                        first_response_narrative,
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    + ". "
                    "Previous exact source_lines: "
                    + json.dumps(list(response.source_lines), ensure_ascii=False)
                ),
            },
        ]

    if last_assessment is not None:
        return last_assessment
    raise OfficialDevelopmentSearchError(
        f"{candidate_id} could not produce a schema-conformant {failure_label} in "
        f"{_GENERATION_CONFORMANCE_ATTEMPTS} attempts: {'; '.join(schema_errors)}"
    )


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
    research_plan: Any | None = None,
) -> tuple[OfficialCandidateRecord, ...]:
    """Ask the model for N INDEPENDENT candidates. Score-blind by construction."""

    now = clock or (lambda: datetime.now(timezone.utc))
    output_root = Path(output_dir).resolve()
    plan_contract = _compile_requested_plan_execution_contract(research_plan)
    if plan_contract is not None:
        write_plan_execution_contract(contract=plan_contract, output_dir=output_root)
    brief = _generation_brief(
        panel, budget, plan_execution_contract=plan_contract
    )
    records: list[OfficialCandidateRecord] = []
    for index in range(1, identity.initial_candidate_count + 1):
        candidate_id = f"official-{index:02d}"
        interaction_id = f"official-generate-{index:02d}"
        _register_candidate_authoring_attempt(
            output_root=output_root,
            stage="generate-gen1",
            generation=1,
            candidate_id=candidate_id,
            base_interaction_id=interaction_id,
            parent_source_sha256=None,
            now=now,
        )
        if isinstance(plan_contract, ProspectivePlanExecutionContract):
            topology_instruction = _formal_prospective_topology_instruction(
                plan_contract,
                revision=False,
            )
        else:
            topology_instruction = (
                "Define exactly the two top-level functions fit_equations(payload) and "
                "predict_derivative(payload)."
            )
        messages = [
            {
                "role": "system",
                "content": (
                    "You are the autonomous scientist authoring an equation-discovery "
                    "method for real noisy measured data. Return exactly one JSON "
                    "object matching the supplied schema. Encode exact standalone "
                    "Python as the JSON array source_lines, one array element per "
                    "physical line, with no newline escapes anywhere. "
                    + topology_instruction
                    + " Obey static_source_contract in the "
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
        (
            response,
            accepted_interaction,
            review,
            legacy_alignment,
            prospective_alignment,
            alignment_findings,
        ) = _author_source_with_bounded_repairs(
            completion=completion,
            messages=messages,
            config_path=config_path,
            env_path=env_path,
            provider_timeout_seconds=provider_timeout_seconds,
            base_interaction_id=interaction_id,
            first_stage="scientific_contract_implementation",
            candidate_id=candidate_id,
            output_root=output_root,
            now=now,
            plan_contract=plan_contract,
            failure_label="response",
        )
        source_text = response.source_text
        source_path = output_root / "candidates" / candidate_id / "candidate.py"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        with source_path.open("w", encoding="utf-8", newline="") as handle:
            handle.write(source_text)
        findings = [
            f"{item.code}: {item.message[:160]}" for item in review.findings
        ]
        findings.extend(alignment_findings)
        alignment_passed = (
            (legacy_alignment is None or legacy_alignment.passed)
            and (prospective_alignment is None or prospective_alignment.passed)
            and not alignment_findings
        )
        records.append(
            OfficialCandidateRecord(
                candidate_id=candidate_id,
                generation=1,
                interaction_id=accepted_interaction.interaction_id,
                interaction_hash=accepted_interaction.interaction_hash,
                source_relative_path=source_path.relative_to(output_root).as_posix(),
                source_sha256=review.source_sha256,
                static_review_approved=(
                    review.approved and alignment_passed
                ),
                static_review_findings=tuple(findings),
                implementation_summary=response.implementation_summary,
                approved_plan_hash=(
                    plan_contract.approved_plan_hash if plan_contract is not None else None
                ),
                plan_contract_hash=(
                    plan_contract.contract_hash if plan_contract is not None else None
                ),
                plan_alignment=legacy_alignment,
                prospective_plan_alignment=prospective_alignment,
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
            "spec_hash": runner_spec["spec_hash"],
        }
        payload["result_hash"] = _canonical(payload)
        result_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        return _result_from_payload(spec, payload)

    if not result_path.is_file():
        payload = {
            "status": "failed",
            "failure_reason": "runner produced no result payload",
            "spec_hash": runner_spec["spec_hash"],
        }
        payload["result_hash"] = _canonical(payload)
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
        status=status,
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
    prior_results: Sequence[OfficialCellResult] = (),
) -> tuple[OfficialCellResult, ...]:
    """Execute one frozen stage, retaining every failure.

    Pass `baseline_method=None` to route each cell to its domain-valid baseline.

    `prior_results` carries cells of THIS stage that already executed in an earlier
    wave, so a stage can be run in waves without the second wave overwriting the
    first's record. `P-20260804-080` needs this: the full stage now runs a smoke wave
    first, and a qualifying candidate's smoke cells are legitimate full cells that
    must stay in the effect rather than being discarded and re-run.

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
    bound_contract_hash: str | None = None
    if research_plan is not None:
        from autoresearch.research.plan_confirmation import require_approved_plan

        # The research-plan gate (Task 267.4) is the physical precondition and
        # must fire before any contract compilation: an unapproved plan is
        # refused even when its brief cannot yet be compiled, so a contract
        # error can never mask a missing approval.
        approval_plan = _approval_plan(research_plan)
        # Raises unless a human recorded an approval against this exact plan.
        bound_plan_hash = require_approved_plan(
            plan=approval_plan, decision=plan_decision
        )

        expected_contract = _compile_requested_plan_execution_contract(research_plan)
        if expected_contract is None:  # pragma: no cover - narrowed by the branch
            raise OfficialDevelopmentSearchError("research plan contract is missing")
        retained_contract = _load_matching_plan_execution_contract(
            output_root=output_root,
            expected=expected_contract,
        )
        _require_candidates_match_contract(
            candidates=candidates,
            contract=retained_contract,
            output_root=output_root,
        )
        bound_contract_hash = retained_contract.contract_hash

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
        executed = tuple(pool.map(run, specs))
    # Earlier waves of the same stage come first, so the persisted order follows
    # execution order and no earlier cell is lost.
    results = (*prior_results, *executed)
    stage_record: dict[str, Any] = {
        "results": [item.model_dump(mode="json") for item in results]
    }
    if bound_plan_hash is not None:
        # Binds this execution to the exact plan text a human approved.
        stage_record["approved_research_plan_hash"] = bound_plan_hash
        stage_record["plan_execution_contract_hash"] = bound_contract_hash
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
    research_plan: Any | None = None,
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
    plan_contract = _compile_requested_plan_execution_contract(research_plan)
    if plan_contract is not None:
        write_plan_execution_contract(contract=plan_contract, output_dir=output_root)
        _require_candidates_match_contract(
            candidates=candidates,
            contract=plan_contract,
            output_root=output_root,
        )
    brief = _generation_brief(
        panel, budget, plan_execution_contract=plan_contract
    )
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
        _register_candidate_authoring_attempt(
            output_root=output_root,
            stage="revise-gen2",
            generation=2,
            candidate_id=revised_id,
            base_interaction_id=interaction_id,
            parent_source_sha256=record.source_sha256,
            now=now,
        )
        if isinstance(plan_contract, ProspectivePlanExecutionContract):
            topology_instruction = _formal_prospective_topology_instruction(
                plan_contract,
                revision=True,
            )
        else:
            topology_instruction = "Keep the same two top-level functions."
        messages = [
            {
                "role": "system",
                "content": (
                    "You are the autonomous scientist improving YOUR OWN "
                    "equation-discovery method after seeing objective measurements of "
                    "its behaviour. Return exactly one JSON object matching the "
                    "supplied schema, with the complete revised program as "
                    "source_lines, one array element per physical line and no newline "
                    "escapes. "
                    + topology_instruction
                    + " Obey the same static_source_contract. You are NOT told any "
                    "baseline score or "
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
        (
            response,
            accepted_interaction,
            review,
            legacy_alignment,
            prospective_alignment,
            alignment_findings,
        ) = _author_source_with_bounded_repairs(
            completion=completion,
            messages=messages,
            config_path=config_path,
            env_path=env_path,
            provider_timeout_seconds=provider_timeout_seconds,
            base_interaction_id=interaction_id,
            first_stage="scientific_contract_repair",
            candidate_id=revised_id,
            output_root=output_root,
            now=now,
            plan_contract=plan_contract,
            failure_label="revision",
        )
        source_text = response.source_text
        source_path = output_root / "candidates" / revised_id / "candidate.py"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        with source_path.open("w", encoding="utf-8", newline="") as handle:
            handle.write(source_text)
        findings = [
            f"{item.code}: {item.message[:160]}" for item in review.findings
        ]
        findings.extend(alignment_findings)
        alignment_passed = (
            (legacy_alignment is None or legacy_alignment.passed)
            and (prospective_alignment is None or prospective_alignment.passed)
            and not alignment_findings
        )
        revised.append(
            OfficialCandidateRecord(
                candidate_id=revised_id,
                generation=2,
                interaction_id=accepted_interaction.interaction_id,
                interaction_hash=accepted_interaction.interaction_hash,
                source_relative_path=source_path.relative_to(output_root).as_posix(),
                source_sha256=review.source_sha256,
                static_review_approved=(
                    review.approved and alignment_passed
                ),
                static_review_findings=tuple(findings),
                implementation_summary=response.implementation_summary,
                approved_plan_hash=(
                    plan_contract.approved_plan_hash if plan_contract is not None else None
                ),
                plan_contract_hash=(
                    plan_contract.contract_hash if plan_contract is not None else None
                ),
                plan_alignment=legacy_alignment,
                prospective_plan_alignment=prospective_alignment,
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
