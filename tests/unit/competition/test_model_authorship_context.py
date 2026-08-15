import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoresearch.competition.model_authorship import (
    ModelAuthorshipError,
    load_bound_authorship_receipt,
    record_model_authorship_receipt,
)
from autoresearch.kernel.contracts import canonical_sha256
from autoresearch.llm.client import LLMJsonCompletionResult
from autoresearch.llm.model_capabilities import OfficialModelCapability
from autoresearch.llm.task_context import AutonomousTaskContextSession


def _capability() -> OfficialModelCapability:
    payload = {
        "schema_version": "official-model-capability-v1",
        "provider": "qwen-dashscope",
        "model_name": "qwen3.7-max",
        "official_source_url": "https://help.aliyun.com/zh/model-studio/qwen3-7-max",
        "official_source_last_modified": "2026-08-03T15:41:58+08:00",
        "fetched_at": "2026-08-11T00:00:00Z",
        "source_sha256": "a" * 64,
        "source_size_bytes": 1,
        "parser_version": "aliyun-model-page-v1",
        "context_window_tokens": 1_000_000,
        "maximum_input_tokens": 991_808,
        "maximum_output_tokens": 131_072,
        "maximum_input_tokens_thinking": 983_616,
        "maximum_output_tokens_thinking": 131_072,
        "maximum_reasoning_tokens": 262_144,
    }
    payload["capability_hash"] = canonical_sha256(payload)
    return OfficialModelCapability.model_validate(payload)


def _completion(**_kwargs) -> LLMJsonCompletionResult:
    parsed = {"title": "系统自主生成的中文研究计划"}
    return LLMJsonCompletionResult(
        provider="qwen-dashscope",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model_name="qwen3.7-max",
        endpoint="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        response_text=json.dumps(parsed, ensure_ascii=False),
        parsed_json=parsed,
        usage={"prompt_tokens": 32, "completion_tokens": 16},
        temperature=0.2,
        reasoning_text="这是配置模型自主完成研究任务时保留的推理文本。" * 5,
        reasoning_transport="dashscope_enable_thinking",
    )


def test_authorship_receipt_binds_source_prompt_and_delivered_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "autoresearch.llm.task_context.load_official_model_capability",
        lambda **_kwargs: _capability(),
    )
    session = AutonomousTaskContextSession(
        project_id="lineage",
        conversation_id="lineage-plan",
        output_dir=tmp_path / "context",
        vault_root=tmp_path / "vault",
        completion=_completion,
    )
    messages = [{"role": "user", "content": "请自主生成中文研究计划。"}]
    with session.task("plan-authoring") as current:
        result = current(
            messages=messages,
            config_path=tmp_path / "missing.yaml",
            max_tokens=128,
            response_schema_name="research_plan",
        )
        receipt = record_model_authorship_receipt(
            artifact_kind="research_plan",
            interaction_id="plan-authoring-01",
            attempt=1,
            messages=messages,
            completion=result,
            output_dir=tmp_path / "lineage",
            clock=datetime(2026, 8, 11, tzinfo=timezone.utc),
        )

    loaded = load_bound_authorship_receipt(
        lineage_dir=tmp_path / "lineage",
        relative_path="interactions/plan-authoring-01.json",
        expected_hash=receipt.receipt_hash,
        artifact_kind="research_plan",
        expected_model_name="qwen3.7-max",
        expected_fields={"title": "系统自主生成的中文研究计划"},
    )
    assert loaded.messages == tuple(messages)
    assert loaded.delivered_messages_sha256 == result.request_messages_sha256
    assert loaded.context_preparation_hash == result.context_preparation_hash
    retained = tmp_path / "lineage" / str(loaded.context_preparation_relative_path)
    assert retained.is_file()

    payload = json.loads(retained.read_text(encoding="utf-8"))
    payload["delivered_messages_sha256"] = "f" * 64
    retained.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ModelAuthorshipError, match="context preparation"):
        load_bound_authorship_receipt(
            lineage_dir=tmp_path / "lineage",
            relative_path="interactions/plan-authoring-01.json",
            expected_hash=receipt.receipt_hash,
            artifact_kind="research_plan",
            expected_model_name="qwen3.7-max",
            expected_fields={"title": "系统自主生成的中文研究计划"},
        )
