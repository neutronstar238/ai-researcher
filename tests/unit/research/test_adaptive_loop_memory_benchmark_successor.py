from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from autoresearch.kernel.contracts import canonical_sha256
from autoresearch.research.adaptive_loop_benchmark import AdaptiveLoopBenchmarkArm
from autoresearch.research.adaptive_loop_memory_benchmark_successor import (
    AdaptiveLoopDelayedMemorySuccessorBundle,
    AdaptiveLoopMemorySuccessorError,
    DelayedMemoryDomain,
    DelayedMemoryPowerSensitivityPoint,
    DelayedMemoryPublicPreregistration,
    DelayedMemoryRunnerAssignment,
    DelayedMemoryStimulusKind,
    audit_delayed_memory_terminal_working_state,
    build_adaptive_loop_delayed_memory_successor_bundle,
    release_adaptive_loop_delayed_memory_turn,
    write_adaptive_loop_delayed_memory_successor_preregistration,
)

_STIMULUS_SEED = (1 << 200) + 123_456_789
_ASSIGNMENT_SEED = (1 << 199) + 987_654_321
_ROW_PATTERN = re.compile(r"^记录(A[0-9A-F]{12})=([^；]+)；$")


@pytest.fixture(scope="module")
def bundle() -> AdaptiveLoopDelayedMemorySuccessorBundle:
    return build_adaptive_loop_delayed_memory_successor_bundle(
        stimulus_seed=_STIMULUS_SEED,
        assignment_seed=_ASSIGNMENT_SEED,
    )


def test_successor_freezes_independent_paired_design_without_claiming_results(
    bundle: AdaptiveLoopDelayedMemorySuccessorBundle,
) -> None:
    prereg = bundle.preregistration

    assert prereg.schema_version == "adaptive-loop-delayed-memory-preregistration-v1"
    assert prereg.superseded_v3_execution_protocol_hash == (
        "cfe042f2061f89e3d8a56d1a39fe65a056fd88ab11d7912165a926b67991d6a3"
    )
    assert len(prereg.scenario_commitments) == 140
    assert Counter(item.domain for item in prereg.scenario_commitments) == Counter(
        {domain: 28 for domain in DelayedMemoryDomain}
    )
    assert len({item.independence_key for item in prereg.scenario_commitments}) == 140
    assert len(bundle.blinded_cells.cells) == 560
    assert len(bundle.runner_private_assignments.assignments) == 560
    assert [item.arm for item in prereg.arm_contracts] == list(AdaptiveLoopBenchmarkArm)
    fixed, linear, derived, sovereign = prereg.arm_contracts
    assert len(fixed.fixed_operator_sequence) == 13
    assert len(linear.fixed_operator_sequence) == 13
    assert derived.fixed_operator_sequence == []
    assert sovereign.fixed_operator_sequence == []
    assert derived.non_intervention_configuration_hash == (
        sovereign.non_intervention_configuration_hash
    )
    assert derived.controller_sovereign_raw_recall_available is False
    assert derived.rebuildable_dreaming_available is False
    assert sovereign.controller_sovereign_raw_recall_available is True
    assert sovereign.rebuildable_dreaming_available is True
    assert prereg.maximum_main_model_requests_per_cell == 39
    assert prereg.fresh_model_session_and_raw_store_per_cell is True
    assert prereg.cross_cell_or_cross_arm_memory_allowed is False
    assert prereg.dreaming_operator_required_at_any_turn is False
    assert prereg.specific_skill_required_at_any_turn is False
    assert prereg.contains_cell_results is False
    assert prereg.execution_authorized is False
    assert prereg.scientific_result is False
    assert prereg.innovation_verified is False
    assert prereg.publication_authorized is False


def test_public_commitments_and_blinded_cells_contain_no_future_text_or_oracle(
    bundle: AdaptiveLoopDelayedMemorySuccessorBundle,
) -> None:
    prereg_payload = bundle.preregistration.model_dump(mode="json")
    blinded_payload = bundle.blinded_cells.model_dump(mode="json")
    first_oracle = bundle.runner_private_oracles.oracles[0]
    first_stimulus = bundle.runner_private_stimuli.scenarios[0].stimuli[0]
    public_raw = json.dumps(
        {"preregistration": prereg_payload, "blinded": blinded_payload},
        ensure_ascii=False,
        sort_keys=True,
    )

    assert not _contains_key(prereg_payload, "payload_cn")
    assert not _contains_key(prereg_payload, "queried_address")
    assert not _contains_key(prereg_payload, "expected_value_cn")
    assert not _contains_key(blinded_payload, "arm")
    assert not _contains_key(blinded_payload, "assignment_seed")
    assert first_oracle.queried_address not in public_raw
    assert first_oracle.expected_value_cn not in public_raw
    assert first_stimulus.payload_cn not in public_raw
    assert first_stimulus.payload_utf8_sha256 not in public_raw
    assert first_stimulus.release_nonce not in public_raw
    assert first_oracle.commitment_nonce not in public_raw
    assert "payload_cn" not in json.dumps(
        bundle.preregistration.model_json_schema(),
        sort_keys=True,
    )
    assert not _contains_key(bundle.blinded_cells.model_json_schema(), "arm")


