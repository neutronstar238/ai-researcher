"""Task 268.2: let the system observe and repair a frozen-protocol contradiction.

Why this module exists
----------------------
Task `268.1` (`P-20260802-070`) proved that the frozen Task `266.1` protocol is
currently UNSATISFIABLE. The estimand carries
``all_domain_baseline_cells_must_succeed`` as an immutable ``Literal[True]``, yet
two PDE systems fail every one of their baseline cells under the frozen baseline
policy:

* ``heat_laser`` -- the pinned pysindy ``FiniteDifference`` needs ``d + order``
  samples along the differentiated axis, and the ``z`` axis physically has 3.
  At the frozen ``pde_derivative_order=[2]`` this is arithmetically impossible.
* ``heat_soil_uniform_2d_p1`` -- ``fit`` and ``predict`` both succeed, but the
  frozen thresholds are two to three orders of magnitude above the data's
  ``max|coef|``, so STLSQ zeroes every coefficient and the library cannot
  represent its own all-zero model.

Neither fault is in our shape transport, so the original `268.2` premise ("fix
only the shape-transport defects") has nothing to fix. That makes the repair a
SCIENTIFIC decision about a frozen protocol, and this project forbids a human
making that decision on the system's behalf.

So this module closes the loop instead, mirroring
``route_p2_self_correction`` exactly:

1. ``observe_frozen_protocol_contradiction`` reads the RETAINED baseline evidence
   and derives the contradiction DETERMINISTICALLY. No model involvement, so the
   evidence cannot be embellished.
2. ``diagnose_frozen_protocol_contradiction`` classifies each failing system's
   mechanism from its recorded failure signature, again deterministically.
3. ``propose_frozen_protocol_repair`` asks the configured model to author the
   repair itself, choosing among a closed set of legitimate moves.
4. ``audit_repair_against_evidence`` then checks the authored proposal against the
   deterministic evidence and RECORDS an accept/reject verdict.

The guard that matters
----------------------
There is a trap here. Making ``heat_soil_uniform_2d_p1`` "succeed" by degrading a
library-side complexity failure would produce an ALL-ZERO baseline model, whose
loss is the zero-null. A candidate would then trivially "beat" it, manufacturing a
large fake positive effect. That is exactly the fabricated-effect pattern already
recorded and corrected as `P-20260802-063` and `P-20260802-065`.

So ``audit_repair_against_evidence`` REFUSES
``align_error_handling_with_reference_harness`` for any system whose evidence
carries the all-zero-model signature, no matter how well the proposal argues for
it. A change that makes the baseline weaker is a gate violation, not a repair.

Boundaries
----------
* Observation, diagnosis, and the guard audit are deterministic. Only the repair
  proposal is model-authored, and it is recorded with full provenance.
* A proposal is never an authorization. Execution stays blocked until a human
  records a plan approval, and a repaired protocol needs a NEW preregistration
  lineage because the frozen stop rule forbids mutating an observed protocol.
* Nothing here mutates a retained artifact, a frozen threshold, the frozen
  configuration grid, or the sealed confirmation panel.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
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
from autoresearch.competition.route_p2_self_correction import _is_substantive_prose
from autoresearch.llm.client import run_llm_json_completion
from autoresearch.schemas.provenance import file_hash

# `FailureKind` has no member for "the frozen protocol demands something the
# frozen policy makes impossible", which is a different failure from a weak
# method or an underpowered design and needs a different repair.
FROZEN_PROTOCOL_CONTRADICTION = "frozen_protocol_contradiction"

_PACKAGE_NAME = "frozen-protocol-contradiction-package.json"

# Mechanism classification, keyed on the failure signature recorded in the
# retained cells. Both mappings are the Task `268.1` diagnosis, not a guess.
INSUFFICIENT_SAMPLES = "insufficient_samples_for_frozen_derivative_order"
ALL_ZERO_MODEL = "all_zero_model_not_representable_by_pinned_library"
UNCLASSIFIED = "unclassified_baseline_failure"

_SIGNATURES: tuple[tuple[str, str], ...] = (
    # pysindy FiniteDifference needs `d + order` samples; the z axis has 3.
    ("is out of bounds for axis 0 with size", INSUFFICIENT_SAMPLES),
    # `str_to_sympy` turns its own parse failure on an empty RHS into a `None`.
    ("SympifyError: None", ALL_ZERO_MODEL),
)

# The closed set of moves that are legitimate for a frozen-protocol
# contradiction. The system picks; this module does not pick for it.
REPAIR_ROUTES: tuple[str, ...] = (
    # Our adapter transports shapes wrongly. Task 268.1 proved this is NOT the
    # case here, but the route stays available so the system can reject it itself.
    "repair_adapter_shape_transport",
    # Let a library-side complexity failure degrade instead of discarding the fit,
    # as MDBench's own harness does. DANGEROUS: for an all-zero model this
    # manufactures a zero-null baseline.
    "align_error_handling_with_reference_harness",
    # Admit the frozen protocol cannot be satisfied as written and require a new
    # preregistration lineage carrying a corrected baseline policy.
    "declare_frozen_protocol_unsatisfiable_and_require_new_lineage",
    # Drop the system from the panel. Thins the stratum under P-20260802-065.
    "exclude_system_from_panel",
)

_ALL_ZERO_FORBIDDEN_ROUTE = "align_error_handling_with_reference_harness"

_REPAIR_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "contradiction_statement",
        "causal_hypothesis",
        "per_system_resolutions",
        "required_protocol_change",
        "changes_frozen_numeric_grid",
        "weakens_baseline",
        "fabricated_effect_risk_analysis",
        "falsification_conditions",
        "why_this_is_not_result_shopping",
    ],
    "properties": {
        "contradiction_statement": {"type": "string", "minLength": 20, "maxLength": 4000},
        "causal_hypothesis": {"type": "string", "minLength": 20, "maxLength": 4000},
        "per_system_resolutions": {
            "type": "array",
            "minItems": 1,
            "maxItems": 8,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["system_name", "resolution_kind", "justification"],
                "properties": {
                    "system_name": {"type": "string", "minLength": 1, "maxLength": 200},
                    "resolution_kind": {"type": "string", "enum": list(REPAIR_ROUTES)},
                    "justification": {
                        "type": "string",
                        "minLength": 40,
                        "maxLength": 4000,
                    },
                },
            },
        },
        "required_protocol_change": {"type": "string", "minLength": 20, "maxLength": 4000},
        "changes_frozen_numeric_grid": {"type": "boolean"},
        "weakens_baseline": {"type": "boolean"},
        "fabricated_effect_risk_analysis": {
            "type": "string",
            "minLength": 40,
            "maxLength": 4000,
        },
        "falsification_conditions": {
            "type": "array",
            "minItems": 2,
            "maxItems": 8,
            "items": {"type": "string", "minLength": 25, "maxLength": 600},
        },
        "why_this_is_not_result_shopping": {
            "type": "string",
            "minLength": 20,
            "maxLength": 4000,
        },
    },
}


class FrozenProtocolContradictionError(RuntimeError):
    """Raised when a self-correction boundary cannot be proved."""


class FailingBaselineSystem(StrictFrozenModel):
    """One system that cannot satisfy the frozen protocol, with its mechanism."""

    system_name: str
    data_type: str
    failed_cell_count: int = Field(ge=1)
    total_cell_count: int = Field(ge=1)
    mechanism: str
    # True when the evidence shows the baseline would return an ALL-ZERO model if
    # the cell were forced to complete. Scoring a candidate against a zero-null
    # baseline manufactures a fake positive effect.
    produces_all_zero_model: bool
    representative_failure_reason: str

    @model_validator(mode="after")
    def _validate_system(self) -> FailingBaselineSystem:
        if self.failed_cell_count > self.total_cell_count:
            raise FrozenProtocolContradictionError(
                "failed cell count cannot exceed the total cell count"
            )
        if self.mechanism not in {INSUFFICIENT_SAMPLES, ALL_ZERO_MODEL, UNCLASSIFIED}:
            raise FrozenProtocolContradictionError(
                f"unsupported baseline failure mechanism: {self.mechanism}"
            )
        return self


class FrozenProtocolContradictionObservation(StrictFrozenModel):
    """Deterministic observation of the contradiction, from retained evidence."""

    schema_version: Literal["frozen-protocol-contradiction-observation-v1"] = (
        "frozen-protocol-contradiction-observation-v1"
    )
    baseline_results_path: str
    baseline_results_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_cell_count: int = Field(ge=1)
    succeeded_cell_count: int = Field(ge=0)
    failed_cell_count: int = Field(ge=0)
    frozen_check_requires_all_cells_to_succeed: Literal[True] = True
    frozen_check_is_currently_satisfiable: bool
    failing_systems: tuple[FailingBaselineSystem, ...] = Field(min_length=1)
    observations: tuple[str, ...] = Field(min_length=1)
    observation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_observation(self) -> FrozenProtocolContradictionObservation:
        if self.succeeded_cell_count + self.failed_cell_count != self.observed_cell_count:
            raise FrozenProtocolContradictionError(
                "baseline cell counts do not sum to the observed total"
            )
        # The frozen check demands every cell succeed, so it is satisfiable if and
        # only if nothing failed. This is the contradiction, stated arithmetically.
        if self.frozen_check_is_currently_satisfiable != (self.failed_cell_count == 0):
            raise FrozenProtocolContradictionError(
                "satisfiability flag contradicts the observed failure count"
            )
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"observation_hash"})
        )
        if self.observation_hash != expected:
            raise FrozenProtocolContradictionError("observation hash mismatch")
        return self


class FrozenProtocolDiagnosis(StrictFrozenModel):
    """Deterministic classification of the contradiction. No model involvement."""

    schema_version: Literal["frozen-protocol-diagnosis-v1"] = (
        "frozen-protocol-diagnosis-v1"
    )
    failure_kind: str
    parent_observation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence: tuple[str, ...] = Field(min_length=1)
    # Systems for which forcing completion would yield a zero-null baseline. Any
    # proposal that scores against these is manufacturing an effect.
    systems_where_completion_would_fabricate_an_effect: tuple[str, ...]
    fault_is_in_pinned_baseline_library: bool
    fault_is_in_our_shape_transport: bool
    diagnosis_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_diagnosis(self) -> FrozenProtocolDiagnosis:
        if self.failure_kind != FROZEN_PROTOCOL_CONTRADICTION:
            raise FrozenProtocolContradictionError("unsupported failure kind")
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"diagnosis_hash"})
        )
        if self.diagnosis_hash != expected:
            raise FrozenProtocolContradictionError("diagnosis hash mismatch")
        return self


class SystemResolution(StrictFrozenModel):
    """One system's model-authored resolution."""

    system_name: str
    resolution_kind: str
    justification: str = Field(min_length=40)

    @model_validator(mode="after")
    def _validate_resolution(self) -> SystemResolution:
        if self.resolution_kind not in REPAIR_ROUTES:
            raise FrozenProtocolContradictionError(
                f"unsupported resolution kind: {self.resolution_kind}"
            )
        if not _is_substantive_prose(self.justification):
            raise FrozenProtocolContradictionError(
                f"resolution justification is not substantive prose: "
                f"{self.justification[:80]!r}"
            )
        return self


