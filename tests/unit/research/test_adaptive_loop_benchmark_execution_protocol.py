from __future__ import annotations

import inspect
import json
from collections import Counter, defaultdict
from pathlib import Path

import pytest
from pydantic import ValidationError

from autoresearch.kernel.contracts import canonical_json
from autoresearch.research.adaptive_loop_benchmark import (
    AdaptiveLoopBenchmarkArm,
    AdaptiveLoopChallengeKind,
)
from autoresearch.research.adaptive_loop_benchmark_execution_protocol import (
    AdaptiveLoopBenchmarkBlindedCellManifest,
    AdaptiveLoopBenchmarkExecutionBundle,
    AdaptiveLoopBenchmarkExecutionProtocol,
    AdaptiveLoopBenchmarkExecutionProtocolError,
    AdaptiveLoopBenchmarkHiddenOracleManifest,
    AdaptiveLoopBenchmarkPublicScenario,
    AdaptiveLoopBenchmarkRunnerAssignmentManifest,
    build_adaptive_loop_benchmark_execution_bundle,
    build_adaptive_loop_benchmark_execution_protocol,
    write_adaptive_loop_benchmark_execution_protocol,
)

_PARENT_V1_HASH = "69a79baa68592fe244805af960a415d62c73f0d76347075fb76c342087f5e721"
_DESIGN_AUDIT_HASH = "ee21aeb74ed3632259f510a4f711e108bd71462a07818ec95629effdf019e4fe"
_RUNNER_SEED = 27132026
_PROHIBITED_SEED_TERMS = (
    "假设",
    "方法",
    "计划",
    "预期结果",
    "研究方案",
    "hypothesis",
    "method",
    "plan",
)
_PRIVATE_FIELD_NAMES = (
    "hidden_oracle",
    "oracle_hash",
    "required_terminal_tokens",
    "forbidden_terminal_tokens",
    "expected_terminal_state",
)


def _build() -> AdaptiveLoopBenchmarkExecutionBundle:
    return build_adaptive_loop_benchmark_execution_bundle(randomization_seed=_RUNNER_SEED)


def test_v3_protocol_freezes_sixty_independent_twelve_turn_chinese_scenarios() -> None:
    bundle = _build()
    protocol = bundle.protocol

    assert protocol.schema_version == "adaptive-loop-benchmark-execution-protocol-v3"
    assert protocol.parent_v1_protocol_hash == _PARENT_V1_HASH
    assert protocol.design_audit_hash == _DESIGN_AUDIT_HASH
    assert protocol.independent_scenario_count == 60
    assert protocol.independent_scenarios_per_challenge == 12
    assert protocol.model_draws_per_scenario_arm == 1
    assert protocol.confirmatory_cell_count == 240
    assert protocol.public_stimulus_turn_count == 12
    assert protocol.non_sovereign_recent_window_turns == 8
    assert len(protocol.public_scenarios) == 60
    assert Counter(scenario.challenge_kind for scenario in protocol.public_scenarios) == Counter(
        {kind: 12 for kind in AdaptiveLoopChallengeKind}
    )
    assert len({scenario.public_scenario_hash for scenario in protocol.public_scenarios}) == 60
    assert len({scenario.independence_key for scenario in protocol.public_scenarios}) == 60
    assert (
        len(
            {
                tuple(item.payload_cn for item in scenario.stimuli)
                for scenario in protocol.public_scenarios
            }
        )
        == 60
    )
    stimulus_hashes = [
        stimulus.stimulus_hash
        for scenario in protocol.public_scenarios
        for stimulus in scenario.stimuli
    ]
    assert len(stimulus_hashes) == 60 * 12
    assert len(set(stimulus_hashes)) == len(stimulus_hashes)
    for public in protocol.public_scenarios:
        assert any("\u3400" <= char <= "\u9fff" for char in public.objective_cn)
        assert any("\u3400" <= char <= "\u9fff" for char in public.scope_cn)
        assert all(term not in public.objective_cn.casefold() for term in _PROHIBITED_SEED_TERMS)
        assert all(term not in public.scope_cn.casefold() for term in _PROHIBITED_SEED_TERMS)
        assert public.content_is_seed_repeat is False
        assert public.contains_required_operator_sequence is False
        assert [item.turn_index for item in public.stimuli] == list(range(1, 13))
        assert [item.turn_index for item in public.stimuli if item.neutral_distractor] == list(
            range(4, 12)
        )
        assert public.stimuli[-1].kind.value == "terminal_request"
        assert all(item.injected_exactly_once for item in public.stimuli)
        assert all(item.injected_before_turn_action for item in public.stimuli)


