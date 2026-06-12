"""Small in-process plugin registry."""

from __future__ import annotations

from dataclasses import dataclass

from .interfaces import Plugin, PluginKind


class PluginDisabledError(RuntimeError):
    """Raised when a disabled plugin is requested."""


@dataclass
class PluginRegistration:
    """Mutable plugin registry state."""

    plugin: Plugin
    enabled: bool = True
    initialized: bool = False


class PluginRegistry:
    """Register, load, and disable local plugin objects."""

    def __init__(self) -> None:
        self._registrations: dict[str, PluginRegistration] = {}

    def register(self, plugin: Plugin, *, enabled: bool = True) -> PluginRegistration:
        """Register a plugin by metadata name."""

        name = plugin.metadata.name
        if name in self._registrations:
            msg = f"plugin already registered: {name}"
            raise ValueError(msg)

        registration = PluginRegistration(plugin=plugin, enabled=enabled)
        self._registrations[name] = registration
        return registration

    def load(self, name: str, config: dict[str, object] | None = None) -> Plugin:
        """Initialize and return an enabled plugin."""

        registration = self._require_registration(name)
        if not registration.enabled:
            msg = f"plugin is disabled: {name}"
            raise PluginDisabledError(msg)

        if not registration.initialized:
            registration.plugin.initialize(config or {})
            registration.initialized = True
        return registration.plugin

    def disable(self, name: str) -> None:
        """Disable a plugin and shut it down if it is initialized."""

        registration = self._require_registration(name)
        if registration.initialized:
            registration.plugin.shutdown()
            registration.initialized = False
        registration.enabled = False

    def enable(self, name: str) -> None:
        """Enable a registered plugin without initializing it."""

        self._require_registration(name).enabled = True

    def get(self, name: str) -> PluginRegistration:
        """Return registry state for one plugin."""

        return self._require_registration(name)

    def list(self, *, kind: PluginKind | None = None, enabled_only: bool = False) -> tuple[Plugin, ...]:
        """List registered plugins with optional kind and enabled filters."""

        plugins: list[Plugin] = []
        for registration in self._registrations.values():
            if enabled_only and not registration.enabled:
                continue
            if kind is not None and registration.plugin.metadata.kind is not kind:
                continue
            plugins.append(registration.plugin)
        return tuple(plugins)

    def _require_registration(self, name: str) -> PluginRegistration:
        try:
            return self._registrations[name]
        except KeyError as exc:
            msg = f"plugin is not registered: {name}"
            raise KeyError(msg) from exc