class FrozenProtocolRepairProposal(StrictFrozenModel):
    """The model-authored repair. A proposal, never an authorization."""

    schema_version: Literal["frozen-protocol-repair-proposal-v1"] = (
        "frozen-protocol-repair-proposal-v1"
    )
    parent_diagnosis_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    contradiction_statement: str = Field(min_length=20)
    causal_hypothesis: str = Field(min_length=20)
    per_system_resolutions: tuple[SystemResolution, ...] = Field(min_length=1)
    required_protocol_change: str = Field(min_length=20)
    changes_frozen_numeric_grid: bool
    weakens_baseline: bool
    fabricated_effect_risk_analysis: str = Field(min_length=40)
    falsification_conditions: tuple[str, ...] = Field(min_length=2, max_length=8)
    why_this_is_not_result_shopping: str = Field(min_length=20)
    authored_by_model: Literal[True] = True
    interaction_id: str
    # Execution requires the human plan gate and a NEW lineage.
    human_approval_recorded: Literal[False] = False
    execution_authorized: Literal[False] = False
    requires_new_preregistration_lineage: Literal[True] = True
    proposal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_proposal(self) -> FrozenProtocolRepairProposal:
        for name, text in (
            ("contradiction_statement", self.contradiction_statement),
            ("causal_hypothesis", self.causal_hypothesis),
            ("required_protocol_change", self.required_protocol_change),
            ("fabricated_effect_risk_analysis", self.fabricated_effect_risk_analysis),
            ("why_this_is_not_result_shopping", self.why_this_is_not_result_shopping),
        ):
            if not _is_substantive_prose(text):
                raise FrozenProtocolContradictionError(
                    f"repair {name} is not substantive prose: {text[:80]!r}"
                )
        for condition in self.falsification_conditions:
            if not _is_substantive_prose(condition):
                raise FrozenProtocolContradictionError(
                    f"falsification condition is not substantive: {condition[:80]!r}"
                )
        if len({item.strip().casefold() for item in self.falsification_conditions}) < 2:
            raise FrozenProtocolContradictionError(
                "falsification conditions must be distinct, or the proposal is not "
                "genuinely falsifiable"
            )
        names = [item.system_name for item in self.per_system_resolutions]
        if len(set(names)) != len(names):
            raise FrozenProtocolContradictionError(
                "each system may carry only one resolution"
            )
        # A proposal that admits it weakens the baseline or edits the frozen grid
        # is self-refuting: Task 268 forbids both outright.
        if self.changes_frozen_numeric_grid:
            raise FrozenProtocolContradictionError(
                "a repair may not change the frozen numeric configuration grid"
            )
        if self.weakens_baseline:
            raise FrozenProtocolContradictionError(
                "a repair that weakens the baseline is a gate violation, not a repair"
            )
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"proposal_hash"})
        )
        if self.proposal_hash != expected:
            raise FrozenProtocolContradictionError("repair proposal hash mismatch")
        return self


