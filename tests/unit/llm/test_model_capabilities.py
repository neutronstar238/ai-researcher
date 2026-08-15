import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoresearch.kernel.contracts import canonical_sha256
from autoresearch.llm.model_capabilities import (
    OfficialModelCapabilityError,
    build_model_context_budget,
    load_official_model_capability,
    parse_official_model_capability,
)

FETCHED_AT = datetime(2026, 8, 11, 2, 0, tzinfo=timezone.utc)
SOURCE_URL = "https://help.aliyun.com/zh/model-studio/qwen3-7-max"


def _official_page() -> bytes:
    content = """
    <main><h1>qwen3.7-max</h1>
      <table><tr><th>能力</th><th>值</th></tr><tr><td>Text</td><td>支持</td></tr></table>
      <table>
        <tr><th>参数</th><th>值</th><th>参数</th><th>值</th></tr>
        <tr><td>最大输入长度</td><td>991808</td><td>最大输出长度</td><td>131072</td></tr>
        <tr><td>上下文长度</td><td>1000000</td><td>最大输入长度（思考模式下）</td><td>983616</td></tr>
        <tr><td>最大输出长度（思考模式下）</td><td>131072</td><td>最大思维链长度</td><td>262144</td></tr>
      </table>
      <h3>qwen3.7-max-preview</h3>
    </main>
    """
    props = {
        "docDetailData": {
            "storeData": {
                "data": {
                    "title": "qwen3.7-max",
                    "lastModifiedTime": 1785742918000,
                    "content": content,
                }
            }
        }
    }
    return (
        '<html><head><meta name="last-modified" '
        'content="2026-08-03T15:41:58+08:00"></head><body><script>'
        "window.__ICE_PAGE_PROPS__="
        + json.dumps(props, ensure_ascii=False, separators=(",", ":"))
        + ";</script></body></html>"
    ).encode("utf-8")


def test_parse_official_qwen_page_and_derive_exact_eighty_percent_budget() -> None:
    page = _official_page()

    capability = parse_official_model_capability(
        page,
        provider="qwen-dashscope",
        model_name="qwen3.7-max",
        source_url=SOURCE_URL,
        fetched_at=FETCHED_AT,
    )
    budget = build_model_context_budget(
        capability,
        thinking_mode="enabled",
        thinking_budget=4_000,
        requested_output_tokens=18_000,
    )

    assert capability.context_window_tokens == 1_000_000
    assert capability.maximum_input_tokens == 991_808
    assert capability.maximum_input_tokens_thinking == 983_616
    assert capability.maximum_output_tokens == 131_072
    assert capability.maximum_output_tokens_thinking == 131_072
    assert capability.maximum_reasoning_tokens == 262_144
    assert capability.source_sha256 == hashlib.sha256(page).hexdigest()
    assert budget.compression_trigger_ratio == 0.8
    assert budget.compression_trigger_tokens == 800_000
    assert budget.hard_input_limit_tokens == 977_990
    assert budget.thinking_budget_tokens == 4_000


def test_context_budget_reserves_answer_reasoning_and_provider_overrun() -> None:
    capability = parse_official_model_capability(
        _official_page(),
        provider="qwen-dashscope",
        model_name="qwen3.7-max",
        source_url=SOURCE_URL,
        fetched_at=FETCHED_AT,
    )

    budget = build_model_context_budget(
        capability,
        thinking_mode="enabled",
        thinking_budget=4_000,
        requested_output_tokens=768,
    )

    assert budget.hard_input_limit_tokens == capability.maximum_input_tokens_thinking
    assert (
        budget.hard_input_limit_tokens
        + budget.requested_output_tokens
        + budget.thinking_budget_tokens
        + budget.completion_token_overrun_allowance_tokens
        <= capability.context_window_tokens
    )


def test_legacy_v1_context_budget_replays_with_its_original_formula() -> None:
    capability = parse_official_model_capability(
        _official_page(),
        provider="qwen-dashscope",
        model_name="qwen3.7-max",
        source_url=SOURCE_URL,
        fetched_at=FETCHED_AT,
    )
    current = build_model_context_budget(
        capability,
        thinking_mode="enabled",
        thinking_budget=4_000,
        requested_output_tokens=18_000,
    )
    legacy = current.model_dump(mode="json")
    legacy["schema_version"] = "model-context-budget-v1"
    legacy["hard_input_limit_tokens"] = 981_990
    legacy["budget_hash"] = canonical_sha256(
        {key: value for key, value in legacy.items() if key != "budget_hash"}
    )

    replayed = type(current).model_validate(legacy)

    assert replayed.schema_version == "model-context-budget-v1"
    assert replayed.hard_input_limit_tokens == 981_990


