from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

import autoresearch.competition.contest_direction_hypothesis_stage as stage_module
from autoresearch.agents.temporary import (
    TemporaryAgentInputRef,
    TemporaryAgentSkillRef,
    issue_stage_controller,
)
from autoresearch.competition.contest_direction_hypothesis_stage import (
    ContestDirectionHypothesisStageError,
    load_contest_direction_hypothesis_brainstorm,
    load_contest_postpilot_objective_review,
    run_contest_direction_hypothesis_brainstorm,
    run_contest_postpilot_objective_review,
)
from autoresearch.competition.contest_prime_preexperiment import (
    ContestPrimePreexperimentParameters,
    PrimeIntervalSpec,
    run_contest_prime_preexperiment,
)
from autoresearch.competition.temporary_qwen_pool import TemporaryQwenSkillContext
from autoresearch.kernel.contracts import canonical_sha256
from autoresearch.llm.client import LLMJsonCompletionResult

_NOW = datetime(2026, 8, 12, 2, 0, tzinfo=timezone.utc)
_DIRECTION = "有限尺度素数间隙序列中模算术约束与高阶顺序结构的信息论检验"
_REQUIREMENTS = "从真实文献形成候选，经真实预实验后只做一次独立目标评审。"
_SKILL = "# 计算数论方法\n\n使用匹配零模型、固定协议和可证伪条件。\n"
_LITERATURE = (
    {
        "title": "Unexpected biases in the distribution of consecutive primes",
        "url": "https://doi.org/10.1073/pnas.1605366113",
        "retrieved_from": "OpenAlex",
        "retrieved_at": "2026-08-12T01:00:00Z",
        "abstract": "Consecutive primes exhibit finite-scale residue-class biases.",
        "doi": "10.1073/pnas.1605366113",
    },
)
_ADAPTERS = (
    {
        "adapter_id": "prime-gap-information-theory-v1",
        "scientific_object": "consecutive_integer_primes",
        "observable": "ordered_prime_gaps",
        "supported_metrics": ["tie_aware_permutation_entropy_m5"],
        "supported_nulls": [
            "local_block_permutation",
            "global_permutation",
            "residue_path_conditioned_permutation",
            "wheel_210",
        ],
        "description": "真实生成素数间隙并与四类零模型比较。",
    },
)


def _input_ref() -> TemporaryAgentInputRef:
    return TemporaryAgentInputRef(
        artifact_id="contest-direction-prime-gap",
        source_ref="inputs/direction.json",
        sha256=canonical_sha256({"direction": _DIRECTION}),
    )


def _skill() -> TemporaryQwenSkillContext:
    return TemporaryQwenSkillContext(
        skill_ref=TemporaryAgentSkillRef(
            skill_id="computational-number-theory",
            source_ref="skills/computational-number-theory/SKILL.md",
            content_sha256=hashlib.sha256(_SKILL.encode("utf-8")).hexdigest(),
        ),
        content=_SKILL,
    )


def _controller(*, suffix: str, stage: str, parallel: int):
    return issue_stage_controller(
        lineage_id=f"direction-pilot-{suffix}",
        stage=stage,
        stage_attempt=1,
        controller_agent_id=f"direction-main-{suffix}",
        stage_input_hash="a" * 64,
        max_parallel_agents=parallel,
        claimed_at=_NOW,
        lease_token=f"direction-token-{suffix}-{stage}",
    )


