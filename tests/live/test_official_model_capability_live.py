import os
from pathlib import Path

import pytest

from autoresearch.llm.model_capabilities import (
    build_model_context_budget,
    load_official_model_capability,
)


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_OFFICIAL_MODEL_CAPABILITY") != "1",
    reason="set RUN_LIVE_OFFICIAL_MODEL_CAPABILITY=1 for the official-page smoke",
)
def test_live_qwen37_max_context_limit_comes_from_current_official_page(
    tmp_path: Path,
) -> None:
    capability = load_official_model_capability(
        provider="qwen-dashscope",
        model_name="qwen3.7-max",
        cache_dir=tmp_path,
        force_refresh=True,
    )
    budget = build_model_context_budget(
        capability,
        thinking_mode="enabled",
        thinking_budget=4_000,
        requested_output_tokens=18_000,
    )

    assert capability.official_source_url == ("https://help.aliyun.com/zh/model-studio/qwen3-7-max")
    assert capability.context_window_tokens == 1_000_000
    assert capability.maximum_input_tokens == 991_808
    assert capability.maximum_input_tokens_thinking == 983_616
    assert capability.maximum_output_tokens == 131_072
    assert capability.maximum_output_tokens_thinking == 131_072
    assert capability.maximum_reasoning_tokens == 262_144
    assert budget.compression_trigger_tokens == 800_000
    assert budget.hard_input_limit_tokens == 977_990
