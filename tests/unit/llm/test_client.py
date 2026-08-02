import json
from pathlib import Path

import pytest

from autoresearch.llm import client as llm_client
from autoresearch.llm.client import (
    LLMEvidenceArtifact,
    _review_messages,
    evaluate_llm_output_quality,
    evaluate_llm_review_quality,
)


def test_evaluate_llm_output_quality_accepts_guarded_json() -> None:
    result = evaluate_llm_output_quality(
        json.dumps(
            {
                "status": "ok",
                "summary": "Unverified research outcomes remain pending verification.",
                "evidence_policy": "Only source-backed evidence should be promoted.",
                "risks": ["missing external evidence", "configuration drift"],
                "next_steps": ["run live literature retrieval", "inspect validation reports"],
            }
        ),
        secret_values=["sk-testsecret"],
    )

    assert result.score == 1.0
    assert result.issues == []


def test_evaluate_llm_output_quality_rejects_secret_leaks_and_fake_urls() -> None:
    result = evaluate_llm_output_quality(
        json.dumps(
            {
                "status": "ok",
                "summary": "Unverified research outcomes remain pending verification.",
                "evidence_policy": "Use source-backed evidence.",
                "risks": ["missing external evidence", "configuration drift"],
                "next_steps": ["run live literature retrieval", "inspect validation reports"],
                "bad": "https://made-up.example and sk-testsecret",
            }
        ),
        secret_values=["sk-testsecret"],
    )

    assert result.checks["no_secret_leak"] is False
    assert result.checks["no_fake_urls"] is False
    assert result.score < 1.0


def test_evaluate_llm_output_quality_caps_missing_next_steps() -> None:
    result = evaluate_llm_output_quality(
        json.dumps(
            {
                "status": "ok",
                "summary": "Unverified research outcomes remain pending verification.",
                "evidence_policy": "Only source-backed evidence should be promoted.",
                "risks": ["missing external evidence", "configuration drift"],
                "next_steps": "[\"run live literature retrieval\", \"inspect validation reports\"]",
            }
        ),
    )

    assert result.checks["next_steps_present"] is False
    assert result.score <= 0.5


def test_run_llm_smoke_retries_once_on_critical_quality_failure(monkeypatch) -> None:
    calls: list[list[dict[str, str]] | None] = []
    invalid_content = json.dumps(
        {
            "status": "ok",
            "summary": "Unverified research outcomes remain pending verification.",
            "evidence_policy": "Only source-backed evidence should be promoted.",
            "risks": ["missing external evidence", "configuration drift"],
            "next_steps": "[\"run live literature retrieval\", \"inspect validation reports\"]",
        }
    )
    valid_content = json.dumps(
        {
            "status": "ok",
            "summary": "Unverified research outcomes remain pending verification.",
            "evidence_policy": "Only source-backed evidence should be promoted.",
            "risks": ["missing external evidence", "configuration drift"],
            "next_steps": ["run live literature retrieval", "inspect validation reports"],
        }
    )

    def fake_post_chat_completion(**kwargs: object) -> dict[str, object]:
        messages = kwargs.get("messages")
        calls.append(messages if isinstance(messages, list) else None)
        content = invalid_content if len(calls) == 1 else valid_content
        return {
            "choices": [{"message": {"content": content}}],
            "usage": {"completion_tokens": 12},
        }

    monkeypatch.setenv("AUTORESEARCH_LLM_API_KEY", "sk-testsecret")
    monkeypatch.setattr(llm_client, "_post_chat_completion", fake_post_chat_completion)

    result = llm_client.run_llm_smoke_test(
        config_path=Path("missing-config.yaml"),
        env_path=Path("missing.env"),
    )

    assert result.attempts == 2
    assert result.quality.score == 1.0
    assert len(calls) == 2
    assert calls[1] is not None
    assert "previous response failed" in calls[1][1]["content"].lower()


