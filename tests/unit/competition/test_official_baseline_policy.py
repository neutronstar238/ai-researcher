"""Tasks 268.3 + 269.2: the corrected baseline policy must not be able to fabricate.

The trap this pins is `P-20260802-063` / `P-20260802-065`: forcing a cell to
complete against an all-zero baseline model manufactures a large fake positive
effect, because any candidate trivially beats a zero-null. `heat_soil_uniform_2d_p1`
carries exactly that signature in the retained evidence.

These tests assert the policy CANNOT express that route, that an exclusion is only
valid when declared with its power cost, that the panel can only thin, and that
preregistration never opens a numeric payload. The final tests derive the policy
from the real retained `268.2` package and the real retained lineage, which is what
proves the per-system handling comes from the system's own authored resolutions
rather than from an agent.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from autoresearch.competition.official_baseline_policy import (
    EXCLUDED,
    PAIRED,
    BaselineImageBinding,
    BaselinePolicyError,
    PreregisteredBaselinePolicy,
    SystemBaselineHandling,
    assert_policy_precedes_numeric_payload,
    derive_carried_defects,
    load_baseline_policy,
    preregister_baseline_policy,
)

_RETAINED = Path("runs/manual-live/task2663-conformant-v1")
_RECHECK = Path("runs/manual-live/task2663-term-cap-recheck-v2")
_AUTHORED = Path(
    "runs/manual-live/task2682-frozen-protocol-self-correction-reasoning-v5/"
    "frozen-protocol-contradiction-package.json"
)
_FROZEN_PLAN = Path(
    "runs/manual-live/task2661-scientific-contract-recovery-plan-v1/"
    "scientific-contract-recovery-plan.json"
)

_HAVE_RETAINED = (
    _AUTHORED.is_file()
    and (_RECHECK / "cells" / "pilot-results.json").is_file()
    and (_RETAINED / "cells" / "baseline-results.json").is_file()
    and (_RETAINED / "cells" / "full-results.json").is_file()
    and _FROZEN_PLAN.is_file()
)

_requires_retained = pytest.mark.skipif(
    not _HAVE_RETAINED,
    reason="retained lineage and self-correction artifacts are not present",
)


# --------------------------------------------------------------------------
# The fabricated-effect guard
# --------------------------------------------------------------------------


def test_an_all_zero_baseline_system_cannot_be_scored_against() -> None:
    """THE guard. This combination must be unrepresentable, not merely discouraged."""

    with pytest.raises(BaselinePolicyError, match="fake positive effect"):
        SystemBaselineHandling(
            system_name="heat_soil_uniform_2d_p1",
            data_type="pde",
            handling=PAIRED,
            produces_all_zero_model=True,
        )


def test_an_all_zero_baseline_system_may_be_excluded_when_declared() -> None:
    handling = SystemBaselineHandling(
        system_name="heat_soil_uniform_2d_p1",
        data_type="pde",
        handling=EXCLUDED,
        produces_all_zero_model=True,
        declared_panel_change="removed from the paired panel for this lineage",
        power_cost="one fewer paired system and one fewer PDE stratum member",
    )
    assert handling.handling == EXCLUDED


def test_an_exclusion_without_a_declared_panel_change_is_refused() -> None:
    with pytest.raises(BaselinePolicyError, match="silent repair"):
        SystemBaselineHandling(
            system_name="heat_laser",
            data_type="pde",
            handling=EXCLUDED,
            power_cost="one fewer paired system",
        )


def test_an_exclusion_without_a_stated_power_cost_is_refused() -> None:
    with pytest.raises(BaselinePolicyError, match="power cost"):
        SystemBaselineHandling(
            system_name="heat_laser",
            data_type="pde",
            handling=EXCLUDED,
            declared_panel_change="removed from the paired panel",
        )


def test_an_unsupported_handling_kind_is_refused() -> None:
    with pytest.raises(BaselinePolicyError, match="unsupported baseline handling"):
        SystemBaselineHandling(
            system_name="heat_laser", data_type="pde", handling="force_completion"
        )


# --------------------------------------------------------------------------
# Image binding, following the 266.1.1 immutable-parent pattern
# --------------------------------------------------------------------------


def test_a_repinned_image_must_record_its_new_id() -> None:
    with pytest.raises(BaselinePolicyError, match="new image id"):
        BaselineImageBinding(
            parent_image_id="sha256:" + "1" * 64,
            parent_runner_sha256="a" * 64,
            child_runner_sha256="b" * 64,
            image_repinned=True,
        )


def test_a_policy_that_does_not_repin_keeps_the_parent_image_id() -> None:
    binding = BaselineImageBinding(
        parent_image_id="sha256:" + "1" * 64,
        parent_runner_sha256="a" * 64,
        child_runner_sha256="b" * 64,
        image_repinned=False,
    )
    assert binding.new_image_id is None
    with pytest.raises(BaselinePolicyError, match="remain the parent's"):
        BaselineImageBinding(
            parent_image_id="sha256:" + "1" * 64,
            parent_runner_sha256="a" * 64,
            child_runner_sha256="b" * 64,
            image_repinned=False,
            new_image_id="sha256:" + "9" * 64,
        )


# --------------------------------------------------------------------------
# Policy-level accounting
# --------------------------------------------------------------------------


def _policy_payload(**overrides: Any) -> dict[str, Any]:
    systems = [
        SystemBaselineHandling(
            system_name="ode-a", data_type="ode", handling=PAIRED
        ).model_dump(mode="json"),
        SystemBaselineHandling(
            system_name="heat_laser",
            data_type="pde",
            handling=EXCLUDED,
            declared_panel_change="removed from the paired panel",
            power_cost="one fewer paired system",
        ).model_dump(mode="json"),
    ]
    payload: dict[str, Any] = {
        "schema_version": "preregistered-baseline-policy-v1",
        "lineage_id": "task2693-new-lineage-v1",
        "parent_plan_hash": "c" * 64,
        "parent_lineage_id": "task2663-conformant-v1",
        "authored_decision_package_hash": "d" * 64,
        "authored_decision_package_path": "runs/x/package.json",
        "baseline_results_sha256": "e" * 64,
        "systems": systems,
        "excluded_system_names": ["heat_laser"],
        "paired_system_count": 1,
        "parent_paired_system_count": 2,
        "pde_stratum_size": 0,
        "parent_pde_stratum_size": 1,
        "power_cost_statement": (
            "the paired panel falls by one system and the PDE stratum loses one member"
        ),
        "image_binding": BaselineImageBinding(
            parent_image_id="sha256:" + "1" * 64,
            parent_runner_sha256="a" * 64,
            child_runner_sha256="b" * 64,
            image_repinned=False,
        ).model_dump(mode="json"),
        "carried_defects": [
            {
                "problem_id": "P-20260802-070",
                "origin": "system_authored",
                "source_artifact": "runs/x/package.json",
                "statement": "the frozen protocol cannot be satisfied as written",
            }
        ],
        "numeric_payload_opened_during_preregistration": False,
        "scores_against_all_zero_baseline": False,
        "is_evidence": False,
        "execution_authorized": False,
        "created_at": datetime(2026, 8, 4, tzinfo=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
    }
    payload.update(overrides)
    return payload


def _finalize(payload: dict[str, Any]) -> PreregisteredBaselinePolicy:
    from autoresearch.competition.manifest import canonical_model_hash

    payload["policy_hash"] = canonical_model_hash(payload)
    payload["output_path"] = "runs/x/preregistered-baseline-policy.json"
    return PreregisteredBaselinePolicy.model_validate(payload)


def test_a_consistent_policy_validates() -> None:
    policy = _finalize(_policy_payload())
    assert policy.paired_system_count == 1
    assert policy.excluded_system_names == ("heat_laser",)
    assert policy.is_evidence is False


def test_a_paired_count_that_contradicts_the_handling_is_refused() -> None:
    """An understated paired count still has to match the per-system handling."""

    with pytest.raises(BaselinePolicyError, match="contradicts"):
        _finalize(_policy_payload(paired_system_count=0))


def test_an_excluded_name_list_that_does_not_match_is_refused() -> None:
    with pytest.raises(BaselinePolicyError, match="does not match"):
        _finalize(_policy_payload(excluded_system_names=[]))


def test_a_policy_cannot_pair_more_systems_than_the_parent_panel() -> None:
    """Panel enlargement is not a baseline repair."""

    payload = _policy_payload(
        systems=[
            SystemBaselineHandling(
                system_name="ode-a", data_type="ode", handling=PAIRED
            ).model_dump(mode="json"),
            SystemBaselineHandling(
                system_name="ode-b", data_type="ode", handling=PAIRED
            ).model_dump(mode="json"),
        ],
        excluded_system_names=[],
        paired_system_count=2,
        parent_paired_system_count=1,
    )
    with pytest.raises(BaselinePolicyError, match="panel enlargement"):
        _finalize(payload)


def test_excluding_a_system_must_lower_the_paired_count() -> None:
    payload = _policy_payload(
        systems=[
            SystemBaselineHandling(
                system_name="ode-a", data_type="ode", handling=PAIRED
            ).model_dump(mode="json"),
            SystemBaselineHandling(
                system_name="ode-b", data_type="ode", handling=PAIRED
            ).model_dump(mode="json"),
            SystemBaselineHandling(
                system_name="heat_laser",
                data_type="pde",
                handling=EXCLUDED,
                declared_panel_change="removed",
                power_cost="one fewer",
            ).model_dump(mode="json"),
        ],
        paired_system_count=2,
        parent_paired_system_count=2,
    )
    with pytest.raises(BaselinePolicyError, match="power cost is not being reported"):
        _finalize(payload)


def test_the_policy_hash_covers_its_content() -> None:
    policy = _finalize(_policy_payload())
    payload = json.loads(policy.model_dump_json())
    # Edit a field the structural checks do not cross-validate, so the hash is the
    # only thing that can detect the tamper.
    payload["power_cost_statement"] = "the panel was not thinned at all, honestly"
    with pytest.raises(BaselinePolicyError, match="hash mismatch"):
        PreregisteredBaselinePolicy.model_validate(payload)


def test_a_missing_policy_is_refused_rather_than_defaulted(tmp_path: Path) -> None:
    with pytest.raises(BaselinePolicyError, match="frozen before any numeric payload"):
        load_baseline_policy(output_dir=tmp_path)


# --------------------------------------------------------------------------
# Derivation from the real retained evidence
# --------------------------------------------------------------------------


@_requires_retained
def test_carried_defects_come_from_the_system_not_from_an_agent() -> None:
    defects = derive_carried_defects(
        authored_decision_package_path=_AUTHORED,
        zero_term_evidence_root=_RECHECK,
        prior_full_results_path=_RETAINED / "cells" / "full-results.json",
    )
    by_id = {item.problem_id: item for item in defects}
    assert sorted(by_id) == ["P-20260802-068", "P-20260802-070"]

    # The frozen-protocol statement must be the model's OWN authored text, verbatim.
    package = json.loads(_AUTHORED.read_text(encoding="utf-8"))
    authored = package["proposal"]["contradiction_statement"]
    assert by_id["P-20260802-070"].origin == "system_authored"
    assert by_id["P-20260802-070"].statement == authored

    # The zero-term statement is arithmetic over retained cells.
    assert by_id["P-20260802-068"].origin == "deterministic_derivation"
    assert "reaction_diffusion_cylinder" in by_id["P-20260802-068"].statement


@_requires_retained
def test_the_policy_is_derived_from_the_retained_evidence(tmp_path: Path) -> None:
    """Both previously failing systems must be named and handled explicitly."""

    policy = preregister_baseline_policy(
        lineage_id="task2693-test-lineage-v1",
        parent_lineage_id="task2663-conformant-v1",
        frozen_plan_path=_FROZEN_PLAN,
        authored_decision_package_path=_AUTHORED,
        parent_identity_path=_RETAINED / "official-development-identity.json",
        prior_baseline_results_path=_RETAINED / "cells" / "baseline-results.json",
        prior_full_results_path=_RETAINED / "cells" / "full-results.json",
        zero_term_evidence_root=_RECHECK,
        child_runner_sha256="b" * 64,
        output_dir=tmp_path,
    )

    assert policy.excluded_system_names == (
        "heat_laser",
        "heat_soil_uniform_2d_p1",
    )
    # 14 retained systems, 2 excluded, so 12 pair and the PDE stratum falls to 2.
    assert policy.parent_paired_system_count == 14
    assert policy.paired_system_count == 12
    assert policy.parent_pde_stratum_size == 4
    assert policy.pde_stratum_size == 2

    handling = {item.system_name: item for item in policy.systems}
    # The all-zero system is the one that must never be scored against.
    assert handling["heat_soil_uniform_2d_p1"].produces_all_zero_model is True
    assert handling["heat_laser"].produces_all_zero_model is False
    for name in policy.excluded_system_names:
        assert handling[name].handling == EXCLUDED
        assert handling[name].declared_panel_change
        assert handling[name].power_cost
        # Each exclusion carries the SYSTEM's own authored resolution.
        assert (
            handling[name].system_authored_resolution_kind
            == "declare_frozen_protocol_unsatisfiable_and_require_new_lineage"
        )
        assert len(handling[name].system_authored_justification or "") > 40

    assert policy.numeric_payload_opened_during_preregistration is False
    assert policy.scores_against_all_zero_baseline is False
    assert policy.is_evidence is False
    assert policy.execution_authorized is False
    # The written artifact is the thing whose hash was verified.
    assert load_baseline_policy(output_dir=tmp_path).policy_hash == policy.policy_hash


@_requires_retained
def test_the_policy_binds_the_immutable_parent(tmp_path: Path) -> None:
    frozen = json.loads(_FROZEN_PLAN.read_text(encoding="utf-8"))
    policy = preregister_baseline_policy(
        lineage_id="task2693-test-lineage-v1",
        parent_lineage_id="task2663-conformant-v1",
        frozen_plan_path=_FROZEN_PLAN,
        authored_decision_package_path=_AUTHORED,
        parent_identity_path=_RETAINED / "official-development-identity.json",
        prior_baseline_results_path=_RETAINED / "cells" / "baseline-results.json",
        prior_full_results_path=_RETAINED / "cells" / "full-results.json",
        zero_term_evidence_root=_RECHECK,
        child_runner_sha256="b" * 64,
        output_dir=tmp_path,
    )
    assert policy.parent_plan_hash == frozen["plan_hash"]
    parent_identity = json.loads(
        (_RETAINED / "official-development-identity.json").read_text(encoding="utf-8")
    )
    assert policy.image_binding.parent_image_id == parent_identity["image_id"]
    assert policy.image_binding.parent_runner_sha256 == parent_identity["runner_sha256"]
    assert policy.image_binding.image_repinned is False
    package = json.loads(_AUTHORED.read_text(encoding="utf-8"))
    assert policy.authored_decision_package_hash == package["package_hash"]


# --------------------------------------------------------------------------
# The ordering proof: policy frozen BEFORE any numeric payload was available
# --------------------------------------------------------------------------


def _write_policy(tmp_path: Path) -> None:
    """Persist a minimal valid policy so only ordering is under test."""

    policy = _finalize(_policy_payload())
    (tmp_path / "preregistered-baseline-policy.json").write_text(
        policy.model_dump_json(indent=2), encoding="utf-8"
    )


def test_a_policy_written_before_the_numbers_is_accepted(tmp_path: Path) -> None:
    _write_policy(tmp_path)
    # The numeric payload appears AFTER the policy, which is the honest ordering.
    cell = tmp_path / "cells" / "full" / "cell-0"
    cell.mkdir(parents=True)
    time.sleep(0.01)
    (cell / "metrics.json").write_text('{"derivative_nmse": 0.5}', encoding="utf-8")

    policy = assert_policy_precedes_numeric_payload(output_dir=tmp_path)
    assert policy.numeric_payload_opened_during_preregistration is False


def test_a_policy_written_after_the_numbers_is_refused(tmp_path: Path) -> None:
    """THE ordering guard. A policy chosen once the numbers are visible is not
    preregistered, however truthfully it labels itself."""

    cell = tmp_path / "cells" / "full" / "cell-0"
    cell.mkdir(parents=True)
    (cell / "metrics.json").write_text('{"derivative_nmse": 0.5}', encoding="utf-8")
    time.sleep(0.01)
    _write_policy(tmp_path)

    with pytest.raises(BaselinePolicyError, match="not frozen before the numbers"):
        assert_policy_precedes_numeric_payload(output_dir=tmp_path)


def test_cell_status_files_do_not_count_as_a_numeric_payload(tmp_path: Path) -> None:
    """Preregistration is allowed to read cell status and failure strings.

    If these counted, deriving the policy from retained evidence would be
    self-forbidding, which would make the guard useless rather than strict.
    """

    cell = tmp_path / "cells" / "baseline" / "cell-0"
    cell.mkdir(parents=True)
    (cell / "result.json").write_text('{"status": "failed"}', encoding="utf-8")
    (cell / "spec.json").write_text('{"attempt": {}}', encoding="utf-8")
    time.sleep(0.01)
    _write_policy(tmp_path)

    assert assert_policy_precedes_numeric_payload(output_dir=tmp_path) is not None


# --------------------------------------------------------------------------
# Re-pinning the image under the 266.1.1 immutable-parent pattern
# --------------------------------------------------------------------------


@_requires_retained
def test_repinning_binds_all_four_quantities_and_leaves_the_parent_immutable(
    tmp_path: Path,
) -> None:
    """A re-pinned image must bind parent image, parent runner, child runner, and the
    new image id, so the erratum is traceable to the exact parent it corrects."""

    parent_identity_path = _RETAINED / "official-development-identity.json"
    before = parent_identity_path.read_bytes()
    new_image = "sha256:" + "7" * 64

    policy = preregister_baseline_policy(
        lineage_id="task2693-test-lineage-v1",
        parent_lineage_id="task2663-conformant-v1",
        frozen_plan_path=_FROZEN_PLAN,
        authored_decision_package_path=_AUTHORED,
        parent_identity_path=parent_identity_path,
        prior_baseline_results_path=_RETAINED / "cells" / "baseline-results.json",
        prior_full_results_path=_RETAINED / "cells" / "full-results.json",
        zero_term_evidence_root=_RECHECK,
        child_runner_sha256="b" * 64,
        output_dir=tmp_path,
        repinned_image_id=new_image,
    )

    parent_identity = json.loads(before.decode("utf-8"))
    binding = policy.image_binding
    assert binding.image_repinned is True
    assert binding.new_image_id == new_image
    # All four quantities, so parent and child are bound on the same axes.
    assert binding.parent_image_id == parent_identity["image_id"]
    assert binding.parent_runner_sha256 == parent_identity["runner_sha256"]
    assert binding.child_runner_sha256 == "b" * 64
    # The child re-pins, so it must NOT silently inherit the parent's image.
    assert binding.new_image_id != binding.parent_image_id

    # The immutable parent must be byte-identical after the child is written.
    assert parent_identity_path.read_bytes() == before


@_requires_retained
def test_both_previously_failing_systems_are_named_explicitly(tmp_path: Path) -> None:
    """The policy must name `heat_laser` AND `heat_soil_uniform_2d_p1`.

    A policy that repaired only one of them would leave the frozen
    `all_domain_baseline_cells_must_succeed` gate just as unsatisfiable.
    """

    policy = preregister_baseline_policy(
        lineage_id="task2693-test-lineage-v1",
        parent_lineage_id="task2663-conformant-v1",
        frozen_plan_path=_FROZEN_PLAN,
        authored_decision_package_path=_AUTHORED,
        parent_identity_path=_RETAINED / "official-development-identity.json",
        prior_baseline_results_path=_RETAINED / "cells" / "baseline-results.json",
        prior_full_results_path=_RETAINED / "cells" / "full-results.json",
        zero_term_evidence_root=_RECHECK,
        child_runner_sha256="b" * 64,
        output_dir=tmp_path,
    )

    named = {item.system_name for item in policy.systems}
    assert {"heat_laser", "heat_soil_uniform_2d_p1"} <= named
    assert "heat_laser" in policy.power_cost_statement
    assert "heat_soil_uniform_2d_p1" in policy.power_cost_statement
    # And both carried defects are present, so the plan can state both repairs.
    assert {item.problem_id for item in policy.carried_defects} == {
        "P-20260802-070",
        "P-20260802-068",
    }
