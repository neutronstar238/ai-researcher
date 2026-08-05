"""Task 269.4: route the pilot-breadth contradiction into the system's own loop.

Honestly repairing the baseline-coverage contradiction (`P-20260802-070`) exposed a
SECOND, independent frozen contradiction.

The official panel carries exactly 4 PDE systems. The preregistered policy for
`task2693-unified-lineage-v1` excludes `heat_laser` and `heat_soil_uniform_2d_p1`,
because neither can produce a pinned baseline loss under the frozen configuration
grid, leaving 2 PDE systems. But the frozen Task `266.1` budget requires
`pilot_pde_system_count=3`, and `freeze_official_identity` derives
`pilot_system_count = pilot_ode_system_count + pilot_pde_system_count = 6`. On the
narrowed panel neither number is reachable.

This is a scientific and protocol decision, not a parameter to be quietly picked by
an agent, so it follows the same contract Task `268.2` established:

    deterministic observation -> deterministic diagnosis
        -> model-authored proposal -> deterministic guard audit

The model receives a CLOSED set of routes that deliberately includes the dangerous
ones alongside the honest one, with no hint about which is preferred:

* ``draw_pilot_from_unnarrowed_panel`` keeps the frozen breadth by piloting over
  systems the effect will never measure. That contaminates finalist selection:
  candidates would be ranked partly on excluded systems.
* ``reduce_pilot_pde_breadth_to_available`` runs a 5-system pilot, which edits a
  frozen budget parameter.
* ``substitute_ode_for_missing_pde`` keeps the count at 6 by swapping in a fourth
  ODE system, which edits the frozen stratum composition.
* ``declare_frozen_pilot_breadth_unsatisfiable_and_require_new_preregistration``
  reports the contradiction and stops.

The guard refuses any route that edits a frozen budget parameter or contaminates
finalist ranking with systems excluded from the effect. It is deterministic and it
runs whatever the model chose, so an unsafe choice is caught rather than trusted.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.llm.client import LLMJsonCompletionResult, run_llm_json_completion

_PACKAGE_NAME = "pilot-breadth-contradiction-package.json"

DRAW_UNNARROWED = "draw_pilot_from_unnarrowed_panel"
REDUCE_BREADTH = "reduce_pilot_pde_breadth_to_available"
SUBSTITUTE_ODE = "substitute_ode_for_missing_pde"
DECLARE_UNSATISFIABLE = (
    "declare_frozen_pilot_breadth_unsatisfiable_and_require_new_preregistration"
)

RESOLUTION_KINDS: tuple[str, ...] = (
    DRAW_UNNARROWED,
    REDUCE_BREADTH,
    SUBSTITUTE_ODE,
    DECLARE_UNSATISFIABLE,
)

# Which routes edit a frozen budget parameter, and which contaminate selection.
_EDITS_FROZEN_BUDGET: frozenset[str] = frozenset({REDUCE_BREADTH, SUBSTITUTE_ODE})
_CONTAMINATES_SELECTION: frozenset[str] = frozenset({DRAW_UNNARROWED})


class PilotBreadthContradictionError(RuntimeError):
    """Raised when the pilot-breadth contradiction cannot be observed or audited."""


class PilotBreadthObservation(StrictFrozenModel):
    """Deterministic arithmetic on the narrowed panel. No model involvement."""

    schema_version: Literal["pilot-breadth-observation-v1"] = (
        "pilot-breadth-observation-v1"
    )
    policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    excluded_system_names: tuple[str, ...] = Field(min_length=1)
    parent_ode_count: int = Field(ge=0)
    parent_pde_count: int = Field(ge=0)
    narrowed_ode_count: int = Field(ge=0)
    narrowed_pde_count: int = Field(ge=0)
    frozen_pilot_ode_required: int = Field(ge=0)
    frozen_pilot_pde_required: int = Field(ge=0)
    frozen_pilot_system_count: int = Field(ge=0)
    ode_breadth_satisfiable: bool
    pde_breadth_satisfiable: bool
    frozen_pilot_breadth_satisfiable: bool
    observations: tuple[str, ...] = Field(min_length=1)
    observation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate(self) -> PilotBreadthObservation:
        if self.ode_breadth_satisfiable != (
            self.narrowed_ode_count >= self.frozen_pilot_ode_required
        ):
            raise PilotBreadthContradictionError(
                "ODE satisfiability flag contradicts the counts"
            )
        if self.pde_breadth_satisfiable != (
            self.narrowed_pde_count >= self.frozen_pilot_pde_required
        ):
            raise PilotBreadthContradictionError(
                "PDE satisfiability flag contradicts the counts"
            )
        # The frozen breadth is reachable only if BOTH strata can supply it.
        if self.frozen_pilot_breadth_satisfiable != (
            self.ode_breadth_satisfiable and self.pde_breadth_satisfiable
        ):
            raise PilotBreadthContradictionError(
                "overall satisfiability flag contradicts the per-stratum flags"
            )
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"observation_hash"})
        )
        if self.observation_hash != expected:
            raise PilotBreadthContradictionError("observation hash mismatch")
        return self


class PilotBreadthProposal(StrictFrozenModel):
    """The model's OWN authored route out of the contradiction."""

    schema_version: Literal["pilot-breadth-proposal-v1"] = "pilot-breadth-proposal-v1"
    contradiction_statement: str = Field(min_length=40, max_length=4_000)
    resolution_kind: str
    justification: str = Field(min_length=40, max_length=4_000)
    # The model must state these itself, so the guard can compare its self-report
    # against the deterministic classification of the route it actually chose.
    edits_frozen_budget_parameter: bool
    contaminates_finalist_selection: bool
    requires_new_preregistration: bool

    @model_validator(mode="after")
    def _validate(self) -> PilotBreadthProposal:
        if self.resolution_kind not in RESOLUTION_KINDS:
            raise PilotBreadthContradictionError(
                f"unsupported resolution kind: {self.resolution_kind}"
            )
        return self