class RepairGuardAudit(StrictFrozenModel):
    """Deterministic audit of the authored repair against the retained evidence."""

    schema_version: Literal["frozen-protocol-repair-guard-audit-v1"] = (
        "frozen-protocol-repair-guard-audit-v1"
    )
    parent_proposal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_observation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    guard_accepted: bool
    findings: tuple[str, ...] = Field(min_length=1)
    audit_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_audit(self) -> RepairGuardAudit:
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"audit_hash"})
        )
        if self.audit_hash != expected:
            raise FrozenProtocolContradictionError("guard audit hash mismatch")
        return self


class FrozenProtocolContradictionPackage(StrictFrozenModel):
    """Complete observe -> diagnose -> propose -> audit cycle, pending approval."""

    schema_version: Literal["frozen-protocol-contradiction-package-v1"] = (
        "frozen-protocol-contradiction-package-v1"
    )
    observation: FrozenProtocolContradictionObservation
    diagnosis: FrozenProtocolDiagnosis
    proposal: FrozenProtocolRepairProposal
    guard_audit: RepairGuardAudit
    human_scientific_decision_count: Literal[0] = 0
    execution_authorized: Literal[False] = False
    publication_ready: Literal[False] = False
    package_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str

    @model_validator(mode="after")
    def _validate_package(self) -> FrozenProtocolContradictionPackage:
        if self.diagnosis.parent_observation_hash != self.observation.observation_hash:
            raise FrozenProtocolContradictionError(
                "diagnosis is not bound to its observation"
            )
        if self.proposal.parent_diagnosis_hash != self.diagnosis.diagnosis_hash:
            raise FrozenProtocolContradictionError(
                "proposal is not bound to its diagnosis"
            )
        if self.guard_audit.parent_proposal_hash != self.proposal.proposal_hash:
            raise FrozenProtocolContradictionError(
                "guard audit is not bound to its proposal"
            )
        if (
            self.guard_audit.parent_observation_hash
            != self.observation.observation_hash
        ):
            raise FrozenProtocolContradictionError(
                "guard audit is not bound to its observation"
            )
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"package_hash", "output_path"})
        )
        if self.package_hash != expected:
            raise FrozenProtocolContradictionError("package hash mismatch")
        return self