class _Completion:
    def __init__(
        self,
        *,
        failed_brainstorm_ordinal: int | None = None,
        decision: str = "narrow_once",
    ) -> None:
        self.failed_brainstorm_ordinal = failed_brainstorm_ordinal
        self.decision = decision
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult:
        self.calls.append(kwargs)
        task = json.loads(kwargs["messages"][-1]["content"])
        dispatch_id = str(task["派工编号"])
        if dispatch_id.startswith("postpilot-objective-"):
            payload = {
                "decision": self.decision,
                "research_objective_cn": "将结论收窄到五个固定区间上的条件顺序差异。",
                "main_hypothesis_cn": "残基路径条件化后仍可能保留有限尺度顺序信号。",
                "falsification_cn": "若强约束零模型下差异不稳定，则终止当前结构假设。",
                "pilot_interpretation_cn": "预实验只支持固定区间内的探索性比较，不能外推总体。",
                "review_cn": "综合四类零模型与边界后只允许一次收窄，不启动第二次重想。",
                "reference_indices": [1],
            }
            reasoning = "先核对预实验哈希与四类零模型，再解释边界并作一次决策。"
        else:
            ordinal = int(dispatch_id.rsplit("-", maxsplit=1)[1])
            payload = {
                "hypothesis_cn": f"候选{ordinal}检验残基约束后的有限尺度顺序信息。",
                "research_objective_cn": "比较真实素数间隙与匹配零模型的排列熵。",
                "falsification_cn": "若强约束零模型下差异消失则拒绝结构假设。",
                "nearest_work_difference_cn": "相邻工作报告残基偏差，本候选检验条件化后的高阶顺序残差。",
                "transferred_method_baseline_cn": "迁移其残基条件思想，并加入局部置换与wheel基线。",
                "strongest_counterevidence_cn": "残差在强条件零模型下消失将支持算术约束解释。",
                "adapter_id": "prime-gap-information-theory-v1",
                "scientific_object": "consecutive_integer_primes",
                "observable": "ordered_prime_gaps",
                "metric": "tie_aware_permutation_entropy_m5",
                "null_models": [
                    "local_block_permutation",
                    "global_permutation",
                    "residue_path_conditioned_permutation",
                    "wheel_210",
                ],
                "reference_indices": [1],
            }
            reasoning = (
                ""
                if ordinal == self.failed_brainstorm_ordinal
                else "从真实文献和技能形成可证伪候选，并检查适配器契约。"
            )
        return LLMJsonCompletionResult(
            provider="qwen-dashscope",
            base_url="https://dashscope.example/compatible-mode/v1",
            model_name="qwen3.7-max",
            endpoint="https://dashscope.example/v1/chat/completions",
            response_text=json.dumps(payload, ensure_ascii=False),
            parsed_json=payload,
            usage={"reasoning_tokens": 50},
            temperature=float(kwargs["temperature"]),
            reasoning_text=reasoning,
            reasoning_transport="dashscope_enable_thinking",
        )


