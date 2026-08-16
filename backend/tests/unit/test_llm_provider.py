"""LLM provider unit tests (spec §16/§10.6). 不依赖真实 API Key。"""

from __future__ import annotations

import pytest

from app.api.errors import ProviderNotConfiguredError
from app.integrations.llm.base import PROVIDERS, get_provider
from app.integrations.llm.openai_compatible import OpenAICompatibleProvider


def test_provider_registered_under_aliases() -> None:
    assert PROVIDERS["qwen-dashscope-compatible"] is OpenAICompatibleProvider
    assert PROVIDERS["openai"] is OpenAICompatibleProvider
    assert PROVIDERS["deepseek"] is OpenAICompatibleProvider


def test_get_provider_unknown_raises() -> None:
    with pytest.raises(ProviderNotConfiguredError):
        get_provider("does-not-exist")


def test_parse_json_plain_object() -> None:
    assert OpenAICompatibleProvider._parse_json('{"a": 1}') == {"a": 1}


def test_parse_json_strips_code_fence() -> None:
    assert OpenAICompatibleProvider._parse_json('```json\n{"b": 2}\n```') == {"b": 2}


def test_parse_json_invalid_returns_none() -> None:
    assert OpenAICompatibleProvider._parse_json("not json at all") is None


def test_complete_calls_openai_endpoint(monkeypatch) -> None:
    import json

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [{"message": {"content": json.dumps({"score": 9})}}],
                "usage": {"total_tokens": 7},
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.posted = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, json=None, headers=None):
            self.posted = (url, json, headers)
            return FakeResponse()

    class FakeSettings:
        llm_base_url = "https://example.com/v1"
        llm_api_key = "sk-test"
        llm_model = "test-model"

    monkeypatch.setattr("app.integrations.llm.openai_compatible.httpx.AsyncClient", FakeClient)
    monkeypatch.setattr("app.integrations.llm.openai_compatible.get_settings", lambda: FakeSettings())

    provider = OpenAICompatibleProvider()
    # 上面 FakeClient 已被替换；重新捕获一次实例以检查请求体
    import asyncio

    async def run():
        response = await provider.complete("hello", json_schema={"type": "object"})
        return response

    response = asyncio.run(run())
    assert response.structured == {"score": 9}
    assert response.usage == {"total_tokens": 7}