def test_context_budget_reserves_full_completion_and_ten_token_overrun() -> None:
    capability = parse_official_model_capability(
        _official_page(),
        provider="qwen-dashscope",
        model_name="qwen3.7-max",
        source_url=SOURCE_URL,
        fetched_at=FETCHED_AT,
    )

    budget = build_model_context_budget(
        capability,
        thinking_mode="disabled",
        thinking_budget=None,
        requested_output_tokens=131_072,
    )

    assert budget.hard_input_limit_tokens == 868_918
    assert (
        budget.hard_input_limit_tokens
        + budget.requested_output_tokens
        + budget.completion_token_overrun_allowance_tokens
        == capability.context_window_tokens
    )


@pytest.mark.parametrize("thinking_budget", [None, 262_145])
def test_thinking_budget_must_be_present_and_within_official_maximum(
    thinking_budget: int | None,
) -> None:
    capability = parse_official_model_capability(
        _official_page(),
        provider="qwen-dashscope",
        model_name="qwen3.7-max",
        source_url=SOURCE_URL,
        fetched_at=FETCHED_AT,
    )

    with pytest.raises(OfficialModelCapabilityError, match="thinking budget"):
        build_model_context_budget(
            capability,
            thinking_mode="enabled",
            thinking_budget=thinking_budget,
            requested_output_tokens=18_000,
        )


def test_disabled_thinking_rejects_a_reasoning_budget() -> None:
    capability = parse_official_model_capability(
        _official_page(),
        provider="qwen-dashscope",
        model_name="qwen3.7-max",
        source_url=SOURCE_URL,
        fetched_at=FETCHED_AT,
    )

    with pytest.raises(OfficialModelCapabilityError, match="disabled"):
        build_model_context_budget(
            capability,
            thinking_mode="disabled",
            thinking_budget=4_000,
            requested_output_tokens=18_000,
        )


def test_official_capability_cache_replays_exact_source_and_rejects_tamper(
    tmp_path: Path,
) -> None:
    page = _official_page()
    calls = 0

    def fetcher(url: str) -> tuple[bytes, str]:
        nonlocal calls
        calls += 1
        assert url == SOURCE_URL
        return page, url

    first = load_official_model_capability(
        provider="qwen-dashscope",
        model_name="qwen3.7-max",
        cache_dir=tmp_path,
        fetcher=fetcher,
        clock=FETCHED_AT,
    )
    cached = load_official_model_capability(
        provider="qwen-dashscope",
        model_name="qwen3.7-max",
        cache_dir=tmp_path,
        fetcher=lambda _url: (_ for _ in ()).throw(AssertionError("network used")),
        clock=FETCHED_AT,
    )

    assert cached == first
    assert calls == 1
    source = tmp_path / f"source-{first.source_sha256}.html"
    source.write_bytes(page + b"tampered")
    with pytest.raises(OfficialModelCapabilityError, match="corrupt"):
        load_official_model_capability(
            provider="qwen-dashscope",
            model_name="qwen3.7-max",
            cache_dir=tmp_path,
            clock=FETCHED_AT,
        )


def test_legacy_capability_cache_is_refreshed_from_the_official_page(tmp_path: Path) -> None:
    page = _official_page()
    current = parse_official_model_capability(
        page,
        provider="qwen-dashscope",
        model_name="qwen3.7-max",
        source_url=SOURCE_URL,
        fetched_at=FETCHED_AT,
    )
    legacy = current.model_dump(mode="json")
    legacy.pop("maximum_reasoning_tokens")
    legacy["capability_hash"] = canonical_sha256(
        {key: value for key, value in legacy.items() if key != "capability_hash"}
    )
    (tmp_path / f"source-{current.source_sha256}.html").write_bytes(page)
    (tmp_path / "qwen3.7-max.json").write_text(
        json.dumps(legacy, ensure_ascii=False),
        encoding="utf-8",
    )
    calls = 0

    def fetcher(url: str) -> tuple[bytes, str]:
        nonlocal calls
        calls += 1
        return page, url

    refreshed = load_official_model_capability(
        provider="qwen-dashscope",
        model_name="qwen3.7-max",
        cache_dir=tmp_path,
        fetcher=fetcher,
        clock=FETCHED_AT,
    )

    assert calls == 1
    assert refreshed.maximum_reasoning_tokens == 262_144


def test_unknown_provider_has_no_guessed_context_limit(tmp_path: Path) -> None:
    with pytest.raises(OfficialModelCapabilityError, match="guessed limit"):
        load_official_model_capability(
            provider="made-up-provider",
            model_name="made-up-model",
            cache_dir=tmp_path,
            clock=FETCHED_AT,
        )


def test_capability_hash_covers_provider_facts() -> None:
    capability = parse_official_model_capability(
        _official_page(),
        provider="qwen-dashscope",
        model_name="qwen3.7-max",
        source_url=SOURCE_URL,
        fetched_at=FETCHED_AT,
    )
    payload = capability.model_dump(mode="json", exclude={"capability_hash"})
    assert capability.capability_hash == canonical_sha256(payload)
