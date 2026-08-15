from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoresearch.competition.contest_direction_context_runtime import (
    ContestDirectionContextRuntime,
)
from autoresearch.competition.contest_direction_stage_checkpoint import (
    replayable_stage_completion,
)
from autoresearch.kernel.contracts import canonical_sha256
from autoresearch.llm.client import LLMJsonCompletionResult, run_llm_json_completion
from autoresearch.llm.model_capabilities import OfficialModelCapability
from autoresearch.llm.task_context import TaskContextPreparationArtifact

NOW = datetime(2026, 8, 12, 6, 0, tzinfo=timezone.utc)


class _FakeTransportResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body
        self.status = 200
        self.headers = {"Content-Type": "application/json; charset=utf-8"}

    def __enter__(self) -> _FakeTransportResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _capability() -> OfficialModelCapability:
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
        "context_window_tokens": 50_000,
        "maximum_input_tokens": 49_900,
        "maximum_output_tokens": 1_000,
        "maximum_input_tokens_thinking": 49_800,
        "maximum_output_tokens_thinking": 1_000,
        "maximum_reasoning_tokens": 8_000,
    }
    payload["capability_hash"] = canonical_sha256(payload)
    return OfficialModelCapability.model_validate(payload)


def _completion_result(
    parsed: dict[str, object], *, prompt_tokens: int = 20
) -> LLMJsonCompletionResult:
    return LLMJsonCompletionResult(
        provider="qwen-dashscope",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model_name="qwen3.7-max",
        endpoint="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        response_text=json.dumps(parsed, ensure_ascii=False),
        parsed_json=parsed,
        usage={"prompt_tokens": prompt_tokens, "completion_tokens": 8},
        temperature=0.2,
        reasoning_text="模型按阶段完成了当前科研任务。" * 4,
        reasoning_transport="dashscope_enable_thinking",
    )


def test_runtime_compacts_only_prior_completed_stage_and_keeps_raw_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capability = _capability()
    monkeypatch.setattr(
        "autoresearch.llm.task_context.load_official_model_capability",
        lambda **_kwargs: capability,
    )
    current_marker = "CURRENT_STAGE_MUST_REMAIN_EXACT"
    calls: list[list[dict[str, str]]] = []

    def completion(**kwargs: object) -> LLMJsonCompletionResult:
        messages = kwargs["messages"]
        assert isinstance(messages, list)
        calls.append(messages)
        if kwargs.get("response_schema_name") == "merged_completed_task_summary":
            rendered = json.dumps(messages, ensure_ascii=False)
            assert current_marker not in rendered
            return _completion_result(
                {
                    "completed_task_ids": ["literature-query-" + "1" * 16 + "-call-001"],
                    "summary_cn": (
                        "历史检索阶段已经完成，查询选择、返回边界和失败情况均已合并记录，"
                        "原始请求与响应继续保存在不可变主权记忆中。"
                    ),
                    "unfinished_handoffs_cn": [],
                }
            )
        if len(calls) == 1:
            return _completion_result({"result": "x" * 41_000}, prompt_tokens=12)
        return _completion_result({"result": "当前阶段完成"})

    runtime = ContestDirectionContextRuntime(
        direction_id="direction-loop-test",
        output_dir=tmp_path / "context-memory",
        vault_root=tmp_path / "vault",
        completion=completion,
        capability_cache_dir=tmp_path / "cache",
    )
    with runtime.stage("literature-query", input_hash="1" * 64) as stage_completion:
        stage_completion(
            messages=[{"role": "user", "content": "生成真实检索查询"}],
            config_path=tmp_path / "missing.yaml",
            max_tokens=8,
        )
    with runtime.stage("skill-routing", input_hash="2" * 64) as stage_completion:
        result = stage_completion(
            messages=[{"role": "user", "content": current_marker}],
            config_path=tmp_path / "missing.yaml",
            max_tokens=8,
        )

    assert result.context_preparation_hash is not None
    preparations = sorted((tmp_path / "context-memory" / "context-preparations").glob("*.json"))
    artifacts = [
        TaskContextPreparationArtifact.model_validate_json(path.read_text(encoding="utf-8"))
        for path in preparations
    ]
    current = next(item for item in artifacts if item.active_task_id.startswith("skill-routing"))
    assert current.compression_triggered is True
    assert current.budget.official_context_window_tokens == capability.context_window_tokens
    assert current.budget.compression_trigger_tokens == 40_000
    assert current.active_task_excluded_from_summary is True
    assert current.active_task_preserved_verbatim is True
    assert current.delivered_messages[-1]["content"] == current_marker
    assert current.completed_task_ids == ("literature-query-" + "1" * 16 + "-call-001",)
    assert current.completed_raw_bindings
    raw_records = list(
        (tmp_path / "vault" / "_private" / "raw-memory").glob("**/records/**/*.json")
    )
    assert len(raw_records) == 3


