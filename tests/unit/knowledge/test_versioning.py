from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoresearch.knowledge import (
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    MarkdownKnowledgeStore,
)


def _entry(body: str) -> KnowledgeEntry:
    return KnowledgeEntry(
        entry_id="entry_versioned",
        entry_type=KnowledgeEntryType.EXPERIMENT_RECORD,
        zone=KnowledgeZone.PROJECT,
        title="Versioned experiment",
        project_id="project-001",
        body=body,
    )


def test_markdown_store_versions_and_rolls_back_entry(tmp_path: Path) -> None:
    store = MarkdownKnowledgeStore(tmp_path)
    relative_path = "projects/project-001/experiments/versioned.md"

    store.write_entry(relative_path, _entry("version 1"))
    store.write_entry(relative_path, _entry("version 2"))
    store.write_entry(relative_path, _entry("version 3"))

    versions = store.list_versions(relative_path)

    assert len(versions) == 3
    assert "version 1" in versions[0].content
    assert "version 2" in versions[1].content
    assert "version 3" in versions[2].content

    store.rollback(relative_path, 1)
    rolled_back = store.read_entry(relative_path)

    assert rolled_back.body == "version 1"


def test_markdown_store_creates_backups_only_when_due(tmp_path: Path) -> None:
    store = MarkdownKnowledgeStore(tmp_path)
    store.write_entry("projects/project-001/knowledge/note.md", _entry("backup target"))
    first_time = datetime(2026, 6, 11, 10, 0, tzinfo=timezone.utc)
    second_time = datetime(2026, 6, 11, 10, 30, tzinfo=timezone.utc)
    third_time = datetime(2026, 6, 11, 11, 1, tzinfo=timezone.utc)

    first_backup = store.backup_if_due(1, now=first_time)
    skipped_backup = store.backup_if_due(1, now=second_time)
    second_backup = store.backup_if_due(1, now=third_time)

    assert first_backup is not None
    assert first_backup.exists()
    assert skipped_backup is None
    assert second_backup is not None
    assert second_backup.exists()


def test_public_backup_excludes_private_raw_memory(tmp_path: Path) -> None:
    store = MarkdownKnowledgeStore(tmp_path)
    private_path = tmp_path / "_private" / "raw-memory" / "secret-source.bin"
    private_path.parent.mkdir(parents=True)
    private_path.write_bytes(b"private source bytes")

    backup = store.backup_if_due(
        1,
        now=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )

    assert backup is not None
    assert not (backup / "_private").exists()


@pytest.mark.parametrize("interval_hours", [0, 27])
def test_markdown_store_rejects_backup_interval_outside_allowed_range(
    tmp_path: Path, interval_hours: int
) -> None:
    store = MarkdownKnowledgeStore(tmp_path)

    with pytest.raises(ValueError):
        store.backup_if_due(interval_hours)
