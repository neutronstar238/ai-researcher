"""Task 267.6: a well-powered negative must be a publishable outcome.

The Task 266.3 gate requires at least 5-percent improvement AND a positive
bootstrap lower bound in BOTH strata, while the project's own 266.1 power audit
records that the four-system PDE stratum is limited to "a directional
qualification gate, not standalone significance". A gate demanding standalone
significance from a stratum known to be underpowered cannot be passed honestly.

Route P1 therefore stays byte-for-byte unchanged, and Route P2 is added beside it
as a preregistered matched-budget audit whose effect estimate and interval ARE the
finding. `arXiv:2607.04108` reported the two arms indistinguishable under matched
budgets (median OOD NMSE 0.045 vs 0.049), so replicating or refuting that is a
contribution whose value does not depend on the sign of the effect.
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from autoresearch.competition.dual_route_preregistration import (
    DualRoutePreregistration,
    DualRoutePreregistrationError,
    PowerAudit,
    RouteP1Gate,
    RouteP2Estimand,
    StratumPlan,
    compute_minimum_detectable_effect,
    describe_publishable_outcome,
    reject_route_substitution,
    validate_stratum_reporting,
)

PARENT_HASH = "8f42cbb684b7b02eee5d4e9287e26f3edaebd49b7215f603d274450a58994576"


def _power_audit(units: int = 40, sigma: float = 0.5) -> PowerAudit:
    mde = compute_minimum_detectable_effect(
        paired_unit_count=units,
        within_pair_standard_deviation=sigma,
    )
    return PowerAudit(
        paired_unit_count=units,
        within_pair_standard_deviation=sigma,
        minimum_detectable_effect=mde,
        interpretation=(
            "Effects smaller than this are not detectable at the frozen precision."
        ),
    )


def _estimand(**overrides: object) -> RouteP2Estimand:
    payload: dict[str, object] = {
        "primary_question": (
            "Does parent-conditioned evolution beat independent sampling plus "
            "set-level selection under a matched model-call budget?"
        ),
        "arm_ids": ("independent_sampling_set_level", "parent_conditioned_evolution"),
        "matched_model_call_budget": 12,
        "bootstrap_resamples": 20_000,
        "strata": (
            StratumPlan(stratum_id="ode", system_count=10, inference_role="confirmatory"),
            StratumPlan(
                stratum_id="pde",
                system_count=4,
                inference_role="directional_qualification_only",
            ),
        ),
        "power_audit": _power_audit(),
        "stop_rule": (
            "Stop after the frozen cell budget; do not add seeds after seeing scores."
        ),
    }
    payload.update(overrides)
    return RouteP2Estimand.model_validate(payload)


def _prereg(primary: str = "route_p2_search_paradigm_audit") -> DualRoutePreregistration:
    return DualRoutePreregistration.create(
        parent_negative_package_hash=PARENT_HASH,
        route_p2_estimand=_estimand(),
        primary_route=primary,  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------
# Route P1 must not be weakened
# --------------------------------------------------------------------------


def test_route_p1_keeps_the_unchanged_gate() -> None:
    gate = RouteP1Gate()

    assert gate.minimum_relative_improvement == pytest.approx(0.05)
    assert gate.require_positive_bootstrap_lower_bound is True
    assert gate.require_both_strata_directional is True
    assert gate.negative_result_is_publishable is False


@pytest.mark.parametrize("weakened", [0.0, 0.01, 0.049])
def test_route_p1_threshold_cannot_be_lowered(weakened: float) -> None:
    """This module may add a route; it may never lower the original bar."""

    with pytest.raises(ValidationError, match="unchanged 5-percent"):
        RouteP1Gate(minimum_relative_improvement=weakened)


# --------------------------------------------------------------------------
# Stratum discipline
# --------------------------------------------------------------------------


def test_pde_stratum_must_stay_directional_only() -> None:
    """The four-system PDE stratum is underpowered for standalone significance."""

    with pytest.raises(ValidationError, match="directional-qualification-only"):
        StratumPlan(stratum_id="pde", system_count=4, inference_role="confirmatory")


def test_ode_stratum_may_be_confirmatory() -> None:
    plan = StratumPlan(stratum_id="ode", system_count=10, inference_role="confirmatory")

    assert plan.inference_role == "confirmatory"


def test_estimand_requires_a_confirmatory_stratum() -> None:
    with pytest.raises(ValidationError, match="confirmatory stratum"):
        _estimand(
            strata=(
                StratumPlan(
                    stratum_id="pde",
                    system_count=4,
                    inference_role="directional_qualification_only",
                ),
            )
        )


def test_every_stratum_must_be_reported_separately() -> None:
    """Prevents a favourable stratum from masking an unfavourable one."""

    prereg = _prereg()
    with pytest.raises(DualRoutePreregistrationError, match="missing \\['pde'\\]"):
        validate_stratum_reporting(
            preregistration=prereg,
            reported_strata={"ode": 0.12},
        )


def test_unpreregistered_stratum_is_rejected() -> None:
    prereg = _prereg()
    with pytest.raises(DualRoutePreregistrationError, match="were not preregistered"):
        validate_stratum_reporting(
            preregistration=prereg,
            reported_strata={"ode": 0.1, "pde": 0.0, "invented": 0.9},
        )


# --------------------------------------------------------------------------
# Matched budget and arms
# --------------------------------------------------------------------------


def test_route_p2_must_compare_exactly_the_two_named_arms() -> None:
    with pytest.raises(ValidationError, match="two named search arms"):
        _estimand(arm_ids=("independent_sampling_set_level", "some_other_arm"))


def test_reasoning_mode_is_a_factor_not_an_assumption() -> None:
    """A 3-seed probe was far too small to claim a reasoning benefit."""

    estimand = _estimand()

    assert estimand.secondary_factor == "reasoning_mode_enabled_vs_disabled"
    assert estimand.secondary_factor_is_assumed_beneficial is False


# --------------------------------------------------------------------------
# Power audit
# --------------------------------------------------------------------------


def test_minimum_detectable_effect_shrinks_with_more_pairs() -> None:
    small = compute_minimum_detectable_effect(
        paired_unit_count=10, within_pair_standard_deviation=0.5
    )
    large = compute_minimum_detectable_effect(
        paired_unit_count=160, within_pair_standard_deviation=0.5
    )

    assert large < small
    # Quadrupling n halves the detectable effect.
    assert math.isclose(large, small / 4.0, rel_tol=1e-9)


def test_power_audit_must_be_reproducible() -> None:
    with pytest.raises(ValidationError, match="not reproducible"):
        PowerAudit(
            paired_unit_count=40,
            within_pair_standard_deviation=0.5,
            minimum_detectable_effect=0.001,
            interpretation="a fabricated minimum detectable effect",
        )


def test_power_audit_rejects_a_degenerate_design() -> None:
    with pytest.raises(DualRoutePreregistrationError, match="at least two units"):
        compute_minimum_detectable_effect(
            paired_unit_count=1, within_pair_standard_deviation=0.5
        )


# --------------------------------------------------------------------------
# Result-blind freezing and route substitution
# --------------------------------------------------------------------------


def test_preregistration_is_hash_bound_and_result_blind() -> None:
    prereg = _prereg()

    assert prereg.observed_outcome_count == 0
    assert prereg.route_substitution_allowed is False
    assert len(prereg.preregistration_hash) == 64


def test_preregistration_hash_detects_tampering() -> None:
    prereg = _prereg()
    tampered = prereg.model_dump(mode="json")
    tampered["primary_route"] = "route_p1_method_claim"

    with pytest.raises(ValidationError, match="hash mismatch"):
        DualRoutePreregistration.model_validate(tampered)


def test_reporting_the_preregistered_primary_route_is_allowed() -> None:
    prereg = _prereg("route_p2_search_paradigm_audit")

    reject_route_substitution(
        preregistration=prereg,
        reported_primary_route="route_p2_search_paradigm_audit",
        outcomes_observed=True,
    )


def test_route_substitution_after_observation_is_rejected() -> None:
    """Swapping the primary endpoint after seeing data manufactures false positives."""

    prereg = _prereg("route_p2_search_paradigm_audit")

    with pytest.raises(DualRoutePreregistrationError, match="route substitution is forbidden"):
        reject_route_substitution(
            preregistration=prereg,
            reported_primary_route="route_p1_method_claim",
            outcomes_observed=True,
        )


def test_route_change_before_observation_still_needs_a_new_lineage() -> None:
    prereg = _prereg("route_p2_search_paradigm_audit")

    with pytest.raises(DualRoutePreregistrationError, match="new preregistration lineage"):
        reject_route_substitution(
            preregistration=prereg,
            reported_primary_route="route_p1_method_claim",
            outcomes_observed=False,
        )


# --------------------------------------------------------------------------
# Honest outcome classification
# --------------------------------------------------------------------------


def test_route_p1_negative_is_not_publishable_as_a_method_claim() -> None:
    prereg = _prereg()

    verdict = describe_publishable_outcome(
        preregistration=prereg,
        route="route_p1_method_claim",
        effect_estimate=-2.796,
        interval_lower=-26.68,
        interval_upper=0.0,
    )

    assert verdict["gate_passed"] is False
    assert verdict["publishable"] is False
    assert verdict["outcome"] == "negative_result"


def test_route_p1_positive_requires_both_threshold_and_lower_bound() -> None:
    prereg = _prereg()

    passing = describe_publishable_outcome(
        preregistration=prereg,
        route="route_p1_method_claim",
        effect_estimate=0.12,
        interval_lower=0.03,
        interval_upper=0.21,
    )
    assert passing["gate_passed"] is True

    # Above threshold but the interval still touches zero.
    borderline = describe_publishable_outcome(
        preregistration=prereg,
        route="route_p1_method_claim",
        effect_estimate=0.12,
        interval_lower=-0.01,
        interval_upper=0.25,
    )
    assert borderline["gate_passed"] is False


def test_informative_null_is_publishable_for_route_p2() -> None:
    """This is the whole point of Route P2.

    An interval that is informative and includes zero REPLICATES the matched-budget
    audit finding. It is a result, not a loop failure.
    """

    prereg = _prereg()
    mde = prereg.route_p2_estimand.power_audit.minimum_detectable_effect

    verdict = describe_publishable_outcome(
        preregistration=prereg,
        route="route_p2_search_paradigm_audit",
        effect_estimate=0.0,
        interval_lower=-mde * 0.9,
        interval_upper=mde * 0.9,
    )

    assert verdict["outcome"] == "informative_null_paradigm_difference"
    assert verdict["publishable"] is True


def test_wide_interval_is_underpowered_not_null() -> None:
    """An uninformative interval must not be reported as 'no effect'."""

    prereg = _prereg()
    mde = prereg.route_p2_estimand.power_audit.minimum_detectable_effect

    verdict = describe_publishable_outcome(
        preregistration=prereg,
        route="route_p2_search_paradigm_audit",
        effect_estimate=0.0,
        interval_lower=-mde * 20.0,
        interval_upper=mde * 20.0,
    )

    assert verdict["outcome"] == "underpowered_inconclusive"
    assert verdict["publishable"] is False


def test_route_p2_detects_a_real_paradigm_difference() -> None:
    prereg = _prereg()
    mde = prereg.route_p2_estimand.power_audit.minimum_detectable_effect

    verdict = describe_publishable_outcome(
        preregistration=prereg,
        route="route_p2_search_paradigm_audit",
        effect_estimate=mde * 1.5,
        interval_lower=mde * 0.6,
        interval_upper=mde * 2.4,
    )

    assert verdict["outcome"] == "positive_paradigm_difference"
    assert verdict["gate_passed"] is True


def test_estimate_must_lie_inside_its_interval() -> None:
    prereg = _prereg()

    with pytest.raises(DualRoutePreregistrationError, match="inside its uncertainty"):
        describe_publishable_outcome(
            preregistration=prereg,
            route="route_p2_search_paradigm_audit",
            effect_estimate=5.0,
            interval_lower=-0.1,
            interval_upper=0.1,
        )