def test_early_panel_exceeds_frozen_working_state_and_terminal_value_never_repeats(
    bundle: AdaptiveLoopDelayedMemorySuccessorBundle,
) -> None:
    contract = bundle.preregistration.working_state_contract
    scenario = bundle.runner_private_stimuli.scenarios[0]
    oracle = bundle.runner_private_oracles.oracles[0]
    parsed_rows: list[tuple[str, str]] = []

    for stimulus in scenario.stimuli[:3]:
        assert stimulus.stimulus_kind is DelayedMemoryStimulusKind.EARLY_RANDOM_PANEL
        assert len(stimulus.public_fact_ids) == 64
        assert len(stimulus.payload_cn.encode()) < 8_000
        rows = [line for line in stimulus.payload_cn.splitlines() if line.startswith("记录")]
        assert len(rows) == 64
        for row in rows:
            matched = _ROW_PATTERN.fullmatch(row)
            assert matched is not None
            parsed_rows.append((matched.group(1), matched.group(2)))

    assert len(parsed_rows) == 192
    assert len({address for address, _ in parsed_rows}) == 192
    assert len({value for _, value in parsed_rows}) == 192
    assert all(len(value) == 22 for _, value in parsed_rows)
    assert contract.nominal_early_value_information_bits == 25_344
    assert contract.maximum_non_sovereign_terminal_projection_bits == 16_384
    assert contract.early_information_exceeds_working_state_bits is True

    early_text = "\n".join(item.payload_cn for item in scenario.stimuli[:3])
    distractor_text = "\n".join(item.payload_cn for item in scenario.stimuli[3:11])
    late_text = "\n".join(item.payload_cn for item in scenario.stimuli[3:])
    assert early_text.count(oracle.expected_value_cn) == 1
    assert oracle.expected_value_cn not in late_text
    assert oracle.queried_address in early_text
    assert oracle.queried_address not in distractor_text
    assert oracle.queried_address in scenario.stimuli[11].payload_cn
    assert oracle.queried_address in scenario.stimuli[12].payload_cn


def test_terminal_cue_arrives_after_recent_window_and_leaves_one_recall_turn(
    bundle: AdaptiveLoopDelayedMemorySuccessorBundle,
) -> None:
    scenario = bundle.preregistration.scenario_commitments[0]
    kinds = [item.stimulus_kind for item in scenario.turn_commitments]

    assert [item.turn_index for item in scenario.turn_commitments] == list(range(1, 14))
    assert kinds[:3] == [DelayedMemoryStimulusKind.EARLY_RANDOM_PANEL] * 3
    assert kinds[3:11] == [DelayedMemoryStimulusKind.NEUTRAL_DISTRACTOR] * 8
    assert kinds[11] is DelayedMemoryStimulusKind.TERMINAL_ADDRESS_CUE
    assert kinds[12] is DelayedMemoryStimulusKind.SCORED_RESPONSE_REQUEST
    assert bundle.preregistration.working_state_contract.recent_event_window_turns < 12 - 3
    assert scenario.terminal_query_selection_unavailable_before_turn_twelve is True
    assert scenario.contains_required_operator_or_skill is False


