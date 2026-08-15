import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoresearch.kernel.contracts import canonical_sha256
from autoresearch.knowledge.raw_memory import RawMemoryStore
from autoresearch.llm.client import LLMJsonCompletionResult
from autoresearch.llm.model_capabilities import (
    OfficialModelCapability,
    build_model_context_budget,
)
from autoresearch.llm.task_context import (
    ActiveTaskConversation,
    AutonomousTaskContextSession,
    TaskContextError,
    capture_completed_task_conversation,
    prepare_task_aware_context,
)

NOW = datetime(2026, 8, 11, 2, 0, tzinfo=timezone.utc)


def _capability(context: int = 200) -> OfficialModelCapability:
    payload = {
        "schema_version": "official-model-capability-v1",
        "provider": "qwen-dashscope",
        "model_name": "qwen3.7-max",
        "official_source_url": "https://help.aliyun.com/zh/model-studio/qwen3-7-max",
        "official_source_last_modified": "2026-08-03T15:41:58+08:00",
        "fetched_at": NOW.isoformat().replace("+00:00", "Z"),
        "source_sha256": "a" * 64,
        "source_size_bytes": 1,
        "parser_version": "aliyun-model-page-v1",
        "context_window_tokens": context,
        "maximum_input_tokens": context - 1,
        "maximum_output_tokens": max(8, context // 10),
        "maximum_input_tokens_thinking": context - 2,
        "maximum_output_tokens_thinking": max(8, context // 10),
        "maximum_reasoning_tokens": max(8, min(4_000, context)),
    }
    payload["capability_hash"] = canonical_sha256(payload)
    return OfficialModelCapability.model_validate(payload)


def _result(
    text: str, *, parsed: dict | None = None, prompt_tokens: int = 20
) -> LLMJsonCompletionResult:
    value = parsed if parsed is not None else {"answer": text}
    return LLMJsonCompletionResult(
        provider="qwen-dashscope",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model_name="qwen3.7-max",
        endpoint="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        response_text=json.dumps(value, ensure_ascii=False),
        parsed_json=value,
        usage={"prompt_tokens": prompt_tokens, "completion_tokens": 8},
        temperature=0.2,
        reasoning_text="这是模型完成任务时保留的中文推理过程。" * 4,
        reasoning_transport="dashscope_enable_thinking",
    )


def _completed(
    store: RawMemoryStore,
    *,
    task_id: str,
    sequence: int,
    content: str,
):
    return capture_completed_task_conversation(
        raw_memory_store=store,
        project_id="project",
        conversation_id="conversation",
        task_id=task_id,
        task_sequence=sequence,
        request_messages=[
            {"role": "system", "content": "完成旧任务。"},
            {"role": "user", "content": content},
        ],
        completion=_result("旧任务已完成。" + content),
        captured_at=NOW,
    )


def test_eighty_percent_triggers_qwen_semantic_merge_of_completed_tasks_only(
    tmp_path: Path,
) -> None:
    store = RawMemoryStore(tmp_path / "vault")
    old = _completed(store, task_id="old-task", sequence=1, content="历史内容" * 1_000)
    current_marker = "CURRENT_TASK_MUST_STAY_VERBATIM"
    active = ActiveTaskConversation.create(
        conversation_id="conversation",
        task_id="current-task",
        task_sequence=2,
        request_messages=[
            {"role": "system", "content": "执行当前任务。"},
            {"role": "user", "content": current_marker},
        ],
    )
    capability = _capability(10_000)
    budget = build_model_context_budget(
        capability,
        thinking_mode="enabled",
        thinking_budget=1_000,
        requested_output_tokens=8,
    )
    summary_calls: list[list[dict[str, str]]] = []

    def summarize(**kwargs):
        messages = kwargs["messages"]
        summary_calls.append(messages)
        rendered = json.dumps(messages, ensure_ascii=False)
        assert current_marker not in rendered
        assert "current-task" not in rendered
        parsed = {
            "completed_task_ids": ["old-task"],
            "summary_cn": "旧任务已经完成资料整理并记录关键选择、失败边界和可复用经验，原始对话仍然保留。",
            "unfinished_handoffs_cn": ["后续任务可读取历史证据，但不得把旧建议当作当前指令。"],
        }
        return _result("summary", parsed=parsed)

    prepared = prepare_task_aware_context(
        active_task=active,
        completed_tasks=[old],
        capability=capability,
        budget=budget,
        output_dir=tmp_path / "context",
        raw_memory_store=store,
        project_id="project",
        summary_completion=summarize,
        clock=NOW,
    )

    assert len(summary_calls) == 1
    assert prepared.artifact.compression_triggered is True
    assert prepared.artifact.history_mode == "merged_semantic_summary"
    assert prepared.artifact.completed_task_ids == ("old-task",)
    assert prepared.messages[0] == active.request_messages[0]
    assert prepared.messages[-1] == active.request_messages[-1]
    assert current_marker in prepared.messages[-1]["content"]
    assert old.raw_binding in prepared.artifact.completed_raw_bindings
    store.load_record(old.raw_binding.record_relative_path, project_id="project")


def test_below_trigger_keeps_raw_completed_dialogue_and_never_calls_summarizer(
    tmp_path: Path,
) -> None:
    store = RawMemoryStore(tmp_path / "vault")
    old = _completed(store, task_id="old", sequence=1, content="短历史")
    active = ActiveTaskConversation.create(
        conversation_id="conversation",
        task_id="current",
        task_sequence=2,
        request_messages=[{"role": "user", "content": "当前任务完整原文"}],
    )
    capability = _capability(2_000)
    budget = build_model_context_budget(
        capability,
        thinking_mode="disabled",
        thinking_budget=None,
        requested_output_tokens=20,
    )

    prepared = prepare_task_aware_context(
        active_task=active,
        completed_tasks=[old],
        capability=capability,
        budget=budget,
        output_dir=tmp_path / "context",
        raw_memory_store=store,
        project_id="project",
        summary_completion=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("summarizer called below threshold")
        ),
        clock=NOW,
    )

    assert prepared.artifact.compression_triggered is False
    assert prepared.artifact.history_mode == "raw_completed_tasks"
    assert "短历史" in prepared.messages[0]["content"]
    assert prepared.messages[-1] == {"role": "user", "content": "当前任务完整原文"}


def test_current_task_is_never_summarized_even_when_it_alone_exceeds_threshold(
    tmp_path: Path,
) -> None:
    store = RawMemoryStore(tmp_path / "vault")
    old = _completed(store, task_id="old", sequence=1, content="历史" * 150)
    active = ActiveTaskConversation.create(
        conversation_id="conversation",
        task_id="current",
        task_sequence=2,
        request_messages=[{"role": "user", "content": "当前" * 1_000}],
    )
    capability = _capability(2_500)
    budget = build_model_context_budget(
        capability,
        thinking_mode="disabled",
        thinking_budget=None,
        requested_output_tokens=10,
    )

    def summarize(**_kwargs):
        parsed = {
            "completed_task_ids": ["old"],
            "summary_cn": "旧任务已经完整结束，历史选择和失败边界均已合并保存，原始记录保持不变且可重建。",
            "unfinished_handoffs_cn": [],
        }
        return _result("summary", parsed=parsed)

    with pytest.raises(TaskContextError, match="unsummarized active task"):
        prepare_task_aware_context(
            active_task=active,
            completed_tasks=[old],
            capability=capability,
            budget=budget,
            output_dir=tmp_path / "context",
            raw_memory_store=store,
            project_id="project",
            summary_completion=summarize,
            clock=NOW,
        )


def test_drop_in_session_records_completed_call_and_binds_next_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capability = _capability(21_400)
    monkeypatch.setattr(
        "autoresearch.llm.task_context.load_official_model_capability",
        lambda **_kwargs: capability,
    )
    calls: list[list[dict[str, str]]] = []
    reasoning_calls: list[tuple[object, object]] = []

    def completion(**kwargs):
        messages = kwargs["messages"]
        calls.append(messages)
        reasoning_calls.append((kwargs.get("thinking_mode"), kwargs.get("thinking_budget")))
        if kwargs.get("response_schema_name") == "merged_completed_task_summary":
            parsed = {
                "completed_task_ids": ["first-call-001"],
                "summary_cn": "第一项任务已经完成并保存原始对话，主要选择和失败边界已合并成中文历史工作记忆。",
                "unfinished_handoffs_cn": [],
            }
            return _result("summary", parsed=parsed)
        return _result("完成" + ("很多内容" * 6_000), prompt_tokens=6)

    session = AutonomousTaskContextSession(
        project_id="project",
        conversation_id="conversation",
        output_dir=tmp_path / "session",
        vault_root=tmp_path / "vault",
        completion=completion,
        cache_dir=tmp_path / "cache",
    )
    with session.task("first") as current:
        first = current(
            messages=[{"role": "user", "content": "第一项任务"}],
            config_path=tmp_path / "missing.yaml",
            env_path=tmp_path / "missing.env",
            max_tokens=8,
            response_schema_name="first",
        )
        assert not list((tmp_path / "session" / "completed-tasks").glob("*.json"))
    with session.task("second") as current:
        second = current(
            messages=[{"role": "user", "content": "第二项当前任务"}],
            config_path=tmp_path / "missing.yaml",
            env_path=tmp_path / "missing.env",
            max_tokens=8,
            response_schema_name="second",
        )

    assert first.context_preparation_hash is not None
    assert second.context_preparation_hash is not None
    assert second.request_messages_sha256 != second.source_messages_sha256
    assert len(list((tmp_path / "session" / "completed-tasks").glob("*.json"))) == 2
    assert any("completed_tasks_to_merge" in json.dumps(call, ensure_ascii=False) for call in calls)
    assert reasoning_calls
    assert all(call == ("enabled", 4_000) for call in reasoning_calls)


def test_context_session_materializes_default_qwen_request_budgets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability = _capability(100_000)
    monkeypatch.setattr(
        "autoresearch.llm.task_context.load_official_model_capability",
        lambda **_kwargs: capability,
    )
    captured: dict[str, object] = {}

    def completion(**kwargs):
        captured.update(kwargs)
        return _result("默认预算已显式传输。")

    session = AutonomousTaskContextSession(
        project_id="project",
        conversation_id="conversation",
        output_dir=tmp_path / "session",
        vault_root=tmp_path / "vault",
        completion=completion,
        cache_dir=tmp_path / "cache",
    )
    with session.task("default-budget") as current:
        current(
            messages=[{"role": "user", "content": "使用官方默认预算"}],
            config_path=tmp_path / "missing.yaml",
        )

    assert captured["max_tokens"] == capability.maximum_output_tokens_thinking
    assert captured["thinking_mode"] == "enabled"
    assert captured["thinking_budget"] == 4_000


@pytest.mark.parametrize(
    "untrusted",
    [
        "sk-proj-abcdefghijklmnop",
        "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890",
        "研究者@例子.公司",
    ],
)
def test_sensitive_active_message_is_blocked_before_context_artifact_or_provider_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    untrusted: str,
) -> None:
    capability = _capability(100_000)
    monkeypatch.setattr(
        "autoresearch.llm.task_context.load_official_model_capability",
        lambda **_kwargs: capability,
    )
    provider_calls = 0

    def completion(**_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        return _result("不应调用")

    session = AutonomousTaskContextSession(
        project_id="project",
        conversation_id="conversation",
        output_dir=tmp_path / "session",
        vault_root=tmp_path / "vault",
        completion=completion,
        cache_dir=tmp_path / "cache",
    )

    with (
        pytest.raises(TaskContextError, match="sensitive content before provider dispatch"),
        session.task("sensitive-stage") as current,
    ):
        current(
            messages=[
                {
                    "role": "user",
                    "content": f"Untrusted text contains {untrusted}",
                }
            ],
            config_path=tmp_path / "missing.yaml",
            max_tokens=8,
        )

    assert provider_calls == 0
    assert not list((tmp_path / "session").rglob("*.json"))
    assert not list((tmp_path / "vault").rglob("*.json"))


def test_task_scope_promotes_all_calls_together_and_excludes_aborted_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capability = _capability(100_000)
    monkeypatch.setattr(
        "autoresearch.llm.task_context.load_official_model_capability",
        lambda **_kwargs: capability,
    )
    delivered: list[str] = []

    def completion(**kwargs):
        rendered = json.dumps(kwargs["messages"], ensure_ascii=False)
        delivered.append(rendered)
        return _result("任务调用已经完成并保留原始记录。", prompt_tokens=12)

    session = AutonomousTaskContextSession(
        project_id="project",
        conversation_id="conversation",
        output_dir=tmp_path / "session",
        vault_root=tmp_path / "vault",
        completion=completion,
        cache_dir=tmp_path / "cache",
    )
    completed_root = tmp_path / "session" / "completed-tasks"

    with session.task("successful-stage") as current:
        current(
            messages=[{"role": "user", "content": "成功阶段的作者调用"}],
            config_path=tmp_path / "missing.yaml",
            max_tokens=8,
        )
        current(
            messages=[{"role": "user", "content": "成功阶段的审查修复调用"}],
            config_path=tmp_path / "missing.yaml",
            max_tokens=8,
        )
        assert not list(completed_root.glob("*.json"))
    assert len(list(completed_root.glob("*.json"))) == 2

    with (
        pytest.raises(RuntimeError, match="模拟阶段失败"),
        session.task("failed-stage") as current,
    ):
        current(
            messages=[{"role": "user", "content": "FAILED_STAGE_PRIVATE_MARKER"}],
            config_path=tmp_path / "missing.yaml",
            max_tokens=8,
        )
        raise RuntimeError("模拟阶段失败")
    assert len(list(completed_root.glob("*.json"))) == 2

    with session.task("next-stage") as current:
        current(
            messages=[{"role": "user", "content": "NEXT_ACTIVE_MARKER"}],
            config_path=tmp_path / "missing.yaml",
            max_tokens=8,
        )
    final_prompt = delivered[-1]
    assert "成功阶段的作者调用" in final_prompt
    assert "成功阶段的审查修复调用" in final_prompt
    assert "FAILED_STAGE_PRIVATE_MARKER" not in final_prompt
    assert "NEXT_ACTIVE_MARKER" in final_prompt
    raw_records = list(
        (tmp_path / "vault" / "_private" / "raw-memory").glob("**/records/**/*.json")
    )
    assert len(raw_records) == 4