def test_runtime_rejects_noncanonical_stage_input_hash(tmp_path: Path) -> None:
    runtime = ContestDirectionContextRuntime(
        direction_id="direction-loop-test",
        output_dir=tmp_path / "context-memory",
        vault_root=tmp_path / "vault",
    )
    with (
        pytest.raises(ValueError, match="canonical SHA-256"),
        runtime.stage("literature-query", input_hash="model-made-id"),
    ):
        pass


def test_checkpoint_replay_still_promotes_completed_context_without_provider_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capability = _capability()
    monkeypatch.setattr(
        "autoresearch.llm.task_context.load_official_model_capability",
        lambda **_kwargs: capability,
    )
    provider_calls = 0

    def provider(**_kwargs: object) -> LLMJsonCompletionResult:
        nonlocal provider_calls
        provider_calls += 1
        return _completion_result({"result": "provider response"})

    messages = [{"role": "user", "content": "阶段输入保持原样"}]
    stage_hash = "3" * 64
    escrow = replayable_stage_completion(
        root=tmp_path / "run",
        stage_name="resume-stage",
        stage_input_hash=stage_hash,
        completion=provider,
    )
    escrow(
        messages=messages,
        config_path=tmp_path / "missing.yaml",
        max_tokens=8,
        thinking_mode="enabled",
        thinking_budget=4_000,
    )
    assert provider_calls == 1

    runtime = ContestDirectionContextRuntime(
        direction_id="direction-loop-resume",
        output_dir=tmp_path / "run" / "context-memory",
        vault_root=tmp_path / "vault",
        completion=provider,
        capability_cache_dir=tmp_path / "cache",
    )
    with runtime.checkpointed_stage(
        "resume-stage",
        input_hash=stage_hash,
        checkpoint_root=tmp_path / "run",
    ) as stage_completion:
        result = stage_completion(
            messages=messages,
            config_path=tmp_path / "missing.yaml",
            max_tokens=8,
        )

    assert provider_calls == 1
    assert result.context_preparation_hash is not None
    completed = list((tmp_path / "run" / "context-memory" / "completed-tasks").glob("*.json"))
    assert len(completed) == 1
    assert "resume-stage-" in completed[0].name


