"""Task 267.7: let the system diagnose its own Route P2 failures and repair them.

Why this module exists
----------------------
Route P2 run `v3` produced a real measurement that the frozen preregistration
classified as `underpowered_inconclusive`: median paired effect `+0.072726` with
CI95 `[-1.050175, +12.538627]`, an interval width of `13.588802` against a
preregistered minimum detectable effect of `1.143742`. The interval is 5.9 times
wider than the publishable threshold.

The wrong response is for a human to pick a bigger budget. That would make the
next protocol a human scientific decision, which is exactly what this project
forbids: the research has to originate inside the loop.

So this module closes the loop instead:

1. ``observe_route_p2_history`` reads every accumulated Route P2 package and
   derives observations DETERMINISTICALLY. No model involvement, so the evidence
   cannot be embellished.
2. ``diagnose_route_p2_failure`` classifies the failure kind from those numbers,
   again deterministically. An underpowered design and a genuinely weak method are
   different failures and must not be conflated.
3. ``propose_route_p2_revision`` asks the configured model to author the revised
   protocol: new budget, paired units, arms, and its own falsification
   conditions. The system chooses; this module only records.
4. The revision is then subject to the Task `267.4` human research-plan gate
   before anything executes, and freezing it requires a NEW preregistration
   lineage because the frozen stop rule forbids mutating an observed protocol.

Boundaries
----------
* Observation and diagnosis are deterministic. Only the repair proposal is
  model-authored, and it is recorded with full provenance.
* A revision is a proposal, never an authorization. Execution stays blocked until
  a human records an approval against the plan hash.
* Nothing here weakens a gate. Route P1 and the publishability rules are untouched.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from autoresearch.campaign.models import FailureKind
from autoresearch.competition.autonomous_engine import (
    JsonCompletion,
    _call_and_record,
)
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.llm.client import run_llm_json_completion

# `FailureKind` has no member for "the design could not have detected an effect",
# which is a different failure from a weak method and needs a different repair.
UNDERPOWERED_DESIGN = "underpowered_design"

_PACKAGE_NAME = "route-p2-self-correction-package.json"

_REVISION_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "causal_hypothesis",
        "required_protocol_change",
        "proposed_matched_model_call_budget",
        "proposed_paired_unit_count",
        "predicted_effect",
        "falsification_conditions",
        "why_this_is_not_p_hacking",
    ],
    "properties": {
        "causal_hypothesis": {"type": "string", "minLength": 20, "maxLength": 4000},
        "required_protocol_change": {"type": "string", "minLength": 20, "maxLength": 4000},
        "proposed_matched_model_call_budget": {
            "type": "integer",
            "minimum": 2,
            "maximum": 64,
        },
        "proposed_paired_unit_count": {"type": "integer", "minimum": 2, "maximum": 200},
        "predicted_effect": {"type": "string", "minLength": 20, "maxLength": 4000},
        "falsification_conditions": {
            "type": "array",
            "minItems": 2,
            "maxItems": 8,
            "items": {"type": "string", "minLength": 10, "maxLength": 600},
        },
        "why_this_is_not_p_hacking": {
            "type": "string",
            "minLength": 20,
            "maxLength": 4000,
        },
    },
}


class RouteP2SelfCorrectionError(RuntimeError):
    """Raised when a self-correction boundary cannot be proved."""


class RouteP2HistoryObservation(StrictFrozenModel):
    """Deterministic observation over accumulated Route P2 outcomes."""

    schema_version: Literal["route-p2-history-observation-v1"] = (
        "route-p2-history-observation-v1"
    )
    observed_run_count: int = Field(ge=1)
    observed_package_hashes: tuple[str, ...] = Field(min_length=1)
    degenerate_run_count: int = Field(ge=0)
    informative_run_count: int = Field(ge=0)
    latest_median_effect: float
    latest_interval_lower: float
    latest_interval_upper: float
    latest_interval_width: float
    minimum_detectable_effect: float = Field(gt=0.0)
    # A degenerate run has a zero-width interval, which is legitimate evidence that
    # nothing was measured, so zero must be representable here.
    interval_width_to_threshold_ratio: float = Field(ge=0.0)
    latest_paired_unit_count: int = Field(ge=1)
    latest_matched_budget: int = Field(ge=1)
    observed_effect_spread: float = Field(ge=0.0)
    stratum_medians: dict[str, float | None]
    strata_disagree_in_sign: bool
    observations: tuple[str, ...] = Field(min_length=1)
    observation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_observation(self) -> RouteP2HistoryObservation:
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"observation_hash"})
        )
        if self.observation_hash != expected:
            raise RouteP2SelfCorrectionError("Route P2 history observation hash mismatch")
        return self


class RouteP2Diagnosis(StrictFrozenModel):
    """Deterministic classification of why the Route P2 outcome was not publishable."""

    schema_version: Literal["route-p2-diagnosis-v1"] = "route-p2-diagnosis-v1"
    failure_kind: str
    parent_observation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence: tuple[str, ...] = Field(min_length=1)
    # A required sample size derived from the OBSERVED spread, not chosen by anyone.
    implied_paired_unit_count_for_current_spread: int = Field(ge=2)
    diagnosis_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_diagnosis(self) -> RouteP2Diagnosis:
        if self.failure_kind not in {
            UNDERPOWERED_DESIGN,
            FailureKind.ROOT_NEGATIVE_RESULT.value,
            FailureKind.EVIDENCE_INCOMPLETE.value,
            FailureKind.CONTRIBUTION_INSUFFICIENT.value,
        }:
            raise RouteP2SelfCorrectionError("unsupported Route P2 failure kind")
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"diagnosis_hash"})
        )
        if self.diagnosis_hash != expected:
            raise RouteP2SelfCorrectionError("Route P2 diagnosis hash mismatch")
        return self


class RouteP2RevisionProposal(StrictFrozenModel):
    """The model-authored repair. A proposal, never an authorization."""

    schema_version: Literal["route-p2-revision-proposal-v1"] = (
        "route-p2-revision-proposal-v1"
    )
    parent_diagnosis_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    causal_hypothesis: str = Field(min_length=20)
    required_protocol_change: str = Field(min_length=20)
    proposed_matched_model_call_budget: int = Field(ge=2, le=64)
    proposed_paired_unit_count: int = Field(ge=2, le=200)
    predicted_effect: str = Field(min_length=20)
    falsification_conditions: tuple[str, ...] = Field(min_length=2, max_length=8)
    why_this_is_not_p_hacking: str = Field(min_length=20)
    authored_by_model: Literal[True] = True
    interaction_id: str
    # Execution requires the Task 267.4 human plan gate and a NEW lineage.
    human_approval_recorded: Literal[False] = False
    execution_authorized: Literal[False] = False
    requires_new_preregistration_lineage: Literal[True] = True
    proposal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_proposal(self) -> RouteP2RevisionProposal:
        # Live run v1 of this cycle produced a proposal whose prose argued for 212
        # paired units while its structured field said 21, and whose
        # predicted_effect and falsification_conditions were degenerate fragments
        # such as ",0.072726,> 0.072726". A self-correction proposal that
        # contradicts itself, or that carries no falsifiable content, must be
        # rejected rather than recorded as the system's plan.
        for name, text in (
            ("predicted_effect", self.predicted_effect),
            ("why_this_is_not_p_hacking", self.why_this_is_not_p_hacking),
            ("causal_hypothesis", self.causal_hypothesis),
            ("required_protocol_change", self.required_protocol_change),
        ):
            if not _is_substantive_prose(text):
                raise RouteP2SelfCorrectionError(
                    f"revision {name} is not substantive prose: {text[:80]!r}"
                )
        for condition in self.falsification_conditions:
            if not _is_substantive_prose(condition):
                raise RouteP2SelfCorrectionError(
                    f"falsification condition is not substantive: {condition[:80]!r}"
                )
        if len({item.strip().casefold() for item in self.falsification_conditions}) < 2:
            raise RouteP2SelfCorrectionError(
                "falsification conditions must be distinct, or the proposal is not "
                "genuinely falsifiable"
            )
        stated = _stated_unit_counts(self.required_protocol_change)
        if stated and self.proposed_paired_unit_count not in stated:
            raise RouteP2SelfCorrectionError(
                "revision prose and structured paired-unit count disagree: prose "
                f"states {sorted(stated)} but the field says "
                f"{self.proposed_paired_unit_count}"
            )
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"proposal_hash"})
        )
        if self.proposal_hash != expected:
            raise RouteP2SelfCorrectionError("Route P2 revision proposal hash mismatch")
        return self


class RouteP2SelfCorrectionPackage(StrictFrozenModel):
    """Complete observe -> diagnose -> propose cycle, pending human approval."""

    schema_version: Literal["route-p2-self-correction-package-v1"] = (
        "route-p2-self-correction-package-v1"
    )
    observation: RouteP2HistoryObservation
    diagnosis: RouteP2Diagnosis
    proposal: RouteP2RevisionProposal
    human_scientific_decision_count: Literal[0] = 0
    execution_authorized: Literal[False] = False
    publication_ready: Literal[False] = False
    package_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str

    @model_validator(mode="after")
    def _validate_package(self) -> RouteP2SelfCorrectionPackage:
        if self.diagnosis.parent_observation_hash != self.observation.observation_hash:
            raise RouteP2SelfCorrectionError("diagnosis is not bound to its observation")
        if self.proposal.parent_diagnosis_hash != self.diagnosis.diagnosis_hash:
            raise RouteP2SelfCorrectionError("proposal is not bound to its diagnosis")
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"package_hash", "output_path"})
        )
        if self.package_hash != expected:
            raise RouteP2SelfCorrectionError("Route P2 self-correction package hash mismatch")
        return self


def _is_substantive_prose(text: str) -> bool:
    """Reject a field that carries numbers or punctuation but no actual statement.

    Live run v1 returned `predicted_effect` as ",0.072726,> 0.072726", which is
    syntactically a string of adequate length but says nothing falsifiable.
    """

    stripped = text.strip()
    if len(stripped) < 20:
        return False
    letters = sum(character.isalpha() for character in stripped)
    # Real prose is mostly letters; a numeric fragment is not.
    return letters >= 12 and letters / len(stripped) >= 0.4


def _stated_unit_counts(text: str) -> set[int]:
    """Extract paired-unit counts asserted in prose, to catch self-contradiction."""

    import re

    counts: set[int] = set()
    # "paired_units from 6 to 212" must yield BOTH endpoints, so that a structured
    # field of 21 is caught as disagreeing with prose that argues for 212.
    for match in re.finditer(
        r"(?:paired[_ ]units?|units?)((?:\s*(?:from|to|,|and|->|→)?\s*\d{1,4})+)",
        text,
        flags=re.IGNORECASE,
    ):
        counts.update(int(item) for item in re.findall(r"\d{1,4}", match.group(1)))
    for match in re.finditer(
        r"(?:from|to)\s+(\d{1,4})\s*(?:paired[_ ]units?|units?)",
        text,
        flags=re.IGNORECASE,
    ):
        counts.add(int(match.group(1)))
    return counts


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    count = len(ordered)
    middle = count // 2
    if count % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _required_paired_units(
    *,
    current_paired_units: int,
    observed_interval_width: float,
    target_interval_width: float,
) -> int:
    """Units needed to reach the target width, derived from the OBSERVED bootstrap.

    Deliberately assumption-light. An earlier version used a normal-consistent MAD
    scaling and returned 2 units for the `v3` outcome, which contradicted the
    observed interval being 5.94 times too wide. The paired effects were bimodal
    and heavy-tailed -- ODE `+24.465181` against PDE `-0.007654` -- so the robust
    spread estimator discarded exactly the outlier that drove the bootstrap. A
    normality assumption is therefore invalid here.

    A bootstrap median interval narrows roughly as `1/sqrt(n)`, so
    `required_n ~= current_n * (observed_width / target_width)^2`. This is grounded
    in the measurement actually taken rather than in an assumed distribution.
    """

    if target_interval_width <= 0.0:
        raise RouteP2SelfCorrectionError("target interval width must be positive")
    if current_paired_units < 1:
        raise RouteP2SelfCorrectionError("current paired unit count must be positive")
    if observed_interval_width <= target_interval_width:
        return max(2, current_paired_units)
    ratio = observed_interval_width / target_interval_width
    return max(2, math.ceil(current_paired_units * ratio * ratio))


def observe_route_p2_history(
    *,
    package_paths: Sequence[Path | str],
    minimum_detectable_effect: float,
) -> RouteP2HistoryObservation:
    """Derive observations from accumulated Route P2 packages, with no model input."""

    if not package_paths:
        raise RouteP2SelfCorrectionError("self-correction requires at least one run")
    packages = []
    for path in package_paths:
        resolved = Path(path)
        if not resolved.is_file():
            raise RouteP2SelfCorrectionError(f"missing Route P2 package: {resolved}")
        packages.append(json.loads(resolved.read_text(encoding="utf-8")))

    degenerate = 0
    informative = 0
    for package in packages:
        effects = list(package.get("paired_effects", {}).values())
        # A run where every paired effect is exactly zero measured nothing.
        if effects and all(value == 0.0 for value in effects):
            degenerate += 1
        else:
            informative += 1

    latest = packages[-1]
    effects = latest.get("paired_effects", {})
    values = list(effects.values())
    if not values:
        raise RouteP2SelfCorrectionError("latest Route P2 run has no paired effects")
    spread = _spread(values)
    lower = float(latest["bootstrap_lower"])
    upper = float(latest["bootstrap_upper"])
    width = upper - lower
    strata = {
        "ode": latest.get("ode_stratum_median"),
        "pde": latest.get("pde_stratum_median"),
    }
    present = [value for value in strata.values() if isinstance(value, int | float)]
    disagree = len(present) == 2 and (present[0] > 0.0) != (present[1] > 0.0)

    observations = [
        f"observed_runs: {len(packages)} of which {degenerate} measured nothing",
        f"latest_median_effect: {_median(values):.6f}",
        f"latest_interval: [{lower:.6f}, {upper:.6f}] width={width:.6f}",
        f"publishable_width_threshold: {2 * minimum_detectable_effect:.6f}",
        f"interval_is_wider_than_threshold_by: "
        f"{width / (2 * minimum_detectable_effect):.4f}x",
        f"paired_units: {len(values)}",
        f"matched_model_call_budget: {latest['matched_model_call_budget']}",
        f"observed_effect_spread: {spread:.6f}",
        f"stratum_medians: {json.dumps(strata, sort_keys=True)}",
        f"strata_disagree_in_sign: {str(disagree).lower()}",
        f"reasoning_mode: {latest.get('reasoning_mode')}",
    ]
    payload: dict[str, Any] = {
        "schema_version": "route-p2-history-observation-v1",
        "observed_run_count": len(packages),
        "observed_package_hashes": tuple(item["package_hash"] for item in packages),
        "degenerate_run_count": degenerate,
        "informative_run_count": informative,
        "latest_median_effect": _median(values),
        "latest_interval_lower": lower,
        "latest_interval_upper": upper,
        "latest_interval_width": width,
        "minimum_detectable_effect": minimum_detectable_effect,
        "interval_width_to_threshold_ratio": width / (2 * minimum_detectable_effect),
        "latest_paired_unit_count": len(values),
        "latest_matched_budget": int(latest["matched_model_call_budget"]),
        "observed_effect_spread": spread,
        "stratum_medians": strata,
        "strata_disagree_in_sign": disagree,
        "observations": tuple(observations),
    }
    payload["observation_hash"] = canonical_model_hash(payload)
    return RouteP2HistoryObservation.model_validate(payload)


def _spread(values: Sequence[float]) -> float:
    """Robust spread of the paired effects, used to derive the required sample size."""

    if len(values) < 2:
        return 0.0
    centre = _median(values)
    deviations = sorted(abs(value - centre) for value in values)
    # Median absolute deviation scaled to a normal-consistent standard deviation.
    return 1.4826 * _median(deviations)


def diagnose_route_p2_failure(
    observation: RouteP2HistoryObservation,
) -> RouteP2Diagnosis:
    """Classify the failure deterministically. No model involvement."""

    evidence = list(observation.observations)
    if observation.degenerate_run_count and not observation.informative_run_count:
        failure_kind = FailureKind.EVIDENCE_INCOMPLETE.value
        evidence.append(
            "every run measured nothing, so no scientific verdict exists yet"
        )
    elif observation.interval_width_to_threshold_ratio > 1.0:
        # The design could not have detected the effect it was looking for.
        failure_kind = UNDERPOWERED_DESIGN
        evidence.append(
            "the interval is wider than twice the preregistered minimum detectable "
            "effect, so this outcome is underpowered rather than null"
        )
    elif observation.latest_median_effect <= 0.0:
        failure_kind = FailureKind.ROOT_NEGATIVE_RESULT.value
        evidence.append("the informative interval does not favour the tested paradigm")
    else:
        failure_kind = FailureKind.CONTRIBUTION_INSUFFICIENT.value
        evidence.append("the effect is informative but does not clear the frozen gate")

    payload: dict[str, Any] = {
        "schema_version": "route-p2-diagnosis-v1",
        "failure_kind": failure_kind,
        "parent_observation_hash": observation.observation_hash,
        "evidence": tuple(evidence),
        "implied_paired_unit_count_for_current_spread": _required_paired_units(
            current_paired_units=observation.latest_paired_unit_count,
            observed_interval_width=observation.latest_interval_width,
            target_interval_width=2 * observation.minimum_detectable_effect,
        ),
    }
    payload["diagnosis_hash"] = canonical_model_hash(payload)
    return RouteP2Diagnosis.model_validate(payload)


def propose_route_p2_revision(
    *,
    observation: RouteP2HistoryObservation,
    diagnosis: RouteP2Diagnosis,
    output_dir: Path | str,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    provider_timeout_seconds: int = 300,
    completion: JsonCompletion = run_llm_json_completion,
    clock: Callable[[], datetime] | None = None,
) -> RouteP2SelfCorrectionPackage:
    """Ask the SYSTEM to author the revised protocol, then stop for human approval."""

    now = clock or (lambda: datetime.now(timezone.utc))
    output_root = Path(output_dir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    messages = [
        {
            "role": "system",
            "content": (
                "You are the autonomous scientist repairing your own research "
                "protocol. You are given deterministic observations of your previous "
                "runs and a deterministic failure diagnosis. Author the revised "
                "protocol yourself. Return exactly one JSON object matching the "
                "supplied schema. You may change the matched model-call budget and "
                "the number of paired units. You may NOT weaken any acceptance "
                "threshold, and you may not reinterpret an underpowered result as a "
                "null result. Explain in why_this_is_not_p_hacking how your revision "
                "avoids selecting a protocol because it is more likely to produce a "
                "favourable answer."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "deterministic_observations": list(observation.observations),
                    "failure_kind": diagnosis.failure_kind,
                    "diagnostic_evidence": list(diagnosis.evidence),
                    "paired_units_implied_by_your_observed_spread": (
                        diagnosis.implied_paired_unit_count_for_current_spread
                    ),
                    "current_paired_units": observation.latest_paired_unit_count,
                    "current_matched_budget": observation.latest_matched_budget,
                    "hard_constraints": [
                        "the minimum detectable effect must not be raised to make a "
                        "wide interval look acceptable",
                        "an underpowered interval is never reported as a null result",
                        "both arms must always spend an identical model-call budget",
                        "strata must be reported separately",
                        "a revised protocol requires a new preregistration lineage "
                        "and human plan approval before it may execute",
                    ],
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        },
    ]
    interaction_id = f"route-p2-revision-{diagnosis.diagnosis_hash[:16]}"
    result, _ = _call_and_record(
        completion=completion,
        messages=messages,
        config_path=config_path,
        env_path=env_path,
        timeout_seconds=provider_timeout_seconds,
        max_tokens=6_000,
        response_schema=_REVISION_RESPONSE_SCHEMA,
        response_schema_name="route_p2_revision",
        interaction_id=interaction_id,
        stage="mechanism_intervention",
        candidate_id=None,
        output_root=output_root,
        now=now,
    )
    parsed = result.parsed_json
    proposal_payload: dict[str, Any] = {
        "schema_version": "route-p2-revision-proposal-v1",
        "parent_diagnosis_hash": diagnosis.diagnosis_hash,
        "causal_hypothesis": parsed["causal_hypothesis"],
        "required_protocol_change": parsed["required_protocol_change"],
        "proposed_matched_model_call_budget": int(
            parsed["proposed_matched_model_call_budget"]
        ),
        "proposed_paired_unit_count": int(parsed["proposed_paired_unit_count"]),
        "predicted_effect": parsed["predicted_effect"],
        "falsification_conditions": tuple(parsed["falsification_conditions"]),
        "why_this_is_not_p_hacking": parsed["why_this_is_not_p_hacking"],
        "authored_by_model": True,
        "interaction_id": interaction_id,
        "human_approval_recorded": False,
        "execution_authorized": False,
        "requires_new_preregistration_lineage": True,
    }
    proposal_payload["proposal_hash"] = canonical_model_hash(proposal_payload)
    proposal = RouteP2RevisionProposal.model_validate(proposal_payload)

    package_payload: dict[str, Any] = {
        "schema_version": "route-p2-self-correction-package-v1",
        "observation": observation.model_dump(mode="json"),
        "diagnosis": diagnosis.model_dump(mode="json"),
        "proposal": proposal.model_dump(mode="json"),
        "human_scientific_decision_count": 0,
        "execution_authorized": False,
        "publication_ready": False,
    }
    package_payload["package_hash"] = canonical_model_hash(package_payload)
    package_payload["output_path"] = (output_root / _PACKAGE_NAME).as_posix()
    package = RouteP2SelfCorrectionPackage.model_validate(package_payload)
    write_json_model(output_root / _PACKAGE_NAME, package)
    return package
