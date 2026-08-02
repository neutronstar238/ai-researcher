"""Task 267.6 Route P2: the matched-budget estimand must be correct and honest.

`arXiv:2607.04108` found parent-conditioned evolution statistically
indistinguishable from independent sampling under MATCHED call budgets (median OOD
NMSE 0.045 vs 0.049). This module replicates or refutes that on the frozen
sentinels, so the estimand, the sign convention, and the matched-budget guard all
have to be right before any live budget is spent.
"""

from __future__ import annotations

import math

import pytest

from autoresearch.competition.route_p2_paradigm_audit import (
    ArmCellResult,
    ArmOutcome,
    RouteP2AuditError,
    _bootstrap_median_interval,
    _clip,
    _median,
    _paired_effect,
    _select_arm_outcome,
)


def _cell(
    *,
    arm: str,
    index: int,
    sentinel: str,
    train: float | None,
    prediction: float | None,
    passed: bool = True,
) -> ArmCellResult:
    return ArmCellResult(
        arm_id=arm,  # type: ignore[arg-type]
        proposal_index=index,
        sentinel_id=sentinel,
        data_type="pde",
        candidate_source_sha256="a" * 64,
        training_nmse=train,
        prediction_nmse=prediction,
        passed=passed,
    )


# --------------------------------------------------------------------------
# Sign convention and loss clipping
# --------------------------------------------------------------------------


def test_positive_effect_means_evolution_had_the_lower_loss() -> None:
    """Sign must match the frozen 266.1 estimand direction."""

    assert _paired_effect(0.01, 0.10) > 0.0
    assert _paired_effect(0.10, 0.01) < 0.0
    assert _paired_effect(0.05, 0.05) == pytest.approx(0.0)


def test_audit_reported_values_reproduce_an_indistinguishable_effect() -> None:
    """The published medians 0.045 vs 0.049 are a near-zero log effect."""

    effect = _paired_effect(0.045, 0.049)

    assert abs(effect) < 0.1


def test_failed_cell_is_penalised_not_dropped() -> None:
    """A missing loss must count as the worst case, never silently vanish."""

    assert _clip(None) == pytest.approx(1e12)
    assert _clip(float("nan")) == pytest.approx(1e12)
    assert _clip(float("inf")) == pytest.approx(1e12)


def test_loss_floor_prevents_an_infinite_effect() -> None:
    """An exact zero loss must not produce an unbounded log ratio."""

    effect = _paired_effect(0.0, 1.0)

    assert math.isfinite(effect)


def test_near_exact_fits_are_not_flattened_by_the_loss_floor() -> None:
    """Regression guard for live run v2.

    The floor was inherited from the noisy official MDBench estimand at 1e-12. The
    synthetic sentinels admit near-exact fits, and v2 produced prediction NMSE
    between 2.4e-32 and 4.5e-28. Every value clipped to the floor, flattening both
    arms and reporting a genuine log ratio of 5.80 as exactly 0.0.
    """

    evolution_loss, independent_loss = 9.73e-32, 3.22e-29

    assert _clip(evolution_loss) == pytest.approx(evolution_loss)
    assert _clip(independent_loss) == pytest.approx(independent_loss)

    effect = _paired_effect(evolution_loss, independent_loss)

    assert effect == pytest.approx(math.log(independent_loss / evolution_loss))
    assert effect > 5.0, "a real order-of-magnitude difference must survive clipping"


# --------------------------------------------------------------------------
# Train-only selection
# --------------------------------------------------------------------------


def test_selection_uses_training_loss_not_the_held_out_result() -> None:
    """Selecting on the held-out result would contaminate the comparison."""

    cells = (
        # Proposal 1: worse on train, better on held out.
        _cell(arm="independent_sampling_set_level", index=1, sentinel="s1", train=0.50, prediction=0.001),
        # Proposal 2: better on train, worse on held out.
        _cell(arm="independent_sampling_set_level", index=2, sentinel="s1", train=0.01, prediction=0.900),
    )

    outcome = _select_arm_outcome(
        arm_id="independent_sampling_set_level",
        cells=cells,
        model_call_count=2,
        generations=1,
    )

    assert outcome.selected_proposal_index == 2
    assert outcome.selection_basis == "train_only_median_nmse"
    # The reported loss is still the held-out one.
    assert outcome.per_sentinel_loss["s1"] == pytest.approx(0.900)


def test_selection_uses_the_median_across_sentinels() -> None:
    cells = (
        _cell(arm="independent_sampling_set_level", index=1, sentinel="s1", train=0.01, prediction=0.1),
        _cell(arm="independent_sampling_set_level", index=1, sentinel="s2", train=9.00, prediction=0.1),
        _cell(arm="independent_sampling_set_level", index=2, sentinel="s1", train=0.20, prediction=0.2),
        _cell(arm="independent_sampling_set_level", index=2, sentinel="s2", train=0.30, prediction=0.2),
    )

    outcome = _select_arm_outcome(
        arm_id="independent_sampling_set_level",
        cells=cells,
        model_call_count=2,
        generations=1,
    )

    # Proposal 1 median is 4.505; proposal 2 median is 0.25.
    assert outcome.selected_proposal_index == 2


