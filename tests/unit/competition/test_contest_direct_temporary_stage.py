from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from autoresearch.agents.temporary import (
    StageControllerBinding,
    StageDispatchCapability,
    TemporaryAgentArchiveRecord,
    TemporaryAgentContractError,
    TemporaryAgentInputRef,
    TemporaryAgentSkillRef,
    TemporaryAgentTaskKind,
    issue_stage_controller,
)
from autoresearch.competition.contest_direct_temporary_stage import (
    ContestDirectTemporaryStageArtifact,
    build_contest_first_question_temporary_tasks,
    run_contest_first_question_temporary_stage,
)
from autoresearch.competition.temporary_qwen_pool import (
    TemporaryQwenPoolError,
    TemporaryQwenSkillContext,
)
from autoresearch.kernel.contracts import canonical_sha256
from autoresearch.llm.client import LLMJsonCompletionResult

_NOW = datetime(2026, 8, 11, 10, 0, tzinfo=timezone.utc)
_QUESTION = "素数为何如此特别？"
_REQUIREMENTS = "生成中文科学假设与研究计划所需的候选意见，不虚构实验结果。"
_SKILL = "# 计算研究方法\n\n先形成可证伪问题，再设置匹配对照与失败判据。\n"
_LITERATURE = (
    "Maynard, Small gaps between primes, Annals of Mathematics, 2015.",
    "Granville, Harald Cramer and the distribution of prime numbers, 1995.",
)


def _question_ref() -> TemporaryAgentInputRef:
    return TemporaryAgentInputRef(
        artifact_id="science125-question-001",
        source_ref="question-input.json",
        sha256=canonical_sha256({"question": _QUESTION}),
    )


def _skill_context() -> TemporaryQwenSkillContext:
    return TemporaryQwenSkillContext(
        skill_ref=TemporaryAgentSkillRef(
            skill_id="prime-computational-method",
            source_ref="skills/prime-computational-method/SKILL.md",
            content_sha256=hashlib.sha256(_SKILL.encode("utf-8")).hexdigest(),
        ),
        content=_SKILL,
    )


def _controller(
    *, suffix: str = "a", parallel: int = 3
) -> tuple[StageControllerBinding, StageDispatchCapability]:
    return issue_stage_controller(
        lineage_id=f"contest-first-question-{suffix}",
        stage="direct-research-plan",
        stage_attempt=1,
        controller_agent_id=f"direct-plan-main-{suffix}",
        stage_input_hash="a" * 64,
        max_parallel_agents=parallel,
        claimed_at=_NOW,
        lease_token=f"contest-stage-token-{suffix}-0001",
    )


class _ParallelThreeRoleCompletion:
    def __init__(self, *, fail_count: int = 0) -> None:
        self.barrier = threading.Barrier(3)
        self.lock = threading.Lock()
        self.calls: list[dict[str, Any]] = []
        self.overlapped: set[str] = set()
        self.fail_count = fail_count

    def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult:
        task_message = json.loads(kwargs["messages"][-1]["content"])
        dispatch_id = str(task_message["派工编号"])
        schema = kwargs["response_schema"]
        with self.lock:
            self.calls.append(kwargs)
            self.overlapped.add(dispatch_id)
            should_fail = len(self.calls) <= self.fail_count
        self.barrier.wait(timeout=5)
        payload = {
            field: f"{field}：这是临时角色基于显式输入形成的中文候选意见。"
            for field in schema["required"]
        }
        return LLMJsonCompletionResult(
            provider="qwen-dashscope",
            base_url="https://dashscope.example/compatible-mode/v1",
            model_name="qwen3.7-max",
            endpoint="https://dashscope.example/v1/chat/completions",
            response_text=json.dumps(payload, ensure_ascii=False),
            parsed_json=payload,
            usage={"reasoning_tokens": 128},
            temperature=float(kwargs["temperature"]),
            reasoning_text=(
                ""
                if should_fail
                else "先理解科学问题，再按临时角色边界形成可证伪且不过度外推的建议。"
            ),
            reasoning_transport="dashscope_enable_thinking",
        )


def _inside(root: Path, relative_path: str) -> Path:
    path = (root / Path(*PurePosixPath(relative_path).parts)).resolve()
    path.relative_to(root.resolve())
    return path


def test_builds_exact_three_deterministic_content_only_roles() -> None:
    first = build_contest_first_question_temporary_tasks(
        question=_QUESTION,
        requirements=_REQUIREMENTS,
        question_ref=_question_ref(),
        parent_task_id="contest-direct-plan-main-task",
        selected_skill_contexts=(_skill_context(),),
        literature_catalog=_LITERATURE,
    )
    second = build_contest_first_question_temporary_tasks(
        question=_QUESTION,
        requirements=_REQUIREMENTS,
        question_ref=_question_ref(),
        parent_task_id="contest-direct-plan-main-task",
        selected_skill_contexts=(_skill_context(),),
        literature_catalog=_LITERATURE,
    )

    assert first == second
    assert len(first) == 3
    assert [item.task_kind for item in first] == [
        TemporaryAgentTaskKind.OPPORTUNITY_MEMO,
        TemporaryAgentTaskKind.CONTENT_CHECKLIST,
        TemporaryAgentTaskKind.ADVERSARIAL_CRITIQUE,
    ]
    assert len({item.dispatch_id for item in first}) == 3
    assert len({item.temporary_agent_id for item in first}) == 3
    assert all(item.parent_task_id == "contest-direct-plan-main-task" for item in first)
    assert all(item.skill_contexts == (_skill_context(),) for item in first)
    assert all(item.max_attempts == 1 for item in first)
    assert all(item.chinese_output_fields == ("memo_cn",) for item in first)
    assert all(item.expected_output_schema["required"] == ["memo_cn"] for item in first)
    assert all(item.input_payload["可用文献编号目录"] for item in first)