def test_power_contract_uses_scenario_pairs_and_covers_worst_case_discordance(
    bundle: AdaptiveLoopDelayedMemorySuccessorBundle,
) -> None:
    analysis = bundle.preregistration.analysis_contract

    assert analysis.experimental_unit == "independent_synthetic_scenario"
    assert analysis.paired_scenario_count == 140
    assert analysis.total_cell_count == 560
    assert analysis.primary_test == "two_sided_exact_mcnemar"
    assert analysis.primary_endpoint == (
        "exact_terminal_value_with_complete_bounded_working_state_projection"
    )
    assert analysis.primary_alpha == 0.05
    assert analysis.target_power == 0.8
    assert analysis.sesoi_risk_difference == 0.25
    assert analysis.turns_or_model_calls_are_not_independent_replicates is True
    assert [item.total_discordance_probability for item in analysis.sensitivity_points] == [
        0.30,
        0.35,
        0.50,
        0.75,
        1.0,
    ]
    assert [item.exact_two_sided_mcnemar_power for item in analysis.sensitivity_points] == [
        0.999983933464,
        0.999695565895,
        0.989247207844,
        0.92235224294,
        0.809086452293,
    ]
    assert analysis.worst_case_exact_power >= analysis.target_power
    assert analysis.missing_failed_or_invalid_cell_scores_zero is True
    assert analysis.incomplete_pairs_are_not_dropped is True
    assert analysis.memory_benefit_claim_requires_actual_use_for_every_a4_only_win is True
    assert analysis.ordinary_working_memory_compression_is_permitted is True
    assert analysis.primary_success_requires_complete_working_state_projection is True
    assert analysis.generalization_limited_to_frozen_synthetic_generator_family is True


def test_arm_allocation_is_blocked_balanced_and_seeded(
    bundle: AdaptiveLoopDelayedMemorySuccessorBundle,
) -> None:
    prereg = bundle.preregistration
    assignments = bundle.runner_private_assignments.assignments
    by_scenario: dict[str, list[DelayedMemoryRunnerAssignment]] = {}
    for assignment in assignments:
        by_scenario.setdefault(assignment.scenario_id, []).append(assignment)

    assert Counter(item.arm for item in assignments) == Counter(
        {arm: 140 for arm in AdaptiveLoopBenchmarkArm}
    )
    assert all(
        {item.arm for item in scenario_assignments} == set(AdaptiveLoopBenchmarkArm)
        for scenario_assignments in by_scenario.values()
    )
    assert sorted(item.global_run_position for item in assignments) == list(range(1, 561))

    domain_by_scenario = {item.scenario_id: item.domain for item in prereg.scenario_commitments}
    for domain in DelayedMemoryDomain:
        sequence_by_scenario = {
            scenario_id: scenario_assignments[0].allocation_sequence_id
            for scenario_id, scenario_assignments in by_scenario.items()
            if domain_by_scenario[scenario_id] is domain
        }
        assert Counter(sequence_by_scenario.values()) == Counter(
            {f"latin-{index}": 7 for index in range(1, 5)}
        )

    changed = build_adaptive_loop_delayed_memory_successor_bundle(
        stimulus_seed=_STIMULUS_SEED,
        assignment_seed=_ASSIGNMENT_SEED + 2,
    )
    assert changed.preregistration == prereg
    assert changed.runner_private_stimuli == bundle.runner_private_stimuli
    assert changed.runner_private_oracles == bundle.runner_private_oracles
    assert changed.blinded_cells.manifest_hash != bundle.blinded_cells.manifest_hash
    assert changed.runner_private_assignments.manifest_hash != (
        bundle.runner_private_assignments.manifest_hash
    )


def test_per_turn_release_is_exact_but_does_not_self_claim_process_isolation(
    bundle: AdaptiveLoopDelayedMemorySuccessorBundle,
) -> None:
    manifest = bundle.runner_private_stimuli
    scenario_id = manifest.scenarios[0].scenario_id
    first = release_adaptive_loop_delayed_memory_turn(
        manifest,
        scenario_id=scenario_id,
        turn_index=1,
        completed_turn_indices=[],
    )
    terminal_cue = release_adaptive_loop_delayed_memory_turn(
        manifest,
        scenario_id=scenario_id,
        turn_index=12,
        completed_turn_indices=list(range(1, 12)),
    )

    assert first.stimulus == manifest.scenarios[0].stimuli[0]
    assert first.stimulus.release_nonce
    assert terminal_cue.stimulus.stimulus_kind is (DelayedMemoryStimulusKind.TERMINAL_ADDRESS_CUE)
    assert terminal_cue.future_stimulus_count_exposed == 0
    assert terminal_cue.commitment_sequence_verified is True
    assert terminal_cue.prior_turn_execution_completion_verified is False
    assert terminal_cue.proves_runner_process_cannot_read_future_stimuli is False
    with pytest.raises(AdaptiveLoopMemorySuccessorError, match="every exact predecessor"):
        release_adaptive_loop_delayed_memory_turn(
            manifest,
            scenario_id=scenario_id,
            turn_index=12,
            completed_turn_indices=list(range(1, 11)),
        )
    with pytest.raises(AdaptiveLoopMemorySuccessorError, match="scenario is absent"):
        release_adaptive_loop_delayed_memory_turn(
            manifest,
            scenario_id="dmem.absent.01",
            turn_index=1,
            completed_turn_indices=[],
        )