def _classify_mechanism(failure_reason: str) -> str:
    """Map a recorded failure signature onto the Task 268.1 mechanism."""

    for signature, mechanism in _SIGNATURES:
        if signature in failure_reason:
            return mechanism
    return UNCLASSIFIED


def observe_frozen_protocol_contradiction(
    *,
    baseline_results_path: Path | str,
) -> FrozenProtocolContradictionObservation:
    """Derive the contradiction from RETAINED baseline evidence, with no model input.

    Read-only. The retained artifact is never mutated, only hashed and parsed.
    """

    resolved = Path(baseline_results_path)
    if not resolved.is_file():
        raise FrozenProtocolContradictionError(
            f"missing baseline results: {resolved}"
        )
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    results = payload.get("results")
    if not results:
        raise FrozenProtocolContradictionError("baseline results carry no cells")

    succeeded = [item for item in results if item.get("status") == "succeeded"]
    failed = [item for item in results if item.get("status") != "succeeded"]
    if not failed:
        raise FrozenProtocolContradictionError(
            "no baseline cell failed, so there is no contradiction to repair"
        )

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in results:
        grouped.setdefault(str(item["system_name"]), []).append(item)

    failing_systems: list[dict[str, Any]] = []
    for system_name in sorted({str(item["system_name"]) for item in failed}):
        cells = grouped[system_name]
        system_failed = [item for item in cells if item.get("status") != "succeeded"]
        reasons = sorted(
            {str(item.get("failure_reason") or "") for item in system_failed}
        )
        representative = reasons[0] if reasons else ""
        mechanism = _classify_mechanism(representative)
        failing_systems.append(
            {
                "system_name": system_name,
                "data_type": str(cells[0].get("data_type", "unknown")),
                "failed_cell_count": len(system_failed),
                "total_cell_count": len(cells),
                "mechanism": mechanism,
                "produces_all_zero_model": mechanism == ALL_ZERO_MODEL,
                "representative_failure_reason": representative,
            }
        )

    observations = [
        f"baseline_cells_observed: {len(results)}",
        f"baseline_cells_succeeded: {len(succeeded)}",
        f"baseline_cells_failed: {len(failed)}",
        "frozen_check: all_domain_baseline_cells_must_succeed is an immutable "
        "Literal[True]",
        f"frozen_check_is_currently_satisfiable: {str(not failed).lower()}",
    ]
    for entry in failing_systems:
        observations.append(
            f"failing_system: {entry['system_name']} "
            f"({entry['data_type']}) "
            f"{entry['failed_cell_count']}/{entry['total_cell_count']} cells failed, "
            f"mechanism={entry['mechanism']}, "
            f"forcing_completion_yields_all_zero_model="
            f"{str(entry['produces_all_zero_model']).lower()}"
        )

    payload_out: dict[str, Any] = {
        "schema_version": "frozen-protocol-contradiction-observation-v1",
        "baseline_results_path": resolved.as_posix(),
        "baseline_results_sha256": file_hash(resolved),
        "observed_cell_count": len(results),
        "succeeded_cell_count": len(succeeded),
        "failed_cell_count": len(failed),
        "frozen_check_requires_all_cells_to_succeed": True,
        "frozen_check_is_currently_satisfiable": False,
        "failing_systems": tuple(failing_systems),
        "observations": tuple(observations),
    }
    payload_out["observation_hash"] = canonical_model_hash(payload_out)
    return FrozenProtocolContradictionObservation.model_validate(payload_out)


