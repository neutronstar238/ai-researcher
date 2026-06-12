import pytest

from autoresearch.literature import AcademicPaper
from autoresearch.plugins import (
    Notification,
    PluginDisabledError,
    PluginKind,
    PluginMetadata,
    PluginRegistry,
)


def test_sample_literature_plugin_loads_and_can_be_disabled_safely() -> None:
    plugin = SampleLiteraturePlugin()
    registry = PluginRegistry()
    registry.register(plugin)

    loaded = registry.load("sample-literature", {"api": "local"})

    assert loaded is plugin
    assert plugin.initialized_with == {"api": "local"}
    assert plugin.get_capabilities() == ("search",)
    assert plugin.search("self evolution", limit=1)[0].title == "Sample Paper"

    registry.disable("sample-literature")
    registry.disable("sample-literature")

    assert plugin.shutdown_count == 1
    assert registry.get("sample-literature").enabled is False

    with pytest.raises(PluginDisabledError, match="sample-literature"):
        registry.load("sample-literature")


def test_registry_lists_enabled_plugins_by_kind() -> None:
    registry = PluginRegistry()
    literature = SampleLiteraturePlugin()
    notification = SampleNotificationPlugin()
    registry.register(literature)
    registry.register(notification, enabled=False)

    assert registry.list(kind=PluginKind.LITERATURE_SOURCE, enabled_only=True) == (literature,)
    assert registry.list(kind=PluginKind.NOTIFICATION, enabled_only=True) == ()
    assert registry.list(kind=PluginKind.NOTIFICATION) == (notification,)


def test_registry_rejects_duplicate_plugin_names() -> None:
    registry = PluginRegistry()
    registry.register(SampleLiteraturePlugin())

    with pytest.raises(ValueError, match="already registered"):
        registry.register(SampleLiteraturePlugin())


def test_plugin_metadata_rejects_missing_identity() -> None:
    with pytest.raises(ValueError, match="plugin name is required"):
        PluginMetadata(name="", version="0.1.0", kind=PluginKind.REPORT_EXPORT)
    with pytest.raises(ValueError, match="plugin version is required"):
        PluginMetadata(name="reporter", version="", kind=PluginKind.REPORT_EXPORT)


class SampleLiteraturePlugin:
    metadata = PluginMetadata(
        name="sample-literature",
        version="0.1.0",
        kind=PluginKind.LITERATURE_SOURCE,
        capabilities=("search",),
    )

    def __init__(self) -> None:
        self.initialized_with: dict[str, object] | None = None
        self.shutdown_count = 0

    def initialize(self, config: dict[str, object]) -> None:
        self.initialized_with = config

    def shutdown(self) -> None:
        self.shutdown_count += 1

    def get_capabilities(self) -> tuple[str, ...]:
        return self.metadata.capabilities

    def search(self, _query: str, *, limit: int = 10) -> list[AcademicPaper]:
        return [
            AcademicPaper(
                source="sample",
                title="Sample Paper",
                authors=["A. Researcher"],
                abstract="Source-backed sample fixture.",
                url="https://example.test/paper",
            )
        ][:limit]


class SampleNotificationPlugin:
    metadata = PluginMetadata(
        name="sample-notification",
        version="0.1.0",
        kind=PluginKind.NOTIFICATION,
        capabilities=("send",),
    )

    def __init__(self) -> None:
        self.sent: list[Notification] = []

    def initialize(self, config: dict[str, object]) -> None:
        _ = config

    def shutdown(self) -> None:
        return None

    def get_capabilities(self) -> tuple[str, ...]:
        return self.metadata.capabilities

    def send(self, notification: Notification) -> None:
        self.sent.append(notification)