def test_turn_twelve_mechanically_expires_early_evidence_from_recent_window() -> None:
    bundle = _build()
    public_by_id = {item.scenario_id: item for item in bundle.protocol.public_scenarios}

    for oracle in bundle.runner_only_scoring.oracles:
        public = public_by_id[oracle.scenario_id]
        turn_by_fact = {
            fact_id: stimulus.turn_index
            for stimulus in public.stimuli
            for fact_id in stimulus.public_fact_ids
        }
        scoring_fact_ids = set(oracle.required_public_fact_ids) | set(
            oracle.forbidden_as_current_fact_ids
        )
        scoring_turns = [turn_by_fact[fact_id] for fact_id in scoring_fact_ids]
        assert max(scoring_turns) == 3
        assert all(turn <= 3 for turn in scoring_turns)
        assert oracle.latest_scoring_relevant_turn_index == 3
        assert oracle.terminal_turn_index == 12
        assert oracle.non_sovereign_recent_window_turns == 8
        assert 12 - max(scoring_turns) > 8
        early_text = "\n".join(item.payload_cn for item in public.stimuli if item.turn_index <= 3)
        recent_and_terminal_text = "\n".join(
            item.payload_cn for item in public.stimuli if item.turn_index >= 4
        )
        for token in oracle.required_terminal_tokens + oracle.forbidden_terminal_tokens:
            assert token in early_text
            assert token not in recent_and_terminal_text

    old_four_turn_payload = bundle.protocol.public_scenarios[0].model_dump(mode="json")
    old_four_turn_payload["schema_version"] = "adaptive-loop-public-scenario-v3"
    old_four_turn_payload["terminal_turn_index"] = 4
    old_four_turn_payload["stimuli"] = [
        *old_four_turn_payload["stimuli"][:3],
        old_four_turn_payload["stimuli"][-1],
    ]
    old_four_turn_payload["stimuli"][-1]["turn_index"] = 4
    with pytest.raises(ValidationError):
        AdaptiveLoopBenchmarkPublicScenario.model_validate(old_four_turn_payload)


def test_public_protocol_and_blinded_schema_have_no_private_scoring_fields() -> None:
    bundle = _build()
    protocol_raw = canonical_json(bundle.protocol)
    blinded_raw = canonical_json(bundle.blinded_cells)
    protocol_decoded = json.loads(protocol_raw)
    blinded_decoded = json.loads(blinded_raw)
    consumer_schema_raw = "\n".join(
        json.dumps(model.model_json_schema(), ensure_ascii=False, sort_keys=True)
        for model in (
            AdaptiveLoopBenchmarkExecutionProtocol,
            AdaptiveLoopBenchmarkPublicScenario,
            AdaptiveLoopBenchmarkBlindedCellManifest,
        )
    )

    for field_name in _PRIVATE_FIELD_NAMES:
        assert not _contains_mapping_key(protocol_decoded, field_name)
        assert not _contains_mapping_key(blinded_decoded, field_name)
        assert f'"{field_name}"' not in protocol_raw
        assert f'"{field_name}"' not in blinded_raw
        assert f'"{field_name}"' not in consumer_schema_raw
    assert "oracle" not in protocol_raw.casefold()
    assert "oracle" not in blinded_raw.casefold()
    assert "oracle" not in consumer_schema_raw.casefold()
    assert "randomization_seed" not in protocol_raw
    assert "randomization_seed" not in blinded_raw
    assert not _contains_mapping_key(protocol_decoded, "arm")
    assert not _contains_mapping_key(blinded_decoded, "arm")
    for arm in AdaptiveLoopBenchmarkArm:
        assert arm.value not in blinded_raw
    assert bundle.protocol.private_scoring_data_absent is True
    assert bundle.protocol.controller_and_blinded_evaluator_schema_public_only is True


