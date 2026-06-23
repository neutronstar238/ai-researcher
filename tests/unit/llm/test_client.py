import json
from pathlib import Path

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
