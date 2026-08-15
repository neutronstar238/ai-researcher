"""Task 267.3.1: opt-in live proof that the Qwen reasoning chain is engaged.

Before the fix the client sent an Anthropic-shaped `{"thinking": {"type": ...}}`
field. DashScope ignores it silently and returns HTTP 200 with empty
`reasoning_content`, so nine runs and 348 cells never revealed that exact-code
authoring ran with reasoning disabled.

Run with:
    $env:AUTORESEARCH_QWEN_REASONING_LIVE='1'
    poetry run pytest tests/smoke/test_qwen_reasoning_live.py -q --no-cov
"""

from __future__ import annotations

import os

import pytest

from autoresearch.llm.client import run_llm_json_completion

pytestmark = pytest.mark.skipif(
    os.environ.get("AUTORESEARCH_QWEN_REASONING_LIVE") != "1",
    reason="set AUTORESEARCH_QWEN_REASONING_LIVE=1 for the live reasoning smoke",
)


def test_enabled_reasoning_returns_nonempty_reasoning_and_content() -> None:
    """Reasoning must be non-empty AND content must still parse.

    The budget bound is what keeps both true: unbounded reasoning on `qwen3-max`
    spent 81,933 completion tokens on a trivial prompt and returned empty content.
    """

    result = run_llm_json_completion(
        messages=[
            {
                "role": "user",
                "content": (
                    "Reply as one json object with a single key answer holding "
                    "the product of 17 and 23 as a string."
                ),
            }
        ],
        thinking_mode="enabled",
        thinking_budget=2_000,
        max_tokens=6_000,
    )

    assert result.reasoning_transport == "dashscope_enable_thinking"
    assert result.reasoning_text, "reasoning chain was not engaged"
    assert result.reasoning_is_evidence is False
    assert result.parsed_json.get("answer") == "391"


def test_omitted_mode_is_recorded_as_qwen_default_thinking() -> None:
    """Qwen3.7 Max defaults to thinking, so omission must be made explicit."""

    result = run_llm_json_completion(
        messages=[
            {
                "role": "user",
                "content": "Reply as one json object with a single key answer set to ok.",
            }
        ],
        max_tokens=256,
    )

    assert result.reasoning_transport == "dashscope_enable_thinking"
    assert result.reasoning_text, "default Qwen thinking was not represented in the request budget"
    assert result.parsed_json.get("answer") == "ok"
