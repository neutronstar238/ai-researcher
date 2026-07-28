"""Tests for the OpenAI-compatible vNext harness adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoresearch.kernel import (
    EpisodeOutcomeStatus,
    FailureDomain,
    HarnessAdapterError,
    HarnessRunner,
    HarnessRunRequest,
    ModelInvocationRequest,
)
from autoresearch.kernel.journal import EventJournal
from autoresearch.llm import harness as harness_adapter
from autoresearch.llm.client import LLMClientError, LLMJsonCompletionResult
from autoresearch.llm.harness import (
    OpenAICompatibleHarnessAdapter,
    build_openai_compatible_characterization_spec,
    build_status_ok_grader,
)

BASE_TIME = datetime(2026, 7, 28, 8, 30, tzinfo=timezone.utc)
MODEL_REF = "qwen3.5-sprint:9b-8k"


def _request() -> ModelInvocationRequest:
    spec = build_openai_compatible_characterization_spec(model_ref=MODEL_REF)
    return ModelInvocationRequest(
        run_id="run_qwen_mock",
        episode_id="episode_qwen_mock",
        trial_id="trial_1",
        harness_spec_id=spec.spec_id,
        harness_spec_hash=spec.spec_hash,
        task_id=spec.task_contract.task_id,
        instructions=spec.task_contract.instructions,
        task_input={"fixture": "mock"},
        context_artifact_ids=[],
        response_schema=spec.task_contract.output_contract.json_schema(),
        model_ref=MODEL_REF,
        max_output_tokens=256,
        temperature=0.0,
        deliberation="disabled",
    )


def _completion() -> LLMJsonCompletionResult:
    return LLMJsonCompletionResult(
        provider="ollama-openai-compatible",
        base_url="http://127.0.0.1:11434/v1",
        model_name=MODEL_REF,
        endpoint="http://127.0.0.1:11434/v1/chat/completions",
        response_text='{"status":"ok","summary":"Harness characterization only."}',
        parsed_json={
            "status": "ok",
            "summary": "Harness characterization only.",
        },
        usage={
            "prompt_tokens": 20,
            "completion_tokens": 8,
            "total_tokens": 28,
        },
        temperature=0.0,
    )


def test_adapter_maps_schema_request_and_discards_endpoint_and_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_completion(**kwargs: object) -> LLMJsonCompletionResult:
        captured.update(kwargs)
        return _completion()

    monkeypatch.setattr(harness_adapter, "run_llm_json_completion", fake_completion)
    adapter = OpenAICompatibleHarnessAdapter(
        config_path=Path("configs/campaign/ollama-qwen35-sprint-8k.yaml"),
        env_path=Path("missing.env"),
        estimated_cost_usd=0.0,
    )

    result = adapter.invoke(_request())

    assert result.model_ref == MODEL_REF
    assert result.provider_ref == "ollama-openai-compatible"
    assert result.structured_output["status"] == "ok"
    assert result.usage.total_tokens == 28
    assert result.usage.cost_known is True
    assert captured["max_tokens"] == 256
    assert captured["reasoning_effort"] == "none"
    assert captured["response_schema_name"] == "autoresearch_harness_output"
    assert captured["response_schema"] == _request().response_schema
    serialized = result.canonical_json()
    assert "127.0.0.1" not in serialized
    assert "chat/completions" not in serialized


def test_adapter_defaults_unknown_cost_truthfully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        harness_adapter,
        "run_llm_json_completion",
        lambda **_kwargs: _completion(),
    )
    adapter = OpenAICompatibleHarnessAdapter(config_path=Path("config.yaml"))

    result = adapter.invoke(_request())

    assert result.usage.estimated_cost_usd == 0.0
    assert result.usage.cost_known is False


@pytest.mark.parametrize(
    ("message", "domain", "code", "blocked"),
    [
        (
            "LLM JSON completion was not valid JSON: bad",
            FailureDomain.OUTPUT_VALIDATION,
            "invalid_provider_response",
            False,
        ),
        (
            "LLM API request failed: connection refused",
            FailureDomain.MODEL,
            "model_unavailable",
            True,
        ),
    ],
)
def test_adapter_classifies_invalid_output_and_unavailable_model(
    monkeypatch: pytest.MonkeyPatch,
    message: str,
    domain: FailureDomain,
    code: str,
    blocked: bool,
) -> None:
    def fail(**_kwargs: object) -> LLMJsonCompletionResult:
        raise LLMClientError(message)

    monkeypatch.setattr(harness_adapter, "run_llm_json_completion", fail)
    adapter = OpenAICompatibleHarnessAdapter(config_path=Path("config.yaml"))

    with pytest.raises(HarnessAdapterError) as raised:
        adapter.invoke(_request())

    assert raised.value.domain == domain
    assert raised.value.code == code
    assert raised.value.blocked is blocked
    assert "connection refused" not in str(raised.value)


def test_mocked_openai_compatible_path_emits_sealed_episode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        harness_adapter,
        "run_llm_json_completion",
        lambda **_kwargs: _completion(),
    )
    spec = build_openai_compatible_characterization_spec(model_ref=MODEL_REF)
    journal = EventJournal.create(
        tmp_path / "journal",
        run_id="run_qwen_mock",
        created_at=BASE_TIME,
    )
    runner = HarnessRunner(
        spec=spec,
        journal=journal,
        model_adapter=OpenAICompatibleHarnessAdapter(
            config_path=Path("configs/campaign/ollama-qwen35-sprint-8k.yaml"),
            env_path=Path("missing.env"),
            estimated_cost_usd=0.0,
        ),
        graders={"grader.status_ok": build_status_ok_grader()},
        clock=lambda: BASE_TIME,
    )

    episode = runner.run(
        HarnessRunRequest(
            run_id="run_qwen_mock",
            episode_id="episode_qwen_mock",
            task_input={"fixture": "mock"},
        )
    )

    assert episode.final_outcome.status == EpisodeOutcomeStatus.SUCCEEDED
    assert episode.final_outcome.structured_output is not None
    assert episode.final_outcome.structured_output["status"] == "ok"
    assert journal.snapshot().seal is not None
