from __future__ import annotations

import ast
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from autoresearch.kernel.contracts import canonical_sha256
from autoresearch.knowledge.raw_memory import RawMemoryCapture, RawMemoryStore
from autoresearch.llm.client import LLMJsonCompletionResult
from autoresearch.research import adaptive_loop_benchmark_context as context_module
from autoresearch.research.adaptive_loop_benchmark_context import (
    AdaptiveLoopBenchmarkContextError,
    AdaptiveLoopBenchmarkPublicContextAdapter,
)
from autoresearch.research.adaptive_loop_benchmark_execution_protocol import (
    AdaptiveLoopBenchmarkBlindedCell,
    AdaptiveLoopBenchmarkExecutionBundle,
    AdaptiveLoopBenchmarkPublicScenario,
    build_adaptive_loop_benchmark_execution_bundle,
)
from autoresearch.research.adaptive_sovereign_loop import (
    AdaptiveExternalTurnContext,
    AdaptiveLoopPolicy,
    AdaptiveLoopRunStatus,
    AdaptiveResearchLoopSnapshot,
    AdaptiveResearchSeed,
    ExternalResearchFeedback,
    ModelResearchActionDraft,
    ResearchLoopZone,
    ResearchOperator,
    build_adaptive_research_messages,
    create_adaptive_research_seed,
    initialize_adaptive_research_loop,
    run_adaptive_research_loop,
)

_PRIVATE_FIELD_NAMES = {
    "arm",
    "expected_terminal_state",
    "hidden_oracle",
    "machine_oracle",
    "ordered_arms",
}
_PRIVATE_VALUE_MARKERS = (
    "oracle",
    "required_",
    "forbidden_",
    "expected_terminal",
    "ordered_arms",
    "arm_assignment",
    "fixed_pipeline",
    "linear_model_loop",
    "adaptive_derived_memory",
    "adaptive_sovereign_memory",
)
_REASONING = (
    "我先核对本轮公开环境刺激、此前外部反馈和剩余预算，再从可用算子中自主选择下一动作。"
    "公开刺激只提供环境事实，不指定科研结论、固定动作或评分答案；当前动作仍是未验证探索。"
    "如果负反馈否定当前路径，我应改变策略而不是循环确认；如果证据不足，我也不能声称创新或发表。"
) * 2


@pytest.fixture(scope="module")
def bundle() -> AdaptiveLoopBenchmarkExecutionBundle:
    return build_adaptive_loop_benchmark_execution_bundle(randomization_seed=27_132_026)


def _scenario_and_cell(
    bundle: AdaptiveLoopBenchmarkExecutionBundle,
    *,
    scenario_index: int = 0,
    run_position: int = 1,
) -> tuple[AdaptiveLoopBenchmarkPublicScenario, AdaptiveLoopBenchmarkBlindedCell]:
    scenario = bundle.protocol.public_scenarios[scenario_index]
    cell = next(
        item
        for item in bundle.blinded_cells.cells
        if item.scenario_id == scenario.scenario_id and item.run_position == run_position
    )
    return scenario, cell


def _loop_inputs(
    tmp_path: Path,
    scenario: AdaptiveLoopBenchmarkPublicScenario,
    *,
    suffix: str = "one",
) -> tuple[RawMemoryStore, AdaptiveResearchSeed, AdaptiveResearchLoopSnapshot]:
    store = RawMemoryStore(tmp_path / f"vault-{suffix}")
    seed = create_adaptive_research_seed(
        loop_id=f"benchmark-loop-{suffix}",
        project_id=f"benchmark_project_{suffix}",
        objective_cn=scenario.objective_cn,
        scope_cn=scenario.scope_cn,
        raw_memory_store=store,
    )
    snapshot = initialize_adaptive_research_loop(
        seed=seed,
        policy=AdaptiveLoopPolicy(
            policy_id="adaptive-benchmark-context-test",
            max_steps=12,
            max_model_calls=12,
            max_external_actions=0,
            max_temporary_agents=0,
        ),
        raw_memory_store=store,
    )
    return store, seed, snapshot


