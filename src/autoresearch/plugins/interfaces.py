"""Typed plugin interfaces for optional extension points."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from autoresearch.literature import AcademicPaper


class PluginKind(str, Enum):
    """Supported extension families."""

    LITERATURE_SOURCE = "literature_source"
    EXPERIMENT_FRAMEWORK = "experiment_framework"
    COMPUTE_PROVIDER = "compute_provider"
    NOTIFICATION = "notification"
    REPORT_EXPORT = "report_export"


@dataclass(frozen=True)
class PluginMetadata:
    """Static plugin identity used by the registry."""

    name: str
    version: str
    kind: PluginKind
    capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip():
            msg = "plugin name is required"
            raise ValueError(msg)
        if not self.version.strip():
            msg = "plugin version is required"
            raise ValueError(msg)


@dataclass(frozen=True)
class PluginArtifact:
    """Artifact produced by experiment or report export plugins."""

    path: Path
    description: str


@dataclass(frozen=True)
class PluginJob:
    """External compute job handle returned by compute provider plugins."""

    job_id: str
    status: str
    dashboard_url: str | None = None


@dataclass(frozen=True)
class Notification:
    """User-facing notification payload."""

    title: str
    body: str
    project_id: str | None = None
    action_url: str | None = None


class Plugin(Protocol):
    """Base plugin contract shared by all extension families."""

    metadata: PluginMetadata

    def initialize(self, config: dict[str, object]) -> None:
        """Prepare the plugin from project configuration."""

    def shutdown(self) -> None:
        """Release plugin resources."""

    def get_capabilities(self) -> tuple[str, ...]:
        """Return runtime capability labels."""


class LiteratureSourcePlugin(Plugin, Protocol):
    """Plugin contract for external academic literature sources."""

    def search(self, query: str, *, limit: int = 10) -> list[AcademicPaper]:
        """Return source-backed papers for one query."""


class ExperimentFrameworkPlugin(Plugin, Protocol):
    """Plugin contract for experiment framework adapters."""

    def prepare_experiment(self, workspace: Path, config: dict[str, object]) -> PluginArtifact:
        """Create or adapt runnable experiment assets."""


class ComputeProviderPlugin(Plugin, Protocol):
    """Plugin contract for optional compute backends."""

    def submit(self, command: tuple[str, ...], *, working_dir: Path) -> PluginJob:
        """Submit a command to the compute provider."""


class NotificationPlugin(Plugin, Protocol):
    """Plugin contract for approval and status notifications."""

    def send(self, notification: Notification) -> None:
        """Send one notification."""


class ReportExportPlugin(Plugin, Protocol):
    """Plugin contract for report export targets."""

    def export(self, source_path: Path, output_path: Path) -> PluginArtifact:
        """Export a report into another format or destination."""
