from pathlib import Path

import pytest

from autoresearch.knowledge import (
    EXPLORATION_DIRECTORIES,
    OBSIDIAN_SYSTEM_DIRECTORIES,
    PROJECT_DIRECTORIES,
    create_obsidian_vault_assets,
    create_vault_layout,
)


def test_create_vault_layout_creates_required_obsidian_paths(tmp_path: Path) -> None:
    vault_root = tmp_path / "autoresearch-vault"

    layout = create_vault_layout(vault_root, "project-001")

    assert layout.root == vault_root
    assert layout.exploration == vault_root / "exploration"
    assert layout.project == vault_root / "projects" / "project-001"
    assert (layout.exploration / "index.md").is_file()
    assert (layout.project / "index.md").is_file()
    assert (
        "Global cross-project knowledge index for AI-Researcher."
        in (layout.exploration / "index.md").read_text(encoding="utf-8")
    )
    assert (
        "Project knowledge index for AI-Researcher."
        in (layout.project / "index.md").read_text(encoding="utf-8")
    )

    for directory in EXPLORATION_DIRECTORIES:
        assert (vault_root / "exploration" / directory).is_dir()

    for directory in PROJECT_DIRECTORIES:
        assert (vault_root / "projects" / "project-001" / directory).is_dir()


@pytest.mark.parametrize("project_id", ["", ".", "..", "nested/project"])
def test_create_vault_layout_rejects_unsafe_project_ids(
    tmp_path: Path, project_id: str
) -> None:
    with pytest.raises(ValueError):
        create_vault_layout(tmp_path / "autoresearch-vault", project_id)


def test_create_obsidian_vault_assets_adds_dashboards_templates_and_snippet(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "autoresearch-vault"

    assets = create_obsidian_vault_assets(
        vault_root,
        "project-001",
        write_local_snippet=True,
    )

    assert assets.home_path == vault_root / "Home.md"
    assert assets.dashboard_path == vault_root / "_system" / "dashboards" / "research-loop.md"
    assert assets.plugin_recommendations_path == (
        vault_root / "_system" / "plugins" / "recommended-plugins.md"
    )
    assert assets.snippet_path == vault_root / "_system" / "snippets" / "ai-researcher.css"
    assert assets.local_snippet_path == vault_root / ".obsidian" / "snippets" / "ai-researcher.css"
    assert len(assets.template_paths) == 6

    for directory in OBSIDIAN_SYSTEM_DIRECTORIES:
        assert (vault_root / "_system" / directory).is_dir()

    assert "Dataview" in assets.plugin_recommendations_path.read_text(encoding="utf-8")
    assert "projects/project-001/issues" in assets.dashboard_path.read_text(encoding="utf-8")
    assert "entry_type: skill_card" in (
        vault_root / "_system" / "templates" / "skill-card.md"
    ).read_text(encoding="utf-8")
    assert "ai-researcher" in (vault_root / ".obsidian" / "appearance.json").read_text(
        encoding="utf-8"
    )
