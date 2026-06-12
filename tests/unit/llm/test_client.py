import json

from autoresearch.llm.client import evaluate_llm_output_quality


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