@pytest.fixture(scope="module")
def completed_chain(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = tmp_path_factory.mktemp("direction-hypothesis-stage")
    brainstorm_controller, brainstorm_capability = _controller(
        suffix="complete", stage="hypothesis-brainstorm", parallel=3
    )
    brainstorm_completion = _Completion()
    brainstorm_dir = root / "brainstorm"
    brainstorm = run_contest_direction_hypothesis_brainstorm(
        direction=_DIRECTION,
        requirements=_REQUIREMENTS,
        direction_ref=_input_ref(),
        parent_task_id="contest-direction-main",
        controller=brainstorm_controller,
        capability=brainstorm_capability,
        output_dir=brainstorm_dir,
        selected_skill_contexts=(_skill(),),
        retrieved_literature_catalog=_LITERATURE,
        executable_adapters=_ADAPTERS,
        completion=brainstorm_completion,
        clock=_NOW,
    )
    pilot_brief = root / "pilot-brief.json"
    selected_candidate = brainstorm.candidates[0].model_dump(mode="json")
    pilot_brief_payload = {
        "schema_version": "contest-prime-gap-pilot-brief-v1",
        "direction": _DIRECTION,
        "artifact_hash": canonical_sha256({"selected_candidate": selected_candidate}),
        "direction_input_hash": canonical_sha256({"direction": _DIRECTION}),
        "hypothesis_artifact_hash": brainstorm.artifact_hash,
        "literature_artifact_hash": brainstorm.literature_catalog_sha256,
        "skill_routing_artifact_hash": "a" * 64,
        "provisional_plan_artifact_hash": "b" * 64,
        "selected_candidate": selected_candidate,
        "adapter_descriptor": dict(_ADAPTERS[0]),
        "frozen_parameters_projection": {
            "ordinal_dimension": 5,
            "primary_null_model": "residue_path_conditioned_permutation",
            "null_draws": 199,
        },
    }
    pilot_brief.write_text(
        json.dumps(pilot_brief_payload, ensure_ascii=False),
        encoding="utf-8",
    )
    pilot_dir = root / "pilot"
    parameters = ContestPrimePreexperimentParameters(
        intervals=tuple(
            PrimeIntervalSpec(start=start, stop=start + 50_000)
            for start in (100_000, 200_000, 300_000, 400_000, 500_000)
        ),
        null_draws=199,
        fixed_interval_resampling_draws=1_000,
        wheel_density_segment_width=10_000,
    )
    run_contest_prime_preexperiment(
        output_dir=pilot_dir,
        parameters=parameters,
        source_plan_path=pilot_brief,
    )
    return {
        "root": root,
        "brainstorm": brainstorm,
        "brainstorm_dir": brainstorm_dir,
        "pilot_brief": pilot_brief,
        "pilot_dir": pilot_dir,
        "brainstorm_completion": brainstorm_completion,
    }


def test_brainstorm_is_unreviewed_and_program_computes_candidate_ids(
    completed_chain: dict[str, Any],
) -> None:
    artifact = completed_chain["brainstorm"]
    assert artifact.status == "complete"
    assert artifact.model_call_count == 3
    assert artifact.review_performed is False
    assert len(artifact.candidates) == 3
    assert all(
        item.candidate_id.startswith("hypothesis-candidate-") for item in artifact.candidates
    )
    assert all(item.adapter_id == "prime-gap-information-theory-v1" for item in artifact.candidates)
    for call in completed_chain["brainstorm_completion"].calls:
        task_input = json.loads(call["messages"][1]["content"])["短任务输入"]
        assert "必须逐字复制" in task_input["适配器边界"]
        assert "不得翻译、改写" in task_input["适配器边界"]
    loaded = load_contest_direction_hypothesis_brainstorm(
        completed_chain["brainstorm_dir"] / artifact.artifact_relative_path
    )
    assert loaded.artifact_hash == artifact.artifact_hash


def test_hypothesis_semantic_gate_downgrades_adapter_when_focus_redefines_gaps(
    tmp_path: Path,
) -> None:
    direction = "构造素数签名，以签名的ℓ∞距离诱导相邻素数间隙，并检验该派生序列的排列熵。"
    controller, capability = _controller(
        suffix="signature-gap", stage="hypothesis-brainstorm", parallel=3
    )
    completion = _Completion()

    artifact = run_contest_direction_hypothesis_brainstorm(
        direction=direction,
        requirements=_REQUIREMENTS,
        direction_ref=_input_ref(),
        parent_task_id="contest-direction-signature-gap",
        controller=controller,
        capability=capability,
        output_dir=tmp_path / "brainstorm",
        selected_skill_contexts=(_skill(),),
        retrieved_literature_catalog=_LITERATURE,
        executable_adapters=_ADAPTERS,
        completion=completion,
        clock=_NOW,
    )

    # Raw model outputs still claim the known adapter, but the trusted
    # projection cannot turn that claim into execution authority.
    assert all(
        call["messages"] and "逐字字段相等仍不充分" in call["messages"][1]["content"]
        for call in completion.calls
    )
    assert all(item.adapter_id == "no_adapter" for item in artifact.candidates)


def test_literature_abstract_projection_removes_markup_without_truncating_text() -> None:
    abstract = (
        "Verified up to &lt;bound&gt; "
        "<inline-formula><mml:math><mml:semantics><mml:mrow><mml:mn>4</mml:mn>"
        "<mml:mo>&sdot;</mml:mo><mml:msup><mml:mn>10</mml:mn><mml:mn>18</mml:mn>"
        "</mml:msup></mml:mrow>"
        '<mml:annotation encoding="application/x-tex"><![CDATA[4\\cdot 10^{18}]]>'
        "</mml:annotation></mml:semantics></mml:math></inline-formula> &amp; retained."
    )
    record = {
        "title": "Goldbach verification",
        "source_url": "https://example.test/goldbach",
        "retrieved_from": "openalex",
        "retrieved_at": "2026-08-13T00:00:00+00:00",
        "abstract": abstract,
        "doi": "10.1000/example",
        "extra_full_record_field": {"kept_only_in_source_hash": [1, 2, 3]},
    }

    projected = stage_module._normalize_literature_catalog((record,))[0]

    assert "<inline-formula" not in str(projected["abstract"])
    assert "&lt;" not in str(projected["abstract"])
    assert "<bound>" in str(projected["abstract"])
    assert "4" in str(projected["abstract"])
    assert "10" in str(projected["abstract"])
    assert r"4\cdot 10^{18}" in str(projected["abstract"])
    assert "retained" in str(projected["abstract"])
    assert "no_length_truncation" in str(projected["abstract_projection"])
    assert projected["record_sha256"] == canonical_sha256(record)


def test_context_shrink_drops_largest_record_and_preserves_source_mapping() -> None:
    records = tuple(
        {
            "catalog_index": index,
            "source_catalog_index": source_index,
            "title": title,
            "abstract": abstract,
        }
        for index, (source_index, title, abstract) in enumerate(
            (
                (2, "small-a", "a"),
                (7, "largest", "x" * 2_000),
                (11, "small-b", "b"),
            ),
            start=1,
        )
    )

    retained = stage_module._drop_largest_serialized_literature_record(records)

    assert [item["title"] for item in retained] == ["small-a", "small-b"]
    assert [item["catalog_index"] for item in retained] == [1, 2]
    assert [item["source_catalog_index"] for item in retained] == [2, 11]


def test_postpilot_dreaming_projection_keeps_hash_navigation_not_full_summary() -> None:
    boundary = stage_module.normalize_optional_dreaming_context.__globals__["_BOUNDARY_ZH"]
    full = {
        "context_kind": "optional_rebuildable_dreaming_navigation",
        "recall_hash": "a" * 64,
        "epistemic_boundary_zh": boundary,
        "derived_context_is_evidence": False,
        "model_consumption_proven_by_this_receipt": False,
        "projections": [
            {
                "source_stage": "real-pilot",
                "stage_receipt_hash": "b" * 64,
                "projection_id": "dream_" + "c" * 64,
                "projection_hash": "c" * 64,
                "summary": "large persisted navigation " * 2_000,
                "raw_bindings": [
                    {
                        "record_id": "rawmem_" + "d" * 64,
                        "payload_sha256": "e" * 64,
                        "record_hash": "f" * 64,
                        "record_relative_path": "_private/raw-memory/record.json",
                    }
                ],
            }
        ],
    }

    projected = stage_module._project_postpilot_dreaming_context(full)

    assert projected is not None
    assert projected["recall_hash"] == "a" * 64
    item = projected["projections"][0]
    assert item["source_stage"] == "real-pilot"
    assert item["stage_receipt_hash"] == "b" * 64
    assert item["raw_binding_count"] == 1
    assert "summary" not in item
    assert "raw_bindings" not in item
    assert len(json.dumps(projected, ensure_ascii=False)) < 2_000


def test_partial_brainstorm_failure_is_degraded(tmp_path: Path) -> None:
    controller, capability = _controller(
        suffix="partial", stage="hypothesis-brainstorm", parallel=3
    )
    artifact = run_contest_direction_hypothesis_brainstorm(
        direction=_DIRECTION,
        requirements=_REQUIREMENTS,
        direction_ref=_input_ref(),
        parent_task_id="contest-direction-main",
        controller=controller,
        capability=capability,
        output_dir=tmp_path / "brainstorm",
        selected_skill_contexts=(_skill(),),
        retrieved_literature_catalog=_LITERATURE,
        executable_adapters=_ADAPTERS,
        completion=_Completion(failed_brainstorm_ordinal=2),
        clock=_NOW,
    )
    assert artifact.status == "degraded"
    assert len(artifact.candidates) == 2
    assert artifact.unavailable_roles == ("experiment_designer",)


@pytest.mark.parametrize("decision", ["narrow_once", "terminate"])
def test_postpilot_review_reads_verified_metrics_and_calls_model_once(
    completed_chain: dict[str, Any],
    tmp_path: Path,
    decision: str,
) -> None:
    controller, capability = _controller(
        suffix=f"review-{decision}", stage="postpilot-objective-review", parallel=1
    )
    completion = _Completion(decision=decision)
    artifact = run_contest_postpilot_objective_review(
        direction=_DIRECTION,
        requirements=_REQUIREMENTS,
        direction_ref=_input_ref(),
        parent_task_id="contest-direction-main",
        controller=controller,
        capability=capability,
        output_dir=tmp_path / "review",
        brainstorm_artifact_path=(
            completed_chain["brainstorm_dir"] / "direction-hypothesis-brainstorm.json"
        ),
        pilot_brief_path=completed_chain["pilot_brief"],
        preexperiment_artifact_path=completed_chain["pilot_dir"] / "prime-preexperiment.json",
        selected_skill_contexts=(_skill(),),
        retrieved_literature_catalog=_LITERATURE,
        completion=completion,
        clock=_NOW,
    )
    assert artifact.decision == decision
    assert artifact.model_call_count == 1
    assert artifact.scientific_rethink_count == 1
    assert artifact.further_scientific_retry_allowed is False
    assert artifact.task_input_utf8_bytes <= 28 * 1_024
    assert len(artifact.literature_catalog) == 1
    assert len(completion.calls) == 1
    assert len(completion.calls[0]["messages"][-1]["content"]) < 28_000
    explicit_input = json.loads(completion.calls[0]["messages"][1]["content"])["短任务输入"]
    metrics_projection = explicit_input["真实预实验"]["metrics_json关键科学投影"]
    assert len(metrics_projection["aggregate_results"]) == 4
    assert "interval_results" not in metrics_projection
    assert metrics_projection["scientific_boundary_zh"]
    assert "stdout正文" in explicit_input["真实预实验"]
    assert "stderr正文" in explicit_input["真实预实验"]
    inventory = explicit_input["已验证输入清单投影"]
    assert inventory["verified_inputs_bundle_sha256"] == (artifact.verified_inputs_bundle_sha256)
    assert all(item["path"] and item["sha256"] for item in inventory["key_files"])
    assert inventory["bulk_csv_groups"]["raw_prime_gaps"]["file_count"] == 5
    assert inventory["bulk_csv_groups"]["null_draws"]["file_count"] == 5
    pilot_projection = explicit_input["pilot_brief"]["送审内容投影"]
    assert pilot_projection["selected_candidate"]["candidate_id"] == (
        completed_chain["brainstorm"].candidates[0].candidate_id
    )
    assert "candidates" not in json.dumps(pilot_projection, ensure_ascii=False)
    assert "没有读取CSV逐行正文" in explicit_input["原始数据读取边界"]
    loaded = load_contest_postpilot_objective_review(
        tmp_path / "review" / artifact.artifact_relative_path
    )
    assert loaded.artifact_hash == artifact.artifact_hash
    assert loaded.plan_context_payload()["decision"] == decision


def test_tampered_raw_preexperiment_fails_before_review(
    completed_chain: dict[str, Any], tmp_path: Path
) -> None:
    copied_pilot = tmp_path / "copied-pilot"
    shutil.copytree(completed_chain["pilot_dir"], copied_pilot)
    raw_path = next((copied_pilot / "raw").glob("*.csv"))
    raw_path.write_text(raw_path.read_text(encoding="utf-8") + "2,3,1\n", encoding="utf-8")
    controller, capability = _controller(
        suffix="tampered", stage="postpilot-objective-review", parallel=1
    )
    completion = _Completion()
    with pytest.raises(Exception, match="hash mismatch|size mismatch"):
        run_contest_postpilot_objective_review(
            direction=_DIRECTION,
            requirements=_REQUIREMENTS,
            direction_ref=_input_ref(),
            parent_task_id="contest-direction-main",
            controller=controller,
            capability=capability,
            output_dir=tmp_path / "review",
            brainstorm_artifact_path=(
                completed_chain["brainstorm_dir"] / "direction-hypothesis-brainstorm.json"
            ),
            pilot_brief_path=completed_chain["pilot_brief"],
            preexperiment_artifact_path=copied_pilot / "prime-preexperiment.json",
            completion=completion,
            clock=_NOW,
        )
    assert completion.calls == []


def test_legacy_postpilot_derives_bundle_and_rejects_tampered_binding(
    completed_chain: dict[str, Any],
    tmp_path: Path,
) -> None:
    controller, capability = _controller(
        suffix="legacy-artifact", stage="postpilot-objective-review", parallel=1
    )
    artifact = run_contest_postpilot_objective_review(
        direction=_DIRECTION,
        requirements=_REQUIREMENTS,
        direction_ref=_input_ref(),
        parent_task_id="contest-direction-main",
        controller=controller,
        capability=capability,
        output_dir=tmp_path / "new-review",
        brainstorm_artifact_path=(
            completed_chain["brainstorm_dir"] / "direction-hypothesis-brainstorm.json"
        ),
        pilot_brief_path=completed_chain["pilot_brief"],
        preexperiment_artifact_path=completed_chain["pilot_dir"] / "prime-preexperiment.json",
        retrieved_literature_catalog=_LITERATURE,
        completion=_Completion(),
        clock=_NOW,
    )
    legacy = artifact.model_dump(mode="json")
    legacy.pop("verified_inputs_bundle_sha256")
    legacy["artifact_hash"] = canonical_sha256(
        {key: value for key, value in legacy.items() if key != "artifact_hash"}
    )
    legacy_path = tmp_path / "legacy-postpilot.json"
    legacy_path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
    original_bytes = legacy_path.read_bytes()
    loaded = load_contest_postpilot_objective_review(legacy_path)
    assert loaded.verified_inputs_bundle_sha256 == canonical_sha256(
        [item.model_dump(mode="json") for item in loaded.verified_inputs]
    )
    assert legacy_path.read_bytes() == original_bytes

    tampered = json.loads(json.dumps(legacy))
    tampered["verified_inputs"][0]["bytes"] += 1
    tampered["artifact_hash"] = canonical_sha256(
        {key: value for key, value in tampered.items() if key != "artifact_hash"}
    )
    tampered_path = tmp_path / "legacy-postpilot-tampered.json"
    tampered_path.write_text(json.dumps(tampered, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ContestDirectionHypothesisStageError, match="verified input changed"):
        load_contest_postpilot_objective_review(tampered_path)


def test_current_live_legacy_postpilot_loads_without_rewrite() -> None:
    path = Path(
        "runs/contest-delivery/direction-prime-gap-evidence-first-live-v1/"
        "postpilot-stage/postpilot-objective-review.json"
    ).resolve()
    if not path.is_file():
        pytest.skip("current live legacy postpilot artifact is not present")
    original = path.read_bytes()
    raw = json.loads(original)
    assert "verified_inputs_bundle_sha256" not in raw
    loaded = load_contest_postpilot_objective_review(path)
    assert loaded.verified_inputs_bundle_sha256 == canonical_sha256(
        [item.model_dump(mode="json") for item in loaded.verified_inputs]
    )
    assert path.read_bytes() == original


def test_current_live_shape_builds_under_budget_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live_root = Path("runs/contest-delivery/direction-prime-gap-evidence-first-live-v1").resolve()
    brainstorm_path = live_root / "hypothesis-stage/direction-hypothesis-brainstorm.json"
    pilot_brief_path = live_root / "preexperiment/pilot-brief.json"
    pilot_path = (
        live_root / "preexperiment/prime-gap-information-theory-v1/prime-preexperiment.json"
    )
    if not all(path.is_file() for path in (brainstorm_path, pilot_brief_path, pilot_path)):
        pytest.skip("current live-shaped direction artifacts are not present")
    brainstorm = load_contest_direction_hypothesis_brainstorm(brainstorm_path)
    captured: dict[str, Any] = {}

    class _StopBeforeModel(RuntimeError):
        pass

    def capture_task(**kwargs: Any) -> None:
        captured["task"] = tuple(kwargs["tasks"])[0]
        raise _StopBeforeModel

    monkeypatch.setattr(stage_module, "run_temporary_qwen_content_batch", capture_task)
    controller, capability = _controller(
        suffix="live-shape", stage="postpilot-objective-review", parallel=1
    )
    with pytest.raises(_StopBeforeModel):
        run_contest_postpilot_objective_review(
            direction=brainstorm.direction,
            requirements=_REQUIREMENTS,
            direction_ref=_input_ref(),
            parent_task_id="contest-direction-main",
            controller=controller,
            capability=capability,
            output_dir=tmp_path / "postpilot-build-only",
            brainstorm_artifact_path=brainstorm_path,
            pilot_brief_path=pilot_brief_path,
            preexperiment_artifact_path=pilot_path,
            retrieved_literature_catalog=brainstorm.literature_catalog,
            clock=_NOW,
        )
    capability.revoke()
    task = captured["task"]
    assert stage_module._task_input_utf8_bytes(task) <= 28 * 1_024
    projected = task.input_payload["真实检索文献目录"]
    assert isinstance(projected, list)
    assert 1 <= len(projected) <= 5
    source_by_index = {int(item["catalog_index"]): item for item in brainstorm.literature_catalog}
    for item in projected:
        assert isinstance(item, dict)
        source = source_by_index[int(item["source_catalog_index"])]
        assert item["title"] == source["title"]
        assert item["abstract"] == source["abstract"]
        assert item["source_url"] == source["source_url"]


def test_brainstorm_schema_requires_a_real_reference_when_literature_exists() -> None:
    schema = stage_module._brainstorm_schema(
        literature_count=3,
        adapter_ids=("prime-gap-information-theory-v1",),
    )

    assert schema["properties"]["reference_indices"]["minItems"] == 1
    assert "nearest_work_difference_cn" in schema["required"]
    assert "transferred_method_baseline_cn" in schema["required"]
    assert "strongest_counterevidence_cn" in schema["required"]


def test_postpilot_literature_projection_refuses_to_invent_reference_one() -> None:
    class _Candidate:
        candidate_id = "hypothesis-candidate-deadbeefdeadbeefdeadbeef"
        adapter_id = "prime-gap-information-theory-v1"
        scientific_object = "consecutive_integer_primes"
        observable = "ordered_prime_gaps"
        metric = "tie_aware_permutation_entropy_m5"
        reference_indices: tuple[int, ...] = ()

    class _Brainstorm:
        candidates = (_Candidate(),)

    pilot_brief = json.dumps(
        {
            "selected_candidate": {
                "candidate_id": _Candidate.candidate_id,
                "adapter_id": _Candidate.adapter_id,
                "scientific_object": _Candidate.scientific_object,
                "observable": _Candidate.observable,
                "metric": _Candidate.metric,
                "reference_indices": [],
            }
        },
        ensure_ascii=False,
    )

    with pytest.raises(ContestDirectionHypothesisStageError, match="refusing to fabricate"):
        stage_module._select_postpilot_literature(
            brainstorm=_Brainstorm(),
            pilot_brief_text=pilot_brief,
            literature_catalog=_LITERATURE,
        )