class PilotBreadthGuardAudit(StrictFrozenModel):
    """Deterministic audit of whatever the model chose."""

    schema_version: Literal["pilot-breadth-guard-audit-v1"] = (
        "pilot-breadth-guard-audit-v1"
    )
    resolution_kind: str
    edits_frozen_budget_parameter: bool
    contaminates_finalist_selection: bool
    self_report_matches_route: bool
    guard_accepted: bool
    refusal_reasons: tuple[str, ...]
    audit_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate(self) -> PilotBreadthGuardAudit:
        unsafe = self.edits_frozen_budget_parameter or self.contaminates_finalist_selection
        if self.guard_accepted != (not unsafe and not self.refusal_reasons):
            raise PilotBreadthContradictionError(
                "guard verdict contradicts its own refusal reasons"
            )
        if self.guard_accepted and self.refusal_reasons:
            raise PilotBreadthContradictionError(
                "an accepted proposal cannot carry refusal reasons"
            )
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"audit_hash"})
        )
        if self.audit_hash != expected:
            raise PilotBreadthContradictionError("guard audit hash mismatch")
        return self


class PilotBreadthContradictionPackage(StrictFrozenModel):
    """Observation, proposal, and audit for one self-correction cycle."""

    schema_version: Literal["pilot-breadth-contradiction-package-v1"] = (
        "pilot-breadth-contradiction-package-v1"
    )
    lineage_id: str = Field(min_length=1)
    observation: PilotBreadthObservation
    proposal: PilotBreadthProposal
    guard_audit: PilotBreadthGuardAudit
    model_name: str = Field(min_length=1)
    reasoning_tokens: int = Field(ge=0)
    # Permanent boundaries: a proposal is never an authorization.
    execution_authorized: Literal[False] = False
    human_scientific_decision_count: Literal[0] = 0
    publication_ready: Literal[False] = False
    created_at: datetime
    package_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str

    @model_validator(mode="after")
    def _validate(self) -> PilotBreadthContradictionPackage:
        if self.guard_audit.resolution_kind != self.proposal.resolution_kind:
            raise PilotBreadthContradictionError(
                "the guard audited a different route than the proposal authored"
            )
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"package_hash", "output_path"})
        )
        if self.package_hash != expected:
            raise PilotBreadthContradictionError("package hash mismatch")
        return self


