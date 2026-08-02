"""Task 267.7: the system must diagnose and repair its own Route P2 failures.

Route P2 run `v3` produced median paired effect `+0.072726` with CI95
`[-1.050175, +12.538627]`. Against the preregistered minimum detectable effect of
`1.143742`, the interval width `13.588802` is 5.94 times the publishable threshold,
so the frozen rule classifies it `underpowered_inconclusive`.

The repair must originate INSIDE the loop. A human choosing a bigger budget would
make the next protocol a human scientific decision, which this project forbids.
Observation and diagnosis are therefore deterministic, only the revision is
model-authored, and execution stays blocked behind the Task 267.4 human plan gate.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from autoresearch.campaign.models import FailureKind
from autoresearch.competition.route_p2_self_correction import (
    UNDERPOWERED_DESIGN,
    RouteP2SelfCorrectionError,
    _is_substantive_prose,
    _required_paired_units,
    _spread,
    _stated_unit_counts,
    diagnose_route_p2_failure,
    observe_route_p2_history,
)

# The exact v3 numbers.
V3_EFFECTS = {
    "ode-linear-2field": 24.46518112647069,
    "pde-advection-1d": -0.007653735234630163,
    "pde-advection-diffusion-2d": 0.15310746872286,
    "pde-diffusion-1d": -0.9999999999,
    "pde-diffusion-1d-2field": 0.0,
    "pde-heat-3d": 1.2,
}
MDE = 1.143742


def _package(
    tmp_path: Path,
    *,
    name: str,
    effects: dict[str, float],
    lower: float,
    upper: float,
    budget: int = 4,
) -> Path:
    payload: dict[str, Any] = {
        "package_hash": f"{abs(hash(name)):064x}"[:64],
        "matched_model_call_budget": budget,
        "reasoning_mode": "disabled",
        "paired_effects": effects,
        "bootstrap_lower": lower,
        "bootstrap_upper": upper,
        "ode_stratum_median": effects.get("ode-linear-2field"),
        "pde_stratum_median": -0.007653735234630163,
    }
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Required sample size must agree with the observed interval
# --------------------------------------------------------------------------


def test_required_units_are_derived_from_the_observed_interval() -> None:
    """Regression guard for a bug in this module's first version.

    The first implementation used a normal-consistent MAD scaling and returned 2
    units for the v3 outcome, contradicting an interval that was 5.94 times too
    wide. The paired effects were bimodal and heavy-tailed (ODE +24.47 against PDE
    -0.008), so the robust estimator discarded the very outlier that drove the
    bootstrap.
    """

    required = _required_paired_units(
        current_paired_units=6,
        observed_interval_width=13.588802,
        target_interval_width=2 * MDE,
    )

    # 6 * (13.588802 / 2.287484)^2 = 6 * 35.29 = 212
    assert required == 212
    assert required > 6, "a too-wide interval must imply MORE units, never fewer"


def test_required_units_never_shrink_below_the_current_design() -> None:
    """An already-narrow interval must not imply a smaller panel."""

    required = _required_paired_units(
        current_paired_units=14,
        observed_interval_width=0.5,
        target_interval_width=2 * MDE,
    )

    assert required >= 14


def test_required_units_scale_quadratically_with_the_width_ratio() -> None:
    """Halving the target width must roughly quadruple the required units."""

    coarse = _required_paired_units(
        current_paired_units=10,
        observed_interval_width=8.0,
        target_interval_width=4.0,
    )
    fine = _required_paired_units(
        current_paired_units=10,
        observed_interval_width=8.0,
        target_interval_width=2.0,
    )

    assert coarse == 40
    assert fine == 160


def test_required_units_reject_a_nonpositive_target() -> None:
    with pytest.raises(RouteP2SelfCorrectionError, match="target interval width"):
        _required_paired_units(
            current_paired_units=6,
            observed_interval_width=1.0,
            target_interval_width=0.0,
        )


# --------------------------------------------------------------------------
# Deterministic observation
# --------------------------------------------------------------------------


def test_observation_counts_degenerate_runs_separately(tmp_path: Path) -> None:
    """A run whose every effect is exactly zero measured nothing."""

    zero = dict.fromkeys(V3_EFFECTS, 0.0)
    paths = [
        _package(tmp_path, name="v1", effects=zero, lower=0.0, upper=0.0),
        _package(tmp_path, name="v2", effects=zero, lower=0.0, upper=0.0),
        _package(
            tmp_path,
            name="v3",
            effects=V3_EFFECTS,
            lower=-1.050175,
            upper=12.538627,
        ),
    ]

    observation = observe_route_p2_history(
        package_paths=paths,
        minimum_detectable_effect=MDE,
    )

    assert observation.observed_run_count == 3
    assert observation.degenerate_run_count == 2
    assert observation.informative_run_count == 1


def test_observation_records_the_width_ratio_and_sign_disagreement(
    tmp_path: Path,
) -> None:
    path = _package(
        tmp_path,
        name="v3",
        effects=V3_EFFECTS,
        lower=-1.050175,
        upper=12.538627,
    )

    observation = observe_route_p2_history(
        package_paths=[path],
        minimum_detectable_effect=MDE,
    )

    assert observation.latest_interval_width == pytest.approx(13.588802)
    assert observation.interval_width_to_threshold_ratio == pytest.approx(5.9405, abs=1e-3)
    # ODE is strongly positive while PDE is slightly negative.
    assert observation.strata_disagree_in_sign is True


def test_observation_is_hash_bound(tmp_path: Path) -> None:
    path = _package(
        tmp_path, name="v3", effects=V3_EFFECTS, lower=-1.0, upper=12.5
    )

    observation = observe_route_p2_history(
        package_paths=[path], minimum_detectable_effect=MDE
    )

    assert len(observation.observation_hash) == 64


def test_observation_requires_at_least_one_run() -> None:
    with pytest.raises(RouteP2SelfCorrectionError, match="at least one run"):
        observe_route_p2_history(package_paths=[], minimum_detectable_effect=MDE)


def test_observation_rejects_a_missing_package(tmp_path: Path) -> None:
    with pytest.raises(RouteP2SelfCorrectionError, match="missing Route P2 package"):
        observe_route_p2_history(
            package_paths=[tmp_path / "absent.json"],
            minimum_detectable_effect=MDE,
        )


# --------------------------------------------------------------------------
# Deterministic diagnosis
# --------------------------------------------------------------------------


def test_wide_interval_is_diagnosed_as_underpowered_not_negative(
    tmp_path: Path,
) -> None:
    """An underpowered design and a weak method need different repairs."""

    path = _package(
        tmp_path,
        name="v3",
        effects=V3_EFFECTS,
        lower=-1.050175,
        upper=12.538627,
    )
    observation = observe_route_p2_history(
        package_paths=[path], minimum_detectable_effect=MDE
    )

    diagnosis = diagnose_route_p2_failure(observation)

    assert diagnosis.failure_kind == UNDERPOWERED_DESIGN
    assert diagnosis.failure_kind != FailureKind.ROOT_NEGATIVE_RESULT.value
    assert diagnosis.implied_paired_unit_count_for_current_spread == 212


def test_all_degenerate_history_is_diagnosed_as_incomplete_evidence(
    tmp_path: Path,
) -> None:
    zero = dict.fromkeys(V3_EFFECTS, 0.0)
    path = _package(tmp_path, name="v1", effects=zero, lower=0.0, upper=0.0)

    observation = observe_route_p2_history(
        package_paths=[path], minimum_detectable_effect=MDE
    )
    diagnosis = diagnose_route_p2_failure(observation)

    assert diagnosis.failure_kind == FailureKind.EVIDENCE_INCOMPLETE.value


def test_narrow_unfavourable_interval_is_a_real_negative(tmp_path: Path) -> None:
    """Only an INFORMATIVE interval may be called a negative result."""

    effects = dict.fromkeys(V3_EFFECTS, -0.30)
    path = _package(tmp_path, name="v4", effects=effects, lower=-0.45, upper=-0.15)

    observation = observe_route_p2_history(
        package_paths=[path], minimum_detectable_effect=MDE
    )
    diagnosis = diagnose_route_p2_failure(observation)

    assert diagnosis.failure_kind == FailureKind.ROOT_NEGATIVE_RESULT.value


def test_diagnosis_is_bound_to_its_observation(tmp_path: Path) -> None:
    path = _package(
        tmp_path, name="v3", effects=V3_EFFECTS, lower=-1.0, upper=12.5
    )
    observation = observe_route_p2_history(
        package_paths=[path], minimum_detectable_effect=MDE
    )

    diagnosis = diagnose_route_p2_failure(observation)

    assert diagnosis.parent_observation_hash == observation.observation_hash


# --------------------------------------------------------------------------
# Spread helper
# --------------------------------------------------------------------------


def test_degenerate_predicted_effect_is_rejected() -> None:
    """Regression guard for live run v1 of the self-correction cycle.

    The system returned `predicted_effect` as ",0.072726,> 0.072726" and both
    falsification conditions as "> 0.072726". Those are long enough to satisfy a
    length check but carry no falsifiable statement.
    """

    assert not _is_substantive_prose(",0.072726,> 0.072726")
    assert not _is_substantive_prose("> 0.072726")
    assert not _is_substantive_prose("0.05 0.10 0.15 0.20 0.25 0.30")
    assert _is_substantive_prose(
        "The paired effect interval will narrow below the preregistered threshold."
    )


def test_prose_and_structured_unit_count_must_agree() -> None:
    """Live run v1 argued for 212 units in prose while its field said 21."""

    stated = _stated_unit_counts(
        "increase paired_units from 6 to 212 as implied by observed spread"
    )

    assert 212 in stated
    assert 21 not in stated


def test_unit_count_extraction_tolerates_absent_claims() -> None:
    """Prose that makes no numeric claim must not block a valid proposal."""

    assert _stated_unit_counts("enable reasoning mode for both arms") == set()


def test_spread_of_identical_values_is_zero() -> None:
    assert _spread([0.2] * 5) == pytest.approx(0.0)


def test_spread_of_a_single_value_is_zero() -> None:
    assert _spread([0.5]) == pytest.approx(0.0)


def test_spread_is_robust_to_one_outlier() -> None:
    """Documents WHY the robust spread alone was the wrong basis for sample size."""

    without = _spread([0.0, 0.1, -0.1, 0.05, -0.05])
    with_outlier = _spread([0.0, 0.1, -0.1, 0.05, -0.05, 24.47])

    # The robust estimator barely moves, yet the bootstrap interval explodes.
    assert math.isclose(without, with_outlier, rel_tol=0.6)
