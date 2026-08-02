"""Task 267.6: preregister a dual publishable-outcome definition.

Why this exists
---------------
The Task `266.3` gate demands at least a 5-percent improvement over frozen
baselines AND a positive bootstrap lower bound in BOTH the ODE and the PDE
stratum. The project's own `266.1` power audit already recorded that the
four-system PDE stratum is limited to "a directional qualification gate, not
standalone significance". A gate that requires standalone significance from a
stratum known to be underpowered cannot be passed honestly, so every faithful run
must terminate as a negative result. That is exactly what happened across tasks
259, 260, 263, and 265.

This module does NOT weaken that gate. Route P1 keeps it byte-for-byte. It adds a
second, independently publishable route whose primary result is an effect estimate
with its uncertainty, so a well-powered negative is a valid scientific outcome
rather than a loop failure:

* Route P1 -- method claim. Unchanged 5-percent plus positive-lower-bound gate.
* Route P2 -- search-paradigm audit. A preregistered controlled comparison of
  parent-conditioned LLM evolution against independent sampling plus set-level
  selection under MATCHED model-call budgets. Reports the effect and its
  interval. Both a positive and a negative answer are publishable.

Route P2 is a direct replication target: `arXiv:2607.04108` found the two arms
statistically indistinguishable under matched budgets (median OOD NMSE 0.045 vs
0.049). Replicating or refuting that on the MDBench lineage is a contribution
whose value does not depend on the sign of the effect.

Reasoning mode is registered as a second preregistered factor rather than an
assumed improvement. A 3-seed probe after the Task `267.3.1` repair was
directionally consistent but also produced one candidate with no real training
fit, which is far too small to claim anything.

Hard boundaries
---------------
* Result-blind by construction. Freezing requires zero observed outcomes, and the
  frozen hash covers the entire specification.
* Route substitution is rejected after observation. A route that was not
  preregistered as primary cannot be promoted once scores are visible, which is
  the classic way an underpowered study becomes a false positive.
* ODE and PDE strata are reported separately, and the PDE stratum stays
  directional-only. Neither stratum may be hidden by the other.
"""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any, Literal

from pydantic import Field, model_validator

from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.models import StrictFrozenModel

PublicationRoute = Literal["route_p1_method_claim", "route_p2_search_paradigm_audit"]
StratumId = Literal["ode", "pde"]

# The four-system PDE stratum is directional-only, per the Task 266.1 power audit.
_DIRECTIONAL_ONLY_STRATA: frozenset[str] = frozenset({"pde"})


class DualRoutePreregistrationError(ValueError):
    """Raised when a preregistration boundary would be violated."""


class RouteP1Gate(StrictFrozenModel):
    """The unchanged Task 266.3 method-claim gate.

    Deliberately immutable `Literal` values: this module must be unable to weaken
    the original gate, only to add a second route beside it.
    """

    route: Literal["route_p1_method_claim"] = "route_p1_method_claim"
    # Pinned by validator rather than Literal, since Literal cannot take a float.
    minimum_relative_improvement: float = 0.05
    require_positive_bootstrap_lower_bound: Literal[True] = True
    require_both_strata_directional: Literal[True] = True
    require_concrete_equation_recovery: Literal[True] = True
    require_every_full_cell_succeeds: Literal[True] = True
    negative_result_is_publishable: Literal[False] = False

    @model_validator(mode="after")
    def _forbid_weakening_the_original_gate(self) -> RouteP1Gate:
        """This module may add a route; it may never lower the original bar."""

        if not math.isclose(self.minimum_relative_improvement, 0.05, rel_tol=1e-12):
            raise DualRoutePreregistrationError(
                "Route P1 must keep the unchanged 5-percent improvement threshold"
            )
        return self


class StratumPlan(StrictFrozenModel):
    """One preregistered reporting stratum."""

    stratum_id: StratumId
    system_count: int = Field(ge=1)
    inference_role: Literal["confirmatory", "directional_qualification_only"]

    @model_validator(mode="after")
    def _validate_stratum(self) -> StratumPlan:
        if self.stratum_id in _DIRECTIONAL_ONLY_STRATA and (
            self.inference_role != "directional_qualification_only"
        ):
            raise DualRoutePreregistrationError(
                f"the {self.stratum_id} stratum is underpowered for standalone "
                "significance and must stay directional-qualification-only"
            )
        return self