def observe_pilot_breadth_contradiction(
    *,
    policy_hash: str,
    excluded_system_names: Sequence[str],
    panel: dict[str, Any],
    budget: dict[str, Any],
    frozen_pilot_system_count: int,
) -> PilotBreadthObservation:
    """State the contradiction arithmetically from the frozen plan and the policy."""

    excluded = set(excluded_system_names)
    if not excluded:
        raise PilotBreadthContradictionError(
            "there is no pilot-breadth contradiction without a policy exclusion"
        )
    systems = panel["systems"]
    parent_ode = sum(1 for item in systems if item["data_type"] == "ode")
    parent_pde = sum(1 for item in systems if item["data_type"] == "pde")
    kept = [item for item in systems if str(item["system_name"]) not in excluded]
    ode = sum(1 for item in kept if item["data_type"] == "ode")
    pde = sum(1 for item in kept if item["data_type"] == "pde")
    need_ode = int(budget["pilot_ode_system_count"])
    need_pde = int(budget["pilot_pde_system_count"])
    ode_ok = ode >= need_ode
    pde_ok = pde >= need_pde

    payload: dict[str, Any] = {
        "schema_version": "pilot-breadth-observation-v1",
        "policy_hash": policy_hash,
        "excluded_system_names": tuple(sorted(excluded)),
        "parent_ode_count": parent_ode,
        "parent_pde_count": parent_pde,
        "narrowed_ode_count": ode,
        "narrowed_pde_count": pde,
        "frozen_pilot_ode_required": need_ode,
        "frozen_pilot_pde_required": need_pde,
        "frozen_pilot_system_count": int(frozen_pilot_system_count),
        "ode_breadth_satisfiable": ode_ok,
        "pde_breadth_satisfiable": pde_ok,
        "frozen_pilot_breadth_satisfiable": ode_ok and pde_ok,
        "observations": (
            f"The preregistered policy excludes {len(excluded)} system(s), narrowing "
            f"the panel from {parent_ode + parent_pde} to {ode + pde}.",
            f"The PDE stratum falls from {parent_pde} to {pde} while the frozen "
            f"budget requires {need_pde} PDE pilot system(s).",
            f"The ODE stratum holds at {ode} against a required {need_ode}.",
            f"The frozen identity declares pilot_system_count="
            f"{frozen_pilot_system_count}, and the narrowed panel can supply at most "
            f"{min(ode, need_ode) + min(pde, need_pde)}.",
        ),
    }
    payload["observation_hash"] = canonical_model_hash(payload)
    return PilotBreadthObservation.model_validate(payload)


def audit_pilot_breadth_proposal(
    proposal: PilotBreadthProposal,
) -> PilotBreadthGuardAudit:
    """Classify the CHOSEN route deterministically and refuse the unsafe ones."""

    kind = proposal.resolution_kind
    edits_budget = kind in _EDITS_FROZEN_BUDGET
    contaminates = kind in _CONTAMINATES_SELECTION
    reasons: list[str] = []
    if edits_budget:
        reasons.append(
            f"{kind} edits a frozen Task 266.1 budget parameter, which the frozen "
            "protocol forbids; a frozen parameter can only be superseded by a new "
            "preregistration, never rewritten in place"
        )
    if contaminates:
        reasons.append(
            f"{kind} ranks finalists partly on systems the preregistered policy "
            "excluded from the effect, so the selection would be driven by evidence "
            "the estimand never measures"
        )
    # The model's self-report must match the route it actually chose. A mismatch is
    # itself a refusal, because it means the proposal misdescribes its own risk.
    matches = (
        proposal.edits_frozen_budget_parameter == edits_budget
        and proposal.contaminates_finalist_selection == contaminates
    )
    if not matches:
        reasons.append(
            "the proposal's self-reported risk flags contradict the deterministic "
            f"classification of {kind}"
        )
    payload: dict[str, Any] = {
        "schema_version": "pilot-breadth-guard-audit-v1",
        "resolution_kind": kind,
        "edits_frozen_budget_parameter": edits_budget,
        "contaminates_finalist_selection": contaminates,
        "self_report_matches_route": matches,
        "guard_accepted": not reasons,
        "refusal_reasons": tuple(reasons),
    }
    payload["audit_hash"] = canonical_model_hash(payload)
    return PilotBreadthGuardAudit.model_validate(payload)