def test_post_chat_completion_omits_max_tokens_by_default(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode("utf-8")

    def fake_urlopen(request: object, *, timeout: int) -> FakeResponse:
        del timeout
        data = request.data
        captured["payload"] = json.loads(data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr(llm_client.urllib.request, "urlopen", fake_urlopen)

    llm_client._post_chat_completion(
        endpoint="https://llm.example.test/v1/chat/completions",
        api_key="sk-testsecret",
        model_name="research-model",
        timeout_seconds=10,
        max_tokens=None,
    )

    assert "max_tokens" not in captured["payload"]


def test_post_chat_completion_includes_explicit_max_tokens(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode("utf-8")

    def fake_urlopen(request: object, *, timeout: int) -> FakeResponse:
        del timeout
        data = request.data
        captured["payload"] = json.loads(data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr(llm_client.urllib.request, "urlopen", fake_urlopen)

    llm_client._post_chat_completion(
        endpoint="https://llm.example.test/v1/chat/completions",
        api_key="sk-testsecret",
        model_name="research-model",
        timeout_seconds=10,
        max_tokens=4096,
    )

    assert captured["payload"]["max_tokens"] == 4096


def test_post_chat_completion_includes_explicit_reasoning_effort(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode(
                "utf-8"
            )

    def fake_urlopen(request: object, *, timeout: int) -> FakeResponse:
        del timeout
        data = request.data
        captured["payload"] = json.loads(data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr(llm_client.urllib.request, "urlopen", fake_urlopen)

    llm_client._post_chat_completion(
        endpoint="http://127.0.0.1:11434/v1/chat/completions",
        api_key="ollama-local",
        model_name="qwen3.5-sprint:9b-8k",
        timeout_seconds=10,
        max_tokens=500,
        reasoning_effort="none",
    )

    assert captured["payload"]["reasoning_effort"] == "none"


def test_post_chat_completion_includes_explicit_thinking_mode(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode(
                "utf-8"
            )

    def fake_urlopen(request: object, *, timeout: int) -> FakeResponse:
        del timeout
        data = request.data
        captured["payload"] = json.loads(data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr(llm_client.urllib.request, "urlopen", fake_urlopen)

    # Task 267.3.1: an Anthropic-shaped provider keeps the thinking block.
    llm_client._post_chat_completion(
        endpoint="https://api.example.test/chat/completions",
        api_key="sk-testsecret",
        model_name="research-model",
        timeout_seconds=10,
        max_tokens=500,
        thinking_mode="disabled",
        provider="anthropic",
    )

    assert captured["payload"]["thinking"] == {"type": "disabled"}
    assert "enable_thinking" not in captured["payload"]


def test_dashscope_provider_receives_enable_thinking_and_bounded_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task 267.3.1: DashScope silently ignores the Anthropic-shaped field.

    Sending `{"thinking": {"type": ...}}` to DashScope returns HTTP 200 with an
    empty `reasoning_content`, so the reasoning chain was never engaged. The
    budget must always be bounded: unbounded reasoning on `qwen3-max` produced
    81,933 completion tokens for a trivial prompt with empty content.
    """

    captured: dict[str, object] = {}

    class FakeThinkingResponse:
        def __enter__(self) -> "FakeThinkingResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {"choices": [{"message": {"content": "{}"}}]}
            ).encode("utf-8")

    def fake_urlopen(request: object, *, timeout: int) -> "FakeThinkingResponse":
        del timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeThinkingResponse()

    monkeypatch.setattr(llm_client.urllib.request, "urlopen", fake_urlopen)

    llm_client._post_chat_completion(
        endpoint="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        api_key="sk-testsecret",
        model_name="qwen3-max",
        timeout_seconds=10,
        max_tokens=8000,
        thinking_mode="enabled",
        provider="qwen-dashscope",
    )

    payload = captured["payload"]
    assert payload["enable_thinking"] is True
    assert payload["thinking_budget"] == llm_client._DEFAULT_THINKING_BUDGET
    # The ignored Anthropic-shaped field must never be sent to DashScope.
    assert "thinking" not in payload


def test_reasoning_transport_is_provider_neutral() -> None:
    """Engine code passes a normalized mode; the client maps it per vendor."""

    assert (
        llm_client.reasoning_transport_for_provider("qwen-dashscope")
        == "dashscope_enable_thinking"
    )
    assert (
        llm_client.reasoning_transport_for_provider("anthropic")
        == "anthropic_thinking_block"
    )
    # Unknown providers use the dialect this deployment verified live.
    assert (
        llm_client.reasoning_transport_for_provider("some-new-vendor")
        == "dashscope_enable_thinking"
    )


def test_disabled_reasoning_on_dashscope_sends_no_budget() -> None:
    """A disabled request must not allocate a reasoning budget."""

    parameters = llm_client._reasoning_parameters(
        provider="qwen-dashscope",
        thinking_mode="disabled",
        thinking_budget=None,
    )

    assert parameters == {"enable_thinking": False}


def test_reasoning_text_is_recorded_but_never_evidence() -> None:
    """Reasoning is process evidence about authoring, not scientific evidence."""

    result = llm_client.LLMJsonCompletionResult(
        provider="qwen-dashscope",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model_name="qwen3-max",
        endpoint="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        response_text="{}",
        parsed_json={},
        temperature=0.0,
        reasoning_text="considered a weak-form estimator, then rejected it",
        reasoning_transport="dashscope_enable_thinking",
    )

    assert result.reasoning_text is not None
    assert result.reasoning_is_evidence is False


def test_extract_reasoning_content_returns_none_when_absent() -> None:
    """A provider that ignores the reasoning parameter must yield None, not ''."""

    assert (
        llm_client._extract_reasoning_content(
            {"choices": [{"message": {"content": "{}"}}]}
        )
        is None
    )
    assert (
        llm_client._extract_reasoning_content(
            {"choices": [{"message": {"content": "{}", "reasoning_content": "   "}}]}
        )
        is None
    )
    assert (
        llm_client._extract_reasoning_content(
            {"choices": [{"message": {"content": "{}", "reasoning_content": "why"}}]}
        )
        == "why"
    )


def test_json_completion_parser_records_one_trailing_closing_delimiter() -> None:
    parsed, normalization, suffix = llm_client._parse_json_completion_content(
        '{"candidate_id":"branch-02","source_text":"exact model code"}]'
    )

    assert parsed == {
        "candidate_id": "branch-02",
        "source_text": "exact model code",
    }
    assert normalization == "discarded_trailing_closing_delimiters"
    assert suffix == "]"


def test_json_completion_parser_rejects_second_object_or_trailing_prose() -> None:
    with pytest.raises(json.JSONDecodeError, match="Extra data"):
        llm_client._parse_json_completion_content('{"first":1}{"second":2}')
    with pytest.raises(json.JSONDecodeError, match="Extra data"):
        llm_client._parse_json_completion_content('{"first":1} explanation')


def test_json_completion_parser_selects_a_schema_identical_final_self_revision() -> None:
    raw = (
        '{"status":"draft","source_text":"first"}'
        "\nThe draft needs one correction.\n"
        '{"status":"final","source_text":"second"}'
    )

    parsed, normalization, discarded = llm_client._parse_json_completion_content(raw)

    assert parsed == {"status": "final", "source_text": "second"}
    assert normalization == "discarded_leading_self_revision"
    assert discarded == raw[: raw.rfind('{"status":"final"')]


def test_ollama_native_endpoint_replaces_openai_v1_path() -> None:
    assert (
        llm_client._ollama_native_chat_endpoint("http://127.0.0.1:11434/v1")
        == "http://127.0.0.1:11434/api/chat"
    )
    assert (
        llm_client._ollama_native_chat_endpoint("https://ollama.example.test/prefix/v1/")
        == "https://ollama.example.test/prefix/api/chat"
    )


def test_post_ollama_native_json_completion_disables_thinking(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "done_reason": "stop",
                    "message": {"role": "assistant", "content": '{"token":"safe"}'},
                    "prompt_eval_count": 7,
                    "eval_count": 3,
                }
            ).encode("utf-8")

    def fake_urlopen(request: object, *, timeout: int) -> FakeResponse:
        del timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["authorization"] = request.headers["Authorization"]
        return FakeResponse()

    monkeypatch.setattr(llm_client.urllib.request, "urlopen", fake_urlopen)
    schema = {
        "type": "object",
        "properties": {"token": {"type": "string", "enum": ["safe"]}},
        "required": ["token"],
        "additionalProperties": False,
    }

    response = llm_client._post_ollama_native_json_completion(
        endpoint="http://127.0.0.1:11434/api/chat",
        api_key="ollama-local",
        model_name="qwen3.5:9b",
        timeout_seconds=10,
        max_tokens=128,
        messages=[{"role": "user", "content": "Return safe."}],
        temperature=0.0,
        response_schema=schema,
    )

    assert captured["payload"] == {
        "model": "qwen3.5:9b",
        "messages": [{"role": "user", "content": "Return safe."}],
        "stream": False,
        "think": False,
        "format": schema,
        "options": {"temperature": 0.0, "num_predict": 128},
    }
    assert captured["authorization"] == "Bearer ollama-local"
    assert response["choices"][0]["message"]["content"] == '{"token":"safe"}'
    assert response["usage"]["total_tokens"] == 10


def test_post_chat_completion_includes_explicit_json_schema(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode(
                "utf-8"
            )

    def fake_urlopen(request: object, *, timeout: int) -> FakeResponse:
        del timeout
        data = request.data
        captured["payload"] = json.loads(data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr(llm_client.urllib.request, "urlopen", fake_urlopen)
    schema = {
        "type": "object",
        "properties": {"decision": {"type": "string"}},
        "required": ["decision"],
        "additionalProperties": False,
    }

    llm_client._post_chat_completion(
        endpoint="http://127.0.0.1:11434/v1/chat/completions",
        api_key="ollama-local",
        model_name="qwen3.5-sprint:9b-8k",
        timeout_seconds=10,
        max_tokens=500,
        response_schema=schema,
        response_schema_name="research_decision",
    )

    response_format = captured["payload"]["response_format"]
    assert response_format == {
        "type": "json_schema",
        "json_schema": {
            "name": "research_decision",
            "strict": True,
            "schema": schema,
        },
    }


def test_post_chat_completion_accepts_creative_temperature(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode("utf-8")

    def fake_urlopen(request: object, *, timeout: int) -> FakeResponse:
        del timeout
        data = request.data
        captured["payload"] = json.loads(data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr(llm_client.urllib.request, "urlopen", fake_urlopen)

    llm_client._post_chat_completion(
        endpoint="https://llm.example.test/v1/chat/completions",
        api_key="sk-testsecret",
        model_name="research-model",
        timeout_seconds=10,
        max_tokens=None,
        temperature=1.35,
    )

    assert captured["payload"]["temperature"] == 1.35
    assert "max_tokens" not in captured["payload"]


def test_evaluate_llm_review_quality_accepts_known_local_evidence_refs() -> None:
    result = evaluate_llm_review_quality(
        json.dumps(
            {
                "verdict": "needs_revision",
                "summary": "The report is mostly grounded but needs one caveat added.",
                "findings": [
                    {
                        "severity": "warning",
                        "claim": "The metric is supported by the validation report.",
                        "evidence_refs": ["evidence_1"],
                    }
                ],
                "unsupported_claims": [],
                "next_steps": ["Add the missing limitation before release."],
            }
        ),
        evidence_ids=["evidence_1"],
        secret_values=["sk-testsecret"],
    )

    assert result.score == 1.0
    assert result.issues == []


def test_evaluate_llm_review_quality_rejects_unknown_evidence_refs() -> None:
    result = evaluate_llm_review_quality(
        json.dumps(
            {
                "verdict": "pass",
                "summary": "The report is grounded in local evidence.",
                "findings": [
                    {
                        "severity": "info",
                        "claim": "The claim is supported.",
                        "evidence_refs": ["external-paper-1"],
                    }
                ],
                "unsupported_claims": [],
                "next_steps": ["Keep evidence attached."],
            }
        ),
        evidence_ids=["evidence_1"],
    )

    assert result.checks["finding_refs_known"] is False
    assert result.score <= 0.5


def test_evaluate_llm_review_quality_treats_missing_refs_as_hard_failure() -> None:
    result = evaluate_llm_review_quality(
        json.dumps(
            {
                "verdict": "pass",
                "summary": "The report is grounded in local evidence.",
                "findings": [
                    {
                        "severity": "info",
                        "claim": "The claim is supported.",
                        "evidence_refs": [],
                    }
                ],
                "unsupported_claims": [],
                "next_steps": ["Keep evidence attached."],
            }
        ),
        evidence_ids=["evidence_1"],
    )

    assert result.checks["finding_refs_present"] is False
    assert result.score <= 0.5


def test_evaluate_llm_review_quality_caps_missing_next_steps() -> None:
    result = evaluate_llm_review_quality(
        json.dumps(
            {
                "verdict": "needs_revision",
                "summary": "The report is grounded in local evidence but needs one follow-up.",
                "findings": [
                    {
                        "severity": "warning",
                        "claim": "The claim is supported.",
                        "evidence_refs": ["evidence_1"],
                    }
                ],
                "unsupported_claims": [],
                "next_steps": "Add the missing limitation before release.",
            }
        ),
        evidence_ids=["evidence_1"],
    )

    assert result.checks["next_steps_present"] is False
    assert result.score <= 0.5


def test_evaluate_llm_review_quality_rejects_profile_context_as_scientific_evidence() -> None:
    result = evaluate_llm_review_quality(
        json.dumps(
            {
                "verdict": "pass",
                "summary": "The report is grounded in local evidence.",
                "findings": [
                    {
                        "severity": "info",
                        "claim": (
                            "stage_agent_contexts and the source-tracing skill prove "
                            "the novelty, benchmark accuracy result, and publication "
                            "readiness of the manuscript."
                        ),
                        "evidence_refs": ["evidence_1"],
                    }
                ],
                "unsupported_claims": [],
                "next_steps": ["Keep evidence attached."],
            }
        ),
        evidence_ids=["evidence_1"],
    )

    assert result.checks["profile_context_not_used_as_scientific_evidence"] is False
    assert result.score <= 0.5
    assert llm_client._has_failed_review_critical_checks(result) is True


def test_evaluate_llm_review_quality_rejects_mcp_contract_as_tool_evidence() -> None:
    result = evaluate_llm_review_quality(
        json.dumps(
            {
                "verdict": "pass",
                "summary": "The report is grounded in local evidence.",
                "findings": [
                    {
                        "severity": "info",
                        "claim": (
                            "The mcp_runtime_contracts prove tool invocation and "
                            "support the benchmark metric result."
                        ),
                        "evidence_refs": ["evidence_1"],
                    }
                ],
                "unsupported_claims": [],
                "next_steps": ["Keep evidence attached."],
            }
        ),
        evidence_ids=["evidence_1"],
    )

    assert result.checks["profile_context_not_used_as_scientific_evidence"] is False
    assert result.score <= 0.5


def test_evaluate_llm_review_quality_allows_profile_context_process_findings() -> None:
    result = evaluate_llm_review_quality(
        json.dumps(
            {
                "verdict": "pass",
                "summary": "The report includes process context without result claims.",
                "findings": [
                    {
                        "severity": "info",
                        "claim": (
                            "stage_agent_contexts identify the reviewer responsibility "
                            "boundaries and available tool context."
                        ),
                        "evidence_refs": ["evidence_1"],
                    }
                ],
                "unsupported_claims": [],
                "next_steps": ["Keep the process context attached to the evidence bundle."],
            }
        ),
        evidence_ids=["evidence_1"],
    )

    assert result.checks["profile_context_not_used_as_scientific_evidence"] is True
    assert result.score == 1.0


def test_run_llm_review_retries_once_on_critical_quality_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    subject = tmp_path / "report.md"
    subject.write_text("Claim cites local validation evidence.", encoding="utf-8")
    evidence = tmp_path / "validation-report.json"
    evidence.write_text('{"metric":"accuracy","value":0.9}', encoding="utf-8")
    calls: list[list[dict[str, str]] | None] = []
    invalid_content = json.dumps(
        {
            "verdict": "needs_revision",
            "summary": "The report is grounded but needs a caveat.",
            "findings": [
                {
                    "severity": "warning",
                    "claim": "The accuracy claim is supported.",
                    "evidence_refs": ["not_allowed"],
                }
            ],
            "unsupported_claims": [],
            "next_steps": "Add a limitation.",
        }
    )
    valid_content = json.dumps(
        {
            "verdict": "needs_revision",
            "summary": "The report is grounded but needs a caveat.",
            "findings": [
                {
                    "severity": "warning",
                    "claim": "The accuracy claim is supported by the local validation report.",
                    "evidence_refs": ["evidence_1"],
                }
            ],
            "unsupported_claims": [],
            "next_steps": ["Add a limitation."],
        }
    )

    def fake_post_chat_completion(**kwargs: object) -> dict[str, object]:
        messages = kwargs.get("messages")
        calls.append(messages if isinstance(messages, list) else None)
        content = invalid_content if len(calls) == 1 else valid_content
        return {
            "choices": [{"message": {"content": content}}],
            "usage": {"completion_tokens": 20},
        }

    monkeypatch.setenv("AUTORESEARCH_LLM_API_KEY", "sk-testsecret")
    monkeypatch.setattr(llm_client, "_post_chat_completion", fake_post_chat_completion)

    result = llm_client.run_llm_evidence_review(
        subject_path=subject,
        evidence_paths=[evidence],
        config_path=Path("missing-config.yaml"),
        env_path=Path("missing.env"),
    )

    assert result.attempts == 2
    assert result.quality.score == 1.0
    assert len(calls) == 2
    assert calls[1] is not None
    assert "previous review response failed" in calls[1][1]["content"].lower()
    assert "evidence_1" in calls[1][1]["content"]
    assert "\"evidence_1\"" in result.response_text


def test_run_llm_evidence_review_keeps_long_manuscript_tail(
    tmp_path: Path,
    monkeypatch,
) -> None:
    subject = tmp_path / "manuscript.md"
    evidence = tmp_path / "evidence.json"
    subject.write_text(("method evidence paragraph\n" * 900) + "TAIL_SENTINEL", encoding="utf-8")
    evidence.write_text('{"status": "passed"}', encoding="utf-8")
    calls: list[list[dict[str, str]] | None] = []

    def fake_post_chat_completion(**kwargs: object) -> dict[str, object]:
        messages = kwargs.get("messages")
        calls.append(messages if isinstance(messages, list) else None)
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "verdict": "pass",
                                "summary": "The manuscript is supported by provided evidence.",
                                "findings": [
                                    {
                                        "severity": "info",
                                        "claim": "Evidence status is passed.",
                                        "evidence_refs": ["evidence_1"],
                                    }
                                ],
                                "unsupported_claims": [],
                                "next_steps": ["Keep the evidence bundle with the paper."],
                            }
                        )
                    }
                }
            ],
            "usage": {"completion_tokens": 20},
        }

    monkeypatch.setenv("AUTORESEARCH_LLM_API_KEY", "sk-testsecret")
    monkeypatch.setattr(llm_client, "_post_chat_completion", fake_post_chat_completion)

    result = llm_client.run_llm_evidence_review(
        subject_path=subject,
        evidence_paths=[evidence],
        config_path=Path("missing-config.yaml"),
        env_path=Path("missing.env"),
    )

    assert result.quality.score == 1.0
    assert calls[0] is not None
    assert "TAIL_SENTINEL" in calls[0][1]["content"]


def test_review_prompt_distinguishes_subject_edge_ids_from_outer_refs() -> None:
    messages = _review_messages(
        subject_path=Path("report.md"),
        subject_text="Metric uses [evidence `evidence_metric`](metrics.json).",
        evidence=[
            LLMEvidenceArtifact(
                evidence_id="evidence_1",
                path="evidence/evidence-map.json",
                sha256="abc123",
                excerpt='{"evidence_edges":[{"id":"evidence_metric"}]}',
            )
        ],
    )

    prompt = messages[1]["content"]
    assert "internal metric evidence edge IDs" in prompt
    assert "outer evidence_refs IDs" in prompt
    assert "Use verdict `pass` when unsupported_claims is empty" in prompt
    assert "evidence_1" in prompt


def test_review_prompt_treats_agent_profiles_as_process_metadata_only() -> None:
    messages = _review_messages(
        subject_path=Path("paper.md"),
        subject_text="The profile includes a source-tracing skill.",
        evidence=[
            LLMEvidenceArtifact(
                evidence_id="evidence_1",
                path="review-evidence-context.json",
                sha256="abc123",
                excerpt=(
                    '{"stage_agent_contexts":{"review":[{"agent_id":"reviewer",'
                    '"skills":[{"skill_id":"source-tracing"}],'
                    '"mcp_runtime_contracts":[{"server_id":"page-agent",'
                    '"tool_invocation_evidence_required":true}]}]},'
                    '"stage_runtime_contexts":{"review":[{"agent_id":"reviewer"}]}}'
                ),
            )
        ],
    )

    prompt = messages[0]["content"]
    assert "stage_agent_contexts" in prompt
    assert "stage_runtime_contexts" in prompt
    assert "mcp_runtime_contracts" in prompt
    assert "process metadata only" in prompt
    assert "not evidence for scientific results" in prompt
    assert "publication readiness" in prompt
    assert "A profile does not prove a tool was invoked" in prompt
