"""文献源注册表（spec §10.6）：领域 Service 不依赖某个 Provider 的私有响应结构。

新增文献源时只需在本模块的 `_ensure_providers_imported()` 里加一行导入，
Provider 模块用 `@register` 装饰器把自己挂进 `PROVIDERS`。
"""

from __future__ import annotations

from app.integrations.literature.base import LiteratureProvider

PROVIDERS: dict[str, type[LiteratureProvider]] = {}


def register(provider_cls: type[LiteratureProvider]) -> type[LiteratureProvider]:
    """把 Provider 类按 `name` 注册进全局注册表。"""
    PROVIDERS[provider_cls.name] = provider_cls
    return provider_cls


def _ensure_providers_imported() -> None:
    """惰性导入所有 Provider 模块，触发各自的 @register。"""
    if PROVIDERS:
        return
    # 每个模块在导入时用 @register 挂载自身（noqa 仅为抑制未使用告警）。
    from app.integrations.literature import (  # noqa: F401
        anyresearch,
        arxiv,
        crossref,
        openalex,
        pubmed,
        semantic_scholar,
    )


def get_provider(name: str) -> LiteratureProvider:
    from app.api.errors import ProviderNotConfiguredError

    _ensure_providers_imported()
    provider_cls = PROVIDERS.get(name)
    if provider_cls is None:
        raise ProviderNotConfiguredError(f"文献源未配置: {name}")
    return provider_cls()


def available_providers() -> list[str]:
    _ensure_providers_imported()
    return sorted(PROVIDERS)
