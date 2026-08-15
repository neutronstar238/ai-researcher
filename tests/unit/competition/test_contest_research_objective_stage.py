from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

import autoresearch.competition.contest_research_objective_stage as objective_stage_module
from autoresearch.agents.temporary import (
    StageControllerBinding,
    StageDispatchCapability,
    TemporaryAgentArchiveRecord,
    TemporaryAgentInputRef,
    TemporaryAgentSkillRef,
    issue_stage_controller,
)
from autoresearch.competition.contest_research_objective_stage import (
    ContestResearchObjectiveStageArtifact,
    ContestResearchObjectiveStageError,
    run_contest_research_objective_stage,
)
from autoresearch.competition.temporary_qwen_pool import TemporaryQwenSkillContext
from autoresearch.kernel.contracts import canonical_sha256
from autoresearch.llm.client import LLMClientError, LLMJsonCompletionResult

_NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
_QUESTION = "素数为何如此特别？"
_DIRECTION = "有限尺度下素数间隙的非随机结构"
_REQUIREMENTS = "先形成可证伪假设与研究目标，再交给研究计划作者。"
_SKILL = "# 计算数论方法\n\n使用匹配对照、稳健性检验和明确的失败判据。\n"
_LITERATURE = (
    {
        "title": "Small gaps between primes",
        "url": "https://annals.math.princeton.edu/2015/181-1/p07",
        "retrieved_from": "OpenAlex",
        "retrieved_at": "2026-08-11T11:00:00Z",
        "abstract": "A retrieved abstract about bounded gaps between primes.",
        "authors": ["James Maynard"],
        "doi": "10.4007/annals.2015.181.1.7",
    },
)


def _input_ref(text: str) -> TemporaryAgentInputRef:
    return TemporaryAgentInputRef(
        artifact_id="contest-research-seed-001",
        source_ref="inputs/research-seed.json",
        sha256=canonical_sha256({"text": text}),
    )


def _skill_context() -> TemporaryQwenSkillContext:
    return TemporaryQwenSkillContext(
        skill_ref=TemporaryAgentSkillRef(
            skill_id="computational-number-theory",
            source_ref="skills/computational-number-theory/SKILL.md",
            content_sha256=hashlib.sha256(_SKILL.encode("utf-8")).hexdigest(),
        ),
        content=_SKILL,
    )


def _controllers(
    *,
    suffix: str,
) -> tuple[
    StageControllerBinding,
    StageDispatchCapability,
    StageControllerBinding,
    StageDispatchCapability,
]:
    brainstorm_controller, brainstorm_capability = issue_stage_controller(
        lineage_id=f"objective-stage-{suffix}",
        stage="research-objective-brainstorm",
        stage_attempt=1,
        controller_agent_id=f"research-objective-main-{suffix}",
        stage_input_hash="a" * 64,
        max_parallel_agents=3,
        claimed_at=_NOW,
        lease_token=f"objective-brainstorm-token-{suffix}-0001",
    )
    review_controller, review_capability = issue_stage_controller(
        lineage_id=f"objective-stage-{suffix}",
        stage="research-objective-review",
        stage_attempt=1,
        controller_agent_id=f"research-objective-main-{suffix}",
        stage_input_hash="a" * 64,
        max_parallel_agents=1,
        claimed_at=_NOW,
        lease_token=f"objective-review-token-{suffix}-0001",
    )
    return (
        brainstorm_controller,
        brainstorm_capability,
        review_controller,
        review_capability,
    )


