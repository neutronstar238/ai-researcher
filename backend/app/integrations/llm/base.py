"""LLM provider contract (spec §10.6/§26.3).

未配置 Provider 时返回 ``PROVIDER_NOT_CONFIGURED``，绝不伪造成功（§23.4）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class LLMResponse:
    content: str
    structured: dict | None = None
    usage: dict | None = None


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    async def complete(self, prompt: str, *, json_schema: dict | None = None) -> LLMResponse: ...


PROVIDERS: dict[str, type[LLMProvider]] = {}


def register_provider(name: str, provider_cls: type[LLMProvider]) -> None:
    PROVIDERS[name] = provider_cls


def get_provider(name: str | None = None) -> LLMProvider:
    from app.api.errors import ProviderNotConfiguredError
    from app.core.config import get_settings

    resolved = name or get_settings().llm_provider
    if resolved is None:
        raise ProviderNotConfiguredError("LLM Provider 未配置（LLM_PROVIDER）")
    provider_cls = PROVIDERS.get(resolved)
    if provider_cls is None:
        raise ProviderNotConfiguredError(f"LLM Provider 未配置: {resolved}")
    return provider_cls()


# OpenAI 兼容端点别名（§26.3：provider-agnostic，不写死某一家）
from app.integrations.llm.openai_compatible import OpenAICompatibleProvider  # noqa: E402

for _name in (
    "openai",
    "openai-compatible",
    "deepseek",
    "ollama",
    "vllm",
    "qwen",
    "qwen-dashscope-compatible",
):
    register_provider(_name, OpenAICompatibleProvider)