def test_runner_only_scoring_manifest_is_bound_and_reveal_barrier_is_closed() -> None:
    bundle = _build()
    scoring = bundle.runner_only_scoring

    assert scoring.schema_version == "adaptive-loop-hidden-oracle-manifest-v3"
    assert len(scoring.oracles) == 60
    assert scoring.runner_and_post_seal_evaluator_only is True
    assert scoring.controller_access_allowed is False
    assert scoring.blinded_evaluator_access_before_reveal_allowed is False
    assert scoring.reveal_allowed_only_after_all_cell_outputs_sealed is True
    assert scoring.reveal_barrier_initially_closed is True
    assert scoring.result_fields_absent is True
    assert scoring.scientific_superiority_established is False
    assert scoring.innovation_verified is False
    assert scoring.publication_authorized is False
    assert bundle.protocol.private_scoring_manifest_hash == (scoring.hidden_oracle_manifest_hash)
    assert bundle.runner_assignments.private_scoring_manifest_hash == (
        scoring.hidden_oracle_manifest_hash
    )


def test_blinded_manifest_has_no_assignment_or_private_reveal() -> None:
    bundle = _build()
    blinded = bundle.blinded_cells
    raw = canonical_json(blinded)
    decoded = json.loads(raw)

    assert len(blinded.cells) == 240
    assert blinded.scientific_superiority_established is False
    assert blinded.innovation_verified is False
    assert blinded.publication_authorized is False
    assert "randomization_seed" not in raw
    assert str(_RUNNER_SEED) not in raw
    assert not _contains_mapping_key(decoded, "arm")
    assert len({item.blinded_cell_id for item in blinded.cells}) == 240
    assert all(item.blinded_cell_id.startswith("cell-") for item in blinded.cells)
    assert all(item.model_draw_ordinal == 1 for item in blinded.cells)
    by_scenario: dict[str, list[int]] = defaultdict(list)
    for cell in blinded.cells:
        by_scenario[cell.scenario_id].append(cell.run_position)
    assert len(by_scenario) == 60
    assert all(sorted(positions) == [1, 2, 3, 4] for positions in by_scenario.values())
    seed_parameter = inspect.signature(build_adaptive_loop_benchmark_execution_bundle).parameters[
        "randomization_seed"
    ]
    assert seed_parameter.default is inspect.Parameter.empty


def test_runner_only_assignment_is_seeded_blocked_and_exactly_balanced() -> None:
    first = _build()
    repeated = _build()
    changed = build_adaptive_loop_benchmark_execution_bundle(randomization_seed=27132027)
    runner = first.runner_assignments

    assert runner == repeated.runner_assignments
    assert runner.runner_only is True
    assert runner.controller_access_allowed is False
    assert runner.blinded_evaluator_access_allowed is False
    assert runner.scientific_superiority_established is False
    assert runner.innovation_verified is False
    assert runner.publication_authorized is False
    assert len(runner.assignments) == 240
    assert runner.runner_assignment_manifest_hash != (
        changed.runner_assignments.runner_assignment_manifest_hash
    )
    assert first.protocol.public_scenario_panel_hash == (
        changed.protocol.public_scenario_panel_hash
    )
    assert first.runner_only_scoring == changed.runner_only_scoring
    for kind in AdaptiveLoopChallengeKind:
        items = [item for item in runner.assignments if item.challenge_kind == kind]
        scenarios = {item.scenario_id for item in items}
        assert len(scenarios) == 12
        sequence_by_scenario = {
            scenario_id: next(item.sequence_id for item in items if item.scenario_id == scenario_id)
            for scenario_id in scenarios
        }
        assert Counter(sequence_by_scenario.values()) == Counter(
            {f"balanced-sequence-{index}": 3 for index in range(1, 5)}
        )
        for arm in AdaptiveLoopBenchmarkArm:
            for position in range(1, 5):
                assert sum(item.arm == arm and item.run_position == position for item in items) == 3


