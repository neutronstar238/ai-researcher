"""Task 268.5 / `P-20260803-071`: bounded reasoning must actually be sent.

`_call_and_record` is the single authoring transport shared by every autonomous
path (candidate portfolios, implementations, technical repairs, Route P2
self-correction, and the frozen-protocol repair cycle). It previously hard-coded
`thinking_mode="disabled"` both in the persisted record and in the provider call,
so the most reasoning-heavy steps in the system ran with the reasoning chain OFF.

These tests pin the four properties that defect violated:

1. Reasoning is threaded ONCE, so every caller sends it without a per-module case.
2. The budget is always BOUNDED (`P-20260802-051`: unbounded reasoning returned
   81,920 reasoning characters and an intermittently empty `content`).
3. The structured-output interaction from Task `267.3.1` is handled correctly:
   strict `json_schema` when reasoning is off, `json_object` plus local strict
   validation when reasoning is on, with the literal word `json` in the messages.
4. `reasoning_content` is persisted as explicitly NON-evidence, and the recorded
   `thinking_mode` reflects what was ACTUALLY sent rather than a constant.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from autoresearch.competition.autonomous_engine import (
    _AUTONOMOUS_THINKING_BUDGET,
    _AUTONOMOUS_THINKING_MODE,
    AutonomousBranchEngineError,
    AutonomousModelInteraction,
    _call_and_record,
)
from autoresearch.llm.client import LLMClientError, LLMJsonCompletionResult

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict"],
    "properties": {"verdict": {"type": "string"}},
}
_PAYLOAD = {"verdict": "reasoning was engaged"}
_REASONING_TEXT = "Step 1: read the retained evidence. Step 2: weigh both routes."


class _RecordingCompletion:
    """Capture exactly what the transport sent to the provider."""

    def __init__(self, *, reasoning_text: str | None = _REASONING_TEXT) -> None:
        self.calls: list[dict[str, Any]] = []
        self._reasoning_text = reasoning_text

    def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult:
        self.calls.append(kwargs)
        thinking_mode = kwargs.get("thinking_mode")
        return LLMJsonCompletionResult(
            provider="qwen-dashscope",
            base_url="https://dashscope.example/compatible-mode/v1",
            model_name="qwen3.7-max",
            endpoint="https://dashscope.example/compatible-mode/v1/chat/completions",
            response_text=json.dumps(_PAYLOAD),
            parsed_json=dict(_PAYLOAD),
            usage={"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            temperature=0.2,
            reasoning_text=(self._reasoning_text if thinking_mode == "enabled" else None),
            reasoning_transport=(
                "dashscope_enable_thinking" if thinking_mode is not None else "absent"
            ),
        )


def _record(
    tmp_path: Path,
    completion: _RecordingCompletion,
    **overrides: Any,
) -> tuple[LLMJsonCompletionResult, AutonomousModelInteraction]:
    kwargs: dict[str, Any] = {
        "completion": completion,
        "messages": [{"role": "user", "content": "Author the repair."}],
        "config_path": tmp_path / "config.yaml",
        "env_path": tmp_path / ".env",
        "timeout_seconds": 30,
        "max_tokens": 2_000,
        "response_schema": _SCHEMA,
        "response_schema_name": "reasoning_probe",
        "interaction_id": "reasoning-probe-0001",
        "stage": "mechanism_intervention",
        "candidate_id": None,
        "output_root": tmp_path / "out",
        "now": lambda: datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc),
    }
    kwargs.update(overrides)
    return _call_and_record(**kwargs)


# --------------------------------------------------------------------------
# 1. Reasoning is threaded once, for every caller, and is ON by default
# --------------------------------------------------------------------------


def test_default_authoring_call_sends_bounded_reasoning(tmp_path: Path) -> None:
    completion = _RecordingCompletion()

    _record(tmp_path, completion)

    assert len(completion.calls) == 1
    sent = completion.calls[0]
    assert sent["thinking_mode"] == "enabled"
    assert sent["thinking_budget"] == _AUTONOMOUS_THINKING_BUDGET


def test_the_shared_default_is_enabled_rather_than_disabled() -> None:
    # The defect was a hard-coded "disabled" on this shared helper.
    assert _AUTONOMOUS_THINKING_MODE == "enabled"


def test_the_reasoning_budget_is_bounded(tmp_path: Path) -> None:
    completion = _RecordingCompletion()

    _, interaction = _record(tmp_path, completion)

    # P-20260802-051: an unbounded budget produced empty content.
    budget = completion.calls[0]["thinking_budget"]
    assert budget is not None
    assert 0 < budget <= 32_000
    assert interaction.thinking_budget == budget


def test_enabled_reasoning_without_a_budget_is_refused(tmp_path: Path) -> None:
    completion = _RecordingCompletion()

    with pytest.raises(AutonomousBranchEngineError, match="bounded reasoning"):
        _record(tmp_path, completion, thinking_mode="enabled", thinking_budget=None)


# --------------------------------------------------------------------------
# 2. The persisted record reflects what was ACTUALLY sent
# --------------------------------------------------------------------------


def test_persisted_thinking_mode_is_not_a_hard_coded_constant(tmp_path: Path) -> None:
    enabled = _RecordingCompletion()
    _, enabled_interaction = _record(tmp_path / "on", enabled)

    disabled = _RecordingCompletion()
    _, disabled_interaction = _record(
        tmp_path / "off",
        disabled,
        thinking_mode="disabled",
        thinking_budget=None,
    )

    assert enabled_interaction.thinking_mode == "enabled"
    assert disabled_interaction.thinking_mode == "disabled"
    assert disabled.calls[0]["thinking_mode"] == "disabled"
    assert disabled_interaction.thinking_budget is None


def test_reasoning_provenance_is_persisted_and_reloads(tmp_path: Path) -> None:
    completion = _RecordingCompletion()

    _, interaction = _record(tmp_path, completion)

    path = tmp_path / "out" / "interactions" / "reasoning-probe-0001.json"
    reloaded = AutonomousModelInteraction.model_validate_json(path.read_text(encoding="utf-8"))
    assert reloaded.reasoning_content == _REASONING_TEXT
    assert reloaded.thinking_mode == "enabled"
    assert reloaded.reasoning_transport == "dashscope_enable_thinking"
    assert reloaded.interaction_hash == interaction.interaction_hash
    assert reloaded.interaction_hash == reloaded.calculated_hash()


def test_reasoning_text_is_flagged_as_non_evidence(tmp_path: Path) -> None:
    completion = _RecordingCompletion()

    _, interaction = _record(tmp_path, completion)

    # Reasoning is process provenance about HOW the answer was authored. It must
    # never satisfy an evidence gate or a publication claim.
    assert interaction.reasoning_is_evidence is False


def _tampered_payload(tmp_path: Path, **changes: Any) -> dict[str, Any]:
    """Persist a real interaction, then tamper with the reasoning provenance."""

    _, interaction = _record(tmp_path, _RecordingCompletion())
    payload = interaction.model_dump(mode="json")
    payload.update(changes)
    return payload


def test_reasoning_content_cannot_be_recorded_without_enabled_reasoning(
    tmp_path: Path,
) -> None:
    payload = _tampered_payload(
        tmp_path,
        thinking_mode="disabled",
        thinking_budget=None,
        reasoning_content="smuggled reasoning",
    )

    with pytest.raises(ValueError, match="reasoning content recorded without"):
        AutonomousModelInteraction.model_validate(payload)


# --------------------------------------------------------------------------
# 3. The Task 267.3.1 structured-output interaction
# --------------------------------------------------------------------------


def test_reasoning_on_downgrades_to_json_object_with_local_validation(
    tmp_path: Path,
) -> None:
    completion = _RecordingCompletion()

    _, interaction = _record(tmp_path, completion)

    # Reasoning and transport-level json_schema are mutually exclusive here.
    assert completion.calls[0]["response_schema"] is None
    assert interaction.structured_transport_mode == "json_object_reasoning_local_validation"


def test_reasoning_messages_contain_the_literal_word_json(tmp_path: Path) -> None:
    completion = _RecordingCompletion()

    _record(tmp_path, completion)

    # json_object mode fails with invalid_parameter_error unless the messages
    # contain the literal lowercase word "json".
    sent_messages = completion.calls[0]["messages"]
    assert any("json" in item["content"] for item in sent_messages)


def test_reasoning_off_keeps_strict_json_schema(tmp_path: Path) -> None:
    completion = _RecordingCompletion()

    _, interaction = _record(
        tmp_path,
        completion,
        thinking_mode="disabled",
        thinking_budget=None,
    )

    assert completion.calls[0]["response_schema"] == _SCHEMA
    assert interaction.structured_transport_mode == "json_schema"
    assert interaction.reasoning_content is None
    assert interaction.thinking_budget is None
    # `reasoning_transport` records the provider DIALECT used to control reasoning,
    # not whether reasoning ran. Disabling still sends `enable_thinking: False`.
    assert interaction.reasoning_transport == "dashscope_enable_thinking"


def test_reasoning_off_still_falls_back_when_a_provider_rejects_json_schema(
    tmp_path: Path,
) -> None:
    """The pre-existing response_format fallback must remain reachable."""

    class _SchemaRejectingCompletion(_RecordingCompletion):
        def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult:
            if kwargs.get("response_schema") is not None:
                raise LLMClientError("LLM API HTTP 400: response_format json_schema is unsupported")
            return super().__call__(**kwargs)

    completion = _SchemaRejectingCompletion()

    _, interaction = _record(
        tmp_path,
        completion,
        thinking_mode="disabled",
        thinking_budget=None,
    )

    assert interaction.structured_transport_mode == "json_object_local_validation"
    assert interaction.provider_format_fallback_relative_path is not None
    assert interaction.provider_request_attempt_count == 2


def test_a_reasoning_call_records_no_provider_format_fallback(tmp_path: Path) -> None:
    completion = _RecordingCompletion()

    _, interaction = _record(tmp_path, completion)

    # json-object mode here is a deliberate request shape, not a provider failure,
    # so it must not masquerade as a response_format fallback.
    assert interaction.provider_format_fallback_relative_path is None
    assert interaction.provider_format_fallback_sha256 is None


def test_enabled_reasoning_cannot_claim_transport_level_json_schema(
    tmp_path: Path,
) -> None:
    payload = _tampered_payload(tmp_path, structured_transport_mode="json_schema")

    with pytest.raises(ValueError, match="cannot claim transport-level json_schema"):
        AutonomousModelInteraction.model_validate(payload)


def test_enabled_reasoning_requires_a_recorded_budget(tmp_path: Path) -> None:
    payload = _tampered_payload(tmp_path, thinking_budget=None)

    with pytest.raises(ValueError, match="requires an explicit bounded budget"):
        AutonomousModelInteraction.model_validate(payload)


# --------------------------------------------------------------------------
# 4. Resume must not silently re-run or lose reasoning provenance
# --------------------------------------------------------------------------


def test_resuming_a_reasoning_interaction_makes_no_second_call(tmp_path: Path) -> None:
    first = _RecordingCompletion()
    _, original = _record(tmp_path, first)

    second = _RecordingCompletion()
    result, resumed = _record(tmp_path, second)

    assert second.calls == []
    assert resumed.interaction_hash == original.interaction_hash
    assert result.reasoning_text == _REASONING_TEXT
    assert result.reasoning_transport == "dashscope_enable_thinking"