class _ObjectiveCompletion:
    def __init__(
        self,
        *,
        direction: bool = False,
        failed_brainstorm_ordinals: set[int] | None = None,
        brainstorm_reference_indices: list[int] | None = None,
        review_candidate_numbers: list[int] | None = None,
        review_reference_indices: list[int] | None = None,
        review_main_hypothesis: str | None = None,
        review_failure_mode: str | None = None,
    ) -> None:
        self.direction = direction
        self.failed_brainstorm_ordinals = failed_brainstorm_ordinals or set()
        self.brainstorm_reference_indices = brainstorm_reference_indices
        self.review_candidate_numbers = review_candidate_numbers
        self.review_reference_indices = review_reference_indices
        self.review_main_hypothesis = review_main_hypothesis
        self.review_failure_mode = review_failure_mode
        self.review_call_count = 0
        self.barrier = threading.Barrier(3)
        self.lock = threading.Lock()
        self.calls: list[dict[str, Any]] = []
        self.overlapped_brainstorm_ids: set[str] = set()

    def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult:
        task_message = json.loads(kwargs["messages"][-1]["content"])
        dispatch_id = str(task_message["派工编号"])
        is_review = dispatch_id.startswith("objective-review-")
        with self.lock:
            self.calls.append(kwargs)
        if is_review:
            self.review_call_count += 1
            fail_this_review = self.review_failure_mode in {
                "transport_always",
                "format",
                "ordinary",
            } or (self.review_failure_mode == "transport_once" and self.review_call_count == 1)
            if fail_this_review:
                if self.review_failure_mode in {"transport_once", "transport_always"}:
                    raise LLMClientError("Qwen request failed: OSError: [WinError 10060] 连接超时")
                if self.review_failure_mode == "format":
                    raise LLMClientError(
                        "LLM response was not valid JSON",
                        response_text="{invalid",
                    )
                raise RuntimeError("review worker ordinary failure")
            explicit_input = json.loads(kwargs["messages"][1]["content"])["短任务输入"]
            candidate_count = len(explicit_input["待评审候选"])
            selected = (
                self.review_candidate_numbers
                if self.review_candidate_numbers is not None
                else ([1] if candidate_count else [])
            )
            references = (
                self.review_reference_indices
                if self.review_reference_indices is not None
                else ([1] if self.direction else [])
            )
            payload = {
                "research_objective_cn": "检验素数局部结构是否偏离匹配置换对照。",
                "main_hypothesis_cn": self.review_main_hypothesis
                or "局部顺序统计量包含超出边际分布的结构信息。",
                "falsification_cn": "若多尺度效应不稳定且不优于匹配对照，则否定该假设。",
                "review_cn": "独立比较候选后保留可证伪且能以公开数据起步的研究目标。",
                "selected_candidate_numbers": selected,
                "reference_indices": references,
            }
            reasoning = "先核对证据边界，再比较候选的可证伪性与可执行性。"
        else:
            ordinal = int(dispatch_id.rsplit("-", maxsplit=1)[1])
            with self.lock:
                self.overlapped_brainstorm_ids.add(dispatch_id)
            self.barrier.wait(timeout=5)
            payload = {
                "memo_cn": f"候选{ordinal}提出可区分竞争解释的计算检验。",
                "hypothesis_cn": "素数局部次序包含无法由边际间隙分布解释的信息。",
                "research_objective_cn": "构建匹配对照并比较局部顺序统计量。",
                "falsification_cn": "效应若不能跨尺度复现则拒绝假设。",
                "reference_indices": (
                    self.brainstorm_reference_indices
                    if self.brainstorm_reference_indices is not None
                    else ([1] if self.direction else [])
                ),
            }
            reasoning = (
                ""
                if ordinal in self.failed_brainstorm_ordinals
                else "从题目出发形成可证伪假设，并检查是否误把预期写成结果。"
            )
        return LLMJsonCompletionResult(
            provider="qwen-dashscope",
            base_url="https://dashscope.example/compatible-mode/v1",
            model_name="qwen3.7-max",
            endpoint="https://dashscope.example/v1/chat/completions",
            response_text=json.dumps(payload, ensure_ascii=False),
            parsed_json=payload,
            usage={"reasoning_tokens": 128},
            temperature=float(kwargs["temperature"]),
            reasoning_text=reasoning,
            reasoning_transport="dashscope_enable_thinking",
        )


def _inside(root: Path, relative_path: str) -> Path:
    path = (root / Path(*PurePosixPath(relative_path).parts)).resolve()
    path.relative_to(root.resolve())
    return path


def _run(
    tmp_path: Path,
    *,
    suffix: str,
    mode: str = "specified_question",
    completion: _ObjectiveCompletion | None = None,
    literature: tuple[dict[str, Any], ...] = (),
) -> tuple[
    ContestResearchObjectiveStageArtifact,
    _ObjectiveCompletion,
    StageDispatchCapability,
    StageDispatchCapability,
]:
    (
        brainstorm_controller,
        brainstorm_capability,
        review_controller,
        review_capability,
    ) = _controllers(suffix=suffix)
    chosen_completion = completion or _ObjectiveCompletion(direction=mode == "specified_direction")
    seed = _QUESTION if mode == "specified_question" else _DIRECTION
    artifact = run_contest_research_objective_stage(
        mode=mode,  # type: ignore[arg-type]
        seed_text=seed,
        requirements=_REQUIREMENTS,
        seed_ref=_input_ref(seed),
        parent_task_id="contest-research-plan-main",
        brainstorm_controller=brainstorm_controller,
        brainstorm_capability=brainstorm_capability,
        review_controller=review_controller,
        review_capability=review_capability,
        output_dir=tmp_path,
        selected_skill_contexts=(_skill_context(),),
        retrieved_literature_catalog=literature,
        brainstorm_completion=chosen_completion,
        review_completion=chosen_completion,
        clock=_NOW,
    )
    return artifact, chosen_completion, brainstorm_capability, review_capability