def test_working_state_audit_allows_bounded_compression_and_separates_sovereign_exposure(
    bundle: AdaptiveLoopDelayedMemorySuccessorBundle,
) -> None:
    oracle = bundle.runner_private_oracles.oracles[0]
    contract = bundle.preregistration.working_state_contract
    legitimate = audit_delayed_memory_terminal_working_state(
        oracle=oracle,
        contract=contract,
        non_sovereign_text_fragments=["普通工作状态只保留问题边界，不含随机校验值。"],
        sovereign_memory_text_fragments=[f"原始记录精确片段：{oracle.expected_value_cn}"],
    )
    bounded_exact_copy = audit_delayed_memory_terminal_working_state(
        oracle=oracle,
        contract=contract,
        non_sovereign_text_fragments=[f"此前已把答案复制为{oracle.expected_value_cn}"],
        sovereign_memory_text_fragments=[],
    )
    overflow = audit_delayed_memory_terminal_working_state(
        oracle=oracle,
        contract=contract,
        non_sovereign_text_fragments=["中" * 1_000],
        sovereign_memory_text_fragments=[],
    )

    assert legitimate.expected_value_present_in_sovereign_projection is True
    assert legitimate.expected_value_present_in_non_sovereign_projection is False
    assert legitimate.mechanical_fragment_budget_condition_satisfied is True
    assert legitimate.complete_terminal_prompt_projection_verified is False
    assert legitimate.terminal_task_score_eligible is False
    assert legitimate.does_not_score_terminal_answer is True
    assert legitimate.does_not_establish_causal_memory_benefit is True
    assert bounded_exact_copy.expected_value_present_in_non_sovereign_projection is True
    assert bounded_exact_copy.exact_value_presence_is_diagnostic_only is True
    assert bounded_exact_copy.mechanical_fragment_budget_condition_satisfied is True
    assert overflow.non_sovereign_projection_utf8_byte_count == 3_000
    assert overflow.non_sovereign_projection_within_budget is False
    assert overflow.mechanical_fragment_budget_condition_satisfied is False


def test_writer_physically_separates_public_and_private_and_is_write_once(
    tmp_path: Path,
) -> None:
    public_root = tmp_path / "public-preregistration"
    private_root = tmp_path / "runner-private"
    written = write_adaptive_loop_delayed_memory_successor_preregistration(
        public_output_dir=public_root,
        runner_private_output_dir=private_root,
        stimulus_seed=_STIMULUS_SEED,
        assignment_seed=_ASSIGNMENT_SEED,
    )

    assert sorted(path.name for path in public_root.iterdir()) == [
        "adaptive-loop-delayed-memory-blinded-cells-v1.json",
        "adaptive-loop-delayed-memory-preregistration-v1.json",
    ]
    assert sorted(path.name for path in private_root.iterdir()) == [
        "adaptive-loop-delayed-memory-hidden-oracles-v1.json",
        "adaptive-loop-delayed-memory-private-stimuli-v1.json",
        "adaptive-loop-delayed-memory-runner-assignments-v1.json",
    ]
    public_bytes = b"\n".join(path.read_bytes() for path in sorted(public_root.iterdir()))
    first_oracle = written.runner_private_oracles.oracles[0]
    assert first_oracle.expected_value_cn.encode() not in public_bytes
    assert first_oracle.queried_address.encode() not in public_bytes
    assert b'"payload_cn"' not in public_bytes
    assert b'"expected_value_cn"' not in public_bytes
    assert b'"queried_address"' not in public_bytes
    with pytest.raises(AdaptiveLoopMemorySuccessorError, match="already exists"):
        write_adaptive_loop_delayed_memory_successor_preregistration(
            public_output_dir=public_root,
            runner_private_output_dir=private_root,
            stimulus_seed=_STIMULUS_SEED,
            assignment_seed=_ASSIGNMENT_SEED,
        )
    with pytest.raises(AdaptiveLoopMemorySuccessorError, match="disjoint siblings"):
        write_adaptive_loop_delayed_memory_successor_preregistration(
            public_output_dir=tmp_path / "nested",
            runner_private_output_dir=tmp_path / "nested" / "private",
            stimulus_seed=_STIMULUS_SEED,
            assignment_seed=_ASSIGNMENT_SEED,
        )