def diagnose_frozen_protocol_contradiction(
    observation: FrozenProtocolContradictionObservation,
) -> FrozenProtocolDiagnosis:
    """Classify the contradiction deterministically. No model involvement."""

    evidence = list(observation.observations)
    evidence.append(
        "the frozen protocol demands an outcome the frozen baseline policy makes "
        "impossible, so this is a protocol contradiction rather than a candidate "
        "failure or an underpowered design"
    )
    fabricating = tuple(
        item.system_name
        for item in observation.failing_systems
        if item.produces_all_zero_model
    )
    for name in fabricating:
        evidence.append(
            f"forcing {name} to complete would score the candidate against an "
            "all-zero baseline model, which manufactures a fake positive effect "
            "rather than measuring one"
        )
    # Task 268.1 proved transport is faithful for both systems; every classified
    # mechanism lives in the pinned library.
    library_side = all(
        item.mechanism in {INSUFFICIENT_SAMPLES, ALL_ZERO_MODEL}
        for item in observation.failing_systems
    )

    payload: dict[str, Any] = {
        "schema_version": "frozen-protocol-diagnosis-v1",
        "failure_kind": FROZEN_PROTOCOL_CONTRADICTION,
        "parent_observation_hash": observation.observation_hash,
        "evidence": tuple(evidence),
        "systems_where_completion_would_fabricate_an_effect": fabricating,
        "fault_is_in_pinned_baseline_library": library_side,
        "fault_is_in_our_shape_transport": not library_side,
    }
    payload["diagnosis_hash"] = canonical_model_hash(payload)
    return FrozenProtocolDiagnosis.model_validate(payload)


