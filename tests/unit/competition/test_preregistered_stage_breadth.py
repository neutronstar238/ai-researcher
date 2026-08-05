"""Task 269.4: this lineage's own pilot breadth, under the `266.1.1` pattern.

`P-20260804-077`: the frozen pilot breadth is unreachable once the preregistered
baseline policy excludes the two systems that cannot produce a pinned baseline loss.
The system's own loop chose `require_new_preregistration` over rewriting the frozen
budget, in three independent live runs.

These tests pin the boundaries that keep a new preregistration from becoming a
loophole:

* it may only SHRINK the breadth, never buy more pilot systems than the frozen plan;
* it must be reachable on the panel it claims to describe;
* it cannot be created unless the system's own audited resolution called for it;
* the frozen parent budget is bound as evidence and never written;
* the pilot never enters the estimand, which is why narrowing it cannot bias a result.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from autoresearch.competition.preregistered_stage_breadth import (
    PreregisteredStageBreadth,
    StageBreadthError,
    load_stage_breadth,
    preregister_stage_breadth,
)

_PANEL: dict[str, Any] = {
    "systems": [
        *({"system_name": f"ode-{i}", "data_type": "ode"} for i in range(10)),
        {"system_name": "reaction_diffusion_cylinder", "data_type": "pde"},
        {"system_name": "heat_laser", "data_type": "pde"},
        {"system_name": "navier_stokes_cylinder", "data_type": "pde"},
        {"system_name": "heat_soil_uniform_2d_p1", "data_type": "pde"},
    ],
    "seeds": [101, 211, 307],
    "conditions": ["clean", "snr_20"],
}
_EXCLUDED = ("heat_laser", "heat_soil_uniform_2d_p1")
_PLAN_HASH = "a" * 64
_POLICY_HASH = "b" * 64
_PACKAGE_HASH = "c" * 64
_RESOLUTION = (
    "declare_frozen_pilot_breadth_unsatisfiable_and_require_new_preregistration"
)


def _write_inputs(
    tmp_path: Path,
    *,
    guard_accepted: bool = True,
    resolution: str = _RESOLUTION,
    requires_new: bool = True,
) -> tuple[Path, Path]:
    plan = tmp_path / "frozen-plan.json"
    plan.write_text(
        json.dumps(
            {
                "plan_hash": _PLAN_HASH,
                "search_budget": {
                    "pilot_ode_system_count": 3,
                    "pilot_pde_system_count": 3,
                    "pilot_seed_count": 1,
                },
            }
        ),
        encoding="utf-8",
    )
    package = tmp_path / "contradiction-package.json"
    package.write_text(
        json.dumps(
            {
                "package_hash": _PACKAGE_HASH,
                "guard_audit": {"guard_accepted": guard_accepted},
                "proposal": {
                    "resolution_kind": resolution,
                    "requires_new_preregistration": requires_new,
                },
            }
        ),
        encoding="utf-8",
    )
    return plan, package


def _preregister(tmp_path: Path, **overrides: Any) -> PreregisteredStageBreadth:
    plan, package = _write_inputs(tmp_path, **overrides.pop("inputs", {}))
    kwargs: dict[str, Any] = {
        "lineage_id": "task2693-unified-lineage-v1",
        "frozen_plan_path": plan,
        "baseline_policy_hash": _POLICY_HASH,
        "contradiction_package_path": package,
        "panel": _PANEL,
        "excluded_system_names": _EXCLUDED,
        "output_dir": tmp_path,
        "clock": datetime(2026, 8, 4, tzinfo=timezone.utc),
    }
    kwargs.update(overrides)
    return preregister_stage_breadth(**kwargs)


# --------------------------------------------------------------------------
# The deterministic derivation
# --------------------------------------------------------------------------


def test_the_breadth_is_min_of_frozen_and_available(tmp_path: Path) -> None:
    """3 ODE are available and asked for; 3 PDE are asked for but only 2 remain."""

    breadth = _preregister(tmp_path)
    assert breadth.available_ode_count == 10
    assert breadth.available_pde_count == 2
    assert breadth.pilot_ode_count == 3
    assert breadth.pilot_pde_count == 2
    assert breadth.pilot_system_count == 5
    assert breadth.breadth_reduced is True


def test_the_parent_breadth_is_bound_as_evidence(tmp_path: Path) -> None:
    breadth = _preregister(tmp_path)
    assert breadth.parent_plan_hash == _PLAN_HASH
    assert breadth.parent_pilot_ode_count == 3
    assert breadth.parent_pilot_pde_count == 3
    assert breadth.parent_pilot_system_count == 6
    assert breadth.frozen_parent_budget_modified is False


def test_the_frozen_plan_file_is_not_written(tmp_path: Path) -> None:
    """The parent must stay byte-identical: this is the 266.1.1 pattern."""

    plan, package = _write_inputs(tmp_path)
    before = plan.read_bytes()
    preregister_stage_breadth(
        lineage_id="task2693-unified-lineage-v1",
        frozen_plan_path=plan,
        baseline_policy_hash=_POLICY_HASH,
        contradiction_package_path=package,
        panel=_PANEL,
        excluded_system_names=_EXCLUDED,
        output_dir=tmp_path,
    )
    assert plan.read_bytes() == before


def test_the_power_cost_is_stated_not_hidden(tmp_path: Path) -> None:
    text = _preregister(tmp_path).power_cost_statement
    assert "narrows from 6 systems" in text
    assert "LESS" in text
    # And it states WHY narrowing cannot bias the reported effect.
    assert "validation NMSE" in text
    assert "not modified" in text


def test_the_pilot_never_enters_the_estimand(tmp_path: Path) -> None:
    """The reason this narrowing is safe, asserted rather than assumed."""

    breadth = _preregister(tmp_path)
    assert breadth.pilot_enters_estimand is False
    assert breadth.is_evidence is False
    assert breadth.execution_authorized is False


def test_the_authored_resolution_is_recorded(tmp_path: Path) -> None:
    breadth = _preregister(tmp_path)
    assert breadth.system_authored_resolution_kind == _RESOLUTION
    assert breadth.contradiction_package_hash == _PACKAGE_HASH
    assert breadth.baseline_policy_hash == _POLICY_HASH


def test_an_unnarrowed_panel_needs_no_reduction(tmp_path: Path) -> None:
    """Excluding one ODE system leaves the frozen breadth reachable unchanged."""

    breadth = _preregister(tmp_path, excluded_system_names=("ode-0",))
    assert breadth.pilot_ode_count == 3
    assert breadth.pilot_pde_count == 3
    assert breadth.breadth_reduced is False


# --------------------------------------------------------------------------
# The boundaries that stop this becoming a loophole
# --------------------------------------------------------------------------


def test_a_breadth_that_exceeds_the_frozen_parent_is_refused(tmp_path: Path) -> None:
    """THE loophole guard. A new preregistration must not buy MORE pilot budget."""

    payload = json.loads(_preregister(tmp_path).model_dump_json())
    payload["pilot_pde_count"] = 4
    payload["pilot_system_count"] = 7
    payload["available_pde_count"] = 4
    with pytest.raises(StageBreadthError, match="cannot exceed the frozen parent"):
        PreregisteredStageBreadth.model_validate(payload)


def test_a_breadth_exceeding_the_narrowed_panel_is_refused(tmp_path: Path) -> None:
    payload = json.loads(_preregister(tmp_path).model_dump_json())
    payload["available_pde_count"] = 1
    with pytest.raises(StageBreadthError, match="exceeds what the narrowed panel"):
        PreregisteredStageBreadth.model_validate(payload)


def test_a_reduced_flag_that_contradicts_the_counts_is_refused(tmp_path: Path) -> None:
    payload = json.loads(_preregister(tmp_path).model_dump_json())
    payload["breadth_reduced"] = False
    with pytest.raises(StageBreadthError, match="contradicts the recorded counts"):
        PreregisteredStageBreadth.model_validate(payload)


def test_counts_that_do_not_sum_are_refused(tmp_path: Path) -> None:
    payload = json.loads(_preregister(tmp_path).model_dump_json())
    payload["pilot_system_count"] = 9
    with pytest.raises(StageBreadthError, match="does not sum"):
        PreregisteredStageBreadth.model_validate(payload)


def test_the_hash_covers_the_power_cost_statement(tmp_path: Path) -> None:
    payload = json.loads(_preregister(tmp_path).model_dump_json())
    payload["power_cost_statement"] = (
        "the pilot was not narrowed at all and nothing was lost, honestly"
    )
    with pytest.raises(StageBreadthError, match="hash mismatch"):
        PreregisteredStageBreadth.model_validate(payload)


def test_a_resolution_that_failed_its_guard_cannot_justify_this(tmp_path: Path) -> None:
    with pytest.raises(StageBreadthError, match="failed its own guard audit"):
        _preregister(tmp_path, inputs={"guard_accepted": False})


def test_a_non_preregistration_route_cannot_justify_this(tmp_path: Path) -> None:
    """The artifact must not contradict the system's own authored decision.

    If the loop had chosen to reduce the frozen breadth in place, creating this
    artifact would be an agent overriding the system's choice.
    """

    with pytest.raises(StageBreadthError, match="not a new-preregistration route"):
        _preregister(
            tmp_path,
            inputs={"resolution": "reduce_pilot_pde_breadth_to_available"},
        )


def test_a_panel_with_an_empty_stratum_is_refused(tmp_path: Path) -> None:
    """A two-stratum pilot must keep both strata; a dropped stratum is not a narrowing."""

    with pytest.raises(StageBreadthError, match="at least one system per stratum"):
        _preregister(
            tmp_path,
            excluded_system_names=(
                "reaction_diffusion_cylinder",
                "heat_laser",
                "navier_stokes_cylinder",
                "heat_soil_uniform_2d_p1",
            ),
        )


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------


def test_the_artifact_round_trips(tmp_path: Path) -> None:
    breadth = _preregister(tmp_path)
    loaded = load_stage_breadth(output_dir=tmp_path)
    assert loaded is not None
    assert loaded.breadth_hash == breadth.breadth_hash


def test_a_lineage_without_a_breadth_loads_none(tmp_path: Path) -> None:
    """A lineage that never needed one is unchanged, so old lineages still replay."""

    assert load_stage_breadth(output_dir=tmp_path) is None
