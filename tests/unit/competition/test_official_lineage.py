"""Task 269.1: the frozen gate and the signed package must be correct before any run.

The retired scratch driver `_lineage268.py` hand-wrote the frozen gate inside its
`adjudicate` stage, so the rule that decides whether a search-freeze receipt is
issued was never reviewed and never tested. It also never constructed an
`OfficialDevelopmentSearchPackage`, so the only adjudication record for the last real
lineage was a scratch text file.

These tests pin the adjudication rule itself:

* an absent aggregate is a FAILED check, never a pass
* an empty arm cannot satisfy a "must succeed" check vacuously
* a receipt is refused whenever any check fails, including budget non-conformance
* every threshold comes from the frozen plan's estimand, not from a literal
* the written package is the artifact whose hash is verified

The final test re-evaluates the retained conformant lineage through this module and
asserts the exact numbers that lineage recorded, which is what proves the gate moved
out of the scratch driver without changing arithmetic.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.official_development_search import (
    OfficialCandidateRecord,
    OfficialCellResult,
    OfficialDevelopmentIdentity,
    OfficialDevelopmentSearchError,
)
from autoresearch.competition.official_lineage import (
    LINEAGE_STAGES,
    OfficialLineageConfig,
    OfficialLineageError,
    _stage_shape,
    evaluate_frozen_gate,
    freeze_lineage,
    frozen_gate_receipt,
    rank_pilot_finalists,
    run_adjudicate_stage,
    select_pilot_systems,
    write_official_development_search_package,
)

# The frozen Task 266.1 estimand, verbatim. Nothing below invents a threshold.
_ESTIMAND: dict[str, Any] = {
    "minimum_overall_log_effect": 0.05129329438755058,
    "exploratory_lower_bound_minimum": 0.0,
    "ode_stratum_median_minimum": 0.0,
    "pde_stratum_median_minimum": 0.0,
}

_RETAINED = Path("runs/manual-live/task2663-conformant-v1")
_FROZEN_PLAN = Path(
    "runs/manual-live/task2661-scientific-contract-recovery-plan-v1/"
    "scientific-contract-recovery-plan.json"
)
_AUTONOMOUS_PLAN = Path(
    "runs/manual-live/task2651-autonomous-recovery-plan-v1/autonomous-research-plan.json"
)
_DATA_ROOT = Path(
    "runs/manual-live/task259-mdbench-official-v1/data/prepared/processed-9fe483c64ad6"
)


def _passing_summary() -> dict[str, Any]:
    """An aggregate that clears every frozen threshold."""

    return {
        "overall_median_log_effect": 0.9,
        "bootstrap_lower": 0.4,
        "bootstrap_upper": 1.4,
        "ode_stratum_median": 0.8,
        "pde_stratum_median": 0.7,
    }


def _cell(
    *,
    candidate_id: str = "c1",
    system: str = "s1",
    status: str = "succeeded",
    nmse: float | None = 0.1,
    validation: float | None = None,
    method_kind: str = "candidate",
    stage: str = "full",
    data_type: str = "ode",
    seed: int = 101,
) -> OfficialCellResult:
    return OfficialCellResult(
        attempt_id=f"{stage}-{candidate_id}-{system}-{seed}",
        method_kind=method_kind,  # type: ignore[arg-type]
        candidate_id=candidate_id,
        stage=stage,  # type: ignore[arg-type]
        system_name=system,
        data_type=data_type,  # type: ignore[arg-type]
        condition="snr_20",
        seed=seed,
        status=status,  # type: ignore[arg-type]
        derivative_nmse=nmse,
        validation_nmse=validation,
        result_hash="a" * 64,
    )


def _record(candidate_id: str, *, approved: bool = True) -> OfficialCandidateRecord:
    return OfficialCandidateRecord(
        candidate_id=candidate_id,
        generation=1,
        interaction_id=f"gen-{candidate_id}",
        source_relative_path=f"candidates/{candidate_id}/candidate.py",
        source_sha256="b" * 64,
        static_review_approved=approved,
        implementation_summary="a model-authored equation-discovery method",
    )


def _identity() -> OfficialDevelopmentIdentity:
    payload: dict[str, Any] = {
        "schema_version": "official-development-identity-v1",
        "plan_hash": "c" * 64,
        "development_panel_hash": "d" * 64,
        "sealed_confirmation_panel_hash": "e" * 64,
        "runner_sha256": "f" * 64,
        "runtime_environment_hash": "0" * 64,
        "image_id": "sha256:" + "1" * 64,
        "data_root": "/data/root",
        "initial_candidate_count": 8,
        "pilot_system_count": 6,
        "full_system_count": 14,
        "conditions": ["clean", "snr_20"],
        "seeds": [101, 211, 307],
        "maximum_official_cells_total": 464,
        "numeric_payload_opened_during_freeze": False,
        "confirmation_identity_read_count": 0,
        "created_at": datetime(2026, 8, 3, tzinfo=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
    }
    payload["identity_hash"] = canonical_model_hash(payload)
    return OfficialDevelopmentIdentity.model_validate(payload)


def _budget(**overrides: Any) -> dict[str, Any]:
    budget = {
        "pilot_ode_system_count": 3,
        "pilot_pde_system_count": 3,
        "pilot_seed_count": 1,
        "full_finalist_count": 3,
        "maximum_seconds_per_cell": 300,
        "maximum_parallel_cells": 4,
    }
    budget.update(overrides)
    return budget


def _panel(*, ode: int = 10, pde: int = 4) -> dict[str, Any]:
    systems = [{"system_name": f"ode-{i}", "data_type": "ode"} for i in range(ode)]
    systems += [{"system_name": f"pde-{i}", "data_type": "pde"} for i in range(pde)]
    return {"systems": systems, "seeds": [101, 211, 307], "conditions": ["clean", "snr_20"]}


# --------------------------------------------------------------------------
# The frozen gate
# --------------------------------------------------------------------------


def test_every_check_passes_on_a_conformant_adjudication() -> None:
    checks = evaluate_frozen_gate(
        estimand=_ESTIMAND,
        summary=_passing_summary(),
        candidate_cells=[_cell()],
        baseline_results=[_cell(method_kind="baseline", stage="baseline")],
        remaining_budget={"candidate_cells": 10, "total_cells": 20},
    )
    assert checks == {
        "all_candidate_cells_succeeded": True,
        "all_baseline_cells_succeeded": True,
        "overall_median_at_least_minimum": True,
        "bootstrap_lower_above_zero": True,
        "ode_stratum_non_negative": True,
        "pde_stratum_non_negative": True,
        "budget_conformant": True,
    }
    assert frozen_gate_receipt(checks) is True


def test_a_failed_candidate_cell_fails_its_check() -> None:
    checks = evaluate_frozen_gate(
        estimand=_ESTIMAND,
        summary=_passing_summary(),
        candidate_cells=[_cell(), _cell(system="s2", status="failed", nmse=None)],
        baseline_results=[_cell(method_kind="baseline", stage="baseline")],
        remaining_budget={"total_cells": 1},
    )
    assert checks["all_candidate_cells_succeeded"] is False
    assert frozen_gate_receipt(checks) is False


def test_a_failed_baseline_cell_fails_its_check() -> None:
    """The frozen estimand carries all_domain_baseline_cells_must_succeed = True."""

    checks = evaluate_frozen_gate(
        estimand=_ESTIMAND,
        summary=_passing_summary(),
        candidate_cells=[_cell()],
        baseline_results=[
            _cell(method_kind="baseline", stage="baseline"),
            _cell(method_kind="baseline", stage="baseline", system="s2", status="failed"),
        ],
        remaining_budget={"total_cells": 1},
    )
    assert checks["all_baseline_cells_succeeded"] is False
    assert frozen_gate_receipt(checks) is False


def test_an_empty_arm_cannot_satisfy_a_must_succeed_check() -> None:
    """`all()` over zero cells is vacuously true; an arm that ran nothing must fail."""

    checks = evaluate_frozen_gate(
        estimand=_ESTIMAND,
        summary=_passing_summary(),
        candidate_cells=[],
        baseline_results=[],
        remaining_budget={"total_cells": 1},
    )
    assert checks["all_candidate_cells_succeeded"] is False
    assert checks["all_baseline_cells_succeeded"] is False


def test_absent_aggregates_fail_rather_than_pass() -> None:
    """No estimate is not evidence the estimand was met."""

    checks = evaluate_frozen_gate(
        estimand=_ESTIMAND,
        summary={
            "overall_median_log_effect": None,
            "bootstrap_lower": None,
            "ode_stratum_median": None,
            "pde_stratum_median": None,
        },
        candidate_cells=[_cell()],
        baseline_results=[_cell(method_kind="baseline", stage="baseline")],
        remaining_budget={"total_cells": 1},
    )
    assert checks["overall_median_at_least_minimum"] is False
    assert checks["bootstrap_lower_above_zero"] is False
    assert checks["ode_stratum_non_negative"] is False
    assert checks["pde_stratum_non_negative"] is False


def test_thresholds_come_from_the_frozen_estimand() -> None:
    """An effect just under the frozen minimum fails; the frozen minimum itself passes."""

    minimum = float(_ESTIMAND["minimum_overall_log_effect"])
    summary = _passing_summary()
    summary["overall_median_log_effect"] = minimum
    at_minimum = evaluate_frozen_gate(
        estimand=_ESTIMAND,
        summary=summary,
        candidate_cells=[_cell()],
        baseline_results=[_cell(method_kind="baseline", stage="baseline")],
        remaining_budget={"total_cells": 1},
    )
    assert at_minimum["overall_median_at_least_minimum"] is True

    summary["overall_median_log_effect"] = minimum - 1e-12
    just_under = evaluate_frozen_gate(
        estimand=_ESTIMAND,
        summary=summary,
        candidate_cells=[_cell()],
        baseline_results=[_cell(method_kind="baseline", stage="baseline")],
        remaining_budget={"total_cells": 1},
    )
    assert just_under["overall_median_at_least_minimum"] is False


def test_a_lower_bound_exactly_at_the_minimum_does_not_pass() -> None:
    """The frozen check is a strict exceedance of the exploratory lower bound."""

    summary = _passing_summary()
    summary["bootstrap_lower"] = float(_ESTIMAND["exploratory_lower_bound_minimum"])
    checks = evaluate_frozen_gate(
        estimand=_ESTIMAND,
        summary=summary,
        candidate_cells=[_cell()],
        baseline_results=[_cell(method_kind="baseline", stage="baseline")],
        remaining_budget={"total_cells": 1},
    )
    assert checks["bootstrap_lower_above_zero"] is False


def test_budget_non_conformance_blocks_a_receipt() -> None:
    """An overrun search is not a protocol-conformant search (P-20260802-066)."""

    checks = evaluate_frozen_gate(
        estimand=_ESTIMAND,
        summary=_passing_summary(),
        candidate_cells=[_cell()],
        baseline_results=[_cell(method_kind="baseline", stage="baseline")],
        remaining_budget={"candidate_cells": 5, "total_cells": -1},
    )
    assert checks["budget_conformant"] is False
    assert frozen_gate_receipt(checks) is False


def test_an_empty_gate_cannot_decide_a_receipt() -> None:
    with pytest.raises(OfficialLineageError, match="empty gate"):
        frozen_gate_receipt({})


# --------------------------------------------------------------------------
# The signed package
# --------------------------------------------------------------------------


def _write_package(
    tmp_path: Path, *, gate_checks: dict[str, bool], selected: str | None = "c1"
) -> Any:
    return write_official_development_search_package(
        identity=_identity(),
        candidates=[_record("c1")],
        cell_results=[_cell()],
        stages_executed=["full"],
        selected_candidate_id=selected,
        selection_basis="median validation NMSE over executed cells",
        system_effects=[],
        summary=_passing_summary(),
        estimand=_ESTIMAND,
        gate_checks=gate_checks,
        output_dir=tmp_path,
    )


def test_a_conformant_package_is_written_and_hash_verified(tmp_path: Path) -> None:
    package = _write_package(tmp_path, gate_checks={"a": True, "b": True})
    written = tmp_path / "official-development-search-package.json"
    assert written.is_file()
    assert package.search_freeze_receipt_issued is True
    payload = json.loads(written.read_text(encoding="utf-8"))
    assert payload["package_hash"] == package.package_hash
    assert payload["minimum_overall_log_effect"] == _ESTIMAND["minimum_overall_log_effect"]
    # The hash must cover the content, so any edit to the persisted bytes is detected.
    payload["overall_median_log_effect"] = 99.0
    with pytest.raises(OfficialDevelopmentSearchError, match="hash mismatch"):
        type(package).model_validate(payload)


def test_a_receipt_is_refused_when_any_check_failed(tmp_path: Path) -> None:
    """The critical case: a failed check and a receipt can never coexist."""

    package = _write_package(tmp_path, gate_checks={"a": True, "b": False})
    assert package.search_freeze_receipt_issued is False


def test_a_receipt_requires_a_selected_candidate(tmp_path: Path) -> None:
    with pytest.raises(OfficialDevelopmentSearchError, match="selected candidate"):
        _write_package(tmp_path, gate_checks={"a": True}, selected=None)


def test_a_package_cannot_be_written_from_an_unevaluated_gate(tmp_path: Path) -> None:
    with pytest.raises(OfficialLineageError, match="empty gate"):
        _write_package(tmp_path, gate_checks={})


# --------------------------------------------------------------------------
# Stage shape read from the frozen plan
# --------------------------------------------------------------------------


def test_pilot_breadth_is_read_from_the_frozen_plan() -> None:
    systems = select_pilot_systems(panel=_panel(), budget=_budget())
    assert [item["data_type"] for item in systems] == ["ode"] * 3 + ["pde"] * 3


def test_a_panel_too_small_for_the_frozen_pilot_is_refused() -> None:
    with pytest.raises(OfficialLineageError, match="frozen pilot breadth"):
        select_pilot_systems(panel=_panel(ode=1, pde=4), budget=_budget())


def test_pilot_breadth_disagreeing_with_the_frozen_identity_is_refused() -> None:
    """The retired script ran 4 pilot systems while its identity declared 6."""

    with pytest.raises(OfficialLineageError, match="contradicts the frozen identity"):
        _stage_shape(
            stage="pilot",
            panel=_panel(),
            budget=_budget(pilot_ode_system_count=2, pilot_pde_system_count=2),
            identity=_identity(),
        )


def test_pilot_uses_the_frozen_seed_count_and_full_uses_every_seed() -> None:
    _, pilot_seeds = _stage_shape(
        stage="pilot", panel=_panel(), budget=_budget(), identity=_identity()
    )
    full_systems, full_seeds = _stage_shape(
        stage="full", panel=_panel(), budget=_budget(), identity=_identity()
    )
    assert pilot_seeds == [101]
    assert full_seeds == [101, 211, 307]
    assert len(full_systems) == 14


# --------------------------------------------------------------------------
# Finalist ranking
# --------------------------------------------------------------------------


def test_finalists_are_the_best_median_validation_losses() -> None:
    candidates = [_record("c1"), _record("c2"), _record("c3"), _record("c4")]
    results = [
        _cell(candidate_id="c1", stage="pilot", validation=0.5),
        _cell(candidate_id="c2", stage="pilot", validation=0.1),
        _cell(candidate_id="c3", stage="pilot", validation=0.9),
        _cell(candidate_id="c4", stage="pilot", validation=0.3),
    ]
    chosen = rank_pilot_finalists(
        candidates=candidates, pilot_results=results, finalist_count=3
    )
    assert [item.candidate_id for item in chosen] == ["c2", "c4", "c1"]


def test_unapproved_and_unexecuted_candidates_cannot_be_finalists() -> None:
    candidates = [_record("c1", approved=False), _record("c2"), _record("c3")]
    results = [
        _cell(candidate_id="c1", stage="pilot", validation=0.01),
        _cell(candidate_id="c2", stage="pilot", validation=0.5),
        _cell(candidate_id="c3", stage="pilot", status="failed", nmse=None),
    ]
    chosen = rank_pilot_finalists(
        candidates=candidates, pilot_results=results, finalist_count=3
    )
    assert [item.candidate_id for item in chosen] == ["c2"]


def test_ties_break_deterministically_so_a_replay_selects_the_same_set() -> None:
    candidates = [_record("c2"), _record("c1")]
    results = [
        _cell(candidate_id="c1", stage="pilot", validation=0.4),
        _cell(candidate_id="c2", stage="pilot", validation=0.4),
    ]
    chosen = rank_pilot_finalists(
        candidates=candidates, pilot_results=results, finalist_count=1
    )
    assert [item.candidate_id for item in chosen] == ["c1"]


def test_the_declared_stage_sequence_matches_the_retired_script() -> None:
    assert LINEAGE_STAGES == (
        "plan",
        "approve",
        "generate",
        "pilot",
        "revise",
        "baseline",
        "full",
        "adjudicate",
    )


# --------------------------------------------------------------------------
# Numerical equivalence with the retired scratch driver
# --------------------------------------------------------------------------


@pytest.mark.skipif(
    not (_RETAINED / "cells" / "full-results.json").is_file(),
    reason="retained conformant lineage artifacts are not present in this checkout",
)
def test_adjudication_reproduces_the_retained_conformant_lineage(tmp_path: Path) -> None:
    """Re-evaluate the retained lineage and assert the numbers it recorded.

    This is the equivalence proof for moving the frozen gate out of `_lineage268.py`:
    the module must reproduce that lineage's adjudication exactly. The lineage is read
    read-only and the package is written to a temporary directory, so no retained
    artifact is mutated.
    """

    config = OfficialLineageConfig(
        lineage_id="task2663-conformant-v1",
        work_dir=_RETAINED,
        frozen_plan_path=_FROZEN_PLAN,
        autonomous_plan_path=_AUTONOMOUS_PLAN,
        data_root=_DATA_ROOT,
    )
    report = run_adjudicate_stage(config, package_output_dir=tmp_path)
    package = json.loads(
        (tmp_path / "official-development-search-package.json").read_text(encoding="utf-8")
    )

    assert package["selected_candidate_id"] == "official-03-r2"
    assert package["overall_median_log_effect"] == pytest.approx(-0.524076, abs=5e-7)
    assert package["bootstrap_lower"] == pytest.approx(-3.235713, abs=5e-7)
    assert package["bootstrap_upper"] == pytest.approx(1.804017, abs=5e-7)
    assert package["ode_stratum_median"] == pytest.approx(0.589509, abs=5e-7)
    assert package["pde_stratum_median"] == pytest.approx(-15.402305, abs=5e-7)
    assert package["search_freeze_receipt_issued"] is False
    assert report.search_freeze_receipt_issued is False

    selected = [
        item
        for item in package["cell_results"]
        if item["candidate_id"] == "official-03-r2" and item["stage"] == "full"
    ]
    assert len(selected) == 84
    assert sum(1 for item in selected if item["status"] == "succeeded") == 78

    # The two PDE systems whose baseline never produced a real loss stay excluded,
    # which is the correction `_verdict.txt` recorded only as prose.
    unpaired = [
        item["system_name"]
        for item in package["system_effects"]
        if not item["baseline_available"]
    ]
    assert sorted(unpaired) == ["heat_laser", "heat_soil_uniform_2d_p1"]

    # The retained lineage must not have been touched.
    assert not (_RETAINED / "official-development-search-package.json").exists()


# --------------------------------------------------------------------------
# Tasks 268.3 + 269.2: a new lineage must start with a provably clean ledger
# --------------------------------------------------------------------------


def _pinned_image_available() -> bool:
    """Report whether the pinned scientific image can be inspected.

    `freeze_lineage` fingerprints the pinned runtime, so it needs a running Docker
    daemon. The scientific dependencies live only in that image, so this test is
    skipped rather than failed when the daemon is absent.
    """

    try:
        completed = subprocess.run(
            ["docker", "image", "inspect", "autoresearch-mdbench:task260"],
            capture_output=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


@pytest.mark.skipif(
    not _pinned_image_available(),
    reason="pinned autoresearch-mdbench:task260 image is not inspectable here",
)
def test_freezing_a_lineage_that_already_spent_is_refused(tmp_path: Path) -> None:
    """A fresh lineage needs a fresh directory, or its spend is not clean.

    Freezing over an existing ledger would let a new lineage inherit the prior
    lineage's spend, which is how `P-20260802-066` overran the frozen budget.
    """

    from autoresearch.competition.official_spend_ledger import (
        OfficialSpendLedger,
        persist_ledger,
    )

    frozen_plan_hash = str(
        json.loads(_FROZEN_PLAN.read_text(encoding="utf-8"))["plan_hash"]
    )
    dirty = OfficialSpendLedger(
        lineage_id="task-dirty-v1",
        plan_hash=frozen_plan_hash,
        maximum_total_candidate_count=12,
        maximum_official_candidate_cells=380,
        maximum_official_cells_total=464,
        maximum_model_interactions=80,
        maximum_generations=2,
    ).record(stage="generate-gen1", candidate_count=8, model_interactions=8)
    persist_ledger(ledger=dirty, output_dir=tmp_path)

    config = OfficialLineageConfig(
        lineage_id="task-dirty-v1",
        work_dir=tmp_path,
        frozen_plan_path=_FROZEN_PLAN,
        autonomous_plan_path=_AUTONOMOUS_PLAN,
        data_root=_DATA_ROOT,
    )
    with pytest.raises(OfficialLineageError, match="not a new lineage"):
        freeze_lineage(config)