def test_question_mode_brainstorms_in_parallel_then_runs_independent_review(
    tmp_path: Path,
) -> None:
    artifact, completion, brainstorm_capability, review_capability = _run(
        tmp_path,
        suffix="question",
    )

    assert artifact.status == "complete"
    assert artifact.candidate_count == 3
    assert len(completion.calls) == 4
    assert len(completion.overlapped_brainstorm_ids) == 3
    assert not brainstorm_capability.active
    assert not review_capability.active
    assert completion.review_call_count == 1
    assert artifact.brainstorm_controller_binding_hash != (artifact.review_controller_binding_hash)
    assert len({item.candidate_id for item in artifact.candidates}) == 3
    assert all(item.candidate_id.startswith("research-candidate-") for item in artifact.candidates)
    assert artifact.review.selected_candidate_numbers == (1,)
    assert artifact.review.selected_candidate_ids == (artifact.candidates[0].candidate_id,)
    assert artifact.plan_context_payload()["最终研究目标"] == (
        "检验素数局部结构是否偏离匹配置换对照。"
    )

    persisted = ContestResearchObjectiveStageArtifact.model_validate_json(
        _inside(tmp_path, artifact.artifact_relative_path).read_text(encoding="utf-8")
    )
    assert persisted.artifact_hash == artifact.artifact_hash

    for call in completion.calls:
        messages = call["messages"]
        assert [message["role"] for message in messages] == [
            "system",
            "user",
            "user",
            "user",
        ]
        assert _QUESTION not in messages[0]["content"]
        assert _SKILL not in messages[0]["content"]
        assert _QUESTION in messages[1]["content"]
        assert json.loads(messages[2]["content"])["技能正文"] == _SKILL
        schema = call["response_schema"]
        assert not {"id", "hash", "status"}.intersection(schema["properties"])
    brainstorm_instructions = [
        json.loads(call["messages"][-1]["content"])["任务指令"]
        for call in completion.calls
        if json.loads(call["messages"][-1]["content"])["派工编号"].startswith(
            "objective-brainstorm-"
        )
    ]
    assert any(
        all(term in instruction for term in ("普通工作站", "数据", "对照", "指标", "失败判据"))
        for instruction in brainstorm_instructions
    )


def test_review_transport_timeout_gets_one_fresh_capability_retry(tmp_path: Path) -> None:
    completion = _ObjectiveCompletion(review_failure_mode="transport_once")
    artifact, completion, _, original_review_capability = _run(
        tmp_path,
        suffix="transport-retry",
        completion=completion,
    )

    assert completion.review_call_count == 2
    assert len(completion.calls) == 5
    assert artifact.review_model_call_count == 2
    assert artifact.model_call_count == 5
    assert len(artifact.review_attempt_batches) == 2
    assert len(artifact.review_attempt_controllers) == 2
    failed_attempt, successful_attempt = artifact.review_attempt_batches
    first_controller, second_controller = artifact.review_attempt_controllers
    assert failed_attempt.failed_count == 1
    assert successful_attempt.succeeded_count == 1
    assert artifact.review_batch.artifact_hash == successful_attempt.artifact_hash
    assert failed_attempt.batch_id != successful_attempt.batch_id
    assert failed_attempt.controller_binding_hash != successful_attempt.controller_binding_hash
    assert artifact.review_controller_binding_hash == successful_attempt.controller_binding_hash
    assert first_controller.lineage_id == second_controller.lineage_id
    assert first_controller.stage == second_controller.stage
    assert second_controller.stage_attempt == first_controller.stage_attempt + 1
    assert not original_review_capability.active
    assert artifact.plan_context_payload()["评审模型调用次数"] == 2
    for batch in artifact.review_attempt_batches:
        record = batch.task_records[0]
        archive = TemporaryAgentArchiveRecord.model_validate_json(
            _inside(tmp_path, record.archive_relative_path).read_text(encoding="utf-8")
        )
        assert archive.runtime_identity_inactive
        assert archive.runtime_identity_removed


