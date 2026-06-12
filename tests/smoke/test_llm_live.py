import os

import pytest

from autoresearch.llm import run_llm_smoke_test


@pytest.mark.skipif(
    os.getenv("AUTORESEARCH_LIVE_APIS") != "1",
    reason="Set AUTORESEARCH_LIVE_APIS=1 and configure .env to run live LLM API smoke tests.",
)
def test_live_llm_smoke_returns_quality_checked_output() -> None:
    result = run_llm_smoke_test()

    assert result.model_name
    assert result.quality.score >= 0.85, result.quality.issues
    assert result.quality.checks["valid_json"] is True
    assert result.quality.checks["no_secret_leak"] is True
