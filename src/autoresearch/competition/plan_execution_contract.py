"""Compile an approved research plan into a source-verifiable execution contract.

The plan-confirmation gate historically bound only a hash to an execution record.
That proved which text had been approved, but not that the generated implementation
performed the method described by that text.  A plan could therefore prescribe one
method family while the candidate source implemented another.

This module closes that gap without asking a language model to grade itself:

* the scientific fields of the approved plan are copied verbatim into a hash-bound
  contract;
* the model-authored ``code_agent_brief`` supplies two to eight stable method tokens;
* a deterministic AST audit accepts a token only when it appears in a callable that
  is actually reached from ``fit_equations`` or ``predict_derivative``. Comments,
  docstrings, variable names, implementation summaries, and dead helper functions
  cannot satisfy the gate.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from pydantic import Field, ValidationError, model_validator

from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.competition.system_plan_component_atoms import SystemPlanComponentAtom
from autoresearch.competition.system_plan_ideation import ResearchDirectionCandidate
from autoresearch.competition.system_plan_prospective_atoms import (
    ComponentExperimentBindingV2,
    FrozenDimension,
    ProspectiveComponentAtom,
    ProspectiveInterventionIdentity,
    ProspectiveResourceRequest,
    PublicHook,
)
from autoresearch.research.plan_confirmation import compute_plan_hash
from autoresearch.schemas import ResearchPlan

if TYPE_CHECKING:
    from autoresearch.competition.system_authored_plan import (
        SystemAuthoredPlanArtifact,
    )

_CONTRACT_NAME = "plan-execution-contract.json"
_SCIENTIFIC_FIELDS: tuple[str, ...] = (
    "title",
    "problem_statement",
    "rationale",
    "technical_details",
    "datasets",
    "methods",
    "experiments",
    "baselines",
    "metrics",
    "expected_results",
    "code_agent_brief",
)
_EXPLICIT_TOKEN_PATTERN = re.compile(
    r"required_method_tokens\s*=\s*\[(?P<body>[^\]]+)\]", re.IGNORECASE
)
_CONFIG_VALUE_PATTERN = re.compile(
    r"(?:--config(?:uration)?\s+|\bconfig(?:uration)?\s*[:=]\s*)"
    r"(?P<value>[A-Za-z][A-Za-z0-9_.-]+)",
    re.IGNORECASE,
)
_CONFIG_FILE_PATTERN = re.compile(
    r"\b(?P<value>[A-Za-z][A-Za-z0-9_-]+)\.(?:yaml|yml|toml|json)\b",
    re.IGNORECASE,
)
_TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_GENERIC_TOKENS = frozenset(
    {
        "config",
        "configuration",
        "candidate",
        "method",
        "model",
        "official",
        "panel",
        "python",
        "runner",
        "script",
        "spec",
        "test",
        "tests",
        "yaml",
        "yml",
        "toml",
        "json",
    }
)
_EXECUTION_ROOTS = ("fit_equations", "predict_derivative")
_PROSPECTIVE_DECLARATION_NAME = "PROSPECTIVE_EXECUTION_DECLARATION"
_FORMAL_INTERVENTION_PATTERN = re.compile(
    r"required_intervention_identity\s*=", re.IGNORECASE
)


class PlanExecutionContractError(ValueError):
    """Raised when plan-to-code alignment cannot be proved."""


class PlanExecutionContract(StrictFrozenModel):
    """Exact approved science plus the code-level method identity it requires."""

    schema_version: Literal["plan-execution-contract-v1"] = "plan-execution-contract-v1"
    approved_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    scientific_plan: dict[str, Any]
    required_method_tokens: tuple[str, ...] = Field(min_length=2, max_length=8)
    contract_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate(self) -> PlanExecutionContract:
        if set(self.scientific_plan) != set(_SCIENTIFIC_FIELDS):
            raise PlanExecutionContractError(
                "plan execution contract does not carry the exact required scientific fields"
            )
        if len(self.required_method_tokens) != len(set(self.required_method_tokens)):
            raise PlanExecutionContractError("required method tokens must be unique")
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"contract_hash"})
        )
        if self.contract_hash != expected:
            raise PlanExecutionContractError("plan execution contract hash mismatch")
        return self


class CandidatePlanAlignmentAudit(StrictFrozenModel):
    """Deterministic proof that one exact source implements the approved method."""

    schema_version: Literal["candidate-plan-alignment-audit-v1"] = (
        "candidate-plan-alignment-audit-v1"
    )
    candidate_id: str = Field(min_length=1)
    approved_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_contract_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    required_method_tokens: tuple[str, ...] = Field(min_length=2, max_length=8)
    reachable_identifier_evidence: dict[str, tuple[str, ...]]
    missing_method_tokens: tuple[str, ...]
    parse_error: str | None = None
    passed: bool
    audit_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate(self) -> CandidatePlanAlignmentAudit:
        expected_pass = not self.missing_method_tokens and self.parse_error is None
        if self.passed != expected_pass:
            raise PlanExecutionContractError(
                "candidate plan-alignment verdict contradicts its evidence"
            )
        if set(self.reachable_identifier_evidence) != set(self.required_method_tokens):
            raise PlanExecutionContractError(
                "candidate plan-alignment evidence does not cover every required token"
            )
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"audit_hash"})
        )
        if self.audit_hash != expected:
            raise PlanExecutionContractError("candidate plan-alignment audit hash mismatch")
        return self


class PairedControlTreatmentContract(StrictFrozenModel):
    """One mechanically checkable single-factor control/treatment pair.

    ``control_configuration`` and ``treatment_configuration`` intentionally carry
    the frozen dimensions as identical values.  Their only permitted byte-level
    difference is the key named by ``intervention_key``.  This is a preregistered
    configuration invariant, not a claim that a future runner actually respected it.
    """

    schema_version: Literal["paired-control-treatment-contract-v1"] = (
        "paired-control-treatment-contract-v1"
    )
    prospective_atom_id: str = Field(pattern=r"^P00[1-3]$")
    prospective_atom_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_observed_atom_id: str = Field(pattern=r"^A[0-9]{3}$")
    baseline_observed_atom_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    change_mode: Literal["替换", "消融", "参数化"]
    intervention_key: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{1,63}$")
    frozen_dimensions: tuple[FrozenDimension, ...] = Field(min_length=1)
    control_configuration: dict[str, str] = Field(min_length=2)
    treatment_configuration: dict[str, str] = Field(min_length=2)
    changed_keys: tuple[str, ...] = Field(min_length=1, max_length=1)
    pair_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_pair(self) -> PairedControlTreatmentContract:
        if set(self.control_configuration) != set(self.treatment_configuration):
            raise PlanExecutionContractError(
                "paired control/treatment configurations must have identical keys"
            )
        actual_changed = tuple(
            sorted(
                key
                for key in self.control_configuration
                if self.control_configuration[key] != self.treatment_configuration[key]
            )
        )
        if self.changed_keys != actual_changed:
            raise PlanExecutionContractError(
                "paired control/treatment changed_keys contradict the mechanical diff"
            )
        if self.changed_keys != (self.intervention_key,):
            raise PlanExecutionContractError(
                "paired control/treatment may change only its declared intervention key"
            )
        if self.intervention_key not in self.control_configuration:
            raise PlanExecutionContractError(
                "paired control/treatment omits its declared intervention key"
            )
        expected_frozen = {
            _frozen_dimension_key(item): "逐字冻结" for item in self.frozen_dimensions
        }
        for key, value in expected_frozen.items():
            if (
                self.control_configuration.get(key) != value
                or self.treatment_configuration.get(key) != value
            ):
                raise PlanExecutionContractError(
                    "paired control/treatment does not carry every frozen dimension"
                )
        expected_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"pair_hash"})
        )
        if self.pair_hash != expected_hash:
            raise PlanExecutionContractError("paired control/treatment hash mismatch")
        return self


class ProspectiveExecutionArmBinding(StrictFrozenModel):
    """One formal arm derived from, but not executed by, a prospective contract."""

    schema_version: Literal["prospective-execution-arm-binding-v1"] = (
        "prospective-execution-arm-binding-v1"
    )
    arm_role: Literal["control", "treatment"]
    plan_execution_contract_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_prospective_atom_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_intervention_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    pair_contract_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    intervention_key: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{1,63}$")
    configuration: dict[str, str] = Field(min_length=2)
    configuration_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    arm_binding_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_arm(self) -> ProspectiveExecutionArmBinding:
        if self.intervention_key not in self.configuration:
            raise PlanExecutionContractError(
                "prospective execution arm omits its declared intervention key"
            )
        if self.configuration_hash != canonical_model_hash(self.configuration):
            raise PlanExecutionContractError(
                "prospective execution arm configuration hash mismatch"
            )
        expected_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"arm_binding_hash"})
        )
        if self.arm_binding_hash != expected_hash:
            raise PlanExecutionContractError(
                "prospective execution arm binding hash mismatch"
            )
        return self


class ProspectivePairedExecutionBinding(StrictFrozenModel):
    """Formal-only two-arm projection with an explicit doubled resource envelope.

    This object is a deterministic future-execution input.  It is neither a cell
    specification nor evidence that either arm ran.
    """

    schema_version: Literal["prospective-paired-execution-binding-v1"] = (
        "prospective-paired-execution-binding-v1"
    )
    plan_execution_contract_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_prospective_atom_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_intervention_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    pair_contract_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    intervention_key: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{1,63}$")
    changed_keys: tuple[str, ...] = Field(min_length=1, max_length=1)
    paired_control_treatment: PairedControlTreatmentContract
    control_arm: ProspectiveExecutionArmBinding
    treatment_arm: ProspectiveExecutionArmBinding
    arm_count: Literal[2] = 2
    per_arm_resource_request: ProspectiveResourceRequest
    total_seconds_budget: int = Field(ge=2)
    total_memory_mb_allocation: int = Field(ge=256)
    total_cpu_core_allocation: int = Field(ge=2)
    total_public_fit_call_budget: int = Field(ge=2)
    execution_authorized: Literal[False] = False
    is_scientific_evidence: Literal[False] = False
    binding_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_binding(self) -> ProspectivePairedExecutionBinding:
        control = self.control_arm
        treatment = self.treatment_arm
        pair = self.paired_control_treatment
        if control.arm_role != "control" or treatment.arm_role != "treatment":
            raise PlanExecutionContractError(
                "prospective paired execution must contain exact control/treatment roles"
            )
        common = (
            self.plan_execution_contract_hash,
            self.selected_prospective_atom_hash,
            self.selected_intervention_hash,
            self.pair_contract_hash,
            self.intervention_key,
        )
        for arm in (control, treatment):
            arm_common = (
                arm.plan_execution_contract_hash,
                arm.selected_prospective_atom_hash,
                arm.selected_intervention_hash,
                arm.pair_contract_hash,
                arm.intervention_key,
            )
            if arm_common != common:
                raise PlanExecutionContractError(
                    "prospective arm identity differs from its paired execution binding"
                )
        if set(control.configuration) != set(treatment.configuration):
            raise PlanExecutionContractError(
                "prospective arm configurations must have identical keys"
            )
        if (
            self.selected_prospective_atom_hash != self.selected_intervention_hash
            or self.pair_contract_hash != pair.pair_hash
            or self.intervention_key != pair.intervention_key
            or self.changed_keys != pair.changed_keys
            or control.configuration != pair.control_configuration
            or treatment.configuration != pair.treatment_configuration
        ):
            raise PlanExecutionContractError(
                "prospective arms drifted from the exact paired control/treatment contract"
            )
        actual_changed = tuple(
            sorted(
                key
                for key in control.configuration
                if control.configuration[key] != treatment.configuration[key]
            )
        )
        if (
            self.changed_keys != actual_changed
            or self.changed_keys != (self.intervention_key,)
        ):
            raise PlanExecutionContractError(
                "prospective arms may change only the declared intervention key"
            )
        request = self.per_arm_resource_request
        expected_totals = (
            2 * request.seconds_per_cell,
            2 * request.memory_mb_per_cell,
            2 * request.cpu_cores_per_cell,
            2 * request.public_fit_calls_per_cell,
        )
        observed_totals = (
            self.total_seconds_budget,
            self.total_memory_mb_allocation,
            self.total_cpu_core_allocation,
            self.total_public_fit_call_budget,
        )
        if observed_totals != expected_totals:
            raise PlanExecutionContractError(
                "prospective paired execution does not explicitly double every per-arm budget"
            )
        expected_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"binding_hash"})
        )
        if self.binding_hash != expected_hash:
            raise PlanExecutionContractError(
                "prospective paired execution binding hash mismatch"
            )
        return self


class ProspectivePlanExecutionContract(StrictFrozenModel):
    """Formal v2 bridge from one system-authored plan to one future intervention.

    Unlike the historical v1 contract, this object does not infer scientific
    identity from method-name tokens.  It carries the complete selected atom, its
    observed baseline, the upstream binding bytes, and the paired configuration that
    future candidate source must declare exactly.
    """

    schema_version: Literal["plan-execution-contract-v2"] = (
        "plan-execution-contract-v2"
    )
    approved_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_plan: dict[str, Any]
    system_authored_plan_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    scientific_lineage_binding: dict[str, Any]
    scientific_lineage_binding_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    component_experiment_binding_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_prospective_atom: ProspectiveComponentAtom
    selected_prospective_atom_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_intervention_identity: ProspectiveInterventionIdentity
    baseline_observed_atom: SystemPlanComponentAtom
    baseline_observed_atom_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    implementation_anchor: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{1,63}$")
    public_hooks: tuple[PublicHook, ...] = Field(min_length=1, max_length=2)
    forbidden_implementation_anchors: tuple[str, ...]
    target_keys: tuple[str, ...] = Field(min_length=1)
    target_systems: tuple[str, ...] = Field(min_length=1)
    supporting_fact_ids: tuple[str, ...] = Field(min_length=1)
    resource_request: ProspectiveResourceRequest
    selected_plan_reference_indices: tuple[int, ...] = Field(min_length=1)
    paired_control_treatment: PairedControlTreatmentContract
    contract_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_contract(self) -> ProspectivePlanExecutionContract:
        try:
            plan = ResearchPlan.model_validate(self.approved_plan)
        except ValidationError as exc:
            raise PlanExecutionContractError(
                f"formal execution contract carries a malformed approved plan: {exc}"
            ) from exc
        if self.approved_plan_hash != compute_plan_hash(plan):
            raise PlanExecutionContractError(
                "formal execution contract approved plan hash mismatch"
            )
        expected_lineage_hash = canonical_model_hash(
            {
                key: value
                for key, value in self.scientific_lineage_binding.items()
                if key != "binding_hash"
            }
        )
        if (
            self.scientific_lineage_binding.get("binding_hash")
            != self.scientific_lineage_binding_hash
            or self.scientific_lineage_binding_hash != expected_lineage_hash
        ):
            raise PlanExecutionContractError(
                "formal execution contract scientific lineage binding hash mismatch"
            )
        try:
            component_binding = ComponentExperimentBindingV2.model_validate(
                self.scientific_lineage_binding.get("component_experiment_binding")
            )
            direction = ResearchDirectionCandidate.model_validate(
                self.scientific_lineage_binding.get("selected_direction")
            )
            binding_identity = ProspectiveInterventionIdentity.model_validate(
                self.scientific_lineage_binding.get("selected_intervention_identity")
            )
        except (ValidationError, ValueError) as exc:
            raise PlanExecutionContractError(
                "formal execution contract lacks a valid component/direction binding"
            ) from exc
        if component_binding.binding_hash != self.component_experiment_binding_hash:
            raise PlanExecutionContractError(
                "formal execution contract component experiment binding hash mismatch"
            )
        if (
            self.scientific_lineage_binding.get("component_experiment_binding_hash")
            != component_binding.binding_hash
            or self.scientific_lineage_binding.get("selected_direction_hash")
            != canonical_model_hash(direction)
        ):
            raise PlanExecutionContractError(
                "formal execution contract retained direction/component hash mismatch"
            )
        atom = self.selected_prospective_atom
        atom_hash = canonical_model_hash(atom)
        if self.selected_prospective_atom_hash != atom_hash:
            raise PlanExecutionContractError(
                "formal execution contract selected prospective atom hash mismatch"
            )
        expected_identities = {
            item.atom_id: item
            for item in component_binding.prospective_components.intervention_identities
        }
        expected_atoms = {
            item.atom_id: item for item in component_binding.prospective_components.atoms
        }
        if expected_atoms.get(atom.atom_id) != atom:
            raise PlanExecutionContractError(
                "formal execution contract selected atom is not in the bound portfolio"
            )
        if expected_identities.get(atom.atom_id) != self.selected_intervention_identity:
            raise PlanExecutionContractError(
                "formal execution contract intervention identity is not the selected atom"
            )
        identity = self.selected_intervention_identity
        if (
            binding_identity != identity
            or direction.prospective_atom_id != atom.atom_id
            or direction.prospective_atom_hash != atom_hash
            or direction.prospective_intervention_hash != identity.intervention_hash
            or direction.prospective_origin_kind != identity.origin_kind
        ):
            raise PlanExecutionContractError(
                "formal execution contract selected atom escaped its retained direction"
            )
        if (
            identity.intervention_hash != atom_hash
            or identity.baseline_observed_atom_id != atom.baseline_observed_atom_id
            or identity.baseline_observed_atom_hash != atom.baseline_observed_atom_hash
            or identity.implementation_anchor != atom.implementation_anchor
            or identity.public_hooks != atom.public_hooks
        ):
            raise PlanExecutionContractError(
                "formal execution contract atom/intervention identity projection mismatch"
            )
        if (
            self.implementation_anchor != identity.implementation_anchor
            or self.public_hooks != identity.public_hooks
        ):
            raise PlanExecutionContractError(
                "formal execution contract implementation anchor or public hooks drifted"
            )
        if self.implementation_anchor in self.public_hooks:
            raise PlanExecutionContractError(
                "formal implementation anchor must be a helper distinct from every "
                "public hook"
            )
        observed = {
            item.atom_id: item for item in component_binding.observed_components.atoms
        }
        if observed.get(atom.baseline_observed_atom_id) != self.baseline_observed_atom:
            raise PlanExecutionContractError(
                "formal execution contract baseline is not the selected observed atom"
            )
        if (
            self.baseline_observed_atom_hash
            != canonical_model_hash(self.baseline_observed_atom)
            or self.baseline_observed_atom_hash != atom.baseline_observed_atom_hash
        ):
            raise PlanExecutionContractError(
                "formal execution contract baseline observed atom hash mismatch"
            )
        aliases = {
            item.target_key: item
            for item in component_binding.prospective_components.target_aliases
        }
        try:
            expected_targets = tuple(aliases[key].system_name for key in atom.target_keys)
        except KeyError as exc:
            raise PlanExecutionContractError(
                f"formal execution contract selected atom uses an unknown target key: {exc}"
            ) from exc
        if self.target_keys != atom.target_keys or self.target_systems != expected_targets:
            raise PlanExecutionContractError(
                "formal execution contract target aliases or systems drifted"
            )
        if direction.target_systems != self.target_systems:
            raise PlanExecutionContractError(
                "formal execution contract targets differ from the retained direction"
            )
        if self.supporting_fact_ids != atom.supporting_fact_ids:
            raise PlanExecutionContractError(
                "formal execution contract supporting facts drifted"
            )
        if direction.evidence_fact_ids != self.supporting_fact_ids:
            raise PlanExecutionContractError(
                "formal execution contract facts differ from the retained direction"
            )
        if self.resource_request != atom.resource_request:
            raise PlanExecutionContractError(
                "formal execution contract resource request drifted"
            )
        expected_plan_references = tuple(
            item.reference_index for item in atom.literature_supports
        )
        if self.selected_plan_reference_indices != expected_plan_references:
            raise PlanExecutionContractError(
                "formal execution contract selected-plan citation domain drifted"
            )
        expected_forbidden = tuple(
            sorted(
                item.implementation_anchor
                for item in component_binding.prospective_components.intervention_identities
                if item.atom_id != atom.atom_id
            )
        )
        if self.forbidden_implementation_anchors != expected_forbidden:
            raise PlanExecutionContractError(
                "formal execution contract omitted a non-selected implementation anchor"
            )
        pair = self.paired_control_treatment
        if (
            pair.prospective_atom_id != atom.atom_id
            or pair.prospective_atom_hash != atom_hash
            or pair.baseline_observed_atom_id != atom.baseline_observed_atom_id
            or pair.baseline_observed_atom_hash != atom.baseline_observed_atom_hash
            or pair.change_mode != atom.change_mode
            or pair.intervention_key != atom.implementation_anchor
            or pair.frozen_dimensions != atom.frozen_dimensions
            or pair.control_configuration[atom.implementation_anchor]
            != atom.control_level_zh
            or pair.treatment_configuration[atom.implementation_anchor]
            != atom.intervention_level_zh
        ):
            raise PlanExecutionContractError(
                "formal execution contract paired control/treatment drifted from the atom"
            )
        expected_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"contract_hash"})
        )
        if self.contract_hash != expected_hash:
            raise PlanExecutionContractError("formal plan execution contract hash mismatch")
        return self


class ProspectiveCandidateExecutionDeclaration(StrictFrozenModel):
    """Exact literal that a prospective candidate must carry in its source."""

    schema_version: Literal["prospective-candidate-execution-declaration-v2"] = (
        "prospective-candidate-execution-declaration-v2"
    )
    plan_execution_contract_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    scientific_lineage_binding_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    component_experiment_binding_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_prospective_atom_id: str = Field(pattern=r"^P00[1-3]$")
    selected_prospective_atom_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_intervention_identity: ProspectiveInterventionIdentity
    baseline_observed_atom_id: str = Field(pattern=r"^A[0-9]{3}$")
    baseline_observed_atom_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    implementation_anchor: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{1,63}$")
    public_hooks: tuple[PublicHook, ...] = Field(min_length=1, max_length=2)
    target_keys: tuple[str, ...] = Field(min_length=1)
    target_systems: tuple[str, ...] = Field(min_length=1)
    supporting_fact_ids: tuple[str, ...] = Field(min_length=1)
    resource_request: ProspectiveResourceRequest
    paired_control_treatment: PairedControlTreatmentContract
    paired_execution_binding: ProspectivePairedExecutionBinding
    declaration_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_declaration(self) -> ProspectiveCandidateExecutionDeclaration:
        expected_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"declaration_hash"})
        )
        if self.declaration_hash != expected_hash:
            raise PlanExecutionContractError(
                "prospective candidate execution declaration hash mismatch"
            )
        return self


class ProspectiveCandidatePlanAlignmentAudit(StrictFrozenModel):
    """Restricted-dispatch AST evidence for one formal prospective candidate."""

    schema_version: Literal["candidate-plan-alignment-audit-v3"] = (
        "candidate-plan-alignment-audit-v3"
    )
    candidate_id: str = Field(min_length=1)
    approved_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_contract_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_declaration_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_declaration: ProspectiveCandidateExecutionDeclaration | None = None
    declaration_exact: bool
    selected_intervention_identity: ProspectiveInterventionIdentity
    implementation_anchor: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{1,63}$")
    public_hooks: tuple[PublicHook, ...] = Field(min_length=1, max_length=2)
    hook_anchor_reachability: dict[str, bool]
    hook_anchor_dominance: dict[str, bool]
    anchor_reads_execution_declaration: bool
    declaration_read_only: bool
    runtime_configuration_consumed: bool
    arm_selector_dominates_scientific_returns: bool
    control_helper: str | None = None
    treatment_helper: str | None = None
    distinct_arm_helpers: bool
    reachable_forbidden_implementation_anchors: tuple[str, ...]
    mechanical_pair_diff_only_declared_intervention: bool
    parse_error: str | None = None
    findings: tuple[str, ...]
    passed: bool
    audit_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_audit(self) -> ProspectiveCandidatePlanAlignmentAudit:
        if (
            set(self.hook_anchor_reachability) != set(self.public_hooks)
            or set(self.hook_anchor_dominance) != set(self.public_hooks)
        ):
            raise PlanExecutionContractError(
                "prospective candidate audit does not cover every public hook"
            )
        exact_from_hash = bool(
            self.source_declaration is not None
            and self.source_declaration.declaration_hash
            == self.expected_declaration_hash
        )
        if self.declaration_exact != exact_from_hash:
            raise PlanExecutionContractError(
                "prospective candidate declaration verdict contradicts its hash"
            )
        structural_pass = (
            self.declaration_exact
            and all(self.hook_anchor_reachability.values())
            and all(self.hook_anchor_dominance.values())
            and self.anchor_reads_execution_declaration
            and self.declaration_read_only
            and self.runtime_configuration_consumed
            and self.arm_selector_dominates_scientific_returns
            and self.distinct_arm_helpers
            and not self.reachable_forbidden_implementation_anchors
            and self.mechanical_pair_diff_only_declared_intervention
        )
        expected_pass = self.parse_error is None and not self.findings and structural_pass
        if self.passed != expected_pass:
            raise PlanExecutionContractError(
                "prospective candidate alignment verdict contradicts its findings"
            )
        if not structural_pass and not self.findings and self.parse_error is None:
            raise PlanExecutionContractError(
                "prospective candidate structural failure lacks an audit finding"
            )
        expected_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"audit_hash"})
        )
        if self.audit_hash != expected_hash:
            raise PlanExecutionContractError(
                "prospective candidate plan-alignment audit hash mismatch"
            )
        return self


def extract_required_method_tokens(code_agent_brief: str) -> tuple[str, ...]:
    """Read stable implementation tokens authored as part of the plan.

    New plans must use single-term identifiers such as
    ``required_method_tokens=[spectral, stlsq]``.  The config-name
    fallback keeps already-retained plans auditable: a brief that names
    ``integral_bayesian_constrained_lars.yaml`` unambiguously commits to those method
    tokens even though it predates the explicit syntax.
    """

    explicit = _EXPLICIT_TOKEN_PATTERN.search(code_agent_brief)
    raw_values: list[str] = []
    if explicit is not None:
        raw_values.extend(_TOKEN_PATTERN.findall(explicit.group("body")))
    else:
        config_values = [
            match.group("value") for match in _CONFIG_VALUE_PATTERN.finditer(code_agent_brief)
        ]
        config_values.extend(
            match.group("value")
            for match in _CONFIG_FILE_PATTERN.finditer(code_agent_brief)
        )
        for value in config_values:
            stem = value.rsplit(".", 1)[0]
            raw_values.extend(_TOKEN_PATTERN.findall(stem.replace("-", "_")))

    tokens: list[str] = []
    for value in raw_values:
        token = value.casefold()
        if len(token) < 2 or token in _GENERIC_TOKENS or token in tokens:
            continue
        tokens.append(token)
    if not 2 <= len(tokens) <= 8:
        raise PlanExecutionContractError(
            "code_agent_brief must author 2-8 distinctive method identifiers using "
            "single-term values such as required_method_tokens=[spectral, stlsq]; "
            "underscored multiword names split into too many unverifiable tokens, and "
            "generic interface names do not prove which scientific method the code "
            "must implement"
        )
    return tuple(tokens)


def compile_plan_execution_contract(
    plan: ResearchPlan | Mapping[str, Any],
) -> PlanExecutionContract:
    """Compile a historical/non-formal plan into the v1 token contract.

    A plan that carries ``required_intervention_identity`` belongs to the formal
    prospective lineage and is deliberately refused here.  Its caller must retain the
    complete :class:`SystemAuthoredPlanArtifact` and use
    :func:`compile_system_authored_plan_execution_contract`; accepting only its
    detached ``ResearchPlan`` would silently discard the upstream atom identity.
    """

    schema_version = (
        plan.get("schema_version")
        if isinstance(plan, Mapping)
        else getattr(plan, "schema_version", None)
    )
    if schema_version == "system-authored-research-plan-v2":
        raise PlanExecutionContractError(
            "formal prospective plan artifacts require the v2 execution-contract compiler"
        )

    validated = plan if isinstance(plan, ResearchPlan) else ResearchPlan.model_validate(plan)
    if _FORMAL_INTERVENTION_PATTERN.search(validated.code_agent_brief):
        raise PlanExecutionContractError(
            "formal prospective plans cannot downgrade to the token-only v1 execution "
            "contract; compile their complete SystemAuthoredPlanArtifact v2"
        )
    scientific_plan = {
        field: validated.model_dump(mode="json")[field] for field in _SCIENTIFIC_FIELDS
    }
    payload: dict[str, Any] = {
        "schema_version": "plan-execution-contract-v1",
        "approved_plan_hash": compute_plan_hash(validated),
        "scientific_plan": scientific_plan,
        "required_method_tokens": extract_required_method_tokens(
            validated.code_agent_brief
        ),
    }
    payload["contract_hash"] = canonical_model_hash(payload)
    return PlanExecutionContract.model_validate(payload)


def compile_system_authored_plan_execution_contract(
    artifact: SystemAuthoredPlanArtifact | Mapping[str, Any],
) -> ProspectivePlanExecutionContract:
    """Compile one formal plan artifact without dropping its prospective lineage.

    The local import is intentional: ``system_authored_plan`` uses the legacy token
    extractor while authoring, so importing its artifact classes at module import time
    would create a cycle.
    """

    from autoresearch.competition.system_authored_plan import (
        PlanScientificLineageBindingV2,
        SystemAuthoredPlanArtifact,
    )

    try:
        raw_artifact: Any = (
            artifact.model_dump(mode="json")
            if isinstance(artifact, SystemAuthoredPlanArtifact)
            else artifact
        )
        validated_artifact = SystemAuthoredPlanArtifact.model_validate(raw_artifact)
    except (ValidationError, ValueError) as exc:
        raise PlanExecutionContractError(
            f"formal system-authored plan artifact is invalid: {exc}"
        ) from exc
    if validated_artifact.schema_version != "system-authored-research-plan-v2":
        raise PlanExecutionContractError(
            "only SystemAuthoredPlanArtifact v2 can compile a formal prospective contract"
        )
    binding = validated_artifact.scientific_lineage_binding
    if not isinstance(binding, PlanScientificLineageBindingV2):
        raise PlanExecutionContractError(
            "formal plan artifact lacks PlanScientificLineageBindingV2"
        )
    try:
        plan = ResearchPlan.model_validate(validated_artifact.plan)
    except ValidationError as exc:
        raise PlanExecutionContractError(
            f"formal plan artifact carries a malformed research plan: {exc}"
        ) from exc
    if not _FORMAL_INTERVENTION_PATTERN.search(plan.code_agent_brief):
        raise PlanExecutionContractError(
            "formal prospective plan omits required_intervention_identity"
        )

    component_binding = binding.component_experiment_binding
    atom = binding.selected_prospective_atom()
    identity = binding.selected_intervention_identity
    if identity.atom_id != atom.atom_id:
        raise PlanExecutionContractError(
            "formal plan binding selected identity and atom disagree"
        )
    baselines = {
        item.atom_id: item for item in component_binding.observed_components.atoms
    }
    baseline = baselines.get(atom.baseline_observed_atom_id)
    if baseline is None:
        raise PlanExecutionContractError(
            "formal plan selected atom has no observed baseline in the component binding"
        )
    baseline_hash = canonical_model_hash(baseline)
    if baseline_hash != atom.baseline_observed_atom_hash:
        raise PlanExecutionContractError(
            "formal plan selected atom baseline hash differs from the observed catalog"
        )
    aliases = {
        item.target_key: item
        for item in component_binding.prospective_components.target_aliases
    }
    try:
        target_systems = tuple(aliases[key].system_name for key in atom.target_keys)
    except KeyError as exc:
        raise PlanExecutionContractError(
            f"formal plan selected atom uses unknown target alias: {exc}"
        ) from exc

    frozen_configuration = {
        _frozen_dimension_key(item): "逐字冻结" for item in atom.frozen_dimensions
    }
    control_configuration = {
        **frozen_configuration,
        atom.implementation_anchor: atom.control_level_zh,
    }
    treatment_configuration = {
        **frozen_configuration,
        atom.implementation_anchor: atom.intervention_level_zh,
    }
    pair_payload: dict[str, Any] = {
        "schema_version": "paired-control-treatment-contract-v1",
        "prospective_atom_id": atom.atom_id,
        "prospective_atom_hash": canonical_model_hash(atom),
        "baseline_observed_atom_id": atom.baseline_observed_atom_id,
        "baseline_observed_atom_hash": atom.baseline_observed_atom_hash,
        "change_mode": atom.change_mode,
        "intervention_key": atom.implementation_anchor,
        "frozen_dimensions": atom.frozen_dimensions,
        "control_configuration": control_configuration,
        "treatment_configuration": treatment_configuration,
        "changed_keys": (atom.implementation_anchor,),
    }
    pair_payload["pair_hash"] = canonical_model_hash(pair_payload)
    pair = PairedControlTreatmentContract.model_validate(pair_payload)
    lineage_payload = binding.model_dump(mode="json")
    payload: dict[str, Any] = {
        "schema_version": "plan-execution-contract-v2",
        "approved_plan_hash": compute_plan_hash(plan),
        "approved_plan": plan.model_dump(mode="json"),
        "system_authored_plan_artifact_hash": validated_artifact.artifact_hash,
        "scientific_lineage_binding": lineage_payload,
        "scientific_lineage_binding_hash": binding.binding_hash,
        "component_experiment_binding_hash": component_binding.binding_hash,
        "selected_prospective_atom": atom.model_dump(mode="json"),
        "selected_prospective_atom_hash": canonical_model_hash(atom),
        "selected_intervention_identity": identity.model_dump(mode="json"),
        "baseline_observed_atom": baseline.model_dump(mode="json"),
        "baseline_observed_atom_hash": baseline_hash,
        "implementation_anchor": identity.implementation_anchor,
        "public_hooks": identity.public_hooks,
        "forbidden_implementation_anchors": tuple(
            sorted(
                item.implementation_anchor
                for item in component_binding.prospective_components.intervention_identities
                if item.atom_id != atom.atom_id
            )
        ),
        "target_keys": atom.target_keys,
        "target_systems": target_systems,
        "supporting_fact_ids": atom.supporting_fact_ids,
        "resource_request": atom.resource_request.model_dump(mode="json"),
        "selected_plan_reference_indices": binding.selected_plan_reference_indices(),
        "paired_control_treatment": pair.model_dump(mode="json"),
    }
    payload["contract_hash"] = canonical_model_hash(payload)
    return ProspectivePlanExecutionContract.model_validate(payload)


def derive_prospective_paired_execution_binding(
    contract: ProspectivePlanExecutionContract,
) -> ProspectivePairedExecutionBinding:
    """Derive exact future control/treatment inputs without executing either arm."""

    pair = contract.paired_control_treatment

    def build_arm(
        role: Literal["control", "treatment"], configuration: Mapping[str, str]
    ) -> ProspectiveExecutionArmBinding:
        arm_payload: dict[str, Any] = {
            "schema_version": "prospective-execution-arm-binding-v1",
            "arm_role": role,
            "plan_execution_contract_hash": contract.contract_hash,
            "selected_prospective_atom_hash": contract.selected_prospective_atom_hash,
            "selected_intervention_hash": (
                contract.selected_intervention_identity.intervention_hash
            ),
            "pair_contract_hash": pair.pair_hash,
            "intervention_key": pair.intervention_key,
            "configuration": dict(configuration),
            "configuration_hash": canonical_model_hash(dict(configuration)),
        }
        arm_payload["arm_binding_hash"] = canonical_model_hash(arm_payload)
        return ProspectiveExecutionArmBinding.model_validate(arm_payload)

    control = build_arm("control", pair.control_configuration)
    treatment = build_arm("treatment", pair.treatment_configuration)
    request = contract.resource_request
    payload: dict[str, Any] = {
        "schema_version": "prospective-paired-execution-binding-v1",
        "plan_execution_contract_hash": contract.contract_hash,
        "selected_prospective_atom_hash": contract.selected_prospective_atom_hash,
        "selected_intervention_hash": (
            contract.selected_intervention_identity.intervention_hash
        ),
        "pair_contract_hash": pair.pair_hash,
        "intervention_key": pair.intervention_key,
        "changed_keys": pair.changed_keys,
        "paired_control_treatment": pair.model_dump(mode="json"),
        "control_arm": control.model_dump(mode="json"),
        "treatment_arm": treatment.model_dump(mode="json"),
        "arm_count": 2,
        "per_arm_resource_request": request.model_dump(mode="json"),
        "total_seconds_budget": 2 * request.seconds_per_cell,
        "total_memory_mb_allocation": 2 * request.memory_mb_per_cell,
        "total_cpu_core_allocation": 2 * request.cpu_cores_per_cell,
        "total_public_fit_call_budget": 2 * request.public_fit_calls_per_cell,
        "execution_authorized": False,
        "is_scientific_evidence": False,
    }
    payload["binding_hash"] = canonical_model_hash(payload)
    return ProspectivePairedExecutionBinding.model_validate(payload)


def build_prospective_candidate_execution_declaration(
    contract: ProspectivePlanExecutionContract,
) -> ProspectiveCandidateExecutionDeclaration:
    """Project the exact source literal required from every formal candidate."""

    identity = contract.selected_intervention_identity
    paired_execution_binding = derive_prospective_paired_execution_binding(contract)
    payload: dict[str, Any] = {
        "schema_version": "prospective-candidate-execution-declaration-v2",
        "plan_execution_contract_hash": contract.contract_hash,
        "scientific_lineage_binding_hash": contract.scientific_lineage_binding_hash,
        "component_experiment_binding_hash": contract.component_experiment_binding_hash,
        "selected_prospective_atom_id": contract.selected_prospective_atom.atom_id,
        "selected_prospective_atom_hash": contract.selected_prospective_atom_hash,
        "selected_intervention_identity": identity.model_dump(mode="json"),
        "baseline_observed_atom_id": contract.baseline_observed_atom.atom_id,
        "baseline_observed_atom_hash": contract.baseline_observed_atom_hash,
        "implementation_anchor": contract.implementation_anchor,
        "public_hooks": contract.public_hooks,
        "target_keys": contract.target_keys,
        "target_systems": contract.target_systems,
        "supporting_fact_ids": contract.supporting_fact_ids,
        "resource_request": contract.resource_request.model_dump(mode="json"),
        "paired_control_treatment": contract.paired_control_treatment.model_dump(
            mode="json"
        ),
        "paired_execution_binding": paired_execution_binding.model_dump(mode="json"),
    }
    payload["declaration_hash"] = canonical_model_hash(payload)
    return ProspectiveCandidateExecutionDeclaration.model_validate(payload)


def write_plan_execution_contract(
    *,
    contract: PlanExecutionContract | ProspectivePlanExecutionContract,
    output_dir: Path | str,
) -> Path:
    """Persist the contract once, refusing a different contract in the same lineage."""

    path = Path(output_dir).resolve() / _CONTRACT_NAME
    if path.is_file():
        existing = _load_any_plan_execution_contract(path)
        if existing != contract:
            raise PlanExecutionContractError(
                "lineage already contains a different plan execution contract"
            )
        return path
    write_json_model(path, contract)
    return path


def load_plan_execution_contract(output_dir: Path | str) -> PlanExecutionContract:
    """Load only a historical v1 contract.

    Formal callers must use :func:`load_prospective_plan_execution_contract`; this
    split prevents existing token-only consumers from accidentally accepting a v2
    object while ignoring its additional identity requirements.
    """

    path = Path(output_dir).resolve() / _CONTRACT_NAME
    if not path.is_file():
        raise PlanExecutionContractError(
            f"missing plan execution contract at {path}; execution is blocked"
        )
    contract = _load_any_plan_execution_contract(path)
    if not isinstance(contract, PlanExecutionContract):
        raise PlanExecutionContractError(
            "formal prospective execution contract cannot be loaded by the legacy v1 "
            "consumer"
        )
    return contract


def load_prospective_plan_execution_contract(
    output_dir: Path | str,
) -> ProspectivePlanExecutionContract:
    """Load only the formal v2 prospective contract."""

    path = Path(output_dir).resolve() / _CONTRACT_NAME
    if not path.is_file():
        raise PlanExecutionContractError(
            f"missing plan execution contract at {path}; execution is blocked"
        )
    contract = _load_any_plan_execution_contract(path)
    if not isinstance(contract, ProspectivePlanExecutionContract):
        raise PlanExecutionContractError(
            "formal prospective execution requires plan-execution-contract-v2"
        )
    return contract


def _load_any_plan_execution_contract(
    path: Path,
) -> PlanExecutionContract | ProspectivePlanExecutionContract:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlanExecutionContractError(
            f"invalid plan execution contract at {path}: {exc}"
        ) from exc
    if not isinstance(raw, Mapping):
        raise PlanExecutionContractError("plan execution contract root must be an object")
    schema_version = raw.get("schema_version")
    try:
        if schema_version == "plan-execution-contract-v1":
            return PlanExecutionContract.model_validate(raw)
        if schema_version == "plan-execution-contract-v2":
            return ProspectivePlanExecutionContract.model_validate(raw)
    except (ValidationError, ValueError) as exc:
        raise PlanExecutionContractError(
            f"plan execution contract failed validation: {exc}"
        ) from exc
    raise PlanExecutionContractError(
        f"unsupported plan execution contract schema: {schema_version!r}"
    )


def audit_candidate_plan_alignment(
    *, candidate_id: str, source_text: str, contract: PlanExecutionContract
) -> CandidatePlanAlignmentAudit:
    """Prove required method tokens occur in code reachable from the public API."""

    source_sha256 = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    parse_error: str | None = None
    identifiers: set[str] = set()
    try:
        tree = ast.parse(source_text)
        identifiers = _reachable_identifiers(tree)
    except SyntaxError as exc:
        parse_error = f"SyntaxError line {exc.lineno}: {exc.msg}"

    evidence: dict[str, tuple[str, ...]] = {}
    missing: list[str] = []
    for token in contract.required_method_tokens:
        matches = tuple(
            sorted(
                identifier
                for identifier in identifiers
                if token in _identifier_terms(identifier)
            )
        )
        evidence[token] = matches
        if not matches:
            missing.append(token)

    payload: dict[str, Any] = {
        "schema_version": "candidate-plan-alignment-audit-v1",
        "candidate_id": candidate_id,
        "approved_plan_hash": contract.approved_plan_hash,
        "plan_contract_hash": contract.contract_hash,
        "source_sha256": source_sha256,
        "required_method_tokens": contract.required_method_tokens,
        "reachable_identifier_evidence": evidence,
        "missing_method_tokens": tuple(missing),
        "parse_error": parse_error,
        "passed": not missing and parse_error is None,
    }
    payload["audit_hash"] = canonical_model_hash(payload)
    return CandidatePlanAlignmentAudit.model_validate(payload)


def require_candidate_plan_alignment(
    *,
    candidates: Sequence[Any],
    contract: PlanExecutionContract,
) -> None:
    """Fail before execution unless every promoted candidate binds to this contract."""

    if not candidates:
        raise PlanExecutionContractError(
            "no plan-aligned candidate is available for execution"
        )
    failures: list[str] = []
    for candidate in candidates:
        alignment = getattr(candidate, "plan_alignment", None)
        if alignment is None:
            failures.append(f"{candidate.candidate_id}: missing plan-alignment audit")
            continue
        if alignment.approved_plan_hash != contract.approved_plan_hash:
            failures.append(f"{candidate.candidate_id}: approved plan hash mismatch")
        if alignment.plan_contract_hash != contract.contract_hash:
            failures.append(f"{candidate.candidate_id}: plan contract hash mismatch")
        if alignment.source_sha256 != candidate.source_sha256:
            failures.append(f"{candidate.candidate_id}: source hash mismatch")
        if not alignment.passed:
            failures.append(
                f"{candidate.candidate_id}: missing method tokens "
                f"{list(alignment.missing_method_tokens)}"
            )
    if failures:
        raise PlanExecutionContractError(
            "candidate implementation is not aligned with the approved research plan: "
            + "; ".join(failures)
        )


def audit_prospective_candidate_plan_alignment(
    *,
    candidate_id: str,
    source_text: str,
    contract: ProspectivePlanExecutionContract,
) -> ProspectiveCandidatePlanAlignmentAudit:
    """Audit an exact declaration and a restricted, reachable two-arm dispatcher.

    Version 3 deliberately refuses the old "three tokens occur somewhere in the
    anchor" rule.  Declaration reads must stay read-only, the runtime configuration
    must select two distinct helpers on reachable paths, and every selected public
    hook must route all of its returns through the anchor.  This is still static
    source evidence, never proof that an arm ran or that its mathematics is correct.
    """

    source_sha256 = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    expected_declaration = build_prospective_candidate_execution_declaration(contract)
    source_declaration: ProspectiveCandidateExecutionDeclaration | None = None
    parse_error: str | None = None
    findings: list[str] = []
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    call_edges: dict[str, set[str]] = {}
    declaration_read_only = False
    tree: ast.Module | None = None
    try:
        tree = ast.parse(source_text)
        literal, declaration_finding = _module_literal_mapping(
            tree, _PROSPECTIVE_DECLARATION_NAME
        )
        if declaration_finding is not None:
            findings.append(declaration_finding)
        elif literal is not None:
            try:
                source_declaration = ProspectiveCandidateExecutionDeclaration.model_validate(
                    literal
                )
            except (ValidationError, ValueError) as exc:
                findings.append(
                    "prospective execution declaration failed exact schema validation: "
                    f"{exc}"
                )
        declaration_findings = _prospective_declaration_read_only_findings(
            tree, assignment_name=_PROSPECTIVE_DECLARATION_NAME
        )
        findings.extend(declaration_findings)
        declaration_read_only = not declaration_findings
        functions, call_edges = _top_level_call_graph(tree)
    except SyntaxError as exc:
        parse_error = f"SyntaxError line {exc.lineno}: {exc.msg}"

    declaration_exact = source_declaration == expected_declaration
    if source_declaration is not None and not declaration_exact:
        findings.append(
            "prospective execution declaration does not equal the approved contract projection"
        )

    if tree is not None:
        anchor_definition_count = sum(
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name == contract.implementation_anchor
            for node in tree.body
        )
        if anchor_definition_count != 1:
            findings.append(
                "implementation anchor must have exactly one top-level definition: "
                f"{contract.implementation_anchor} count={anchor_definition_count}"
            )

    reachability: dict[str, bool] = {}
    hook_dominance: dict[str, bool] = {}
    reachable_union: set[str] = set()
    for hook in contract.public_hooks:
        if tree is not None:
            hook_definition_count = sum(
                isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                and node.name == hook
                for node in tree.body
            )
            if hook_definition_count != 1:
                findings.append(
                    "public hook must have exactly one top-level definition: "
                    f"{hook} count={hook_definition_count}"
                )
        reachable = _reachable_function_names(hook, functions, call_edges)
        reachable_union.update(reachable)
        reachability[hook] = contract.implementation_anchor in reachable
        hook_node = functions.get(hook)
        hook_dominance[hook] = bool(
            hook_node is not None
            and _hook_routes_every_return_through_anchor(
                hook_node, anchor_name=contract.implementation_anchor
            )
        )
        if hook not in functions:
            findings.append(f"missing declared public hook callable: {hook}")
        elif not reachability[hook]:
            findings.append(
                f"public hook {hook} does not reach implementation anchor "
                f"{contract.implementation_anchor}"
            )
        elif not hook_dominance[hook]:
            findings.append(
                f"public hook {hook} reaches the implementation anchor but the anchor "
                "does not dominate every return"
            )

    anchor_node = functions.get(contract.implementation_anchor)
    dispatch = _audit_restricted_prospective_dispatch(
        anchor_node,
        assignment_name=_PROSPECTIVE_DECLARATION_NAME,
    )
    findings.extend(dispatch["findings"])
    anchor_reads_declaration = bool(dispatch["anchor_reads_declaration"])
    runtime_configuration_consumed = bool(
        dispatch["runtime_configuration_consumed"]
    )
    arm_selector_dominates_returns = bool(
        dispatch["arm_selector_dominates_returns"]
    )
    control_helper = cast(str | None, dispatch["control_helper"])
    treatment_helper = cast(str | None, dispatch["treatment_helper"])
    distinct_arm_helpers = bool(
        control_helper
        and treatment_helper
        and control_helper != treatment_helper
        and control_helper in functions
        and treatment_helper in functions
    )
    if anchor_node is None:
        findings.append(
            f"missing implementation anchor callable: {contract.implementation_anchor}"
        )
    elif not anchor_reads_declaration:
        findings.append(
            "implementation anchor does not validate the contract, intervention, and "
            "pair identities on reachable paths before arm selection"
        )
    if not runtime_configuration_consumed:
        findings.append(
            "implementation anchor has no reachable arm selector that consumes the "
            "runtime configuration"
        )
    if not arm_selector_dominates_returns:
        findings.append(
            "control/treatment arm selection does not dominate every scientific return"
        )
    if not distinct_arm_helpers:
        findings.append(
            "runtime arm selector must call distinct control/treatment helpers"
        )

    forbidden_reachable = tuple(
        sorted(set(contract.forbidden_implementation_anchors) & reachable_union)
    )
    if forbidden_reachable:
        findings.append(
            "reachable code also invokes non-selected prospective anchors: "
            + ", ".join(forbidden_reachable)
        )

    mechanical_pair_valid = False
    if source_declaration is not None:
        pair = source_declaration.paired_control_treatment
        expected_pair_binding = derive_prospective_paired_execution_binding(contract)
        mechanical_pair_valid = (
            pair.changed_keys == (pair.intervention_key,)
            and pair.intervention_key == contract.implementation_anchor
            and pair == contract.paired_control_treatment
            and source_declaration.paired_execution_binding == expected_pair_binding
        )
    if not mechanical_pair_valid:
        findings.append(
            "candidate does not carry the exact single-key control/treatment diff"
        )

    findings = list(dict.fromkeys(findings))
    payload: dict[str, Any] = {
        "schema_version": "candidate-plan-alignment-audit-v3",
        "candidate_id": candidate_id,
        "approved_plan_hash": contract.approved_plan_hash,
        "plan_contract_hash": contract.contract_hash,
        "source_sha256": source_sha256,
        "expected_declaration_hash": expected_declaration.declaration_hash,
        "source_declaration": (
            source_declaration.model_dump(mode="json")
            if source_declaration is not None
            else None
        ),
        "declaration_exact": declaration_exact,
        "selected_intervention_identity": contract.selected_intervention_identity.model_dump(
            mode="json"
        ),
        "implementation_anchor": contract.implementation_anchor,
        "public_hooks": contract.public_hooks,
        "hook_anchor_reachability": reachability,
        "hook_anchor_dominance": hook_dominance,
        "anchor_reads_execution_declaration": anchor_reads_declaration,
        "declaration_read_only": declaration_read_only,
        "runtime_configuration_consumed": runtime_configuration_consumed,
        "arm_selector_dominates_scientific_returns": (
            arm_selector_dominates_returns
        ),
        "control_helper": control_helper,
        "treatment_helper": treatment_helper,
        "distinct_arm_helpers": distinct_arm_helpers,
        "reachable_forbidden_implementation_anchors": forbidden_reachable,
        "mechanical_pair_diff_only_declared_intervention": mechanical_pair_valid,
        "parse_error": parse_error,
        "findings": tuple(findings),
        "passed": parse_error is None and not findings,
    }
    payload["audit_hash"] = canonical_model_hash(payload)
    return ProspectiveCandidatePlanAlignmentAudit.model_validate(payload)


def require_prospective_candidate_plan_alignment(
    *,
    candidates: Sequence[Any],
    contract: ProspectivePlanExecutionContract,
) -> None:
    """Fail unless every promoted candidate has an exact v3 source-bound audit."""

    if not candidates:
        raise PlanExecutionContractError(
            "no prospective-plan-aligned candidate is available for execution"
        )
    failures: list[str] = []
    for candidate in candidates:
        candidate_id = str(getattr(candidate, "candidate_id", "<unknown>"))
        alignment = getattr(candidate, "prospective_plan_alignment", None)
        if not isinstance(alignment, ProspectiveCandidatePlanAlignmentAudit):
            failures.append(
                f"{candidate_id}: missing formal prospective plan-alignment audit"
            )
            continue
        if alignment.approved_plan_hash != contract.approved_plan_hash:
            failures.append(f"{candidate_id}: approved plan hash mismatch")
        if alignment.plan_contract_hash != contract.contract_hash:
            failures.append(f"{candidate_id}: formal plan contract hash mismatch")
        if alignment.selected_intervention_identity != contract.selected_intervention_identity:
            failures.append(f"{candidate_id}: prospective intervention identity mismatch")
        if alignment.implementation_anchor != contract.implementation_anchor:
            failures.append(f"{candidate_id}: implementation anchor mismatch")
        source_sha256 = getattr(candidate, "source_sha256", None)
        if alignment.source_sha256 != source_sha256:
            failures.append(f"{candidate_id}: source hash mismatch")
        if not alignment.passed:
            failures.append(
                f"{candidate_id}: formal prospective alignment failed "
                f"{list(alignment.findings)}"
            )
    if failures:
        raise PlanExecutionContractError(
            "candidate implementation is not aligned with the formal prospective plan: "
            + "; ".join(failures)
        )


def _frozen_dimension_key(value: str) -> str:
    return f"frozen::{value}"


def _module_literal_mapping(
    tree: ast.Module,
    assignment_name: str,
) -> tuple[Mapping[str, Any] | None, str | None]:
    assignments: list[ast.expr] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            matching_targets = tuple(
                target
                for target in node.targets
                if isinstance(target, ast.Name) and target.id == assignment_name
            )
            if matching_targets and (
                len(node.targets) != 1
                or not isinstance(node.targets[0], ast.Name)
                or node.targets[0].id != assignment_name
            ):
                return (
                    None,
                    f"module-level {assignment_name} must use one unaliased name target",
                )
            if matching_targets:
                assignments.append(node.value)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == assignment_name
            and node.value is not None
        ):
            assignments.append(node.value)
        elif isinstance(node, ast.AnnAssign) and any(
                isinstance(target, ast.Name) and target.id == assignment_name
                for target in ast.walk(node.target)
        ):
            return (
                None,
                f"module-level {assignment_name} must use one unaliased name target",
            )
    if not assignments:
        return None, f"missing module-level literal {assignment_name}"
    if len(assignments) != 1:
        return None, f"module-level literal {assignment_name} must be assigned exactly once"
    try:
        value = ast.literal_eval(assignments[0])
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return None, f"module-level {assignment_name} must be one literal object"
    if not isinstance(value, Mapping):
        return None, f"module-level {assignment_name} must be one literal object"
    return cast(Mapping[str, Any], value), None


def _prospective_declaration_read_only_findings(
    tree: ast.Module,
    *,
    assignment_name: str,
) -> tuple[str, ...]:
    """Reject declaration writes, aliases, argument escape, or container escape."""

    initializer_nodes: set[int] = set()
    initializer_targets: set[int] = set()
    for statement in tree.body:
        if (
            isinstance(statement, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == assignment_name
                for target in statement.targets
            )
        ) or (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id == assignment_name
        ):
            initializer_nodes.add(id(statement))
            initializer_assignment_targets = (
                statement.targets
                if isinstance(statement, ast.Assign)
                else (statement.target,)
            )
            initializer_targets.update(
                id(target)
                for target in initializer_assignment_targets
                if isinstance(target, ast.Name) and target.id == assignment_name
            )

    parents: dict[int, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[id(child)] = parent

    findings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Name) or node.id != assignment_name:
            continue
        if isinstance(node.ctx, ast.Store) and id(node) in initializer_targets:
            continue
        parent_node = parents.get(id(node))
        direct_read = bool(
            isinstance(node.ctx, ast.Load)
            and isinstance(parent_node, ast.Subscript)
            and parent_node.value is node
            and isinstance(parent_node.ctx, ast.Load)
        )
        if not direct_read:
            findings.append(
                f"{assignment_name} may not escape through an alias or non-subscript use"
            )

    def contains_declaration(value: ast.AST | None) -> bool:
        return bool(
            value is not None
            and any(
                isinstance(item, ast.Name)
                and isinstance(item.ctx, ast.Load)
                and item.id == assignment_name
                for item in ast.walk(value)
            )
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and id(node) not in initializer_nodes:
            if contains_declaration(node.value):
                findings.append(
                    f"{assignment_name} may not escape through an alias or assignment"
                )
        elif isinstance(node, ast.AnnAssign | ast.NamedExpr):
            if id(node) not in initializer_nodes and contains_declaration(node.value):
                findings.append(
                    f"{assignment_name} may not escape through an alias or assignment"
                )
        elif isinstance(node, ast.Call):
            escaped_arguments = (*node.args, *(item.value for item in node.keywords))
            if any(contains_declaration(item) for item in escaped_arguments):
                findings.append(
                    f"{assignment_name} may not escape through a function argument"
                )
        elif isinstance(node, ast.Return) and contains_declaration(node.value):
            findings.append(f"{assignment_name} may not escape through a return value")
        elif isinstance(node, ast.List | ast.Tuple | ast.Set | ast.Dict) and any(
            contains_declaration(child) for child in ast.iter_child_nodes(node)
        ):
            findings.append(f"{assignment_name} may not escape through a container")
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            defaults = (*node.args.defaults, *node.args.kw_defaults)
            if any(contains_declaration(item) for item in defaults):
                findings.append(
                    f"{assignment_name} may not escape through a function default"
                )

    mutating_methods = {
        "clear",
        "pop",
        "popitem",
        "setdefault",
        "update",
        "__delitem__",
        "__setitem__",
    }
    for node in ast.walk(tree):
        mutation_targets: tuple[ast.expr, ...] = ()
        if isinstance(node, ast.Assign):
            if id(node) in initializer_nodes:
                continue
            mutation_targets = tuple(node.targets)
        elif isinstance(node, ast.AnnAssign | ast.AugAssign | ast.NamedExpr):
            if id(node) in initializer_nodes:
                continue
            mutation_targets = (node.target,)
        elif isinstance(node, ast.Delete):
            mutation_targets = tuple(node.targets)
        if mutation_targets and any(
            any(
                isinstance(item, ast.Name) and item.id == assignment_name
                for item in ast.walk(target)
            )
            for target in mutation_targets
        ):
            return (
                f"{assignment_name} is mutated after its exact literal initialization",
            )
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in mutating_methods
            and any(
                isinstance(item, ast.Name) and item.id == assignment_name
                for item in ast.walk(node.func.value)
            )
        ):
            return (
                f"{assignment_name} is mutated after its exact literal initialization",
            )
    return tuple(dict.fromkeys(findings))


def _static_subscript_path(node: ast.AST) -> tuple[str, tuple[str, ...]] | None:
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
        return node.id, ()
    if not (
        isinstance(node, ast.Subscript)
        and isinstance(node.ctx, ast.Load)
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, str)
    ):
        return None
    parent = _static_subscript_path(node.value)
    if parent is None:
        return None
    root, keys = parent
    return root, (*keys, node.slice.value)


def _has_static_subscript_path(
    node: ast.AST,
    *,
    root: str,
    keys: tuple[str, ...],
) -> bool:
    return any(
        _static_subscript_path(item) == (root, keys)
        for item in ast.walk(node)
        if isinstance(item, ast.Name | ast.Subscript)
    )


def _hook_routes_every_return_through_anchor(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    anchor_name: str,
) -> bool:
    def is_anchor_return(node: ast.AST) -> bool:
        return bool(
            isinstance(node, ast.Return)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == anchor_name
        )

    returns = [node for node in ast.walk(function) if isinstance(node, ast.Return)]
    return bool(
        returns
        and all(is_anchor_return(node) for node in returns)
        and function.body
        and is_anchor_return(function.body[-1])
    )


def _identity_guard_matches(
    statement: ast.stmt,
    *,
    payload_name: str,
    runtime_key: str,
    declaration_keys: tuple[str, ...],
    assignment_name: str,
) -> bool:
    if not (
        isinstance(statement, ast.If)
        and not statement.orelse
        and len(statement.body) == 1
        and isinstance(statement.body[0], ast.Raise)
        and isinstance(statement.test, ast.Compare)
        and len(statement.test.ops) == 1
        and isinstance(statement.test.ops[0], ast.NotEq)
        and len(statement.test.comparators) == 1
    ):
        return False
    left = _static_subscript_path(statement.test.left)
    right = _static_subscript_path(statement.test.comparators[0])
    runtime = (
        payload_name,
        ("prospective_execution_binding", runtime_key),
    )
    declaration = (assignment_name, declaration_keys)
    return (left == runtime and right == declaration) or (
        left == declaration and right == runtime
    )


def _runtime_arm_value_matches(
    node: ast.AST,
    *,
    payload_name: str,
    assignment_name: str,
) -> bool:
    return bool(
        isinstance(node, ast.Subscript)
        and _static_subscript_path(node.value)
        == (payload_name, ("prospective_execution_binding", "configuration"))
        and _has_static_subscript_path(
            node.slice,
            root=assignment_name,
            keys=("paired_control_treatment", "intervention_key"),
        )
    )


def _declared_arm_level_matches(
    node: ast.AST,
    *,
    configuration_key: Literal["control_configuration", "treatment_configuration"],
    assignment_name: str,
) -> bool:
    return bool(
        isinstance(node, ast.Subscript)
        and _static_subscript_path(node.value)
        == (
            assignment_name,
            ("paired_control_treatment", configuration_key),
        )
        and _has_static_subscript_path(
            node.slice,
            root=assignment_name,
            keys=("paired_control_treatment", "intervention_key"),
        )
    )


def _selector_helper(
    statement: ast.stmt,
    *,
    payload_name: str,
    configuration_key: Literal["control_configuration", "treatment_configuration"],
    assignment_name: str,
) -> tuple[str | None, ast.Return | None]:
    if not (
        isinstance(statement, ast.If)
        and not statement.orelse
        and len(statement.body) == 1
        and isinstance(statement.body[0], ast.Return)
        and isinstance(statement.test, ast.Compare)
        and len(statement.test.ops) == 1
        and isinstance(statement.test.ops[0], ast.Eq)
        and len(statement.test.comparators) == 1
    ):
        return None, None
    left = statement.test.left
    right = statement.test.comparators[0]
    exact_comparison = (
        _runtime_arm_value_matches(
            left, payload_name=payload_name, assignment_name=assignment_name
        )
        and _declared_arm_level_matches(
            right,
            configuration_key=configuration_key,
            assignment_name=assignment_name,
        )
    ) or (
        _runtime_arm_value_matches(
            right, payload_name=payload_name, assignment_name=assignment_name
        )
        and _declared_arm_level_matches(
            left,
            configuration_key=configuration_key,
            assignment_name=assignment_name,
        )
    )
    returned = statement.body[0]
    if not (
        exact_comparison
        and isinstance(returned.value, ast.Call)
        and isinstance(returned.value.func, ast.Name)
        and len(returned.value.args) == 1
        and isinstance(returned.value.args[0], ast.Name)
        and returned.value.args[0].id == payload_name
        and not returned.value.keywords
    ):
        return None, None
    return returned.value.func.id, returned


def _audit_restricted_prospective_dispatch(
    function: ast.FunctionDef | ast.AsyncFunctionDef | None,
    *,
    assignment_name: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "anchor_reads_declaration": False,
        "runtime_configuration_consumed": False,
        "arm_selector_dominates_returns": False,
        "control_helper": None,
        "treatment_helper": None,
        "findings": (),
    }
    if function is None:
        return result
    if (
        isinstance(function, ast.AsyncFunctionDef)
        or len(function.args.args) != 1
        or function.args.posonlyargs
        or function.args.kwonlyargs
        or function.args.vararg is not None
        or function.args.kwarg is not None
    ):
        result["findings"] = (
            "implementation anchor must accept exactly one positional payload",
        )
        return result

    payload_name = function.args.args[0].arg
    guard_specs = (
        (
            "plan_execution_contract_hash",
            ("plan_execution_contract_hash",),
        ),
        (
            "selected_intervention_hash",
            ("selected_intervention_identity", "intervention_hash"),
        ),
        (
            "pair_contract_hash",
            ("paired_control_treatment", "pair_hash"),
        ),
    )
    guard_indices: list[int] = []
    missing_guards: list[str] = []
    for runtime_key, declaration_keys in guard_specs:
        index = next(
            (
                item_index
                for item_index, statement in enumerate(function.body)
                if _identity_guard_matches(
                    statement,
                    payload_name=payload_name,
                    runtime_key=runtime_key,
                    declaration_keys=declaration_keys,
                    assignment_name=assignment_name,
                )
            ),
            None,
        )
        if index is None:
            missing_guards.append(runtime_key)
        else:
            guard_indices.append(index)

    control_helper: str | None = None
    treatment_helper: str | None = None
    control_return: ast.Return | None = None
    treatment_return: ast.Return | None = None
    control_index: int | None = None
    treatment_index: int | None = None
    for index, statement in enumerate(function.body):
        helper, returned = _selector_helper(
            statement,
            payload_name=payload_name,
            configuration_key="control_configuration",
            assignment_name=assignment_name,
        )
        if helper is not None and control_helper is None:
            control_helper, control_return, control_index = helper, returned, index
        helper, returned = _selector_helper(
            statement,
            payload_name=payload_name,
            configuration_key="treatment_configuration",
            assignment_name=assignment_name,
        )
        if helper is not None and treatment_helper is None:
            treatment_helper, treatment_return, treatment_index = helper, returned, index

    runtime_consumed = bool(control_helper and treatment_helper)
    allowed_returns = {
        id(item) for item in (control_return, treatment_return) if item is not None
    }
    observed_returns = {
        id(item) for item in ast.walk(function) if isinstance(item, ast.Return)
    }
    selectors_are_ordered = bool(
        control_index is not None
        and treatment_index is not None
        and control_index < treatment_index
    )
    guards_dominate = bool(
        not missing_guards
        and control_index is not None
        and treatment_index is not None
        and all(index < control_index for index in guard_indices)
    )
    final_rejects_unknown = bool(
        function.body and isinstance(function.body[-1], ast.Raise)
    )
    dominates = bool(
        runtime_consumed
        and selectors_are_ordered
        and guards_dominate
        and final_rejects_unknown
        and observed_returns == allowed_returns
    )
    findings: list[str] = []
    if missing_guards:
        findings.append(
            "restricted dispatcher lacks reachable identity guards: "
            + ", ".join(missing_guards)
        )
    if not runtime_consumed:
        findings.append(
            "restricted dispatcher lacks a reachable arm selector for control or treatment"
        )
    if runtime_consumed and not dominates:
        findings.append(
            "restricted arm selector does not dominate every anchor return"
        )
    result.update(
        {
            "anchor_reads_declaration": not missing_guards,
            "runtime_configuration_consumed": runtime_consumed,
            "arm_selector_dominates_returns": dominates,
            "control_helper": control_helper,
            "treatment_helper": treatment_helper,
            "findings": tuple(findings),
        }
    )
    return result


def _callable_reads_required_declaration_keys(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    assignment_name: str,
    required_keys: set[str],
) -> bool:
    observed: set[str] = set()
    for node in ast.walk(function):
        if not isinstance(node, ast.Subscript):
            continue
        if not (
            isinstance(node.value, ast.Name)
            and node.value.id == assignment_name
            and isinstance(node.value.ctx, ast.Load)
        ):
            continue
        if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
            observed.add(node.slice.value)
    return required_keys.issubset(observed)


def _top_level_call_graph(
    tree: ast.Module,
) -> tuple[
    dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    dict[str, set[str]],
]:
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    edges: dict[str, set[str]] = {}
    for name, function in functions.items():
        edges[name] = {
            node.func.id
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in functions
        }
    return functions, edges


def _reachable_function_names(
    root: str,
    functions: Mapping[str, ast.FunctionDef | ast.AsyncFunctionDef],
    call_edges: Mapping[str, set[str]],
) -> set[str]:
    if root not in functions:
        return set()
    queue = [root]
    reachable: set[str] = set()
    while queue:
        name = queue.pop()
        if name in reachable:
            continue
        reachable.add(name)
        queue.extend(sorted(call_edges.get(name, set()) - reachable))
    return reachable


def _reachable_identifiers(tree: ast.Module) -> set[str]:
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    queue = [name for name in _EXECUTION_ROOTS if name in functions]
    reachable: set[str] = set()
    while queue:
        name = queue.pop()
        if name in reachable:
            continue
        reachable.add(name)
        for node in ast.walk(functions[name]):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                called = node.func.id
                if called in functions and called not in reachable:
                    queue.append(called)

    # Only CALLABLE names count. Merely assigning a variable called
    # `integral_bayesian` inside fit_equations is labels, not implementation evidence.
    identifiers = set(reachable)
    for name in reachable:
        for node in ast.walk(functions[name]):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                identifiers.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                identifiers.add(node.func.attr)
    return identifiers


def _identifier_terms(identifier: str) -> set[str]:
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", identifier)
    return {
        item.casefold()
        for item in re.split(r"[^A-Za-z0-9]+", separated)
        if item
    }