@pytest.mark.parametrize("failure_mode", ["format", "ordinary"])
def test_non_transport_review_failures_are_not_retried(
    tmp_path: Path,
    failure_mode: str,
) -> None:
    (
        brainstorm_controller,
        brainstorm_capability,
        review_controller,
        review_capability,
    ) = _controllers(suffix=f"no-retry-{failure_mode}")
    completion = _ObjectiveCompletion(review_failure_mode=failure_mode)

    with pytest.raises(
        ContestResearchObjectiveStageError,
        match="without a retryable transport error",
    ) as caught:
        run_contest_research_objective_stage(
            mode="specified_question",
            seed_text=_QUESTION,
            requirements=_REQUIREMENTS,
            seed_ref=_input_ref(_QUESTION),
            parent_task_id="contest-research-plan-main",
            brainstorm_controller=brainstorm_controller,
            brainstorm_capability=brainstorm_capability,
            review_controller=review_controller,
            review_capability=review_capability,
            output_dir=tmp_path,
            selected_skill_contexts=(_skill_context(),),
            brainstorm_completion=completion,
            review_completion=completion,
            clock=_NOW,
        )

    assert completion.review_call_count == 1
    assert len(caught.value.review_attempt_batches) == 1
    assert caught.value.review_attempt_batches[0].failed_count == 1
    assert not brainstorm_capability.active
    assert not review_capability.active


def test_two_transport_failures_stop_and_revoke_both_capabilities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        brainstorm_controller,
        brainstorm_capability,
        review_controller,
        review_capability,
    ) = _controllers(suffix="transport-twice")
    completion = _ObjectiveCompletion(review_failure_mode="transport_always")
    issued_retry_capabilities: list[StageDispatchCapability] = []
    issued_retry_controllers: list[StageControllerBinding] = []
    real_issue_stage_controller = objective_stage_module.issue_stage_controller

    def tracking_issue_stage_controller(
        **kwargs: Any,
    ) -> tuple[StageControllerBinding, StageDispatchCapability]:
        controller, capability = real_issue_stage_controller(**kwargs)
        issued_retry_controllers.append(controller)
        issued_retry_capabilities.append(capability)
        return controller, capability

    monkeypatch.setattr(
        objective_stage_module,
        "issue_stage_controller",
        tracking_issue_stage_controller,
    )

    with pytest.raises(
        ContestResearchObjectiveStageError,
        match="after one transport retry",
    ) as caught:
        run_contest_research_objective_stage(
            mode="specified_question",
            seed_text=_QUESTION,
            requirements=_REQUIREMENTS,
            seed_ref=_input_ref(_QUESTION),
            parent_task_id="contest-research-plan-main",
            brainstorm_controller=brainstorm_controller,
            brainstorm_capability=brainstorm_capability,
            review_controller=review_controller,
            review_capability=review_capability,
            output_dir=tmp_path,
            selected_skill_contexts=(_skill_context(),),
            brainstorm_completion=completion,
            review_completion=completion,
            clock=_NOW,
        )

    assert completion.review_call_count == 2
    assert len(caught.value.review_attempt_batches) == 2
    assert all(batch.failed_count == 1 for batch in caught.value.review_attempt_batches)
    assert caught.value.review_attempt_batches[0].batch_id != (
        caught.value.review_attempt_batches[1].batch_id
    )
    assert caught.value.review_attempt_batches[0].controller_binding_hash != (
        caught.value.review_attempt_batches[1].controller_binding_hash
    )
    assert not brainstorm_capability.active
    assert not review_capability.active
    assert len(issued_retry_capabilities) == 1
    assert not issued_retry_capabilities[0].active
    assert len(issued_retry_controllers) == 1
    assert issued_retry_controllers[0].lineage_id == review_controller.lineage_id
    assert issued_retry_controllers[0].stage == review_controller.stage
    assert issued_retry_controllers[0].stage_attempt == review_controller.stage_attempt + 1
    for batch in caught.value.review_attempt_batches:
        record = batch.task_records[0]
        archive = TemporaryAgentArchiveRecord.model_validate_json(
            _inside(tmp_path, record.archive_relative_path).read_text(encoding="utf-8")
        )
        assert archive.runtime_identity_removed


def test_direction_mode_consumes_only_provenance_bearing_retrieved_catalog(
    tmp_path: Path,
) -> None:
    artifact, completion, _, _ = _run(
        tmp_path,
        suffix="direction",
        mode="specified_direction",
        literature=_LITERATURE,
    )

    assert artifact.mode == "specified_direction"
    assert len(artifact.literature_catalog) == 1
    assert artifact.literature_catalog[0].record_id.startswith("retrieved-literature-")
    assert artifact.review.reference_indices == (1,)
    context = artifact.plan_context_payload()
    assert context["采用的真实文献"] == [
        {
            "目录编号": 1,
            "题名": "Small gaps between primes",
            "来源链接": "https://annals.math.princeton.edu/2015/181-1/p07",
            "检索来源": "OpenAlex",
            "检索时间": "2026-08-11T11:00:00Z",
        }
    ]
    assert all(
        "Small gaps between primes" in call["messages"][1]["content"] for call in completion.calls
    )


