import json

from autoresearch.llm.client import evaluate_llm_output_quality, evaluate_llm_review_quality


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