def test_confirmatory_analysis_contract_is_exact_and_non_gameable() -> None:
    protocol = build_adaptive_loop_benchmark_execution_protocol(randomization_seed=_RUNNER_SEED)
    analysis = protocol.analysis

    assert analysis.primary_endpoint == "objectively_confirmed_terminal_success"
    assert analysis.primary_contrast == ("adaptive_sovereign_minus_adaptive_derived_only")
    assert analysis.a4_arm == AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN
    assert analysis.a3_arm == AdaptiveLoopBenchmarkArm.ADAPTIVE_DERIVED_ONLY
    assert analysis.primary_test == "two_sided_exact_mcnemar"
    assert analysis.primary_alpha == 0.05
    assert analysis.sesoi_risk_difference == 0.25
    assert analysis.holm_applies_to_primary is False
    assert analysis.holm_applies_only_to_secondary is True
    assert analysis.secondary_multiplicity_adjustment == "holm_step_down"
    assert analysis.runtime_failure_terminal_success is False
    assert analysis.missing_artifact_terminal_success is False
    assert analysis.zero_auditable_action_terminal_success is False
    assert analysis.failed_missing_or_zero_action_pairs_dropped is False
    assert analysis.failed_missing_or_zero_action_score == 0
    assert analysis.outcome_imputation_allowed is False
    assert analysis.parent_v1_cells_are_engineering_pilot_only is True
    assert analysis.parent_v1_observations_enter_confirmatory_test is False
    assert analysis.terminal_after_non_sovereign_recent_window_expiry is True
    assert analysis.private_scoring_revealed_only_after_all_cell_outputs_sealed is True
    assert analysis.confirmatory_superiority_claim_allowed is False
    assert analysis.innovation_verified is False
    assert analysis.publication_authorized is False
    assert protocol.execution_started is False
    assert protocol.result_cell_count == 0
    assert protocol.scientific_superiority_established is False
    assert protocol.innovation_verified is False
    assert protocol.publication_authorized is False


def test_old_v2_schema_and_all_nested_hash_tamper_fail_closed() -> None:
    bundle = _build()

    old_schema_payload = bundle.protocol.model_dump(mode="json")
    old_schema_payload["schema_version"] = "adaptive-loop-benchmark-execution-protocol-v2"
    with pytest.raises(ValidationError):
        AdaptiveLoopBenchmarkExecutionProtocol.model_validate(old_schema_payload)

    protocol_payload = bundle.protocol.model_dump(mode="json")
    protocol_payload["execution_protocol_id"] += "-tampered"
    with pytest.raises(ValidationError, match="execution protocol hash mismatch"):
        AdaptiveLoopBenchmarkExecutionProtocol.model_validate(protocol_payload)

    public_payload = bundle.protocol.model_dump(mode="json")
    public_payload["public_scenarios"][0]["objective_cn"] += "篡改"
    with pytest.raises(ValidationError, match="public scenario hash mismatch"):
        AdaptiveLoopBenchmarkExecutionProtocol.model_validate(public_payload)

    stimulus_payload = bundle.protocol.model_dump(mode="json")
    stimulus_payload["public_scenarios"][0]["stimuli"][4]["payload_cn"] += "篡改"
    with pytest.raises(ValidationError, match="public stimulus hash mismatch"):
        AdaptiveLoopBenchmarkExecutionProtocol.model_validate(stimulus_payload)

    scoring_payload = bundle.runner_only_scoring.model_dump(mode="json")
    scoring_payload["oracles"][0]["required_terminal_tokens"][0] += "篡改"
    with pytest.raises(ValidationError, match="machine oracle hash mismatch"):
        AdaptiveLoopBenchmarkHiddenOracleManifest.model_validate(scoring_payload)

    blinded_payload = bundle.blinded_cells.model_dump(mode="json")
    blinded_payload["parent_v1_protocol_hash"] = "0" * 64
    with pytest.raises(ValidationError, match="blinded cell manifest hash mismatch"):
        AdaptiveLoopBenchmarkBlindedCellManifest.model_validate(blinded_payload)

    runner_payload = bundle.runner_assignments.model_dump(mode="json")
    runner_payload["randomization_seed"] += 1
    with pytest.raises(ValidationError, match="runner assignment manifest hash mismatch"):
        AdaptiveLoopBenchmarkRunnerAssignmentManifest.model_validate(runner_payload)


