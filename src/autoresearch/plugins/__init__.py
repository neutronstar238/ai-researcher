"""Plugin interfaces and registry for optional AI-Researcher extensions."""

from .interfaces import (
    ComputeProviderPlugin,
    ExperimentFrameworkPlugin,
    LiteratureSourcePlugin,
    Notification,
    NotificationPlugin,
    Plugin,
    PluginArtifact,
    PluginJob,
    PluginKind,
    PluginMetadata,
    ReportExportPlugin,
)
from .registry import PluginDisabledError, PluginRegistration, PluginRegistry

__all__ = [
    "ComputeProviderPlugin",
    "ExperimentFrameworkPlugin",
    "LiteratureSourcePlugin",
    "Notification",
    "NotificationPlugin",
    "Plugin",
    "PluginArtifact",
    "PluginDisabledError",
    "PluginJob",
    "PluginKind",
    "PluginMetadata",
    "PluginRegistration",
    "PluginRegistry",
    "ReportExportPlugin",
]
