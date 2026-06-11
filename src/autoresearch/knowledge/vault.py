"""Filesystem layout helpers for the Obsidian knowledge vault."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

EXPLORATION_DIRECTORIES = (
    "topics",
    "skills",
    "methodologies",
    "datasets",
    "failure_patterns",
    "strategy_cards",
)

PROJECT_DIRECTORIES = (
    "knowledge",
    "progress",
    "issues",
    "experience",
    "experiments",
    "results",
    "evidence",
    "paper",
)


@dataclass(frozen=True)
class VaultLayout:
    """Created Obsidian vault paths for one project."""

    root: Path
    exploration: Path
    project: Path


def _validate_project_id(project_id: str) -> None:
    if not project_id or project_id in {".", ".."}:
        msg = "project_id must be a non-empty path-safe name"
        raise ValueError(msg)

    project_path = Path(project_id)
    if project_path.name != project_id:
        msg = "project_id must not contain path separators"
        raise ValueError(msg)


def _write_if_missing(path: Path, content: str) -> None:
    if not path.exists():
        path.write_text(content, encoding="utf-8")


def create_vault_layout(vault_root: Path | str, project_id: str) -> VaultLayout:
    """Create the required Obsidian-compatible vault directories."""

    _validate_project_id(project_id)

    root = Path(vault_root)
    exploration = root / "exploration"
    project = root / "projects" / project_id

    root.mkdir(parents=True, exist_ok=True)
    exploration.mkdir(parents=True, exist_ok=True)
    for directory in EXPLORATION_DIRECTORIES:
        (exploration / directory).mkdir(parents=True, exist_ok=True)

    projects_root = root / "projects"
    projects_root.mkdir(parents=True, exist_ok=True)
    project.mkdir(parents=True, exist_ok=True)
    for directory in PROJECT_DIRECTORIES:
        (project / directory).mkdir(parents=True, exist_ok=True)

    _write_if_missing(
        exploration / "index.md",
        "# Exploration Index\n\nGlobal cross-project knowledge index for AutoResearch.\n",
    )
    _write_if_missing(
        project / "index.md",
        f"# {project_id}\n\nProject knowledge index for AutoResearch.\n",
    )

    return VaultLayout(root=root, exploration=exploration, project=project)