def audit_repair_against_evidence(
    *,
    observation: FrozenProtocolContradictionObservation,
    diagnosis: FrozenProtocolDiagnosis,
    proposal: FrozenProtocolRepairProposal,
) -> RepairGuardAudit:
    """Check the authored repair against the deterministic evidence.

    This is the guard that refuses the fabricated-effect trap. A proposal that
    would force an all-zero baseline to completion is REJECTED here regardless of
    how well it argues, because the resulting effect would be manufactured rather
    than measured.
    """

    findings: list[str] = []
    accepted = True

    observed_names = {item.system_name for item in observation.failing_systems}
    proposed_names = {item.system_name for item in proposal.per_system_resolutions}
    missing = sorted(observed_names - proposed_names)
    extra = sorted(proposed_names - observed_names)
    if missing:
        accepted = False
        findings.append(
            f"rejected: no resolution authored for failing systems {missing}"
        )
    if extra:
        accepted = False
        findings.append(
            f"rejected: resolutions authored for systems that did not fail {extra}"
        )

    fabricating = set(diagnosis.systems_where_completion_would_fabricate_an_effect)
    for resolution in proposal.per_system_resolutions:
        if (
            resolution.system_name in fabricating
            and resolution.resolution_kind == _ALL_ZERO_FORBIDDEN_ROUTE
        ):
            accepted = False
            findings.append(
                f"rejected: {resolution.system_name} would complete with an "
                "all-zero baseline model, so "
                f"{_ALL_ZERO_FORBIDDEN_ROUTE} manufactures a fake positive effect "
                "(the P-20260802-063 and P-20260802-065 pattern) instead of "
                "repairing the baseline"
            )
        else:
            findings.append(
                f"accepted: {resolution.system_name} -> {resolution.resolution_kind}"
            )

    # Task 268.1 proved the transport is faithful, so claiming a transport defect
    # contradicts the retained evidence.
    if diagnosis.fault_is_in_pinned_baseline_library:
        for resolution in proposal.per_system_resolutions:
            if resolution.resolution_kind == "repair_adapter_shape_transport":
                accepted = False
                findings.append(
                    f"rejected: {resolution.system_name} has no shape-transport "
                    "defect in the retained evidence, so that route repairs nothing"
                )

    findings.append(
        f"guard_verdict: {'accepted' if accepted else 'rejected'}"
    )
    payload: dict[str, Any] = {
        "schema_version": "frozen-protocol-repair-guard-audit-v1",
        "parent_proposal_hash": proposal.proposal_hash,
        "parent_observation_hash": observation.observation_hash,
        "guard_accepted": accepted,
        "findings": tuple(findings),
    }
    payload["audit_hash"] = canonical_model_hash(payload)
    return RepairGuardAudit.model_validate(payload)