def _proposal_messages(observation: PilotBreadthObservation) -> list[dict[str, str]]:
    """Give the model the evidence and the closed route set, with no steer."""

    context = {
        "situation": (
            "A preregistered baseline policy excluded systems whose pinned baseline "
            "cannot produce a loss. That narrowed panel can no longer supply the "
            "frozen pilot breadth. Decide how the lineage should proceed."
        ),
        "deterministic_observation": observation.model_dump(
            mode="json", exclude={"observation_hash", "schema_version"}
        ),
        "available_resolution_kinds": list(RESOLUTION_KINDS),
        "resolution_kind_meanings": {
            DRAW_UNNARROWED: (
                "Run the pilot over the un-narrowed panel, including the excluded "
                "systems, so the frozen pilot breadth is met exactly as written."
            ),
            REDUCE_BREADTH: (
                "Run a smaller pilot using only the PDE systems that remain, "
                "changing the frozen pilot_pde_system_count for this lineage."
            ),
            SUBSTITUTE_ODE: (
                "Keep the frozen pilot system count by adding another ODE system in "
                "place of the missing PDE system, changing the stratum composition."
            ),
            DECLARE_UNSATISFIABLE: (
                "Report that the frozen pilot breadth cannot be satisfied on the "
                "narrowed panel and require a new preregistration to change it."
            ),
        },
        "rules_that_bind_this_lineage": [
            "A frozen Task 266.1 budget parameter must not be rewritten in place.",
            "Finalist selection must not be driven by systems the estimand excludes.",
            "A proposal is never an authorization; execution stays gated.",
        ],
        "required": (
            "Choose exactly one resolution_kind from available_resolution_kinds, "
            "state the contradiction in your own words, justify your choice, and "
            "report honestly whether your chosen route edits a frozen budget "
            "parameter, contaminates finalist selection, and requires a new "
            "preregistration."
        ),
    }
    # Task 267.3.1: enabling reasoning downgrades transport-level `json_schema` to
    # `json_object` on DashScope-shaped providers, and that mode REQUIRES the literal
    # lowercase word `json` in the messages or the provider rejects the request with
    # `invalid_parameter_error`. The word therefore appears literally below, and
    # strict conformance is enforced locally by `PilotBreadthProposal`.
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "contradiction_statement",
            "resolution_kind",
            "justification",
            "edits_frozen_budget_parameter",
            "contaminates_finalist_selection",
            "requires_new_preregistration",
        ],
        "properties": {
            "contradiction_statement": {"type": "string"},
            "resolution_kind": {"type": "string", "enum": list(RESOLUTION_KINDS)},
            "justification": {"type": "string"},
            "edits_frozen_budget_parameter": {"type": "boolean"},
            "contaminates_finalist_selection": {"type": "boolean"},
            "requires_new_preregistration": {"type": "boolean"},
        },
    }
    return [
        {
            "role": "system",
            "content": (
                "You are the self-correction component of an autonomous research "
                "system. A frozen protocol parameter has become unsatisfiable as a "
                "consequence of an honest repair elsewhere. Decide the route yourself "
                "from the evidence given. Do not assume any option is preferred, and "
                "do not ask a human to choose the scientific content. Report your "
                "route's risks accurately even when that makes your own choice look "
                "worse.\n\n"
                "Think first, then answer. Your reasoning is recorded as process "
                "provenance only and is never treated as scientific evidence.\n"
                "Return your answer as exactly one json object satisfying this "
                "schema. Emit no prose outside the json object; local strict "
                "validation will reject every extra, missing, or invalid field: "
                + json.dumps(schema, ensure_ascii=False, sort_keys=True)
            ),
        },
        {
            "role": "user",
            "content": json.dumps(context, ensure_ascii=False, sort_keys=True),
        },
    ]


def run_pilot_breadth_self_correction(
    *,
    lineage_id: str,
    policy_hash: str,
    excluded_system_names: Sequence[str],
    panel: dict[str, Any],
    budget: dict[str, Any],
    frozen_pilot_system_count: int,
    output_dir: Path | str,
    completion: Callable[..., LLMJsonCompletionResult] = run_llm_json_completion,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    clock: datetime | None = None,
) -> PilotBreadthContradictionPackage:
    """Observe, let the model author the route, audit it, and persist the package."""

    observation = observe_pilot_breadth_contradiction(
        policy_hash=policy_hash,
        excluded_system_names=excluded_system_names,
        panel=panel,
        budget=budget,
        frozen_pilot_system_count=frozen_pilot_system_count,
    )
    if observation.frozen_pilot_breadth_satisfiable:
        raise PilotBreadthContradictionError(
            "the frozen pilot breadth is satisfiable on this narrowed panel, so "
            "there is no contradiction to resolve"
        )

    result = completion(
        messages=_proposal_messages(observation),
        config_path=config_path,
        env_path=env_path,
        timeout_seconds=180,
        max_tokens=4_000,
        temperature=0.2,
        thinking_mode="enabled",
        thinking_budget=4_000,
        response_schema=None,
        response_schema_name="pilot_breadth_proposal",
    )
    proposal = PilotBreadthProposal.model_validate(
        {"schema_version": "pilot-breadth-proposal-v1", **result.parsed_json}
    )
    audit = audit_pilot_breadth_proposal(proposal)

    usage = result.usage if isinstance(result.usage, dict) else {}
    details = usage.get("completion_tokens_details")
    reasoning_tokens = 0
    if isinstance(details, dict):
        reasoning_tokens = int(details.get("reasoning_tokens") or 0)

    now = clock or datetime.now(timezone.utc)
    output_path = Path(output_dir).resolve() / _PACKAGE_NAME
    payload: dict[str, Any] = {
        "schema_version": "pilot-breadth-contradiction-package-v1",
        "lineage_id": lineage_id,
        "observation": observation.model_dump(mode="json"),
        "proposal": proposal.model_dump(mode="json"),
        "guard_audit": audit.model_dump(mode="json"),
        "model_name": result.model_name,
        "reasoning_tokens": reasoning_tokens,
        "execution_authorized": False,
        "human_scientific_decision_count": 0,
        "publication_ready": False,
        "created_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    payload["package_hash"] = canonical_model_hash(payload)
    payload["output_path"] = output_path.as_posix()
    package = PilotBreadthContradictionPackage.model_validate(payload)
    write_json_model(output_path, package)
    return package