def test_empty_arm_is_rejected() -> None:
    with pytest.raises(RouteP2AuditError, match="produced no cells"):
        _select_arm_outcome(
            arm_id="independent_sampling_set_level",
            cells=(),
            model_call_count=1,
            generations=1,
        )


# --------------------------------------------------------------------------
# Arm shape guards
# --------------------------------------------------------------------------


def test_independent_arm_must_be_one_generation() -> None:
    with pytest.raises(RouteP2AuditError, match="one-generation by construction"):
        ArmOutcome(
            arm_id="independent_sampling_set_level",
            model_call_count=4,
            proposal_count=4,
            generations=2,
            selected_proposal_index=1,
            per_sentinel_loss={"s1": 0.1},
            cells=(_cell(arm="independent_sampling_set_level", index=1, sentinel="s1", train=0.1, prediction=0.1),),
        )


def test_evolution_arm_requires_at_least_two_generations() -> None:
    with pytest.raises(RouteP2AuditError, match="at least two generations"):
        ArmOutcome(
            arm_id="parent_conditioned_evolution",
            model_call_count=4,
            proposal_count=4,
            generations=1,
            selected_proposal_index=1,
            per_sentinel_loss={"s1": 0.1},
            cells=(_cell(arm="parent_conditioned_evolution", index=1, sentinel="s1", train=0.1, prediction=0.1),),
        )


# --------------------------------------------------------------------------
# Bootstrap
# --------------------------------------------------------------------------


def test_bootstrap_interval_brackets_the_median() -> None:
    values = [0.05, -0.02, 0.11, -0.07, 0.03, 0.00]

    lower, upper = _bootstrap_median_interval(values)

    assert lower <= _median(values) <= upper


def test_bootstrap_is_deterministic_for_replay() -> None:
    values = [0.4, -0.1, 0.2, 0.0, -0.3]

    assert _bootstrap_median_interval(values) == _bootstrap_median_interval(values)


def test_bootstrap_on_identical_effects_has_zero_width() -> None:
    lower, upper = _bootstrap_median_interval([0.25] * 6)

    assert lower == pytest.approx(0.25)
    assert upper == pytest.approx(0.25)


def test_bootstrap_requires_at_least_one_effect() -> None:
    with pytest.raises(RouteP2AuditError, match="at least one sentinel effect"):
        _bootstrap_median_interval([])


def test_all_failed_comparison_is_refused_not_reported_as_a_null() -> None:
    """Regression guard for the first live attempt.

    All 8 candidates in both arms failed static review, so every cell took the
    worst-case loss and the paired effect was 0.0 with a zero-width interval.
    Reporting that as an informative null would have been a false finding: it
    measured the prompt, not the search paradigm.
    """

    from autoresearch.competition.route_p2_paradigm_audit import _finalize_package

    def _worst_arm(arm_id: str, generations: int) -> ArmOutcome:
        return ArmOutcome(
            arm_id=arm_id,  # type: ignore[arg-type]
            model_call_count=4,
            proposal_count=4,
            generations=generations,
            selected_proposal_index=1,
            per_sentinel_loss={"s1": 1e12, "s2": 1e12},
            cells=(
                _cell(arm=arm_id, index=1, sentinel="s1", train=None, prediction=None, passed=False),
                _cell(arm=arm_id, index=1, sentinel="s2", train=None, prediction=None, passed=False),
            ),
        )

    class _Fixture:
        def __init__(self, sentinel_id: str) -> None:
            self.sentinel_id = sentinel_id
            self.data_type = "pde"

    class _Runtime:
        environment_hash = "b" * 64

    with pytest.raises(RouteP2AuditError, match="worst-case loss"):
        _finalize_package(
            output_root=pytest.importorskip("pathlib").Path("."),
            preregistration_hash="c" * 64,
            plan_hash="d" * 64,
            erratum_hash="e" * 64,
            runner_sha256="f" * 64,
            runtime=_Runtime(),  # type: ignore[arg-type]
            matched_model_call_budget=4,
            arms=(
                _worst_arm("independent_sampling_set_level", 1),
                _worst_arm("parent_conditioned_evolution", 4),
            ),
            fixtures=[_Fixture("s1"), _Fixture("s2")],
        )


def test_wide_disagreement_produces_an_interval_spanning_zero() -> None:
    """An honest null must be reachable, since that is a valid Route P2 outcome."""

    lower, upper = _bootstrap_median_interval([0.9, -0.8, 0.7, -0.6, 0.1, -0.1])

    assert lower < 0.0 < upper