def test_real_context_chain_has_one_checkpoint_owner_and_exactly_one_transport_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capability = _capability()
    monkeypatch.setattr(
        "autoresearch.llm.task_context.load_official_model_capability",
        lambda **_kwargs: capability,
    )
    monkeypatch.setenv("AUTORESEARCH_LLM_API_KEY", "unit-only-placeholder-key")
    calls = 0
    request_ids = iter(
        [
            "request-real-context-retry-0001",
            "request-real-context-retry-0002",
        ]
    )
    raw_body = json.dumps(
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": '{"status":"complete"}'},
                }
            ],
            "usage": {"prompt_tokens": 8, "completion_tokens": 3},
        }
    ).encode("utf-8")

    def opener(_request: urllib.request.Request, *, timeout: int) -> _FakeTransportResponse:
        nonlocal calls
        del timeout
        calls += 1
        if calls == 1:
            raise urllib.error.URLError("synthetic context-chain outage")
        return _FakeTransportResponse(raw_body)

    run_root = tmp_path / "run"
    refinement_root = run_root / "literature" / "refinement"
    runtime = ContestDirectionContextRuntime(
        direction_id="direction-loop-retry-owner",
        output_dir=run_root / "context-memory",
        vault_root=tmp_path / "vault",
        completion=run_llm_json_completion,
        capability_cache_dir=tmp_path / "cache",
    )
    with runtime.checkpointed_stage(
        "focus-selection",
        input_hash="4" * 64,
        checkpoint_root=run_root,
    ) as context_completion:
        nested = replayable_stage_completion(
            root=refinement_root,
            stage_name="direction-focus-selection",
            stage_input_hash="5" * 64,
            completion=context_completion,
        )
        result = nested(
            messages=[{"role": "user", "content": "Select one synthetic focus."}],
            config_path=tmp_path / "missing.yaml",
            env_path=tmp_path / "missing.env",
            max_tokens=32,
            thinking_mode="disabled",
            _http_opener=opener,
            _request_id_factory=lambda: next(request_ids),
        )

    assert result.parsed_json == {"status": "complete"}
    assert calls == 2
    assert len(list((run_root / "checkpoints" / "provider-call-attempts").rglob("*.json"))) == 3
    assert not list((refinement_root / "checkpoints").rglob("*.json"))


def test_context_chain_crash_after_owner_transport_trace_resumes_without_alias_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capability = _capability()
    monkeypatch.setattr(
        "autoresearch.llm.task_context.load_official_model_capability",
        lambda **_kwargs: capability,
    )
    monkeypatch.setenv("AUTORESEARCH_LLM_API_KEY", "unit-only-placeholder-key")
    calls = 0
    first_ids = iter(["request-real-context-crash-0001"])
    raw_body = json.dumps(
        {
            "choices": [{"message": {"content": '{"status":"complete"}'}}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 3},
        }
    ).encode("utf-8")

    def opener(_request: urllib.request.Request, *, timeout: int) -> _FakeTransportResponse:
        nonlocal calls
        del timeout
        calls += 1
        if calls == 1:
            raise urllib.error.URLError("synthetic context-chain outage")
        return _FakeTransportResponse(raw_body)

    def crash_before_attempt_two() -> str:
        try:
            return next(first_ids)
        except StopIteration:
            raise SystemExit("synthetic crash between owner attempts") from None

    run_root = tmp_path / "run"
    refinement_root = run_root / "literature" / "refinement"

    def run_nested(request_id_factory: object) -> LLMJsonCompletionResult:
        runtime = ContestDirectionContextRuntime(
            direction_id="direction-loop-retry-crash",
            output_dir=run_root / "context-memory",
            vault_root=tmp_path / "vault",
            completion=run_llm_json_completion,
            capability_cache_dir=tmp_path / "cache",
        )
        with runtime.checkpointed_stage(
            "focus-selection",
            input_hash="6" * 64,
            checkpoint_root=run_root,
        ) as context_completion:
            nested = replayable_stage_completion(
                root=refinement_root,
                stage_name="direction-focus-selection",
                stage_input_hash="7" * 64,
                completion=context_completion,
            )
            return nested(
                messages=[{"role": "user", "content": "Select one synthetic focus."}],
                config_path=tmp_path / "missing.yaml",
                env_path=tmp_path / "missing.env",
                max_tokens=32,
                thinking_mode="disabled",
                _http_opener=opener,
                _request_id_factory=request_id_factory,
            )

    with pytest.raises(SystemExit, match="between owner attempts"):
        run_nested(crash_before_attempt_two)
    assert not list((refinement_root / "checkpoints").rglob("*.json"))

    result = run_nested(lambda: "request-real-context-crash-0002")
    assert result.parsed_json == {"status": "complete"}
    assert calls == 2