def propose_frozen_protocol_repair(
    *,
    observation: FrozenProtocolContradictionObservation,
    diagnosis: FrozenProtocolDiagnosis,
    output_dir: Path | str,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    provider_timeout_seconds: int = 300,
    completion: JsonCompletion = run_llm_json_completion,
    clock: Callable[[], datetime] | None = None,
) -> FrozenProtocolContradictionPackage:
    """Ask the SYSTEM to author the repair, audit it, then stop for human approval."""

    now = clock or (lambda: datetime.now(timezone.utc))
    output_root = Path(output_dir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    messages = [
        {
            "role": "system",
            "content": (
                "You are the autonomous scientist repairing a contradiction in your "
                "own frozen research protocol. You are given deterministic "
                "observations of your retained baseline evidence and a deterministic "
                "diagnosis. Author the repair yourself. Return exactly one JSON "
                "object matching the supplied schema.\n\n"
                "The contradiction: your frozen estimand requires EVERY domain "
                "baseline cell to succeed, but some cells cannot succeed under your "
                "frozen baseline policy. You must resolve this without changing any "
                "frozen numeric value.\n\n"
                "HARD RULES. You may NOT change the frozen numeric configuration "
                "grid, any threshold, any gate, or any estimand. You may NOT make "
                "the baseline weaker: the baseline is the thing your candidate is "
                "measured against, so weakening it would inflate your own result. "
                "Choose one resolution_kind per failing system from the supplied "
                "enum, and justify each choice against the evidence you were given. "
                "Set changes_frozen_numeric_grid and weakens_baseline truthfully; a "
                "false declaration will be caught by a deterministic audit against "
                "the evidence.\n\n"
                "In fabricated_effect_risk_analysis, reason explicitly about what "
                "happens to a measured effect if a baseline cell is forced to "
                "complete while the baseline model retains no terms at all. "
                "Every prose field must be complete sentences, never a bare number "
                "or a fragment. Each falsification_condition must name an observable "
                "outcome that would refute your repair, and they must differ."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "deterministic_observations": list(observation.observations),
                    "failure_kind": diagnosis.failure_kind,
                    "diagnostic_evidence": list(diagnosis.evidence),
                    "fault_is_in_pinned_baseline_library": (
                        diagnosis.fault_is_in_pinned_baseline_library
                    ),
                    "fault_is_in_our_shape_transport": (
                        diagnosis.fault_is_in_our_shape_transport
                    ),
                    "systems_where_forcing_completion_would_fabricate_an_effect": list(
                        diagnosis.systems_where_completion_would_fabricate_an_effect
                    ),
                    "failing_systems": [
                        item.model_dump(mode="json")
                        for item in observation.failing_systems
                    ],
                    "available_resolution_kinds": list(REPAIR_ROUTES),
                    "hard_constraints": [
                        "the frozen numeric configuration grid must not change",
                        "no threshold, gate, or estimand may be weakened",
                        "the baseline must get stronger or stay equal; a weaker "
                        "baseline is a gate violation rather than a repair",
                        "a retained artifact may never be mutated",
                        "a repaired protocol requires a new preregistration lineage "
                        "and human plan approval before it may execute",
                    ],
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        },
    ]
    interaction_id = f"frozen-protocol-repair-{diagnosis.diagnosis_hash[:16]}"
    result, _ = _call_and_record(
        completion=completion,
        messages=messages,
        config_path=config_path,
        env_path=env_path,
        timeout_seconds=provider_timeout_seconds,
        max_tokens=8_000,
        response_schema=_REPAIR_RESPONSE_SCHEMA,
        response_schema_name="frozen_protocol_repair",
        interaction_id=interaction_id,
        stage="mechanism_intervention",
        candidate_id=None,
        output_root=output_root,
        now=now,
    )
    parsed = result.parsed_json
    proposal_payload: dict[str, Any] = {
        "schema_version": "frozen-protocol-repair-proposal-v1",
        "parent_diagnosis_hash": diagnosis.diagnosis_hash,
        "contradiction_statement": parsed["contradiction_statement"],
        "causal_hypothesis": parsed["causal_hypothesis"],
        "per_system_resolutions": tuple(
            {
                "system_name": item["system_name"],
                "resolution_kind": item["resolution_kind"],
                "justification": item["justification"],
            }
            for item in parsed["per_system_resolutions"]
        ),
        "required_protocol_change": parsed["required_protocol_change"],
        "changes_frozen_numeric_grid": bool(parsed["changes_frozen_numeric_grid"]),
        "weakens_baseline": bool(parsed["weakens_baseline"]),
        "fabricated_effect_risk_analysis": parsed["fabricated_effect_risk_analysis"],
        "falsification_conditions": tuple(parsed["falsification_conditions"]),
        "why_this_is_not_result_shopping": parsed["why_this_is_not_result_shopping"],
        "authored_by_model": True,
        "interaction_id": interaction_id,
        "human_approval_recorded": False,
        "execution_authorized": False,
        "requires_new_preregistration_lineage": True,
    }
    proposal_payload["proposal_hash"] = canonical_model_hash(proposal_payload)
    proposal = FrozenProtocolRepairProposal.model_validate(proposal_payload)

    guard_audit = audit_repair_against_evidence(
        observation=observation,
        diagnosis=diagnosis,
        proposal=proposal,
    )

    package_payload: dict[str, Any] = {
        "schema_version": "frozen-protocol-contradiction-package-v1",
        "observation": observation.model_dump(mode="json"),
        "diagnosis": diagnosis.model_dump(mode="json"),
        "proposal": proposal.model_dump(mode="json"),
        "guard_audit": guard_audit.model_dump(mode="json"),
        "human_scientific_decision_count": 0,
        "execution_authorized": False,
        "publication_ready": False,
    }
    package_payload["package_hash"] = canonical_model_hash(package_payload)
    package_payload["output_path"] = (output_root / _PACKAGE_NAME).as_posix()
    package = FrozenProtocolContradictionPackage.model_validate(package_payload)
    write_json_model(output_root / _PACKAGE_NAME, package)
    return package


def run_frozen_protocol_self_correction(
    *,
    baseline_results_path: Path | str,
    output_dir: Path | str,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    provider_timeout_seconds: int = 300,
    completion: JsonCompletion = run_llm_json_completion,
    clock: Callable[[], datetime] | None = None,
) -> FrozenProtocolContradictionPackage:
    """Run the full observe -> diagnose -> propose -> audit cycle."""

    observation = observe_frozen_protocol_contradiction(
        baseline_results_path=baseline_results_path
    )
    diagnosis = diagnose_frozen_protocol_contradiction(observation)
    return propose_frozen_protocol_repair(
        observation=observation,
        diagnosis=diagnosis,
        output_dir=output_dir,
        config_path=config_path,
        env_path=env_path,
        provider_timeout_seconds=provider_timeout_seconds,
        completion=completion,
        clock=clock,
    )


__all__: Sequence[str] = (
    "ALL_ZERO_MODEL",
    "FROZEN_PROTOCOL_CONTRADICTION",
    "INSUFFICIENT_SAMPLES",
    "REPAIR_ROUTES",
    "FailingBaselineSystem",
    "FrozenProtocolContradictionError",
    "FrozenProtocolContradictionObservation",
    "FrozenProtocolContradictionPackage",
    "FrozenProtocolDiagnosis",
    "FrozenProtocolRepairProposal",
    "RepairGuardAudit",
    "SystemResolution",
    "audit_repair_against_evidence",
    "diagnose_frozen_protocol_contradiction",
    "observe_frozen_protocol_contradiction",
    "propose_frozen_protocol_repair",
    "run_frozen_protocol_self_correction",
)