def test_current_main_controller_runs_in_parallel_then_archives_every_identity(
    tmp_path: Path,
) -> None:
    controller, capability = _controller()
    completion = _ParallelThreeRoleCompletion()

    artifact = run_contest_first_question_temporary_stage(
        question=_QUESTION,
        requirements=_REQUIREMENTS,
        question_ref=_question_ref(),
        parent_task_id="contest-direct-plan-main-task",
        controller=controller,
        capability=capability,
        output_dir=tmp_path,
        selected_skill_contexts=(_skill_context(),),
        completion=completion,
        clock=_NOW,
    )

    assert len(completion.calls) == 3
    assert len(completion.overlapped) == 3
    assert not capability.active
    assert artifact.controller_binding_hash == controller.binding_hash
    assert artifact.batch.dispatched_count == 3
    assert artifact.batch.succeeded_count == 3
    assert artifact.status == "complete"
    assert artifact.unavailable_roles == ()
    assert [item.role for item in artifact.contributions] == [
        "hypothesis_candidates",
        "experiment_design",
        "adversarial_critique",
    ]
    assert artifact.all_runtime_identities_removed
    assert artifact.outputs_and_receipts_retained
    suggestions = artifact.plan_context_payload()["临时建议"]
    assert isinstance(suggestions, list)
    assert len(suggestions) == 3

    persisted = ContestDirectTemporaryStageArtifact.model_validate_json(
        _inside(tmp_path, artifact.artifact_relative_path).read_text(encoding="utf-8")
    )
    assert persisted.artifact_hash == artifact.artifact_hash
    for record in artifact.batch.task_records:
        archive = TemporaryAgentArchiveRecord.model_validate_json(
            _inside(tmp_path, record.archive_relative_path).read_text(encoding="utf-8")
        )
        assert archive.runtime_identity_inactive
        assert archive.runtime_identity_removed
        assert record.result_relative_path is not None
        assert record.authorship_receipt_relative_path is not None
        assert _inside(tmp_path, record.result_relative_path).is_file()
        assert _inside(tmp_path, record.authorship_receipt_relative_path).is_file()

    for call in completion.calls:
        assert call["thinking_mode"] == "enabled"
        assert [message["role"] for message in call["messages"]] == [
            "system",
            "user",
            "user",
            "user",
        ]
        assert _SKILL not in call["messages"][0]["content"]
        assert _QUESTION in call["messages"][1]["content"]
        assert json.loads(call["messages"][2]["content"])["技能正文"] == _SKILL
        assert "可再派工" in call["messages"][-1]["content"]


@pytest.mark.parametrize("fail_count", [1, 3])
def test_agent_failures_return_degraded_context_without_blocking_main_plan(
    tmp_path: Path,
    fail_count: int,
) -> None:
    controller, capability = _controller(suffix=f"degraded-{fail_count}")

    artifact = run_contest_first_question_temporary_stage(
        question=_QUESTION,
        requirements=_REQUIREMENTS,
        question_ref=_question_ref(),
        parent_task_id="contest-direct-plan-main-task",
        controller=controller,
        capability=capability,
        output_dir=tmp_path,
        completion=_ParallelThreeRoleCompletion(fail_count=fail_count),
        clock=_NOW,
    )

    assert artifact.status == "degraded"
    assert artifact.batch.failed_count == fail_count
    assert len(artifact.contributions) == 3 - fail_count
    assert len(artifact.unavailable_roles) == fail_count
    assert not capability.active
    assert artifact.plan_context_payload()["运行状态"] == "degraded"
    for record in artifact.batch.task_records:
        archive = TemporaryAgentArchiveRecord.model_validate_json(
            _inside(tmp_path, record.archive_relative_path).read_text(encoding="utf-8")
        )
        assert archive.runtime_identity_removed


def test_rejects_another_controller_capability_before_any_completion(tmp_path: Path) -> None:
    controller, _ = _controller(suffix="owner")
    _, wrong_capability = _controller(suffix="other")
    completion = _ParallelThreeRoleCompletion()

    with pytest.raises(TemporaryAgentContractError, match="another controller|belongs to another"):
        run_contest_first_question_temporary_stage(
            question=_QUESTION,
            requirements=_REQUIREMENTS,
            question_ref=_question_ref(),
            parent_task_id="contest-direct-plan-main-task",
            controller=controller,
            capability=wrong_capability,
            output_dir=tmp_path,
            completion=completion,
            clock=_NOW,
        )

    assert completion.calls == []


def test_rejects_controller_without_three_parallel_slots(tmp_path: Path) -> None:
    controller, capability = _controller(parallel=2)

    with pytest.raises(TemporaryQwenPoolError, match="at least three"):
        run_contest_first_question_temporary_stage(
            question=_QUESTION,
            requirements=_REQUIREMENTS,
            question_ref=_question_ref(),
            parent_task_id="contest-direct-plan-main-task",
            controller=controller,
            capability=capability,
            output_dir=tmp_path,
            completion=_ParallelThreeRoleCompletion(),
            clock=_NOW,
        )