def test_hash_tamper_numeric_recalculation_and_forcing_fail_closed(
    bundle: AdaptiveLoopDelayedMemorySuccessorBundle,
) -> None:
    prereg_payload = bundle.preregistration.model_dump(mode="json")
    prereg_payload["scenario_commitments"][0]["turn_commitments"][0]["payload_utf8_byte_count"] += 1
    with pytest.raises(ValidationError, match="commitment_hash mismatch"):
        DelayedMemoryPublicPreregistration.model_validate(prereg_payload)

    point_payload = bundle.preregistration.analysis_contract.sensitivity_points[0].model_dump(
        mode="json"
    )
    point_payload["exact_two_sided_mcnemar_power"] -= 0.1
    point_payload["point_hash"] = canonical_sha256(
        {key: value for key, value in point_payload.items() if key != "point_hash"}
    )
    with pytest.raises(ValidationError, match="power sensitivity result mismatch"):
        DelayedMemoryPowerSensitivityPoint.model_validate(point_payload)

    all_stimulus_text = "\n".join(
        stimulus.payload_cn
        for scenario in bundle.runner_private_stimuli.scenarios
        for stimulus in scenario.stimuli
    )
    assert "必须选择" not in all_stimulus_text
    assert "consolidate_dreaming" not in all_stimulus_text
    assert "agent-memory-evaluation" not in all_stimulus_text
    assert bundle.preregistration.dreaming_operator_required_at_any_turn is False
    assert bundle.preregistration.specific_skill_required_at_any_turn is False


def test_rehashed_blinded_cell_cannot_switch_scenario_commitment(
    bundle: AdaptiveLoopDelayedMemorySuccessorBundle,
) -> None:
    payload = bundle.model_dump(mode="json")
    cells = payload["blinded_cells"]["cells"]
    cells[0]["scenario_commitment_hash"] = payload["preregistration"]["scenario_commitments"][1][
        "commitment_hash"
    ]
    cells[0]["cell_hash"] = canonical_sha256(
        {key: value for key, value in cells[0].items() if key != "cell_hash"}
    )
    blinded = payload["blinded_cells"]
    blinded["manifest_hash"] = canonical_sha256(
        {key: value for key, value in blinded.items() if key != "manifest_hash"}
    )
    assignments = payload["runner_private_assignments"]
    assignments["blinded_cell_manifest_hash"] = blinded["manifest_hash"]
    assignments["manifest_hash"] = canonical_sha256(
        {key: value for key, value in assignments.items() if key != "manifest_hash"}
    )
    payload["bundle_hash"] = canonical_sha256(
        {key: value for key, value in payload.items() if key != "bundle_hash"}
    )

    with pytest.raises(ValidationError, match="blinded-cell scenario binding mismatch"):
        AdaptiveLoopDelayedMemorySuccessorBundle.model_validate(payload)


def test_secret_seed_and_write_preflight_fail_before_partial_publication(tmp_path: Path) -> None:
    with pytest.raises(AdaptiveLoopMemorySuccessorError, match="128-to-256-bit"):
        build_adaptive_loop_delayed_memory_successor_bundle(
            stimulus_seed=17,
            assignment_seed=_ASSIGNMENT_SEED,
        )
    with pytest.raises(AdaptiveLoopMemorySuccessorError, match="must differ"):
        build_adaptive_loop_delayed_memory_successor_bundle(
            stimulus_seed=_STIMULUS_SEED,
            assignment_seed=_STIMULUS_SEED,
        )

    public_root = tmp_path / "public"
    private_root = tmp_path / "private"
    private_root.mkdir()
    occupied = private_root / "adaptive-loop-delayed-memory-hidden-oracles-v1.json"
    occupied.write_text("occupied", encoding="utf-8")
    with pytest.raises(AdaptiveLoopMemorySuccessorError, match="already exists"):
        write_adaptive_loop_delayed_memory_successor_preregistration(
            public_output_dir=public_root,
            runner_private_output_dir=private_root,
            stimulus_seed=_STIMULUS_SEED,
            assignment_seed=_ASSIGNMENT_SEED,
        )
    assert not public_root.exists()


def _contains_key(value: object, target: str) -> bool:
    if isinstance(value, dict):
        return target in value or any(_contains_key(item, target) for item in value.values())
    if isinstance(value, list):
        return any(_contains_key(item, target) for item in value)
    return False