class PowerAudit(StrictFrozenModel):
    """Minimum detectable effect for the Route P2 paired estimand.

    Computed analytically for a paired design so the audit is deterministic and
    dependency-free. Reported BEFORE any Route P2 score is observed, which is what
    makes an eventual negative result interpretable rather than merely inconclusive.
    """

    paired_unit_count: int = Field(ge=2)
    within_pair_standard_deviation: float = Field(gt=0.0)
    alpha: float = Field(default=0.05, gt=0.0, lt=1.0)
    power: float = Field(default=0.8, gt=0.0, lt=1.0)
    minimum_detectable_effect: float = Field(gt=0.0)
    interpretation: str = Field(min_length=10)

    @model_validator(mode="after")
    def _validate_power(self) -> PowerAudit:
        expected = compute_minimum_detectable_effect(
            paired_unit_count=self.paired_unit_count,
            within_pair_standard_deviation=self.within_pair_standard_deviation,
            alpha=self.alpha,
            power=self.power,
        )
        if not math.isclose(self.minimum_detectable_effect, expected, rel_tol=1e-9):
            raise DualRoutePreregistrationError(
                "power audit minimum detectable effect is not reproducible"
            )
        return self


def compute_minimum_detectable_effect(
    *,
    paired_unit_count: int,
    within_pair_standard_deviation: float,
    alpha: float = 0.05,
    power: float = 0.8,
) -> float:
    """Return the smallest paired effect detectable at the given alpha and power."""

    if paired_unit_count < 2:
        raise DualRoutePreregistrationError("a paired design needs at least two units")
    if within_pair_standard_deviation <= 0.0:
        raise DualRoutePreregistrationError("within-pair standard deviation must be positive")
    normal = NormalDist()
    z_alpha = normal.inv_cdf(1.0 - alpha / 2.0)
    z_power = normal.inv_cdf(power)
    return (z_alpha + z_power) * within_pair_standard_deviation / math.sqrt(
        paired_unit_count
    )


class RouteP2Estimand(StrictFrozenModel):
    """The frozen Route P2 comparison, fixed before any outcome is seen."""

    route: Literal["route_p2_search_paradigm_audit"] = "route_p2_search_paradigm_audit"
    primary_question: str = Field(min_length=20)
    arm_ids: tuple[str, ...] = Field(min_length=2, max_length=2)
    matched_model_call_budget: int = Field(ge=1)
    estimand: Literal[
        "paired_median_difference_in_derivative_nmse",
    ] = "paired_median_difference_in_derivative_nmse"
    pairing_unit: Literal["system_condition_seed"] = "system_condition_seed"
    uncertainty_method: Literal["paired_bootstrap"] = "paired_bootstrap"
    bootstrap_resamples: int = Field(ge=1_000)
    strata: tuple[StratumPlan, ...] = Field(min_length=1)
    power_audit: PowerAudit
    stop_rule: str = Field(min_length=20)
    # A negative answer is a valid publishable result for this route. That is the
    # entire point: the effect and its interval ARE the finding.
    negative_result_is_publishable: Literal[True] = True
    secondary_factor: Literal["reasoning_mode_enabled_vs_disabled"] = (
        "reasoning_mode_enabled_vs_disabled"
    )
    secondary_factor_is_assumed_beneficial: Literal[False] = False

    @model_validator(mode="after")
    def _validate_estimand(self) -> RouteP2Estimand:
        if set(self.arm_ids) != {
            "independent_sampling_set_level",
            "parent_conditioned_evolution",
        }:
            raise DualRoutePreregistrationError(
                "Route P2 must compare exactly the two named search arms"
            )
        stratum_ids = [item.stratum_id for item in self.strata]
        if len(stratum_ids) != len(set(stratum_ids)):
            raise DualRoutePreregistrationError("Route P2 strata must be unique")
        if not any(item.inference_role == "confirmatory" for item in self.strata):
            raise DualRoutePreregistrationError(
                "Route P2 needs at least one confirmatory stratum"
            )
        return self


class DualRoutePreregistration(StrictFrozenModel):
    """Hash-bound, result-blind registration of both publishable routes."""

    schema_version: Literal["dual-route-preregistration-v1"] = (
        "dual-route-preregistration-v1"
    )
    parent_negative_package_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    route_p1_gate: RouteP1Gate
    route_p2_estimand: RouteP2Estimand
    primary_route: PublicationRoute
    # Result-blind invariant: freezing is only legal at zero observations.
    observed_outcome_count: Literal[0] = 0
    route_substitution_allowed: Literal[False] = False
    preregistration_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_preregistration(self) -> DualRoutePreregistration:
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"preregistration_hash"})
        )
        if self.preregistration_hash != expected:
            raise DualRoutePreregistrationError("dual-route preregistration hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        parent_negative_package_hash: str,
        route_p2_estimand: RouteP2Estimand,
        primary_route: PublicationRoute,
        route_p1_gate: RouteP1Gate | None = None,
    ) -> DualRoutePreregistration:
        """Freeze both routes before any outcome exists."""

        payload: dict[str, Any] = {
            "schema_version": "dual-route-preregistration-v1",
            "parent_negative_package_hash": parent_negative_package_hash,
            "route_p1_gate": (route_p1_gate or RouteP1Gate()).model_dump(mode="json"),
            "route_p2_estimand": route_p2_estimand.model_dump(mode="json"),
            "primary_route": primary_route,
            "observed_outcome_count": 0,
            "route_substitution_allowed": False,
        }
        payload["preregistration_hash"] = canonical_model_hash(payload)
        return cls.model_validate(payload)


