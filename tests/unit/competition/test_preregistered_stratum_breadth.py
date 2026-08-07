"""The breadth rule must hold for ANY stratum taxonomy, not just MDBench's.

The v1 module hardcoded `ode`/`pde` into field names, so the general rule could not be
reused on another panel. These tests therefore exercise the rule on THREE different
taxonomies, including one with strata that have nothing to do with equation discovery,
because a methodology invariant that only works for one domain is not an invariant.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from autoresearch.competition.preregistered_stratum_breadth import (
    PreregisteredStratumBreadth,
    StratumBreadthError,
    derive_available_breadth,
    load_stratum_breadth,
    preregister_stratum_breadth,
)

_PLAN = "a" * 64


def _prereg(
    tmp_path: Path,
    *,
    parent: dict[str, int],
    available: dict[str, int],
    **kw: Any,
) -> PreregisteredStratumBreadth:
    return preregister_stratum_breadth(
        lineage_id="lineage-under-test",
        parent_plan_hash=_PLAN,
        parent_breadth=parent,
        available_breadth=available,
        output_dir=tmp_path,
        reason=kw.pop("reason", "Two members were excluded for a baseline defect."),
        clock=datetime(2026, 8, 4, tzinfo=timezone.utc),
        **kw,
    )


# --------------------------------------------------------------------------
# The rule is domain-agnostic
# --------------------------------------------------------------------------


def test_the_rule_holds_on_the_mdbench_taxonomy(tmp_path: Path) -> None:
    """The real case: 3 ODE + 3 PDE asked for, only 2 PDE remain."""

    breadth = _prereg(
        tmp_path, parent={"ode": 3, "pde": 3}, available={"ode": 10, "pde": 2}
    )
    assert breadth.breadth == {"ode": 3, "pde": 2}
    assert breadth.total_breadth == 5
    assert breadth.narrowed_strata == ("pde",)
    assert breadth.breadth_reduced is True


def test_the_rule_holds_on_an_unrelated_taxonomy(tmp_path: Path) -> None:
    """Nothing about this rule is specific to equation discovery.

    If the same module cannot express a breadth over, say, tabular and image cohorts,
    then the domain taxonomy leaked into the methodology, which is the defect this
    module exists to remove.
    """

    breadth = _prereg(
        tmp_path,
        parent={"tabular": 4, "image": 4, "text": 2},
        available={"tabular": 9, "image": 1, "text": 7},
        reason="The image cohort lost members to a licence restriction.",
    )
    assert breadth.breadth == {"tabular": 4, "image": 1, "text": 2}
    assert breadth.total_breadth == 7
    assert breadth.narrowed_strata == ("image",)


def test_the_rule_holds_on_a_single_stratum(tmp_path: Path) -> None:
    breadth = _prereg(tmp_path, parent={"only": 5}, available={"only": 3})
    assert breadth.breadth == {"only": 3}
    assert breadth.narrowed_strata == ("only",)


def test_an_unnarrowed_panel_reports_no_reduction(tmp_path: Path) -> None:
    breadth = _prereg(
        tmp_path, parent={"ode": 3, "pde": 3}, available={"ode": 10, "pde": 4}
    )
    assert breadth.breadth_reduced is False
    assert breadth.narrowed_strata == ()


# --------------------------------------------------------------------------
# The invariants that stop this becoming a loophole
# --------------------------------------------------------------------------


def test_breadth_may_only_shrink(tmp_path: Path) -> None:
    """THE loophole guard, on a taxonomy the v1 module could not express."""

    payload = json.loads(
        _prereg(
            tmp_path, parent={"cohort-a": 2, "cohort-b": 2}, available={"cohort-a": 9, "cohort-b": 9}
        ).model_dump_json()
    )
    payload["breadth"]["cohort-a"] = 5
    payload["total_breadth"] = 7
    with pytest.raises(StratumBreadthError, match="cannot exceed the frozen parent"):
        PreregisteredStratumBreadth.model_validate(payload)


def test_a_stratum_cannot_be_dropped_entirely(tmp_path: Path) -> None:
    """Dropping a stratum is a change of question, not a narrowing of breadth."""

    with pytest.raises(StratumBreadthError, match="cannot supply a single member"):
        _prereg(tmp_path, parent={"ode": 3, "pde": 3}, available={"ode": 10, "pde": 0})


def test_renaming_a_stratum_is_refused(tmp_path: Path) -> None:
    payload = json.loads(
        _prereg(tmp_path, parent={"ode": 3, "pde": 3}, available={"ode": 9, "pde": 2}).model_dump_json()
    )
    payload["breadth"] = {"ode": 3, "renamed": 2}
    with pytest.raises(StratumBreadthError, match="exactly the parent's strata"):
        PreregisteredStratumBreadth.model_validate(payload)


def test_a_breadth_exceeding_the_panel_is_refused(tmp_path: Path) -> None:
    payload = json.loads(
        _prereg(tmp_path, parent={"ode": 3, "pde": 3}, available={"ode": 9, "pde": 2}).model_dump_json()
    )
    payload["available_breadth"]["pde"] = 1
    with pytest.raises(StratumBreadthError, match="exceeds what the panel holds"):
        PreregisteredStratumBreadth.model_validate(payload)


def test_narrowed_strata_cannot_be_misreported(tmp_path: Path) -> None:
    payload = json.loads(
        _prereg(tmp_path, parent={"ode": 3, "pde": 3}, available={"ode": 9, "pde": 2}).model_dump_json()
    )
    payload["narrowed_strata"] = []
    with pytest.raises(StratumBreadthError, match="contradicts the recorded"):
        PreregisteredStratumBreadth.model_validate(payload)


def test_a_missing_stratum_in_the_panel_is_refused(tmp_path: Path) -> None:
    with pytest.raises(StratumBreadthError, match="supplies no member for stratum"):
        _prereg(tmp_path, parent={"ode": 3, "pde": 3}, available={"ode": 9})


def test_the_hash_covers_the_power_cost_statement(tmp_path: Path) -> None:
    payload = json.loads(
        _prereg(tmp_path, parent={"ode": 3, "pde": 3}, available={"ode": 9, "pde": 2}).model_dump_json()
    )
    payload["power_cost_statement"] = "nothing was narrowed and nothing was lost at all"
    with pytest.raises(StratumBreadthError, match="hash mismatch"):
        PreregisteredStratumBreadth.model_validate(payload)


def test_the_artifact_states_why_narrowing_cannot_bias_a_result(tmp_path: Path) -> None:
    breadth = _prereg(
        tmp_path, parent={"ode": 3, "pde": 3}, available={"ode": 9, "pde": 2}
    )
    assert breadth.stage_enters_estimand is False
    assert "does not modify" in breadth.power_cost_statement or (
        "is not modified" in breadth.power_cost_statement
    )
    assert "LESS" in breadth.power_cost_statement
    # The caller's own reason is recorded verbatim rather than paraphrased.
    assert "baseline defect" in breadth.power_cost_statement


def test_preregistration_authorizes_nothing(tmp_path: Path) -> None:
    breadth = _prereg(
        tmp_path, parent={"ode": 3, "pde": 3}, available={"ode": 9, "pde": 2}
    )
    assert breadth.is_evidence is False
    assert breadth.execution_authorized is False
    assert breadth.frozen_parent_budget_modified is False


# --------------------------------------------------------------------------
# Counting members per stratum, without knowing the taxonomy
# --------------------------------------------------------------------------


def test_available_breadth_is_derived_without_naming_strata() -> None:
    members = [
        {"system_name": "a", "data_type": "ode"},
        {"system_name": "b", "data_type": "ode"},
        {"system_name": "c", "data_type": "pde"},
        {"system_name": "d", "data_type": "pde"},
    ]
    counts = derive_available_breadth(
        members=members, stratum_key="data_type", excluded_names=("d",)
    )
    assert counts == {"ode": 2, "pde": 1}


def test_available_breadth_works_on_any_keys() -> None:
    """The caller names the keys, so the function needs no domain knowledge."""

    members = [
        {"id": "r1", "cohort": "train"},
        {"id": "r2", "cohort": "holdout"},
        {"id": "r3", "cohort": "holdout"},
    ]
    counts = derive_available_breadth(
        members=members, stratum_key="cohort", name_key="id", excluded_names=("r1",)
    )
    assert counts == {"holdout": 2}


def test_excluding_everything_is_refused() -> None:
    with pytest.raises(StratumBreadthError, match="no panel member"):
        derive_available_breadth(
            members=[{"system_name": "a", "data_type": "ode"}],
            stratum_key="data_type",
            excluded_names=("a",),
        )


def test_the_artifact_round_trips(tmp_path: Path) -> None:
    breadth = _prereg(
        tmp_path, parent={"ode": 3, "pde": 3}, available={"ode": 9, "pde": 2}
    )
    loaded = load_stratum_breadth(output_dir=tmp_path)
    assert loaded is not None
    assert loaded.breadth_hash == breadth.breadth_hash


def test_a_lineage_without_a_breadth_loads_none(tmp_path: Path) -> None:
    assert load_stratum_breadth(output_dir=tmp_path) is None