def test_write_splits_public_and_runner_only_artifacts_and_is_write_once(
    tmp_path: Path,
) -> None:
    first = write_adaptive_loop_benchmark_execution_protocol(
        tmp_path,
        randomization_seed=_RUNNER_SEED,
    )
    repeated = write_adaptive_loop_benchmark_execution_protocol(
        tmp_path,
        randomization_seed=_RUNNER_SEED,
    )
    assert first == repeated

    protocol_path = tmp_path / "adaptive-loop-benchmark-execution-protocol-v3.json"
    blinded_path = tmp_path / "adaptive-loop-benchmark-blinded-cell-manifest-v3.json"
    runner_path = (
        tmp_path / "runner-only" / "adaptive-loop-benchmark-runner-assignment-manifest-v3.json"
    )
    scoring_path = (
        tmp_path / "runner-only" / "adaptive-loop-benchmark-hidden-oracle-manifest-v3.json"
    )
    assert (
        AdaptiveLoopBenchmarkExecutionProtocol.model_validate_json(protocol_path.read_bytes())
        == first.protocol
    )
    assert (
        AdaptiveLoopBenchmarkBlindedCellManifest.model_validate_json(blinded_path.read_bytes())
        == first.blinded_cells
    )
    assert (
        AdaptiveLoopBenchmarkRunnerAssignmentManifest.model_validate_json(runner_path.read_bytes())
        == first.runner_assignments
    )
    assert (
        AdaptiveLoopBenchmarkHiddenOracleManifest.model_validate_json(scoring_path.read_bytes())
        == first.runner_only_scoring
    )
    assert runner_path.parent.name == "runner-only"
    assert scoring_path.parent.name == "runner-only"
    for public_path in (protocol_path, blinded_path):
        public_raw = public_path.read_text(encoding="utf-8")
        public_decoded = json.loads(public_raw)
        assert "oracle" not in public_raw.casefold()
        assert not _contains_mapping_key(public_decoded, "arm")
        for field_name in _PRIVATE_FIELD_NAMES:
            assert not _contains_mapping_key(public_decoded, field_name)
    for path in (protocol_path, blinded_path, runner_path, scoring_path):
        decoded = json.loads(path.read_text(encoding="utf-8"))
        assert "cell_results" not in decoded
        assert "outcomes" not in decoded

    blinded_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(
        AdaptiveLoopBenchmarkExecutionProtocolError,
        match="immutable adaptive benchmark execution artifact changed",
    ):
        write_adaptive_loop_benchmark_execution_protocol(
            tmp_path,
            randomization_seed=_RUNNER_SEED,
        )


def _contains_mapping_key(value: object, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(_contains_mapping_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(_contains_mapping_key(item, key) for item in value)
    return False
