"""Task 268.2: the system must observe and repair its own frozen-protocol contradiction.

Task `268.1` (`P-20260802-070`) proved the frozen Task `266.1` protocol is
currently unsatisfiable: the estimand requires every domain baseline cell to
succeed, yet `heat_laser` fails `6/6` and `heat_soil_uniform_2d_p1` fails `6/6`
under the frozen baseline policy. Neither fault is in our shape transport, so the
repair is a SCIENTIFIC decision and must originate inside the loop.

The guard under test is the fabricated-effect refusal. Forcing
`heat_soil_uniform_2d_p1` to complete would yield an ALL-ZERO baseline model whose
loss is the zero-null, so a candidate would trivially "beat" it. That is the
`P-20260802-063` and `P-20260802-065` pattern and must be rejected no matter how
well a proposal argues for it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from autoresearch.competition.frozen_protocol_contradiction import (
    ALL_ZERO_MODEL,
    FROZEN_PROTOCOL_CONTRADICTION,
    INSUFFICIENT_SAMPLES,
    FrozenProtocolContradictionError,
    FrozenProtocolRepairProposal,
    audit_repair_against_evidence,
    diagnose_frozen_protocol_contradiction,
    observe_frozen_protocol_contradiction,
)
from autoresearch.competition.manifest import canonical_model_hash

# The exact recorded failure signatures from the retained conformant cells.
HEAT_LASER_REASON = (
    "RuntimeError: every frozen sparse configuration failed: [\"{'basis_functions': "
    "'polynomial', 'optimizer_threshold': 0.1, 'poly_order': 2, 'alpha': 0.001, "
    "'derivative_order': 2}: index 3 is out of bounds for axis 0 with size 3\"]"
)
HEAT_SOIL_REASON = (
    "RuntimeError: every frozen sparse configuration failed: [\"{'basis_functions': "
    "'polynomial', 'optimizer_threshold': 0.01, 'poly_order': 2, 'alpha': 1e-06, "
    "'derivative_order': 2}: SympifyError: None\"]"
)


def _cell(
    *,
    system: str,
    status: str,
    data_type: str = "pde",
    reason: str | None = None,
    seed: int = 101,
    condition: str = "clean",
) -> dict[str, Any]:
    return {
        "attempt_id": f"baseline-operon_or_pdefind-{system}-{condition}-{seed}",
        "candidate_id": "operon_or_pdefind",
        "condition": condition,
        "data_type": data_type,
        "derivative_nmse": None if status != "succeeded" else 0.5,
        "failure_reason": reason,
        "method_kind": "baseline",
        "seed": seed,
        "stage": "baseline",
        "status": status,
        "system_name": system,
    }


def _baseline_results(tmp_path: Path, cells: list[dict[str, Any]]) -> Path:
    path = tmp_path / "baseline-results.json"
    path.write_text(
        json.dumps({"approved_research_plan_hash": "a" * 64, "results": cells}),
        encoding="utf-8",
    )
    return path


def _retained_shaped_results(tmp_path: Path) -> Path:
    """Mirror the retained evidence: 72 succeeded, 6 + 6 failed."""

    cells: list[dict[str, Any]] = []
    for index in range(72):
        cells.append(
            _cell(
                system=f"ode-system-{index // 6}",
                status="succeeded",
                data_type="ode",
                seed=101 + index,
            )
        )
    for index in range(6):
        cells.append(
            _cell(
                system="heat_laser",
                status="failed",
                reason=HEAT_LASER_REASON,
                seed=101 + index,
            )
        )
    for index in range(6):
        cells.append(
            _cell(
                system="heat_soil_uniform_2d_p1",
                status="failed",
                reason=HEAT_SOIL_REASON,
                seed=101 + index,
            )
        )
    return _baseline_results(tmp_path, cells)


# --------------------------------------------------------------------------
# Deterministic observation
# --------------------------------------------------------------------------


def test_observation_reproduces_the_retained_cell_counts(tmp_path: Path) -> None:
    path = _retained_shaped_results(tmp_path)

    observation = observe_frozen_protocol_contradiction(baseline_results_path=path)

    assert observation.observed_cell_count == 84
    assert observation.succeeded_cell_count == 72
    assert observation.failed_cell_count == 12
    assert {item.system_name for item in observation.failing_systems} == {
        "heat_laser",
        "heat_soil_uniform_2d_p1",
    }


def test_observation_states_the_contradiction_arithmetically(tmp_path: Path) -> None:
    """The frozen check is satisfiable if and only if nothing failed."""

    path = _retained_shaped_results(tmp_path)

    observation = observe_frozen_protocol_contradiction(baseline_results_path=path)

    assert observation.frozen_check_requires_all_cells_to_succeed is True
    assert observation.frozen_check_is_currently_satisfiable is False


def test_observation_classifies_both_mechanisms_from_the_signatures(
    tmp_path: Path,
) -> None:
    path = _retained_shaped_results(tmp_path)

    observation = observe_frozen_protocol_contradiction(baseline_results_path=path)
    mechanisms = {
        item.system_name: item.mechanism for item in observation.failing_systems
    }

    assert mechanisms["heat_laser"] == INSUFFICIENT_SAMPLES
    assert mechanisms["heat_soil_uniform_2d_p1"] == ALL_ZERO_MODEL


def test_observation_flags_only_the_all_zero_system(tmp_path: Path) -> None:
    """Only `heat_soil` would return a zero-null baseline if forced to complete."""

    path = _retained_shaped_results(tmp_path)

    observation = observe_frozen_protocol_contradiction(baseline_results_path=path)
    flags = {
        item.system_name: item.produces_all_zero_model
        for item in observation.failing_systems
    }

    assert flags["heat_soil_uniform_2d_p1"] is True
    assert flags["heat_laser"] is False


def test_observation_binds_the_retained_artifact_hash(tmp_path: Path) -> None:
    path = _retained_shaped_results(tmp_path)

    observation = observe_frozen_protocol_contradiction(baseline_results_path=path)

    assert len(observation.baseline_results_sha256) == 64
    assert len(observation.observation_hash) == 64


def test_observation_rejects_a_missing_artifact(tmp_path: Path) -> None:
    with pytest.raises(FrozenProtocolContradictionError, match="missing baseline"):
        observe_frozen_protocol_contradiction(
            baseline_results_path=tmp_path / "absent.json"
        )


def test_observation_refuses_a_fully_succeeding_panel(tmp_path: Path) -> None:
    """With no failure there is no contradiction, so the cycle must not run."""

    path = _baseline_results(
        tmp_path, [_cell(system="navier_stokes_cylinder", status="succeeded")]
    )

    with pytest.raises(FrozenProtocolContradictionError, match="no baseline cell failed"):
        observe_frozen_protocol_contradiction(baseline_results_path=path)


# --------------------------------------------------------------------------
# Deterministic diagnosis
# --------------------------------------------------------------------------


def test_diagnosis_names_the_contradiction_and_the_library_owner(
    tmp_path: Path,
) -> None:
    path = _retained_shaped_results(tmp_path)
    observation = observe_frozen_protocol_contradiction(baseline_results_path=path)

    diagnosis = diagnose_frozen_protocol_contradiction(observation)

    assert diagnosis.failure_kind == FROZEN_PROTOCOL_CONTRADICTION
    # Task 268.1 proved transport is faithful for both systems.
    assert diagnosis.fault_is_in_pinned_baseline_library is True
    assert diagnosis.fault_is_in_our_shape_transport is False


def test_diagnosis_isolates_the_fabricated_effect_risk(tmp_path: Path) -> None:
    path = _retained_shaped_results(tmp_path)
    observation = observe_frozen_protocol_contradiction(baseline_results_path=path)

    diagnosis = diagnose_frozen_protocol_contradiction(observation)

    assert diagnosis.systems_where_completion_would_fabricate_an_effect == (
        "heat_soil_uniform_2d_p1",
    )


def test_diagnosis_is_bound_to_its_observation(tmp_path: Path) -> None:
    path = _retained_shaped_results(tmp_path)
    observation = observe_frozen_protocol_contradiction(baseline_results_path=path)

    diagnosis = diagnose_frozen_protocol_contradiction(observation)

    assert diagnosis.parent_observation_hash == observation.observation_hash


# --------------------------------------------------------------------------
# Proposal coherence
# --------------------------------------------------------------------------


def _proposal_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "frozen-protocol-repair-proposal-v1",
        "parent_diagnosis_hash": "a" * 64,
        "contradiction_statement": (
            "The frozen estimand requires every domain baseline cell to succeed while "
            "the frozen baseline policy makes success impossible for two systems."
        ),
        "causal_hypothesis": (
            "The pinned baseline library cannot evaluate a three-sample axis at the "
            "frozen derivative order, and it cannot represent an all-zero model."
        ),
        "per_system_resolutions": (
            {
                "system_name": "heat_laser",
                "resolution_kind": (
                    "declare_frozen_protocol_unsatisfiable_and_require_new_lineage"
                ),
                "justification": (
                    "The differentiated axis physically carries three samples while the "
                    "frozen derivative order requires four, so no configuration in the "
                    "frozen grid can ever succeed on this system."
                ),
            },
            {
                "system_name": "heat_soil_uniform_2d_p1",
                "resolution_kind": (
                    "declare_frozen_protocol_unsatisfiable_and_require_new_lineage"
                ),
                "justification": (
                    "The frozen thresholds sit orders of magnitude above the largest "
                    "coefficient in this system, so the optimizer eliminates every term "
                    "and the resulting model cannot be represented."
                ),
            },
        ),
        "required_protocol_change": (
            "Record that the frozen protocol cannot be satisfied as written and carry "
            "a corrected baseline policy into a new preregistration lineage."
        ),
        "changes_frozen_numeric_grid": False,
        "weakens_baseline": False,
        "fabricated_effect_risk_analysis": (
            "Forcing a cell to complete while the baseline retains no terms would make "
            "the baseline loss equal to the zero-null, so any candidate would appear to "
            "win by a large margin that reflects no real scientific improvement."
        ),
        "falsification_conditions": (
            "A configuration inside the frozen grid is demonstrated that succeeds on "
            "the three-sample axis without changing any frozen numeric value.",
            "The pinned library is shown to represent an all-zero model cleanly, which "
            "would mean the reported contradiction was misdiagnosed.",
        ),
        "why_this_is_not_result_shopping": (
            "The chosen resolution cannot improve the measured effect because it adds "
            "no favourable comparison and instead blocks the receipt until repair."
        ),
        "authored_by_model": True,
        "interaction_id": "frozen-protocol-repair-test",
        "human_approval_recorded": False,
        "execution_authorized": False,
        "requires_new_preregistration_lineage": True,
    }
    payload.update(overrides)
    payload["proposal_hash"] = canonical_model_hash(payload)
    return payload


def test_a_coherent_proposal_validates() -> None:
    proposal = FrozenProtocolRepairProposal.model_validate(_proposal_payload())

    assert proposal.authored_by_model is True
    assert len(proposal.per_system_resolutions) == 2


def test_proposal_can_never_self_authorize() -> None:
    """A repair is a proposal; execution needs the human plan gate."""

    proposal = FrozenProtocolRepairProposal.model_validate(_proposal_payload())

    assert proposal.human_approval_recorded is False
    assert proposal.execution_authorized is False
    assert proposal.requires_new_preregistration_lineage is True


def test_proposal_admitting_a_frozen_grid_change_is_rejected() -> None:
    with pytest.raises(FrozenProtocolContradictionError, match="frozen numeric"):
        FrozenProtocolRepairProposal.model_validate(
            _proposal_payload(changes_frozen_numeric_grid=True)
        )


def test_proposal_admitting_a_weaker_baseline_is_rejected() -> None:
    with pytest.raises(FrozenProtocolContradictionError, match="gate violation"):
        FrozenProtocolRepairProposal.model_validate(
            _proposal_payload(weakens_baseline=True)
        )


def test_duplicate_falsification_conditions_are_rejected() -> None:
    duplicate = (
        "A configuration inside the frozen grid is demonstrated that succeeds on the "
        "three-sample axis without changing any frozen value.",
    ) * 2

    with pytest.raises(FrozenProtocolContradictionError, match="must be distinct"):
        FrozenProtocolRepairProposal.model_validate(
            _proposal_payload(falsification_conditions=duplicate)
        )


def test_numeric_fragment_prose_is_rejected() -> None:
    fragment = ",0.000172,> 0.01, 0.1, 1.72e-4, 3, 4, 84, 72, 12, 6, 6, 2, 201, 51"

    with pytest.raises(FrozenProtocolContradictionError, match="not substantive prose"):
        FrozenProtocolRepairProposal.model_validate(
            _proposal_payload(fabricated_effect_risk_analysis=fragment)
        )


def test_unsupported_resolution_kind_is_rejected() -> None:
    with pytest.raises(FrozenProtocolContradictionError, match="unsupported resolution"):
        FrozenProtocolRepairProposal.model_validate(
            _proposal_payload(
                per_system_resolutions=(
                    {
                        "system_name": "heat_laser",
                        "resolution_kind": "lower_the_threshold_until_it_passes",
                        "justification": (
                            "This would make the cell complete by relaxing the frozen "
                            "configuration, which the protocol forbids outright."
                        ),
                    },
                )
            )
        )


# --------------------------------------------------------------------------
# The guard that refuses the fabricated-effect trap
# --------------------------------------------------------------------------


def test_guard_accepts_a_proposal_that_avoids_the_zero_null(tmp_path: Path) -> None:
    path = _retained_shaped_results(tmp_path)
    observation = observe_frozen_protocol_contradiction(baseline_results_path=path)
    diagnosis = diagnose_frozen_protocol_contradiction(observation)
    proposal = FrozenProtocolRepairProposal.model_validate(
        _proposal_payload(parent_diagnosis_hash=diagnosis.diagnosis_hash)
    )

    audit = audit_repair_against_evidence(
        observation=observation, diagnosis=diagnosis, proposal=proposal
    )

    assert audit.guard_accepted is True
    assert "guard_verdict: accepted" in audit.findings


def test_guard_refuses_forcing_the_all_zero_system_to_complete(
    tmp_path: Path,
) -> None:
    """The core guard. This is the P-20260802-063 fabricated-effect pattern.

    Degrading the complexity failure would make the cell "succeed" with a baseline
    that retains no terms, so the candidate would trivially beat the zero-null.
    """

    path = _retained_shaped_results(tmp_path)
    observation = observe_frozen_protocol_contradiction(baseline_results_path=path)
    diagnosis = diagnose_frozen_protocol_contradiction(observation)
    proposal = FrozenProtocolRepairProposal.model_validate(
        _proposal_payload(
            parent_diagnosis_hash=diagnosis.diagnosis_hash,
            per_system_resolutions=(
                {
                    "system_name": "heat_laser",
                    "resolution_kind": (
                        "declare_frozen_protocol_unsatisfiable_and_require_new_lineage"
                    ),
                    "justification": (
                        "The differentiated axis carries three samples while the frozen "
                        "derivative order requires four, so success is impossible here."
                    ),
                },
                {
                    "system_name": "heat_soil_uniform_2d_p1",
                    "resolution_kind": "align_error_handling_with_reference_harness",
                    "justification": (
                        "The reference harness degrades a complexity failure instead of "
                        "discarding the fit, so aligning error handling would let this "
                        "cell complete and satisfy the frozen coverage check."
                    ),
                },
            ),
        )
    )

    audit = audit_repair_against_evidence(
        observation=observation, diagnosis=diagnosis, proposal=proposal
    )

    assert audit.guard_accepted is False
    assert any("fake positive effect" in finding for finding in audit.findings)


def test_guard_refuses_a_transport_claim_the_evidence_contradicts(
    tmp_path: Path,
) -> None:
    """Task 268.1 proved transport is faithful, so that route repairs nothing."""

    path = _retained_shaped_results(tmp_path)
    observation = observe_frozen_protocol_contradiction(baseline_results_path=path)
    diagnosis = diagnose_frozen_protocol_contradiction(observation)
    proposal = FrozenProtocolRepairProposal.model_validate(
        _proposal_payload(
            parent_diagnosis_hash=diagnosis.diagnosis_hash,
            per_system_resolutions=(
                {
                    "system_name": "heat_laser",
                    "resolution_kind": "repair_adapter_shape_transport",
                    "justification": (
                        "The payload axes may be transported in the wrong order, so "
                        "correcting the adapter could resolve the out-of-bounds index."
                    ),
                },
                {
                    "system_name": "heat_soil_uniform_2d_p1",
                    "resolution_kind": (
                        "declare_frozen_protocol_unsatisfiable_and_require_new_lineage"
                    ),
                    "justification": (
                        "The frozen thresholds exceed the largest coefficient by orders "
                        "of magnitude, so every term is eliminated on this system."
                    ),
                },
            ),
        )
    )

    audit = audit_repair_against_evidence(
        observation=observation, diagnosis=diagnosis, proposal=proposal
    )

    assert audit.guard_accepted is False
    assert any("no shape-transport defect" in finding for finding in audit.findings)


def test_guard_refuses_an_incomplete_proposal(tmp_path: Path) -> None:
    """Every failing system needs a resolution, or the contradiction survives."""

    path = _retained_shaped_results(tmp_path)
    observation = observe_frozen_protocol_contradiction(baseline_results_path=path)
    diagnosis = diagnose_frozen_protocol_contradiction(observation)
    proposal = FrozenProtocolRepairProposal.model_validate(
        _proposal_payload(
            parent_diagnosis_hash=diagnosis.diagnosis_hash,
            per_system_resolutions=(
                {
                    "system_name": "heat_laser",
                    "resolution_kind": (
                        "declare_frozen_protocol_unsatisfiable_and_require_new_lineage"
                    ),
                    "justification": (
                        "The differentiated axis carries three samples while the frozen "
                        "derivative order requires four, so success is impossible here."
                    ),
                },
            ),
        )
    )

    audit = audit_repair_against_evidence(
        observation=observation, diagnosis=diagnosis, proposal=proposal
    )

    assert audit.guard_accepted is False
    assert any("no resolution authored" in finding for finding in audit.findings)


def test_guard_is_bound_to_its_proposal_and_observation(tmp_path: Path) -> None:
    path = _retained_shaped_results(tmp_path)
    observation = observe_frozen_protocol_contradiction(baseline_results_path=path)
    diagnosis = diagnose_frozen_protocol_contradiction(observation)
    proposal = FrozenProtocolRepairProposal.model_validate(
        _proposal_payload(parent_diagnosis_hash=diagnosis.diagnosis_hash)
    )

    audit = audit_repair_against_evidence(
        observation=observation, diagnosis=diagnosis, proposal=proposal
    )

    assert audit.parent_proposal_hash == proposal.proposal_hash
    assert audit.parent_observation_hash == observation.observation_hash
