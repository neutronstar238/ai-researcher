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
    assert "evidence_1" in prompt