@pytest.mark.parametrize("failed_ordinals", [{1}, {1, 2, 3}])
def test_brainstorm_failures_degrade_but_do_not_skip_successful_reviewer(
    tmp_path: Path,
    failed_ordinals: set[int],
) -> None:
    completion = _ObjectiveCompletion(failed_brainstorm_ordinals=failed_ordinals)
    artifact, _, _, review_capability = _run(
        tmp_path,
        suffix=f"degraded-{len(failed_ordinals)}",
        completion=completion,
    )

    assert artifact.status == "degraded"
    assert artifact.candidate_count == 3 - len(failed_ordinals)
    assert artifact.review_batch.succeeded_count == 1
    assert not review_capability.active
    assert artifact.plan_context_payload()["最终研究目标"]


def test_unknown_brainstorm_reference_is_rejected_before_review_context(
    tmp_path: Path,
) -> None:
    completion = _ObjectiveCompletion(brainstorm_reference_indices=[99])
    artifact, _, _, _ = _run(
        tmp_path,
        suffix="candidate-unknown-reference",
        completion=completion,
    )

    assert artifact.status == "degraded"
    assert artifact.candidate_count == 0
    assert len(artifact.rejected_candidate_dispatch_ids) == 3
    assert artifact.review.selected_candidate_numbers == ()


def test_unknown_reviewer_candidate_number_is_a_hard_failure(tmp_path: Path) -> None:
    (
        brainstorm_controller,
        brainstorm_capability,
        review_controller,
        review_capability,
    ) = _controllers(suffix="invalid-review")
    completion = _ObjectiveCompletion(review_candidate_numbers=[99])

    with pytest.raises(ContestResearchObjectiveStageError, match="unknown index"):
        run_contest_research_objective_stage(
            mode="specified_question",
            seed_text=_QUESTION,
            requirements=_REQUIREMENTS,
            seed_ref=_input_ref(_QUESTION),
            parent_task_id="contest-research-plan-main",
            brainstorm_controller=brainstorm_controller,
            brainstorm_capability=brainstorm_capability,
            review_controller=review_controller,
            review_capability=review_capability,
            output_dir=tmp_path,
            selected_skill_contexts=(_skill_context(),),
            brainstorm_completion=completion,
            review_completion=completion,
            clock=_NOW,
        )

    assert completion.review_call_count == 1
    assert not brainstorm_capability.active
    assert not review_capability.active


def test_optional_reviewer_scientific_content_must_remain_chinese(tmp_path: Path) -> None:
    completion = _ObjectiveCompletion(
        review_main_hypothesis="Local order contains extra information."
    )

    with pytest.raises(ContestResearchObjectiveStageError, match="must be Chinese"):
        _run(
            tmp_path,
            suffix="english-review-content",
            completion=completion,
        )
    assert completion.review_call_count == 1


def test_direction_without_real_catalog_fails_before_dispatch(tmp_path: Path) -> None:
    (
        brainstorm_controller,
        brainstorm_capability,
        review_controller,
        review_capability,
    ) = _controllers(suffix="no-literature")
    completion = _ObjectiveCompletion(direction=True)

    with pytest.raises(ContestResearchObjectiveStageError, match="real retrieved literature"):
        run_contest_research_objective_stage(
            mode="specified_direction",
            seed_text=_DIRECTION,
            requirements=_REQUIREMENTS,
            seed_ref=_input_ref(_DIRECTION),
            parent_task_id="contest-research-plan-main",
            brainstorm_controller=brainstorm_controller,
            brainstorm_capability=brainstorm_capability,
            review_controller=review_controller,
            review_capability=review_capability,
            output_dir=tmp_path,
            selected_skill_contexts=(_skill_context(),),
            brainstorm_completion=completion,
            review_completion=completion,
            clock=_NOW,
        )

    assert completion.calls == []
    assert brainstorm_capability.active
    assert review_capability.active


def test_direction_reviewer_must_bind_objective_to_known_literature(tmp_path: Path) -> None:
    completion = _ObjectiveCompletion(direction=True, review_reference_indices=[])

    with pytest.raises(ContestResearchObjectiveStageError, match="cite at least one"):
        _run(
            tmp_path,
            suffix="direction-no-reference",
            mode="specified_direction",
            completion=completion,
            literature=_LITERATURE,
        )