def reject_route_substitution(
    *,
    preregistration: DualRoutePreregistration,
    reported_primary_route: PublicationRoute,
    outcomes_observed: bool,
) -> None:
    """Forbid promoting a non-primary route after outcomes are visible.

    Swapping the primary endpoint after seeing the data is the standard way an
    underpowered comparison turns into a false positive. Both routes stay
    reportable; only the PRIMARY designation is frozen.
    """

    if reported_primary_route == preregistration.primary_route:
        return
    if outcomes_observed:
        raise DualRoutePreregistrationError(
            f"primary route was preregistered as {preregistration.primary_route!r} "
            f"but {reported_primary_route!r} was reported after outcomes were "
            "observed; route substitution is forbidden"
        )
    raise DualRoutePreregistrationError(
        "changing the primary route requires a new preregistration lineage, "
        "not mutation of a frozen one"
    )


def validate_stratum_reporting(
    *,
    preregistration: DualRoutePreregistration,
    reported_strata: dict[str, float],
) -> None:
    """Require every preregistered stratum to be reported separately.

    Prevents a favourable stratum from masking an unfavourable one, which is how
    the Task 265.3 cycle-01 intervention briefly looked positive: one ODE gain
    masked negligible PDE change.
    """

    expected = {item.stratum_id for item in preregistration.route_p2_estimand.strata}
    missing = expected - set(reported_strata)
    if missing:
        raise DualRoutePreregistrationError(
            f"every preregistered stratum must be reported separately; missing {sorted(missing)}"
        )
    extra = set(reported_strata) - expected
    if extra:
        raise DualRoutePreregistrationError(
            f"reported strata were not preregistered: {sorted(extra)}"
        )


def describe_publishable_outcome(
    *,
    preregistration: DualRoutePreregistration,
    route: PublicationRoute,
    effect_estimate: float,
    interval_lower: float,
    interval_upper: float,
) -> dict[str, Any]:
    """Classify an outcome honestly, without inflating it into a claim.

    Route P2 is publishable in either direction, but only when the interval is
    informative relative to the preregistered minimum detectable effect. An
    interval wider than that means "underpowered", not "no effect".
    """

    if not interval_lower <= effect_estimate <= interval_upper:
        raise DualRoutePreregistrationError(
            "effect estimate must lie inside its uncertainty interval"
        )

    if route == "route_p1_method_claim":
        gate = preregistration.route_p1_gate
        passed = (
            effect_estimate >= gate.minimum_relative_improvement and interval_lower > 0.0
        )
        return {
            "route": route,
            "gate_passed": passed,
            "publishable": passed,
            "outcome": "positive_method_claim" if passed else "negative_result",
            "rationale": (
                "met the unchanged 5-percent and positive-lower-bound gate"
                if passed
                else "did not meet the unchanged gate; no method claim is permitted"
            ),
        }

    mde = preregistration.route_p2_estimand.power_audit.minimum_detectable_effect
    interval_width = interval_upper - interval_lower
    informative = interval_width <= 2.0 * mde
    excludes_zero = interval_lower > 0.0 or interval_upper < 0.0
    if not informative:
        outcome = "underpowered_inconclusive"
    elif excludes_zero:
        outcome = "positive_paradigm_difference"
    else:
        outcome = "informative_null_paradigm_difference"
    return {
        "route": route,
        "gate_passed": excludes_zero and informative,
        # An informative null IS the finding for this route.
        "publishable": informative,
        "outcome": outcome,
        "minimum_detectable_effect": mde,
        "interval_width": interval_width,
        "rationale": (
            "interval is wider than twice the preregistered minimum detectable "
            "effect, so this is underpowered rather than null"
            if not informative
            else (
                "interval excludes zero at the preregistered precision"
                if excludes_zero
                else "interval is informative and includes zero, which replicates "
                "the matched-budget audit result rather than failing"
            )
        ),
    }