def _assert_no_private_scoring(value: Any, *, path: str = "output") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).casefold()
            if normalized == "contains_required_operator":
                assert item is False, f"{path}.{key} must be the inherited false safety flag"
            else:
                assert normalized not in _PRIVATE_FIELD_NAMES
                assert not normalized.startswith(("oracle", "required_", "forbidden_", "arm_"))
                assert not normalized.endswith(("_oracle", "_arm"))
            _assert_no_private_scoring(item, path=f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for index, item in enumerate(value):
            _assert_no_private_scoring(item, path=f"{path}[{index}]")
        return
    if isinstance(value, str):
        folded = value.casefold()
        assert not any(marker in folded for marker in _PRIVATE_VALUE_MARKERS), path


def _external_context_messages(
    messages: Sequence[Mapping[Any, str]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for message in messages:
        if message["role"] != "user":
            continue
        payload = json.loads(message["content"])
        if payload.get("context_kind") == "adaptive_external_turn_context":
            result.append(payload)
    return result


def test_one_current_public_stimulus_is_captured_before_content_addressed_context(
    tmp_path: Path,
    bundle: AdaptiveLoopBenchmarkExecutionBundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario, cell = _scenario_and_cell(bundle)
    store, seed, snapshot = _loop_inputs(tmp_path, scenario)
    order: list[str] = []
    original_capture = store.capture_text
    original_create = AdaptiveExternalTurnContext.create

    def capture_text(text: str, **kwargs: Any) -> RawMemoryCapture:
        order.append("capture_text")
        return original_capture(text, **kwargs)

    def create_context(**values: Any) -> AdaptiveExternalTurnContext:
        assert order == ["capture_text"]
        binding = values["raw_binding"]
        store.load_record(binding.record_relative_path, project_id=seed.project_id)
        order.append("create_context")
        return original_create(**values)

    monkeypatch.setattr(store, "capture_text", capture_text)
    monkeypatch.setattr(context_module.AdaptiveExternalTurnContext, "create", create_context)
    adapter = AdaptiveLoopBenchmarkPublicContextAdapter(
        public_scenario=scenario,
        blinded_cell=cell,
        raw_memory_store=store,
    )

    contexts = adapter.contexts_for_turn(
        seed=seed,
        snapshot=snapshot,
        branch=snapshot.branches[0],
    )

    assert order == ["capture_text", "create_context"]
    assert len(contexts) == 1
    context = contexts[0]
    stimulus = scenario.stimuli[0]
    identity_hash = canonical_sha256(
        {
            "schema_version": "adaptive-loop-benchmark-public-context-binding-v1",
            "blinded_cell_id": cell.blinded_cell_id,
            "scenario_id": scenario.scenario_id,
            "public_scenario_hash": scenario.public_scenario_hash,
            "stimulus_id": stimulus.stimulus_id,
            "turn_index": stimulus.turn_index,
            "stimulus_hash": stimulus.stimulus_hash,
            "loop_id": seed.loop_id,
            "project_id": seed.project_id,
        }
    )
    expected_id = f"adaptive-benchmark-context-{identity_hash}"
    assert context.context_id == expected_id
    assert context.source_ref == (
        f"adaptive-loop:{seed.loop_id}:step:1:external-context:{expected_id}"
    )
    assert context.content_cn == stimulus.payload_cn
    assert context.content_sha256 == hashlib.sha256(stimulus.payload_cn.encode("utf-8")).hexdigest()
    assert all(item.payload_cn not in context.content_cn for item in scenario.stimuli[1:])
    capture = store.load_record(
        context.raw_binding.record_relative_path,
        project_id=seed.project_id,
    )
    assert capture.blob_path.read_bytes() == stimulus.payload_cn.encode("utf-8")
    assert capture.record.envelope.source_ref == context.source_ref
    _assert_no_private_scoring(context.model_dump(mode="json"))

    messages = build_adaptive_research_messages(
        seed=seed,
        snapshot=snapshot,
        selected_branch=snapshot.branches[0],
        skill_contexts=[],
        external_turn_contexts=contexts,
    )
    projections = _external_context_messages(messages)
    assert len(projections) == 1
    assert projections[0]["content_cn"] == stimulus.payload_cn
    _assert_no_private_scoring(projections[0], path="external_message")


class _NoExternalEnvironment:
    def supported_operators(self) -> frozenset[ResearchOperator]:
        return frozenset()

    def execute(self, **_: Any) -> ExternalResearchFeedback:
        raise AssertionError("public-context test must not execute an external capability")


class _DiagnosticCompletion:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult:
        self.calls += 1
        messages = kwargs["messages"]
        task = json.loads(messages[-1]["content"])
        step_index = int(task["step_index"])
        branch_id = str(task["selected_branch"]["branch_id"])
        payload = ModelResearchActionDraft(
            step_index=step_index,
            branch_id=branch_id,
            operator=ResearchOperator.DECOMPOSE_UNCERTAINTY,
            action_title_cn="继续拆分当前公开环境信息中的未知量",
            action_body_cn="仅依据本轮公开刺激更新待核对项，不把当前探索当成科学证据。",
            reason_for_choice_cn="拆分未知量可以保留开放探索，而不由编排器规定固定步骤。",
            expected_information_gain_cn="可判断后续公开反馈是否改变当前分支的自主选择。",
        ).model_dump(mode="json")
        return LLMJsonCompletionResult(
            provider="diagnostic-local",
            base_url="https://diagnostic.invalid/v1",
            model_name="qwen-diagnostic-double",
            endpoint="https://diagnostic.invalid/v1/chat/completions",
            response_text=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            parsed_json=payload,
            usage={"prompt_tokens": 1, "completion_tokens": 1},
            temperature=0.7,
            reasoning_text=_REASONING,
            reasoning_transport="dashscope_enable_thinking",
        )


def test_twelve_turns_are_strict_single_stimuli_and_early_bytes_leave_recent_window(
    tmp_path: Path,
    bundle: AdaptiveLoopBenchmarkExecutionBundle,
) -> None:
    scenario, cell = _scenario_and_cell(bundle)
    store, seed, _ = _loop_inputs(tmp_path, scenario, suffix="twelve")
    completion = _DiagnosticCompletion()
    adapter = AdaptiveLoopBenchmarkPublicContextAdapter(
        public_scenario=scenario,
        blinded_cell=cell,
        raw_memory_store=store,
    )

    final_snapshot = run_adaptive_research_loop(
        seed=seed,
        policy=AdaptiveLoopPolicy(
            policy_id="adaptive-benchmark-context-test",
            max_steps=12,
            max_model_calls=12,
            max_external_actions=0,
            max_temporary_agents=0,
        ),
        raw_memory_store=store,
        output_dir=tmp_path / "loop-twelve",
        environment=_NoExternalEnvironment(),
        external_turn_context_provider=adapter,
        completion=completion,
    )

    assert completion.calls == 12
    assert final_snapshot.status is AdaptiveLoopRunStatus.PAUSED_BUDGET
    contexts = [event.interaction.external_turn_contexts for event in final_snapshot.events]
    assert all(len(items) == 1 for items in contexts)
    assert [items[0].content_cn for items in contexts] == [
        stimulus.payload_cn for stimulus in scenario.stimuli
    ]
    assert len({items[0].context_id for items in contexts}) == 12
    for event, stimulus in zip(final_snapshot.events, scenario.stimuli, strict=True):
        projections = _external_context_messages(event.interaction.messages)
        assert len(projections) == 1
        assert projections[0]["content_cn"] == stimulus.payload_cn
        _assert_no_private_scoring(projections[0], path=f"turn_{event.step_index}")

    terminal_messages = final_snapshot.events[-1].interaction.messages
    assert all(scenario.stimuli[0].payload_cn not in item["content"] for item in terminal_messages)
    terminal_task = json.loads(terminal_messages[-1]["content"])
    assert [item["step_index"] for item in terminal_task["recent_external_feedback"]] == list(
        range(4, 12)
    )
    assert _external_context_messages(terminal_messages)[0]["content_cn"] == (
        scenario.stimuli[11].payload_cn
    )

    prefix = AdaptiveResearchLoopSnapshot.create(
        seed=final_snapshot.seed,
        policy=final_snapshot.policy,
        zone=ResearchLoopZone.OPEN_EXPLORATION,
        status=AdaptiveLoopRunStatus.RUNNING,
        next_step_index=2,
        branches=final_snapshot.branches,
        events=[final_snapshot.events[0]],
        strategy_notes_cn=[],
        model_call_count=1,
        skill_routing_model_call_count=0,
        external_action_count=0,
        temporary_agent_count=0,
        consecutive_stalls=0,
    )
    _, other_cell = _scenario_and_cell(bundle, run_position=2)
    cross_cell_adapter = AdaptiveLoopBenchmarkPublicContextAdapter(
        public_scenario=scenario,
        blinded_cell=other_cell,
        raw_memory_store=store,
    )
    with pytest.raises(AdaptiveLoopBenchmarkContextError, match="cell, scenario, step"):
        cross_cell_adapter.contexts_for_turn(
            seed=seed,
            snapshot=prefix,
            branch=prefix.branches[0],
        )


def test_cross_scenario_step_repeat_private_input_and_tamper_fail_closed(
    tmp_path: Path,
    bundle: AdaptiveLoopBenchmarkExecutionBundle,
) -> None:
    scenario, cell = _scenario_and_cell(bundle)
    other_scenario, other_cell = _scenario_and_cell(bundle, scenario_index=1)
    store, seed, snapshot = _loop_inputs(tmp_path, scenario, suffix="failclosed")

    with pytest.raises(AdaptiveLoopBenchmarkContextError, match="frozen pair"):
        AdaptiveLoopBenchmarkPublicContextAdapter(
            public_scenario=scenario,
            blinded_cell=other_cell,
            raw_memory_store=store,
        )
    with pytest.raises(TypeError, match="public_scenario"):
        AdaptiveLoopBenchmarkPublicContextAdapter(
            public_scenario=bundle.runner_only_scoring,  # type: ignore[arg-type]
            blinded_cell=cell,
            raw_memory_store=store,
        )

    skipped_payload = snapshot.model_dump(mode="json", exclude={"snapshot_hash"})
    skipped_payload["next_step_index"] = 2
    skipped_snapshot = snapshot.model_copy(
        update={
            "next_step_index": 2,
            "snapshot_hash": canonical_sha256(skipped_payload),
        }
    )
    adapter = AdaptiveLoopBenchmarkPublicContextAdapter(
        public_scenario=scenario,
        blinded_cell=cell,
        raw_memory_store=store,
    )
    with pytest.raises(AdaptiveLoopBenchmarkContextError, match="canonical validation"):
        adapter.contexts_for_turn(
            seed=seed,
            snapshot=skipped_snapshot,
            branch=snapshot.branches[0],
        )

    first = adapter.contexts_for_turn(
        seed=seed,
        snapshot=snapshot,
        branch=snapshot.branches[0],
    )
    assert len(first) == 1
    with pytest.raises(AdaptiveLoopBenchmarkContextError, match="already emitted"):
        adapter.contexts_for_turn(
            seed=seed,
            snapshot=snapshot,
            branch=snapshot.branches[0],
        )
    restarted = AdaptiveLoopBenchmarkPublicContextAdapter(
        public_scenario=scenario,
        blinded_cell=cell,
        raw_memory_store=store,
    )
    with pytest.raises(AdaptiveLoopBenchmarkContextError, match="already has"):
        restarted.contexts_for_turn(
            seed=seed,
            snapshot=snapshot,
            branch=snapshot.branches[0],
        )
    first_capture = store.load_record(
        first[0].raw_binding.record_relative_path,
        project_id=seed.project_id,
    )
    first_capture.blob_path.write_bytes(first_capture.blob_path.read_bytes() + b"tamper")
    raw_tamper_adapter = AdaptiveLoopBenchmarkPublicContextAdapter(
        public_scenario=scenario,
        blinded_cell=cell,
        raw_memory_store=store,
    )
    with pytest.raises(AdaptiveLoopBenchmarkContextError, match="could not be verified"):
        raw_tamper_adapter.contexts_for_turn(
            seed=seed,
            snapshot=snapshot,
            branch=snapshot.branches[0],
        )

    tampered_scenario = scenario.model_copy(update={"public_scenario_hash": "0" * 64})
    with pytest.raises(AdaptiveLoopBenchmarkContextError, match="canonical validation"):
        AdaptiveLoopBenchmarkPublicContextAdapter(
            public_scenario=tampered_scenario,
            blinded_cell=cell,
            raw_memory_store=store,
        )

    clean_store, clean_seed, clean_snapshot = _loop_inputs(
        tmp_path,
        scenario,
        suffix="internal-tamper",
    )
    mutable_adapter = AdaptiveLoopBenchmarkPublicContextAdapter(
        public_scenario=scenario,
        blinded_cell=cell,
        raw_memory_store=clean_store,
    )
    mutable_adapter._public_scenario.stimuli[0].payload_cn = (  # noqa: SLF001
        "篡改后的公开刺激仍是中文，但没有同步内容哈希，因此必须在写入前失败关闭。"
    )
    with pytest.raises(AdaptiveLoopBenchmarkContextError, match="frozen public benchmark"):
        mutable_adapter.contexts_for_turn(
            seed=clean_seed,
            snapshot=clean_snapshot,
            branch=clean_snapshot.branches[0],
        )

    wrong_store, wrong_seed, wrong_snapshot = _loop_inputs(
        tmp_path,
        other_scenario,
        suffix="wrong-scenario",
    )
    wrong_adapter = AdaptiveLoopBenchmarkPublicContextAdapter(
        public_scenario=scenario,
        blinded_cell=cell,
        raw_memory_store=wrong_store,
    )
    with pytest.raises(AdaptiveLoopBenchmarkContextError, match="objective and scope"):
        wrong_adapter.contexts_for_turn(
            seed=wrong_seed,
            snapshot=wrong_snapshot,
            branch=wrong_snapshot.branches[0],
        )


def test_production_adapter_does_not_import_private_scoring_contracts() -> None:
    path = Path(context_module.__file__ or "")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    }
    assert all("oracle" not in name.casefold() for name in imported_names)
    assert "runner_only_scoring" not in path.read_text(encoding="utf-8")
