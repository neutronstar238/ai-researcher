from pathlib import Path

import pytest

from autoresearch.knowledge import (
    EXPLORATION_DIRECTORIES,
    PROJECT_DIRECTORIES,
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
